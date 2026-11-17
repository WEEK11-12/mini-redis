"""Sequential HTTP interface for the in-memory hash table."""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

from .store import HashTableStore


_KEY = re.compile(r"[A-Za-z0-9_.~-]+\Z")
_LENGTH = re.compile(r"[0-9]+\Z")
_MAX_BODY = 65536


def create_server(host, port, store):
    """Return a single-threaded server using the supplied store for its lifetime."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

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

        def _value(self):
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
                value = json.loads(body.decode("utf-8"))
            except (OSError, UnicodeError, ValueError):
                return None
            if not isinstance(value, dict) or set(value) != {"value"} or not isinstance(value["value"], str):
                return None
            return value

        def _handle(self):
            path, separator, _ = self.path.partition("?")
            if not path.startswith("/keys/"):
                self._error(404, "ROUTE_NOT_FOUND")
                return
            suffix = path[len("/keys/"):]
            exists = suffix.endswith("/exists")
            key = suffix[:-len("/exists")] if exists else suffix
            if not _KEY.fullmatch(key) or key in (".", ".."):
                self._error(400, "INVALID_KEY")
                return
            allow = "GET" if exists else "GET, PUT, DELETE"
            if self.command not in allow.split(", "):
                self._error(405, "METHOD_NOT_ALLOWED", allow=allow)
                return
            if separator:
                self._error(400, "INVALID_QUERY")
                return
            value = None
            if self.command == "PUT":
                value = self._value()
                if value is None:
                    self._error(400, "INVALID_BODY")
                    return
            try:
                if exists:
                    payload = {"exists": store.exists(key)}
                elif self.command == "GET":
                    found, stored_value = store.get(key)
                    if not found:
                        self._error(404, "KEY_NOT_FOUND")
                        return
                    payload = {"value": stored_value}
                elif self.command == "PUT":
                    assert value is not None
                    store.set(key, value["value"])
                    payload = {"stored": True}
                else:
                    payload = {"deleted": store.delete(key)}
            except Exception:
                # Storage failures must not become input errors or leak details.
                self._error(500, "INTERNAL_ERROR")
                return
            self._send(200, payload)

        def log_message(self, format, *args):
            pass

    return HTTPServer((host, port), Handler)


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
        server.server_close()


if __name__ == "__main__":
    main()
