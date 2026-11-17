"""Iteration 03 contract tests (RED until the HTTP modules exist).

Provisional seams, not an established product API:
  mini_redis.http_api.create_server(host, port, store) -> HTTPServer
  python -m mini_redis.http_api --host HOST --port PORT
  python -m examples.origin_api --host HOST --port PORT
  python -m examples.client --cache-url URL --origin-url URL
Each server must support shutdown()/server_close(). Adapt these seams when the
implementation is chosen; do not add product APIs solely to satisfy probes.
"""

import contextlib
import http.client
import importlib
import json
import socket
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from mini_redis.store import HashTableStore


HOST = "127.0.0.1"


def module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name != name and not name.startswith(exc.name + "."):
            raise
        raise AssertionError(f"Implementation missing: {name} (provisional test seam)") from exc


@contextlib.contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{HOST}:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("HTTP server did not stop")


def request(url, method, path, *, body=None, headers=None):
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()
    finally:
        conn.close()


def put(url, key, value):
    return request(url, "PUT", f"/keys/{key}", body=json.dumps({"value": value}).encode(),
                   headers={"Content-Type": "application/json"})


def result(test, response, status, body, *, no_store=True):
    code, headers, data = response
    test.assertEqual(code, status)
    actual = json.loads(data)
    test.assertEqual(actual, body)
    for field in ("stored", "exists", "deleted", "count"):
        if field in body:
            test.assertIs(type(actual[field]), type(body[field]))
    if no_store:
        test.assertEqual(headers.get("cache-control"), "no-store")


def error(code):
    return {"error": {"code": code}}


def raw(url, payload, *, half_close=False):
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    sock = socket.create_connection((parsed.hostname, parsed.port), timeout=3)
    sock.settimeout(5)
    try:
        sock.sendall(payload)
        if half_close:
            sock.shutdown(socket.SHUT_WR)
        data = bytearray()
        while True:
            try:
                chunk = sock.recv(65536)
            except ConnectionResetError:
                break
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)
    finally:
        sock.close()


def early_rejection(url, headers, followup):
    """Keep the body unwritten until the server starts its rejection response."""
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    with socket.create_connection((parsed.hostname, parsed.port), timeout=3) as sock:
        sock.settimeout(5)
        sock.sendall(headers)
        first = sock.recv(1)  # A server waiting to read the declared body times out here.
        if not first:
            raise AssertionError("server closed before sending a rejection")
        try:
            sock.sendall(followup)
        except (BrokenPipeError, ConnectionResetError):
            pass
        response = bytearray(first)
        while True:
            try:
                chunk = sock.recv(65536)
            except ConnectionResetError:
                break
            if not chunk:
                break
            response.extend(chunk)
        return bytes(response)


def raw_put(path, body, *headers):
    return (f"PUT {path} HTTP/1.1\r\nHost: localhost\r\n".encode()
            + b"".join(h + b"\r\n" for h in headers) + b"\r\n" + body)


NEXT_GET = b"GET /keys/kept HTTP/1.1\r\nHost: localhost\r\n\r\n"


class HTTPContractTests(unittest.TestCase):
    def setUp(self):
        self.store = HashTableStore()
        api = module("mini_redis.http_api")
        try:
            server = api.create_server(HOST, 0, self.store)
        except AttributeError as exc:
            raise AssertionError("Implementation missing: mini_redis.http_api.create_server(host, port, store)") from exc
        self.server = server
        self.addCleanup(server.server_close)
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop, server)
        self.url = f"http://{HOST}:{server.server_address[1]}"

    def _stop(self, server):
        server.shutdown()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def check(self, method, path, status, expected, **kwargs):
        result(self, request(self.url, method, path, **kwargs), status, expected)

    def seeded(self):
        result(self, put(self.url, "kept", "before"), 200, {"stored": True})

    def unchanged(self):
        self.check("GET", "/keys/kept", 200, {"value": "before"})

    def raw_error(self, response, code):
        headers, body = response.split(b"\r\n\r\n", 1)
        self.assertIn(b" 400 ", headers.split(b"\r\n", 1)[0])
        self.assertIn(b"cache-control: no-store", headers.lower())
        self.assertEqual(json.loads(body), error(code))

    def test_i_001_put_overwrite(self):
        result(self, put(self.url, "a", "first"), 200, {"stored": True})
        self.check("GET", "/keys/a", 200, {"value": "first"})
        result(self, put(self.url, "a", "last"), 200, {"stored": True})
        self.check("GET", "/keys/a", 200, {"value": "last"})

    def test_i_002_empty_value_is_present(self):
        result(self, put(self.url, "empty", ""), 200, {"stored": True})
        self.check("GET", "/keys/empty", 200, {"value": ""})
        self.check("GET", "/keys/empty/exists", 200, {"exists": True})

    def test_i_003_missing_key(self):
        self.check("GET", "/keys/absent", 404, error("KEY_NOT_FOUND"))
        self.check("GET", "/keys/absent/exists", 200, {"exists": False})

    def test_i_004_delete_and_isolation(self):
        put(self.url, "a", "one")
        put(self.url, "b", "two")
        self.check("GET", "/keys/a/exists", 200, {"exists": True})
        self.check("DELETE", "/keys/a", 200, {"deleted": True})
        self.check("DELETE", "/keys/a", 200, {"deleted": False})
        self.check("GET", "/keys/a", 404, error("KEY_NOT_FOUND"))
        self.check("GET", "/keys/a/exists", 200, {"exists": False})
        self.check("GET", "/keys/b", 200, {"value": "two"})

    def test_i_005_delete_missing(self):
        self.check("DELETE", "/keys/absent", 200, {"deleted": False})

    def test_i_006_invalid_key_segments(self):
        self.seeded()
        with patch.object(self.store, "get", wraps=self.store.get) as get:
            for path in ("/keys/", "/keys/a/b", "/keys/a/unknown", "/keys/a/exists/extra",
                         "/keys/.", "/keys/.."):
                with self.subTest(path=path):
                    self.check("GET", path, 400, error("INVALID_KEY"))
            get.assert_not_called()
        self.unchanged()

    def test_i_007_encoded_and_illegal_keys(self):
        self.seeded()
        for path in ("/keys/%61", "/keys/a%2Fb", "/keys/a%20b", "/keys/한글"):
            with self.subTest(path=path):
                # http.client preserves the supplied request target; UTF-8 bytes are sent as-is.
                if path.isascii():
                    self.check("GET", path, 400, error("INVALID_KEY"))
                else:
                    response = raw(self.url, f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
                    self.assertIn(b" 400 ", response.split(b"\r\n", 1)[0])
                    self.assertEqual(json.loads(response.split(b"\r\n\r\n", 1)[1]), error("INVALID_KEY"))
        self.unchanged()
        # A raw space can fail before application routing; no JSON error contract applies.
        raw(self.url, b"GET /keys/a b HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")

    def test_i_008_valid_keys_keep_case(self):
        for key in ("a", "A", "a.b", ".name", "...", "a-_~"):
            with self.subTest(key=key):
                result(self, put(self.url, key, key), 200, {"stored": True})
        for key in ("a", "A", "a.b", ".name", "...", "a-_~"):
            with self.subTest(key=key):
                self.check("GET", f"/keys/{key}", 200, {"value": key})

    def test_i_009_unknown_routes(self):
        for method, path in (("GET", "/keys"), ("POST", "/unrelated"),
                             ("GET", "/unrelated?x=1")):
            with self.subTest(method=method, path=path):
                self.check(method, path, 404, error("ROUTE_NOT_FOUND"))

    def test_i_010_unsupported_methods_and_head(self):
        for method, path, allow in (("POST", "/keys/a", "GET, PUT, DELETE"),
                                    ("PUT", "/keys/a/exists", "GET"),
                                    ("OPTIONS", "/keys/a", "GET, PUT, DELETE"),
                                    ("HEAD", "/keys/a", "GET, PUT, DELETE")):
            with self.subTest(method=method, path=path):
                status, headers, body = request(self.url, method, path)
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("allow"), allow)
                self.assertEqual(headers.get("cache-control"), "no-store")
                if method == "HEAD":
                    wire = raw(self.url, f"HEAD {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
                    head, wire_body = wire.split(b"\r\n\r\n", 1)
                    self.assertIn(b" 405 ", head.split(b"\r\n", 1)[0])
                    self.assertIn(b"cache-control: no-store", head.lower())
                    self.assertIn(f"allow: {allow}".lower().encode(), head.lower())
                    self.assertEqual(wire_body, b"")
                else:
                    self.assertEqual(json.loads(body), error("METHOD_NOT_ALLOWED"))

    def test_i_011_query_rejected_before_put(self):
        self.seeded()
        with patch.object(self.store, "set", wraps=self.store.set) as set_value:
            for method, path in (("GET", "/keys/kept?x=1"), ("GET", "/keys/kept?"),
                                 ("GET", "/keys/kept/exists?x=1"), ("PUT", "/keys/kept?x=1")):
                with self.subTest(path=path):
                    self.check(method, path, 400, error("INVALID_QUERY"))
            set_value.assert_not_called()
        self.unchanged()

    def test_i_012_routing_precedence(self):
        self.seeded()
        for method, path, status, code in (("POST", "/keys/a?x=1", 405, "METHOD_NOT_ALLOWED"),
                                          ("GET", "/keys/a/b?x=1", 400, "INVALID_KEY"),
                                          ("POST", "/unrelated?x=1", 404, "ROUTE_NOT_FOUND"),
                                          ("PUT", "/keys/a/b", 400, "INVALID_KEY")):
            with self.subTest(path=path):
                response = request(self.url, method, path)
                result(self, response, status, error(code))
                if status == 405:
                    self.assertEqual(response[1].get("allow"), "GET, PUT, DELETE")
        self.unchanged()

    def test_i_013_malformed_json(self):
        self.seeded()
        with patch.object(self.store, "set", wraps=self.store.set) as set_value:
            for body in (b"{", b"null", b"[]", b"", b'\xff'):
                with self.subTest(body=body):
                    self.check("PUT", "/keys/kept", 400, error("INVALID_BODY"), body=body,
                               headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
            set_value.assert_not_called()
        self.unchanged()

    def test_i_014_invalid_fields(self):
        self.seeded()
        with patch.object(self.store, "set", wraps=self.store.set) as set_value:
            for body in ({}, {"value": None}, {"value": 1}, {"value": True},
                         {"value": "ok", "extra": 1}):
                with self.subTest(body=body):
                    self.check("PUT", "/keys/kept", 400, error("INVALID_BODY"),
                               body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            set_value.assert_not_called()
        self.unchanged()

    def test_i_015_content_type_exact(self):
        self.seeded()
        with patch.object(self.store, "set", wraps=self.store.set) as set_value:
            for headers in ({}, {"Content-Type": "text/plain"},
                            {"Content-Type": "application/json; charset=utf-8"}):
                with self.subTest(headers=headers):
                    self.check("PUT", "/keys/kept", 400, error("INVALID_BODY"),
                               body=b'{"value":"changed"}', headers=headers)
            set_value.assert_not_called()
        self.unchanged()

    def test_i_016_declared_length_limit(self):
        self.seeded()
        reads = []
        original_handler = self.server.RequestHandlerClass

        class BodyReadProbe:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                value = getattr(self.stream, name)
                if name not in ("read", "read1", "readinto", "readinto1", "readline", "readlines", "peek"):
                    return value

                def counted(*args, **kwargs):
                    reads.append(name)
                    return value(*args, **kwargs)

                return counted

        class ProbedHandler(original_handler):
            def parse_request(self):
                accepted = super().parse_request()
                if accepted:
                    self.rfile = BodyReadProbe(self.rfile)
                return accepted

        prefix = b'{"value":"'
        suffix = b'"}'
        for size, expected in ((65536, 200), (65537, 400)):
            with self.subTest(size=size):
                body = prefix + b"a" * (size - len(prefix) - len(suffix)) + suffix
                headers = (b"Content-Type: application/json", f"Content-Length: {size}".encode())
                with patch.object(self.store, "set", wraps=self.store.set) as set_value:
                    if size == 65536:
                        payload = raw_put("/keys/large", body, *headers, b"Connection: close")
                        response = raw(self.url, payload)
                    else:
                        # A declared oversize body must be rejected before any body byte is sent.
                        self.server.RequestHandlerClass = ProbedHandler
                        try:
                            response = early_rejection(self.url, raw_put("/keys/large", b"", *headers), NEXT_GET)
                        finally:
                            self.server.RequestHandlerClass = original_handler
                        self.assertEqual(reads, [], "oversize rejection must not read the request body")
                    self.assertIn(f" {expected} ".encode(), response.split(b"\r\n", 1)[0])
                    if size == 65537:
                        self.raw_error(response, "INVALID_BODY")
                        self.assertEqual(response.count(b"HTTP/1."), 1)
                    self.assertEqual(set_value.call_count, int(size == 65536))
        self.assertEqual(self.store.get("large"), (True, "a" * (65536 - len(prefix) - len(suffix))))
        self.unchanged()

    def test_i_017_invalid_content_length(self):
        self.seeded()
        for fields in ((b"Content-Type: application/json",),
                       (b"Content-Type: application/json", b"Content-Length: 0"),
                       (b"Content-Type: application/json", b"Content-Length: -1"),
                       (b"Content-Type: application/json", b"Content-Length: +4"),
                       (b"Content-Type: application/json", b"Content-Length: \xff"),
                       (b"Content-Type: application/json", b"Content-Length: 1, 1"),
                       (b"Content-Type: application/json", b"Content-Length: 4", b"Content-Length: 4")):
            with self.subTest(fields=fields), patch.object(self.store, "set", wraps=self.store.set) as set_value:
                response = raw(self.url, raw_put("/keys/kept", b"", *fields) + NEXT_GET)
                self.raw_error(response, "INVALID_BODY")
                self.assertEqual(response.count(b"HTTP/1."), 1)
                set_value.assert_not_called()
        self.unchanged()

    def test_i_017_long_zero_content_length_and_leading_zeros(self):
        self.seeded()
        fields = (b"Content-Type: application/json", b"Content-Length: " + b"0" * 5000)
        with patch.object(self.store, "set", wraps=self.store.set) as set_value:
            self.raw_error(raw(self.url, raw_put("/keys/kept", b"", *fields)), "INVALID_BODY")
            set_value.assert_not_called()
        self.unchanged()
        body = b'{"value":"after"}'
        fields = (b"Content-Type: application/json",
                  b"Content-Length: " + b"0" * 5000 + str(len(body)).encode())
        response = raw(self.url, raw_put("/keys/kept", body, *fields))
        self.assertIn(b" 200 ", response.split(b"\r\n", 1)[0])
        self.check("GET", "/keys/kept", 200, {"value": "after"})

    def test_i_018_transfer_encoding_rejected(self):
        self.seeded()
        for fields in ((b"Transfer-Encoding: chunked",),
                       (b"Transfer-Encoding: chunked", b"Content-Length: 20")):
            with self.subTest(fields=fields), patch.object(self.store, "set", wraps=self.store.set) as set_value:
                response = raw(self.url, raw_put("/keys/kept", b"", b"Content-Type: application/json",
                                                      *fields) + NEXT_GET)
                self.raw_error(response, "INVALID_BODY")
                self.assertEqual(response.count(b"HTTP/1."), 1)
                set_value.assert_not_called()
        self.unchanged()

    def test_i_019_short_body_does_not_write(self):
        self.seeded()
        with patch.object(self.store, "set", wraps=self.store.set) as set_value:
            raw(self.url, raw_put("/keys/kept", b'{"value":', b"Content-Type: application/json",
                                  b"Content-Length: 200", b"Connection: close"), half_close=True)
            set_value.assert_not_called()
        self.unchanged()

    def test_i_020_rejected_body_closes_connection(self):
        self.seeded()
        payload = raw_put("/keys/kept", b"bad" + b"GET /keys/kept HTTP/1.1\r\nHost: localhost\r\n\r\n",
                          b"Content-Type: text/plain", b"Content-Length: 3")
        with patch.object(self.store, "set", wraps=self.store.set) as set_value:
            response = raw(self.url, payload)
            self.assertEqual(response.count(b"HTTP/1.1 ") + response.count(b"HTTP/1.0 "), 1)
            self.raw_error(response, "INVALID_BODY")
            set_value.assert_not_called()
        self.unchanged()

    def test_i_021_internal_error_is_not_input_error(self):
        self.seeded()
        for operation, method, path in (("get", "GET", "/keys/kept"),
                                        ("set", "PUT", "/keys/kept"),
                                        ("exists", "GET", "/keys/kept/exists"),
                                        ("delete", "DELETE", "/keys/kept")):
            with self.subTest(operation=operation):
                for failure in (TypeError("private secret"), RuntimeError("private secret")):
                    with patch.object(self.store, operation, side_effect=failure):
                        response = put(self.url, "kept", "changed") if method == "PUT" else request(self.url, method, path)
                    result(self, response, 500, error("INTERNAL_ERROR"))
                    self.assertNotIn(b"private secret", response[2])
                    self.unchanged()

    def test_i_022_no_store_on_all_final_responses(self):
        self.seeded()
        requests = (("GET", "/keys/kept"), ("PUT", "/keys/kept"),
                    ("GET", "/keys/kept/exists"), ("DELETE", "/keys/absent"),
                    ("GET", "/keys/absent"), ("GET", "/keys/"),
                    ("GET", "/keys/kept?"), ("POST", "/keys/kept"),
                    ("GET", "/unrelated"), ("HEAD", "/keys/kept"))
        for method, path in requests:
            with self.subTest(method=method, path=path):
                self.assertEqual(request(self.url, method, path)[1].get("cache-control"), "no-store")
        self.assertEqual(request(self.url, "PUT", "/keys/kept", body=b"{}",
                                 headers={"Content-Type": "application/json"})[1].get("cache-control"), "no-store")
        with patch.object(self.store, "get", side_effect=RuntimeError("secret")):
            self.assertEqual(request(self.url, "GET", "/keys/kept")[1].get("cache-control"), "no-store")

    def test_i_023_server_lifetime(self):
        put(self.url, "a", "lifetime")
        self.check("GET", "/keys/a", 200, {"value": "lifetime"})
        api = module("mini_redis.http_api")
        with running(api.create_server(HOST, 0, HashTableStore())) as other:
            result(self, request(other, "GET", "/keys/a"), 404, error("KEY_NOT_FOUND"))


class ExampleContractTests(unittest.TestCase):
    """Black-box one-shot client against separate local HTTP server processes."""

    def setUp(self):
        module("examples.client")
        module("examples.origin_api")
        module("mini_redis.http_api")
        self.processes = []
        self.addCleanup(self.stop_servers)

    def stop_servers(self):
        for process in self.processes:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=3)
        self.processes.clear()

    def start(self, name):
        with socket.socket() as reserved:
            reserved.bind((HOST, 0))
            port = reserved.getsockname()[1]
        process = subprocess.Popen([sys.executable, "-m", name, "--host", HOST, "--port", str(port)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes.append(process)
        url = f"http://{HOST}:{port}"
        for _ in range(60):
            if process.poll() is not None:
                _, stderr = process.communicate()
                self.fail(f"{name} exited before ready: {stderr.decode(errors='replace')}")
            try:
                # An unknown route is enough to show that the listening socket is ready.
                request(url, "GET", "/not-a-route")
                return url
            except (OSError, http.client.HTTPException):
                time.sleep(0.05)
        self.fail(f"{name} did not become ready")

    def client(self, cache, origin):
        return subprocess.run([sys.executable, "-m", "examples.client", "--cache-url", cache,
                               "--origin-url", origin], text=True, capture_output=True, timeout=5)

    def test_e_001_miss_then_hit(self):
        cache, origin = self.start("mini_redis.http_api"), self.start("examples.origin_api")
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 0}, no_store=False)
        first = self.client(cache, origin)
        self.assertEqual((first.returncode, first.stdout.strip()), (0, "sample-response"), first.stderr)
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 1}, no_store=False)
        second = self.client(cache, origin)
        self.assertEqual((second.returncode, second.stdout.strip()), (0, "sample-response"), second.stderr)
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 1}, no_store=False)
        result(self, request(cache, "GET", "/keys/example-demo"), 200, {"value": "sample-response"})

    def test_e_002_empty_hit(self):
        cache, origin = self.start("mini_redis.http_api"), self.start("examples.origin_api")
        put(cache, "example-demo", "")
        response = self.client(cache, origin)
        self.assertEqual((response.returncode, response.stdout), (0, "\n"), response.stderr)
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 0}, no_store=False)

    def test_e_003_cache_failure_does_not_fallback(self):
        origin = self.start("examples.origin_api")
        with socket.socket() as reserved:
            reserved.bind((HOST, 0))
            cache = f"http://{HOST}:{reserved.getsockname()[1]}"
            response = self.client(cache, origin)
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(response.stdout, "")
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 0}, no_store=False)
        with running(self.fake(500, error("INTERNAL_ERROR"))) as cache:
            response = self.client(cache, origin)
            self.assertNotEqual(response.returncode, 0)
            self.assertEqual(response.stdout, "")
        with running(self.fake(404, error("ROUTE_NOT_FOUND"))) as cache:
            response = self.client(cache, origin)
            self.assertNotEqual(response.returncode, 0)
            self.assertEqual(response.stdout, "")
        with running(self.fake(200, {"unexpected": "body"})) as cache:
            response = self.client(cache, origin)
            self.assertNotEqual(response.returncode, 0)
            self.assertEqual(response.stdout, "")
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 0}, no_store=False)

    def test_e_003_cache_redirect_does_not_call_origin(self):
        origin = self.start("examples.origin_api")

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", origin + "/items/demo")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format, *args):
                pass

        with running(HTTPServer((HOST, 0), Redirect)) as cache:
            response = self.client(cache, origin)
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(response.stdout, "")
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 0}, no_store=False)

    def fake(self, status, payload):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                pass

        return HTTPServer((HOST, 0), Handler)

    def test_e_004_origin_failure_does_not_write(self):
        writes = []

        class Cache(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps(error("KEY_NOT_FOUND")).encode()
                self.send_response(404)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_PUT(self):
                writes.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        with running(HTTPServer((HOST, 0), Cache)) as cache:
            with running(self.fake(500, error("ORIGIN_FAILURE"))) as origin:
                response = self.client(cache, origin)
                self.assertNotEqual(response.returncode, 0)
                self.assertEqual(response.stdout, "")
                self.assertEqual(writes, [])
            with running(self.fake(200, {"value": 1})) as origin:
                response = self.client(cache, origin)
                self.assertNotEqual(response.returncode, 0)
                self.assertEqual(response.stdout, "")
                self.assertEqual(writes, [])
            with socket.socket() as reserved:
                reserved.bind((HOST, 0))
                response = self.client(cache, f"http://{HOST}:{reserved.getsockname()[1]}")
            self.assertNotEqual(response.returncode, 0)
            self.assertEqual(response.stdout, "")
            self.assertEqual(writes, [])

    def test_e_005_put_failure_is_not_success(self):
        origin = self.start("examples.origin_api")

        class Handler(BaseHTTPRequestHandler):
            put_status = 200
            put_payload: object = {"stored": False}

            def do_GET(self):
                data = json.dumps(error("KEY_NOT_FOUND")).encode()
                self.send_response(404)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_PUT(self):
                data = json.dumps(self.put_payload).encode()
                self.send_response(self.put_status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                pass

        with running(HTTPServer((HOST, 0), Handler)) as cache:
            response = self.client(cache, origin)
            self.assertNotEqual(response.returncode, 0)
            self.assertEqual(response.stdout, "")
            Handler.put_status = 500
            Handler.put_payload = error("INTERNAL_ERROR")
            response = self.client(cache, origin)
            self.assertNotEqual(response.returncode, 0)
            self.assertEqual(response.stdout, "")
            def disconnect(self):
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)

            with patch.object(Handler, "do_PUT", disconnect):
                response = self.client(cache, origin)
                self.assertNotEqual(response.returncode, 0)
                self.assertEqual(response.stdout, "")
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 3}, no_store=False)

    def test_e_005_numeric_stored_is_not_true(self):
        origin = self.start("examples.origin_api")
        stored: list[object] = [None]

        class Cache(BaseHTTPRequestHandler):
            def do_GET(self):
                self.reply(404, error("KEY_NOT_FOUND"))

            def do_PUT(self):
                self.reply(200, {"stored": stored[0]})

            def reply(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                pass

        server = HTTPServer((HOST, 0), Cache)
        with running(server) as cache:
            for value in (1, 1.0):
                with self.subTest(value=value):
                    stored[0] = value
                    response = self.client(cache, origin)
                    self.assertNotEqual(response.returncode, 0)
                    self.assertEqual(response.stdout, "")
            stored[0] = True
            response = self.client(cache, origin)
            self.assertEqual((response.returncode, response.stdout), (0, "sample-response\n"))

    def test_e_006_restart_resets_server_state(self):
        cache, origin = self.start("mini_redis.http_api"), self.start("examples.origin_api")
        self.assertEqual(self.client(cache, origin).returncode, 0)
        self.stop_servers()
        cache, origin = self.start("mini_redis.http_api"), self.start("examples.origin_api")
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 0}, no_store=False)
        result(self, request(cache, "GET", "/keys/example-demo"), 404, error("KEY_NOT_FOUND"))
        self.assertEqual(self.client(cache, origin).returncode, 0)
        result(self, request(origin, "GET", "/origin-calls"), 200, {"count": 1}, no_store=False)


if __name__ == "__main__":
    unittest.main()
