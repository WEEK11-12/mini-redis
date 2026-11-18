"""HTTP interface with serial store commands and parallel request parsing."""

import argparse
import json
import queue
import re
import select
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from .store import HashTableStore


_KEY = re.compile(r"[A-Za-z0-9_.~-]+\Z")
_LENGTH = re.compile(r"[0-9]+\Z")
_MAX_BODY = 65536
_REQUEST_TIMEOUT = 6
_REJECTION_TIMEOUT = 0.5

def _json_integer(digits):
    # Avoid the interpreter's decimal-to-int digit cap for valid bounded JSON bodies.
    value = 0
    negative = digits.startswith("-")
    for digit in digits[negative:]:
        value = value * 10 + ord(digit) - ord("0")
    return -value if negative else value


def create_server(host, port, store):
    """Return a server whose store calls all run on one dedicated thread."""

    class RequestGone(Exception):
        pass

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            # A total deadline bounds trickled request lines, headers, bodies and writes.
            self._expired = False
            self._deadline = threading.Timer(_REQUEST_TIMEOUT, self._expire)
            self._deadline.daemon = True
            self._deadline.start()
            self.connection.settimeout(2)

        def _expire(self):
            self._expired = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def finish(self):
            try:
                super().finish()
            finally:
                self._deadline.cancel()

        def handle(self):
            try:
                super().handle()
            except OSError:
                # A disconnected client cannot receive a response; never retry its command.
                pass

        def __getattr__(self, name):
            # BaseHTTPRequestHandler otherwise sends HTML/501 for unknown methods.
            if name.startswith("do_"):
                return self._handle
            raise AttributeError(name)

        def do_GET(self):
            self._handle()

        do_PUT = do_DELETE = do_HEAD = do_OPTIONS = do_POST = do_GET

        def _send(self, status, payload, *, allow=None):
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            if allow:
                self.send_header("Allow", allow)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _error(self, status, code, *, allow=None):
            self._send(status, {"error": {"code": code}}, allow=allow)

        def _value(self, field="value"):
            # Reject ambiguous framing before reading any body bytes.
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get_all("Transfer-Encoding") or len(lengths) != 1 or not _LENGTH.fullmatch(lengths[0]):
                return None
            digits = lengths[0].lstrip("0")
            if not digits or len(digits) > 5:
                return None
            length = int(digits)
            if (length > _MAX_BODY
                    or self.headers.get_all("Content-Type", []) != ["application/json"]):
                return None
            try:
                self.connection.settimeout(2)
                body = self.rfile.read(length)
                if len(body) != length:
                    return None
                value = json.loads(body.decode("utf-8"), parse_int=_json_integer)
            except (OSError, UnicodeError, ValueError):
                return None
            if not isinstance(value, dict) or set(value) != {field}:
                return None
            if field == "value" and not isinstance(value[field], str):
                return None
            if field == "ttl_seconds" and (type(value[field]) is not int or value[field] <= 0):
                return None
            return value

        def _handle(self):
            path, separator, _ = self.path.partition("?")
            if not path.startswith("/keys/"):
                self._error(404, "ROUTE_NOT_FOUND")
                return
            suffix = path[len("/keys/"):]
            exists = suffix.endswith("/exists")
            ttl = suffix.endswith("/ttl")
            key = suffix[:-len("/exists")] if exists else suffix[:-len("/ttl")] if ttl else suffix
            if not _KEY.fullmatch(key) or key in (".", ".."):
                self._error(400, "INVALID_KEY")
                return
            allow = "GET" if exists else "PUT, DELETE" if ttl else "GET, PUT, DELETE"
            if self.command not in allow.split(", "):
                self._error(405, "METHOD_NOT_ALLOWED", allow=allow)
                return
            if separator:
                self._error(400, "INVALID_QUERY")
                return
            value = None
            if self.command == "PUT":
                value = self._value("ttl_seconds" if ttl else "value")
                if value is None:
                    self._error(400, "INVALID_BODY")
                    return
            try:
                assert isinstance(self.server, Server)
                operation = ("exists" if exists else
                             "set_ttl" if ttl and self.command == "PUT" else
                             "clear_ttl" if ttl else
                             "get" if self.command == "GET" else
                             "set" if self.command == "PUT" else "delete")
                if self.command == "PUT":
                    assert value is not None
                arguments = (key, value["ttl_seconds"] if ttl else value["value"]) if value is not None else (key,)
                outcome = self.server.execute(operation, arguments, self.connection, self)
                if exists:
                    payload = {"exists": outcome}
                elif ttl and self.command == "PUT":
                    if not outcome:
                        self._error(404, "KEY_NOT_FOUND")
                        return
                    payload = {"ttl_set": True}
                elif ttl:
                    payload = {"ttl_removed": outcome}
                elif self.command == "GET":
                    found, stored_value = outcome
                    if not found:
                        self._error(404, "KEY_NOT_FOUND")
                        return
                    payload = {"value": stored_value}
                elif self.command == "PUT":
                    payload = {"stored": True}
                else:
                    payload = {"deleted": outcome}
            except RequestGone:
                return
            except Exception:
                # Storage failures must not become input errors or leak details.
                self._error(500, "INTERNAL_ERROR")
                return
            self._send(200, payload)

        def log_message(self, format, *args):
            pass

    class Server(ThreadingMixIn, HTTPServer):
        def __init__(self, address, handler):
            super().__init__(address, handler)
            self._slots = threading.BoundedSemaphore(16)
            self._condition = threading.Condition()
            self._active = 0
            self._draining = False
            self._failed = False
            self._stop_executor = False
            self._serve_started = False
            self._commands = queue.Queue()
            self._executor = threading.Thread(target=self._run_commands, name="mini-redis-commands")
            self._next_sweep = time.monotonic() + 1
            self._executor.start()

        def serve_forever(self, poll_interval=0.5):
            self._serve_started = True
            super().serve_forever(poll_interval)

        def execute(self, operation, arguments, connection, handler):
            command = [operation, arguments, threading.Event(), None, None]
            with self._condition:
                if self._failed:
                    raise RuntimeError("command executor stopped")
                if handler._expired:
                    raise RequestGone("request deadline expired")
                # A FIN can mean a valid half-close; only a confirmed reset aborts.
                try:
                    if select.select([connection], [], [], 0)[0]:
                        connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
                except (ConnectionResetError, BrokenPipeError):
                    raise RequestGone("client disconnected")
                self._commands.put(command)
            while not command[2].wait(0.1):
                if self._failed:
                    raise RuntimeError("command executor stopped")
            if command[4] is not None:
                raise command[4]
            return command[3]

        def _run_commands(self):
            try:
                while True:
                    now = time.monotonic()
                    if not self._stop_executor and now >= self._next_sweep:
                        try:
                            store.sweep_expired()
                        except Exception as exc:
                            try:
                                print(f"expiration sweep failed: {exc!r}", file=sys.stderr)
                            except Exception:
                                pass
                        self._next_sweep = time.monotonic() + 1
                    try:
                        command = self._commands.get(timeout=max(0, self._next_sweep - time.monotonic()))
                    except queue.Empty:
                        continue
                    if command is None:
                        break
                    try:
                        command[3] = getattr(store, command[0])(*command[1])
                    except BaseException as exc:
                        command[4] = exc if isinstance(exc, Exception) else RuntimeError("command executor stopped")
                        if not isinstance(exc, Exception):
                            with self._condition:
                                self._draining = True
                            break
                    finally:
                        try:
                            command[2].set()
                        except Exception:
                            # Do not repeat an already applied operation on delivery failure.
                            command[4] = RuntimeError("command result delivery failed")
                            command[2].set()
            finally:
                # An unexpected worker death must not strand completed admissions.
                with self._condition:
                    self._failed = True
                    self._draining = True
                    while True:
                        try:
                            pending = self._commands.get_nowait()
                        except queue.Empty:
                            break
                        if pending is not None:
                            pending[4] = RuntimeError("command executor stopped")
                            pending[2].set()

        def process_request(self, request, client_address):
            with self._condition:
                accepted = not self._draining and self._slots.acquire(blocking=False)
                if accepted:
                    self._active += 1
            if accepted:
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    self._finish_request()
                    raise
            else:
                self._reject(request)

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self._finish_request()

        def _finish_request(self):
            with self._condition:
                self._active -= 1
                self._slots.release()
                self._condition.notify_all()

        def _reject(self, request):
            try:
                request.settimeout(_REJECTION_TIMEOUT)
                deadline = time.monotonic() + _REJECTION_TIMEOUT
                line = bytearray()
                while len(line) < 65537 and not line.endswith(b"\n"):
                    request.settimeout(max(0.001, deadline - time.monotonic()))
                    byte = request.recv(1)
                    if not byte or time.monotonic() >= deadline:
                        return
                    line.extend(byte)
                method = line.split(b" ", 1)[0]
                if method not in (b"GET", b"PUT", b"DELETE", b"HEAD", b"POST", b"OPTIONS"):
                    return
                # Consume only bounded headers; unread input can reset a just-sent reply.
                headers = bytearray(line)
                while not headers.endswith(b"\r\n\r\n") and len(headers) < 65536:
                    request.settimeout(max(0.001, deadline - time.monotonic()))
                    byte = request.recv(1)
                    if not byte or time.monotonic() >= deadline:
                        return
                    headers.extend(byte)
                if not headers.endswith(b"\r\n\r\n"):
                    return
                body = b'{"error":{"code":"SERVER_BUSY"}}'
                response = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n"
                            + f"Content-Length: {len(body)}\r\n".encode()
                            + b"Cache-Control: no-store\r\nConnection: close\r\n\r\n")
                request.settimeout(max(0.001, deadline - time.monotonic()))
                request.sendall(response + (b"" if method == b"HEAD" else body))
                request.shutdown(socket.SHUT_WR)
                for _ in range(2):
                    request.settimeout(min(0.01, max(0.001, deadline - time.monotonic())))
                    if time.monotonic() >= deadline or not request.recv(65536):
                        break
            except OSError:
                pass
            finally:
                self.shutdown_request(request)

        def shutdown(self):
            with self._condition:
                self._draining = True
            super().shutdown()
            with self._condition:
                self._condition.wait_for(lambda: self._active == 0)
                if not self._stop_executor:
                    self._stop_executor = True
                    self._commands.put(None)
            self._executor.join()

        def server_close(self):
            # A constructed server may be closed without ever serving requests.
            if not self._executor.is_alive():
                super().server_close()
                return
            if not self._serve_started:
                with self._condition:
                    self._draining = True
                    self._stop_executor = True
                    self._commands.put(None)
                self._executor.join()
            super().server_close()

    return Server((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Run the Mini Redis HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = create_server(args.host, args.port, HashTableStore())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
