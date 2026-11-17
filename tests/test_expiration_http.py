"""Iteration 04 HTTP/server contract tests (expected RED until TTL is implemented).

Provisional clock keyword: HashTableStore(clock=monotonic_ns_callable). The HTTP
create_server(host, port, store) seam exists. Fault-injection and periodic-loop
observations use the supplied store; adapt private hooks if the chosen sweep
implementation has different boundaries. No product code is supplied here.
"""
from contextlib import ExitStack
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from mini_redis.http_api import create_server
from mini_redis.store import HashTableStore
from test_http_api import HOST, early_rejection, error, put, raw, raw_put, request, result as base_result
from test_expiration_store import Clock, SECOND


def result(test, response, status, expected):
    base_result(test, response, status, expected)
    actual = json.loads(response[2])
    for field in ("ttl_set", "ttl_removed"):
        if field in expected:
            test.assertIs(type(actual[field]), bool)


class ExpirationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        try:
            self.store = HashTableStore(clock=self.clock)
        except TypeError as exc:
            raise AssertionError("Implementation missing: injectable monotonic-ns clock (provisional clock keyword)") from exc
        self.server = create_server(HOST, 0, self.store)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.url = f"http://{HOST}:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive(), "server did not stop")

    def check(self, method, path, status, expected, **kwargs):
        response = request(self.url, method, path, **kwargs)
        result(self, response, status, expected)
        return response

    def ttl(self, key="k", seconds=2):
        body = json.dumps({"ttl_seconds": seconds}).encode()
        return self.check("PUT", f"/keys/{key}/ttl", 200, {"ttl_set": True},
                          body=body, headers={"Content-Type": "application/json"})

    def seed(self, key="k", value="before", seconds=2):
        result(self, put(self.url, key, value), 200, {"stored": True})
        self.ttl(key, seconds)
        return self.clock.now + seconds * SECOND

    def preserved(self, deadline, key="k", value="before"):
        self.check("GET", f"/keys/{key}", 200, {"value": value})
        self.clock.now = deadline - 1
        self.check("GET", f"/keys/{key}", 200, {"value": value})
        self.clock.now = deadline
        self.check("GET", f"/keys/{key}", 404, error("KEY_NOT_FOUND"))

    def raw_error(self, wire, status, code):
        head, body = wire.split(b"\r\n\r\n", 1)
        self.assertIn(f" {status} ".encode(), head.split(b"\r\n", 1)[0])
        self.assertIn(b"cache-control: no-store", head.lower())
        self.assertEqual(json.loads(body), error(code))

    def fresh(self, value="before", seconds=2):
        self.clock.now = 100 * SECOND
        deadline = self.seed(value=value, seconds=seconds)
        return deadline

    def test_i_001_empty_value_before_and_at_expiration(self):
        for offset in (-1, 0, 1):
            for operation in ("GET", "EXISTS", "DELETE"):
                with self.subTest(offset=offset, operation=operation):
                    # Independent key per observation: DELETE and lazy cleanup mutate state.
                    key = f"k{offset + 1}{operation.lower()}"
                    deadline = self.seed(key, "")
                    self.clock.now = deadline + offset
                    method = "GET" if operation == "EXISTS" else operation
                    path = f"/keys/{key}" + ("/exists" if operation == "EXISTS" else "")
                    if operation == "DELETE":
                        expected = (200, {"deleted": offset < 0})
                    elif operation == "EXISTS":
                        expected = (200, {"exists": offset < 0})
                    else:
                        expected = (200, {"value": ""}) if offset < 0 else (404, error("KEY_NOT_FOUND"))
                    self.check(method, path, *expected)
                    self.clock.now = 100 * SECOND

    def test_i_002_refresh_clear_missing_and_expired_ttl(self):
        old = self.seed()
        self.clock.now += SECOND
        new = self.clock.now + 2 * SECOND
        self.ttl()
        self.clock.now = old + 1
        self.check("GET", "/keys/k", 200, {"value": "before"})
        self.clock.now = new
        self.check("GET", "/keys/k", 404, error("KEY_NOT_FOUND"))
        old = self.fresh(value="persist")
        self.check("DELETE", "/keys/k/ttl", 200, {"ttl_removed": True})
        self.check("DELETE", "/keys/k/ttl", 200, {"ttl_removed": False})
        self.clock.now = old + 1
        self.check("GET", "/keys/k", 200, {"value": "persist"})
        self.check("PUT", "/keys/missing/ttl", 404, error("KEY_NOT_FOUND"),
                   body=b'{"ttl_seconds":2}', headers={"Content-Type": "application/json"})
        self.check("DELETE", "/keys/missing/ttl", 200, {"ttl_removed": False})
        old = self.seed("expired", "stale")
        self.clock.now = old
        self.check("PUT", "/keys/expired/ttl", 404, error("KEY_NOT_FOUND"),
                   body=b'{"ttl_seconds":2}', headers={"Content-Type": "application/json"})
        self.check("DELETE", "/keys/expired/ttl", 200, {"ttl_removed": False})
        self.check("GET", "/keys/expired", 404, error("KEY_NOT_FOUND"))

    def test_i_003_put_clears_ttl_delete_then_reinsert(self):
        old = self.seed()
        result(self, put(self.url, "k", "new"), 200, {"stored": True})
        self.clock.now = old + 1
        self.check("GET", "/keys/k", 200, {"value": "new"})
        old = self.seed("gone", "stale")
        self.check("DELETE", "/keys/gone", 200, {"deleted": True})
        result(self, put(self.url, "gone", "fresh"), 200, {"stored": True})
        self.clock.now = old + 1
        self.check("GET", "/keys/gone", 200, {"value": "fresh"})
        self.check("GET", "/keys/k", 200, {"value": "new"})
        self.check("PUT", "/keys/k", 400, error("INVALID_BODY"),
                   body=b'{"value":"bad","ttl_seconds":2}', headers={"Content-Type": "application/json"})
        self.check("GET", "/keys/k", 200, {"value": "new"})

    def test_i_004_invalid_ttl_json_preserves_value_and_deadline(self):
        bodies = (b"{}", b'{"extra":1}', b'{"ttl_seconds":2,"extra":1}',
                  *(json.dumps({"ttl_seconds": value}).encode() for value in
                    (0, -1, 1.5, "2", True, None)), b"[]", b"{", b"\xff")
        for body in bodies:
            with self.subTest(body=body):
                deadline = self.fresh()
                with patch.object(self.store, "set_ttl", wraps=self.store.set_ttl) as setter:
                    self.check("PUT", "/keys/k/ttl", 400, error("INVALID_BODY"),
                               body=body, headers={"Content-Type": "application/json"})
                    setter.assert_not_called()
                self.preserved(deadline)

    def test_i_005_framing_and_media_type_fail_before_store(self):
        body = b'{"ttl_seconds":3}'
        fields = ((b"Content-Length: 17",),
                  (b"Content-Type: text/plain", b"Content-Length: 17"),
                  (b"Content-Type: application/json; charset=utf-8", b"Content-Length: 17"),
                  (b"Content-Type: application/json",),
                  *((b"Content-Type: application/json", b"Content-Length: " + length)
                    for length in (b"0", b"-1", b"+17", b"17, 17")),
                  (b"Content-Type: application/json", b"Content-Length: 17", b"Content-Length: 17"),
                  (b"Content-Type: application/json", b"Transfer-Encoding: chunked"),
                  (b"Content-Type: application/json", b"Content-Length: 17", b"Transfer-Encoding: chunked"))
        for headers in fields:
            with self.subTest(headers=headers):
                deadline = self.fresh()
                with patch.object(self.store, "set_ttl", wraps=self.store.set_ttl) as setter:
                    wire = raw(self.url, raw_put("/keys/k/ttl", body, *headers))
                    self.raw_error(wire, 400, "INVALID_BODY")
                    setter.assert_not_called()
                self.preserved(deadline)

    def test_i_006_body_length_limit_rejects_before_read(self):
        deadline = self.seed()
        prefix, suffix = b'{"ttl_seconds":', b"}"
        body = prefix + b"1" + b"0" * (65536 - len(prefix) - len(suffix) - 1) + suffix
        wire = raw(self.url, raw_put("/keys/k/ttl", body,
                   b"Content-Type: application/json", b"Content-Length: 65536"))
        head, payload = wire.split(b"\r\n\r\n", 1)
        self.assertIn(b" 200 ", head.split(b"\r\n", 1)[0])
        self.assertEqual(json.loads(payload), {"ttl_set": True})
        self.assertIs(type(json.loads(payload)["ttl_set"]), bool)
        self.clock.now = deadline
        self.check("GET", "/keys/k", 200, {"value": "before"})
        # Reseed before the rejected case: normal 65,536-byte request changed TTL.
        self.clock.now = 100 * SECOND
        deadline = self.seed()
        reads = []
        original = self.server.RequestHandlerClass
        class ReadProbe:
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
        class Probed(original):
            def parse_request(self):
                accepted = super().parse_request()
                if accepted:
                    self.rfile = ReadProbe(self.rfile)
                return accepted
        self.server.RequestHandlerClass = Probed
        try:
            headers = raw_put("/keys/k/ttl", b"", b"Content-Type: application/json", b"Content-Length: 65537")
            with ExitStack() as stack:
                calls = [stack.enter_context(patch.object(self.store, name, wraps=getattr(self.store, name)))
                         for name in ("set", "get", "exists", "delete", "set_ttl", "clear_ttl")]
                wire = early_rejection(self.url, headers, b"GET /keys/k HTTP/1.1\r\nHost: localhost\r\n\r\n")
                for call in calls:
                    call.assert_not_called()
        finally:
            self.server.RequestHandlerClass = original
        self.raw_error(wire, 400, "INVALID_BODY")
        self.assertEqual(reads, [], "declared oversize body must not be read")
        self.assertEqual(wire.count(b"HTTP/1."), 1)
        self.preserved(deadline)

    def test_i_007_short_ttl_body_does_not_change_key(self):
        for half_close in (True, False):
            with self.subTest(half_close=half_close):
                deadline = self.fresh()
                with patch.object(self.store, "set_ttl", wraps=self.store.set_ttl) as setter:
                    wire = raw(self.url, raw_put("/keys/k/ttl", b'{"ttl_seconds":',
                               b"Content-Type: application/json", b"Content-Length: 200"),
                               half_close=half_close)
                    setter.assert_not_called()
                self.assertNotIn(b" 200 ", wire.split(b"\r\n", 1)[0])
                self.preserved(deadline)

    def test_i_008_large_json_integer_preserves_exact_deadline(self):
        # JSON's default int conversion limit must not silently cap a valid body.
        for text in ("9007199254740993", "1" + "0" * 5000 + "1"):
            with self.subTest(digits=len(text)):
                self.clock.now = 100 * SECOND
                result(self, put(self.url, "k", "before"), 200, {"stored": True})
                start = self.clock.now
                wire = raw(self.url, raw_put("/keys/k/ttl", b'{"ttl_seconds":' + text.encode() + b'}',
                            b"Content-Type: application/json", f"Content-Length: {len(text)+16}".encode()))
                head, payload = wire.split(b"\r\n\r\n", 1)
                self.assertIn(b" 200 ", head.split(b"\r\n", 1)[0])
                self.assertEqual(json.loads(payload), {"ttl_set": True})
                self.assertIs(type(json.loads(payload)["ttl_set"]), bool)
                seconds = int(text, 10) if len(text) < 4300 else 10 ** (len(text) - 1) + 1
                self.clock.now = start + seconds * SECOND - 1
                self.check("GET", "/keys/k", 200, {"value": "before"})
                self.clock.now += 1
                self.check("GET", "/keys/k", 404, error("KEY_NOT_FOUND"))

    def test_i_009_ttl_exists_keys_and_invalid_subpaths(self):
        for key in ("ttl", "exists"):
            result(self, put(self.url, key, key), 200, {"stored": True})
            self.check("GET", f"/keys/{key}", 200, {"value": key})
            self.check("DELETE", f"/keys/{key}", 200, {"deleted": True})
        for path in ("/keys/a/ttl/exists", "/keys/a/unknown", "/keys/%61/ttl", "/keys/./ttl"):
            with self.subTest(path=path), patch.object(self.store, "set_ttl", wraps=self.store.set_ttl) as setter:
                self.check("PUT", path, 400, error("INVALID_KEY"))
                setter.assert_not_called()

    def test_i_010_ttl_route_precedence_head_and_allow(self):
        for method in ("GET", "POST", "OPTIONS", "HEAD"):
            with self.subTest(method=method):
                wire = raw(self.url, f"{method} /keys/k/ttl HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
                head, body = wire.split(b"\r\n\r\n", 1)
                self.assertIn(b" 405 ", head.split(b"\r\n", 1)[0])
                self.assertIn(b"allow: put, delete", head.lower())
                self.assertIn(b"cache-control: no-store", head.lower())
                if method == "HEAD":
                    self.assertEqual(body, b"")
                else:
                    self.assertEqual(json.loads(body), error("METHOD_NOT_ALLOWED"))
        for method, path, status, code in (("DELETE", "/keys/k/ttl?", 400, "INVALID_QUERY"),
                                          ("PUT", "/keys/k/ttl?x=1", 400, "INVALID_QUERY"),
                                          ("POST", "/keys/k/ttl?x=1", 405, "METHOD_NOT_ALLOWED"),
                                          ("PUT", "/keys/a/ttl/exists?x=1", 400, "INVALID_KEY"),
                                          ("POST", "/unrelated?x=1", 404, "ROUTE_NOT_FOUND")):
            with self.subTest(method=method, path=path), patch.object(self.store, "set_ttl", wraps=self.store.set_ttl) as setter:
                self.check(method, path, status, error(code))
                setter.assert_not_called()

    def test_i_011_store_errors_are_internal_errors(self):
        deadline = self.seed()
        for method, path, name in (("PUT", "/keys/k/ttl", "set_ttl"),
                                   ("DELETE", "/keys/k/ttl", "clear_ttl"),
                                   ("GET", "/keys/k", "get"),
                                   ("DELETE", "/keys/k", "delete")):
            with self.subTest(name=name), patch.object(self.store, name, side_effect=TypeError("secret")):
                body = b'{"ttl_seconds":2}' if method == "PUT" else None
                response = request(self.url, method, path, body=body,
                                   headers={"Content-Type": "application/json"} if body else None)
                result(self, response, 500, error("INTERNAL_ERROR"))
                self.assertNotIn(b"secret", response[2])
        self.preserved(deadline)

    def test_i_012_no_store_on_new_success_and_error_paths(self):
        self.seed()
        responses = (request(self.url, "PUT", "/keys/k/ttl", body=b'{"ttl_seconds":3}',
                             headers={"Content-Type": "application/json"}),
                     request(self.url, "DELETE", "/keys/k/ttl"),
                     request(self.url, "DELETE", "/keys/k/ttl"),
                     request(self.url, "PUT", "/keys/missing/ttl", body=b'{"ttl_seconds":2}',
                             headers={"Content-Type": "application/json"}),
                     request(self.url, "PUT", "/keys/k/ttl", body=b'{"ttl_seconds":0}',
                             headers={"Content-Type": "application/json"}),
                     request(self.url, "GET", "/keys/k/ttl"),
                     request(self.url, "DELETE", "/keys/k/ttl?x=1"))
        for response in responses:
            self.assertEqual(response[1].get("cache-control"), "no-store")
        self.assertEqual(responses[5][1].get("allow"), "PUT, DELETE")
        with patch.object(self.store, "set_ttl", side_effect=RuntimeError("secret")):
            self.assertEqual(request(self.url, "PUT", "/keys/k/ttl", body=b'{"ttl_seconds":2}',
                                     headers={"Content-Type": "application/json"})[1].get("cache-control"), "no-store")

    def test_i_013_idle_periodic_sweep_and_shutdown(self):
        self.seed()
        self.clock.now += 2 * SECOND
        # Allow the server's fixed 1s target interval; never access the key.
        deadline = time.monotonic() + 3
        while self.store._size and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.store._size, 0, "idle server did not sweep expired entry")
        with patch.object(self.store, "sweep_expired", wraps=self.store.sweep_expired) as sweep:
            self.stop()
            stopped_count = sweep.call_count
            time.sleep(1.2)
            self.assertEqual(sweep.call_count, stopped_count, "sweep continued after shutdown")
        # stop() is also a cleanup; shutdown is idempotent in HTTPServer.

    def test_i_014_sweep_failure_isolated_and_retried_next_interval(self):
        self.seed()
        original = self.store.sweep_expired
        attempts = []
        def once():
            attempts.append(time.monotonic())
            if len(attempts) == 1:
                raise RuntimeError("injected sweep failure")
            return original()
        with patch.object(self.store, "sweep_expired", side_effect=once):
            self.clock.now += 2 * SECOND
            deadline = time.monotonic() + 4
            while len(attempts) < 1 and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(len(attempts), 1)
            self.check("GET", "/keys/other", 404, error("KEY_NOT_FOUND"))
            time.sleep(0.05)
            self.assertEqual(len(attempts), 1, "immediate retry rather than next interval")
            while len(attempts) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertGreaterEqual(len(attempts), 2)
            self.assertEqual(self.store._size, 0)
        # Diagnostic output failure and precise loop scheduling are provisional
        # injection seams; review-only until the server implementation chooses them.

    def test_i_015_legacy_contract_regression_smoke(self):
        result(self, put(self.url, "plain", ""), 200, {"stored": True})
        self.check("GET", "/keys/plain", 200, {"value": ""})
        self.check("GET", "/keys/plain/exists", 200, {"exists": True})
        self.check("DELETE", "/keys/plain", 200, {"deleted": True})
        self.check("DELETE", "/keys/plain", 200, {"deleted": False})
        self.check("GET", "/keys/plain", 404, error("KEY_NOT_FOUND"))
        self.check("GET", "/keys/", 400, error("INVALID_KEY"))
        self.check("PUT", "/keys/plain", 400, error("INVALID_BODY"), body=b"{}",
                   headers={"Content-Type": "application/json"})
        self.check("GET", "/unrelated", 404, error("ROUTE_NOT_FOUND"))
        # Full 2/3 regression suites are run separately, not renamed as TC-04.


if __name__ == "__main__":
    unittest.main()
