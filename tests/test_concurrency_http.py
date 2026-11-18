"""Iteration 05 HTTP concurrency contracts (expected RED on the sequential server).

One test_i_NNN corresponds to TC-05-I-NNN. R-001/002 are code-review-only.
The public seam create_server(host, port, store) already exists. The fault and
submission seams in tests 021/023/025 are provisional: adapt their names to
implementation, never add production hooks solely to satisfy these probes.
"""

import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from mini_redis.http_api import create_server
from mini_redis.store import HashTableStore
from test_http_api import HOST, early_rejection, error, put, raw, request, result

SECOND = 1_000_000_000


class Clock:
    def __init__(self):
        self.now = 100 * SECOND

    def __call__(self):
        return self.now


class ObservedStore(HashTableStore):
    """Record real store calls; never replace the storage implementation."""

    def __init__(self, clock):
        super().__init__(clock=clock)
        self.calls = []
        self.executions = []
        self.active = 0
        self.active_threads = {}
        self.overlap = False
        self.lock = threading.Lock()
        self.block = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def _call(self, name, key, operation, detail=None):
        with self.lock:
            self.active += 1
            ident = threading.get_ident()
            self.overlap |= any(other != ident for other in self.active_threads)
            self.active_threads[ident] = self.active_threads.get(ident, 0) + 1
            self.calls.append((name, key, ident, "enter"))
            self.executions.append((name, key, detail))
        try:
            if self.block == (name, key):
                self.entered.set()
                if not self.release.wait(8):
                    raise AssertionError("blocked store operation was not released")
            return operation()
        finally:
            with self.lock:
                self.calls.append((name, key, threading.get_ident(), "exit"))
                self.active -= 1
                self.active_threads[ident] -= 1
                if not self.active_threads[ident]:
                    del self.active_threads[ident]

    def set(self, key, value):
        return self._call("set", key, lambda: super(ObservedStore, self).set(key, value), value)

    def get(self, key):
        return self._call("get", key, lambda: super(ObservedStore, self).get(key))

    def exists(self, key):
        return self._call("exists", key, lambda: super(ObservedStore, self).exists(key))

    def delete(self, key):
        return self._call("delete", key, lambda: super(ObservedStore, self).delete(key))

    def set_ttl(self, key, seconds):
        return self._call("set_ttl", key, lambda: super(ObservedStore, self).set_ttl(key, seconds))

    def clear_ttl(self, key):
        return self._call("clear_ttl", key, lambda: super(ObservedStore, self).clear_ttl(key))

    def sweep_expired(self):
        return self._call("sweep_expired", None, lambda: super(ObservedStore, self).sweep_expired())

    def _rehash(self):
        return self._call("rehash", None, lambda: super(ObservedStore, self)._rehash())

    def hold(self, name, key):
        self.entered.clear()
        self.release.clear()
        self.block = name, key

    def unblock(self):
        self.block = None
        self.release.set()


def wire(method, path, *, body=b"", length=None):
    headers = (f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
               + ("Content-Type: application/json\r\n" if method == "PUT" else "")
               + (f"Content-Length: {len(body) if length is None else length}\r\n" if method == "PUT" else "")
               + "\r\n").encode()
    return headers + body


def parsed(wire_bytes):
    head, separator, body = wire_bytes.partition(b"\r\n\r\n")
    if not separator:
        raise AssertionError("incomplete HTTP response")
    lines = head.split(b"\r\n")
    status = int(lines[0].split()[1])
    headers = dict(line.decode("latin1").lower().split(": ", 1) for line in lines[1:])
    return status, headers, body


class ConcurrencyHTTPTests(unittest.TestCase):
    def setUp(self):
        if self._testMethodName.startswith(("test_i_023_", "test_i_024_", "test_i_025_")) \
                and not os.environ.get("MINI_REDIS_LIFECYCLE_CHILD"):
            return  # The parent owns only the watchdog, not server threads.
        self.clock = Clock()
        self.store = ObservedStore(self.clock)
        self.server = create_server(HOST, 0, self.store)
        self.addCleanup(self.server.server_close)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.stop)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=32)
        self.addCleanup(self.pool.shutdown, wait=False, cancel_futures=True)
        self.addCleanup(self.store.unblock)
        self.url = f"http://{HOST}:{self.server.server_address[1]}"
        self.address = (HOST, self.server.server_address[1])

    def run_isolated(self):
        if os.environ.get("MINI_REDIS_LIFECYCLE_CHILD"):
            return False
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["MINI_REDIS_LIFECYCLE_CHILD"] = "1"
        env["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "tests"),
                                              env.get("PYTHONPATH", "")))
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", f"test_concurrency_http.ConcurrencyHTTPTests.{self._testMethodName}"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("lifecycle test exceeded 30s (including server_close and live threads)")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return True

    def stop(self):
        self.store.unblock()
        if self.server_thread.is_alive():
            self.shutdown_bounded(self.server)
            self.server_thread.join(timeout=5)
            self.assertFalse(self.server_thread.is_alive(), "serve_forever did not stop")

    def shutdown_bounded(self, server, timeout=5):
        errors = []
        def shutdown():
            try:
                server.shutdown()
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=shutdown, daemon=True)
        worker.start()
        worker.join(timeout=timeout)
        self.assertFalse(worker.is_alive(), "server.shutdown did not return")
        if errors:
            raise errors[0]

    def shutdown_async(self, server):
        task = concurrent.futures.Future()
        def shutdown():
            try:
                task.set_result(server.shutdown())
            except BaseException as exc:
                task.set_exception(exc)
        threading.Thread(target=shutdown, daemon=True).start()
        return task

    def check(self, method, path, status, payload, **kwargs):
        response = request(self.url, method, path, **kwargs)
        result(self, response, status, payload)
        for field in ("ttl_set", "ttl_removed"):
            if field in payload:
                self.assertIs(type(json.loads(response[2])[field]), bool)
        return response

    def put(self, key, value):
        result(self, put(self.url, key, value), 200, {"stored": True})

    def ttl(self, key, seconds=2):
        return self.check("PUT", f"/keys/{key}/ttl", 200, {"ttl_set": True},
                          body=json.dumps({"ttl_seconds": seconds}).encode(),
                          headers={"Content-Type": "application/json"})

    def run_async(self, method, path, *, body=None, headers=None):
        return self.pool.submit(request, self.url, method, path, body=body, headers=headers)

    def future(self, task, timeout=4):
        return task.result(timeout=timeout)

    def wait_entered(self):
        self.assertTrue(self.store.entered.wait(3), "store operation did not start")

    def entries(self, key=None):
        with self.store.lock:
            return [call for call in self.store.calls
                    if call[3] == "enter" and (key is None or call[1] == key)]

    def assert_single_executor(self):
        entries = self.entries()
        self.assertTrue(entries, "no store calls observed")
        self.assertFalse(self.store.overlap, "store calls overlapped")
        self.assertEqual(len({call[2] for call in entries}), 1)
        self.assertNotEqual(entries[0][2], self.server_thread.ident)

    def connect(self, payload):
        sock = socket.create_connection(self.address, timeout=3)
        sock.settimeout(4)
        sock.sendall(payload)
        self.addCleanup(sock.close)
        return sock

    def receive(self, sock):
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except ConnectionResetError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def assert_busy(self, response, *, head=False):
        status, headers, body = parsed(response)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(headers.get("connection"), "close")
        if head:
            self.assertEqual(body, b"")
        else:
            self.assertEqual(json.loads(body), error("SERVER_BUSY"))

    def test_i_001_slow_body_does_not_block_other_client(self):
        self.put("b", "ready")
        slow = self.connect(wire("PUT", "/keys/a", body=b'{"val', length=len(b'{"value":"a"}')))
        # B must finish before A's body is complete, not merely after both finish.
        response = self.run_async("GET", "/keys/b")
        try:
            result(self, self.future(response, 1), 200, {"value": "ready"})
        finally:
            slow.sendall(b'ue":"a"}')
            self.receive(slow)
        self.assert_single_executor()

    def test_i_002_all_public_operations_use_one_execution_thread(self):
        self.put("held", "old")
        self.put("ttl", "old")
        self.store.hold("get", "held")
        first = self.run_async("GET", "/keys/held")
        self.wait_entered()
        requests = [self.run_async("PUT", "/keys/other", body=b'{"value":"x"}',
                                   headers={"Content-Type": "application/json"}),
                    self.run_async("GET", "/keys/ttl"),
                    self.run_async("GET", "/keys/ttl/exists"),
                    self.run_async("DELETE", "/keys/ttl"),
                    self.run_async("PUT", "/keys/held/ttl", body=b'{"ttl_seconds":2}',
                                   headers={"Content-Type": "application/json"}),
                    self.run_async("DELETE", "/keys/held/ttl")]
        try:
            self.assertEqual([x for x in self.entries() if x[1] != "held" and x[0] != "set"], [])
        finally:
            self.store.unblock()
        self.future(first)
        for task in requests:
            self.future(task)
        self.assert_single_executor()
        self.check("GET", "/keys/other", 200, {"value": "x"})

    def test_i_003_idle_sweep_and_get_never_overlap(self):
        self.put("stale", "old")
        self.ttl("stale")
        self.put("live", "ok")
        self.clock.now += 3 * SECOND
        self.store.hold("sweep_expired", None)
        self.assertTrue(self.store.entered.wait(3), "no idle periodic sweep")
        getter = self.run_async("GET", "/keys/live")
        try:
            self.assertEqual(len([x for x in self.entries() if x[0] == "get" and x[1] == "live"]), 0)
        finally:
            self.store.unblock()
        result(self, self.future(getter), 200, {"value": "ok"})
        self.assert_single_executor()
        self.assertEqual(self.store._size, 1)

    def test_i_004_submitted_same_key_commands_run_in_order(self):
        self.store.hold("set", "k")
        first = self.run_async("PUT", "/keys/k", body=b'{"value":"a"}',
                               headers={"Content-Type": "application/json"})
        self.wait_entered()
        try:
            jobs = self.submit_ordered([
                ("get", "GET", "/keys/k", None),
                ("exists", "GET", "/keys/k/exists", None),
                ("set", "PUT", "/keys/k", b'{"value":"b"}'),
                ("delete", "DELETE", "/keys/k", None),
            ])
        finally:
            self.store.unblock()
        result(self, self.future(first), 200, {"stored": True})
        for job, status, expected in zip(jobs, (200, 200, 200, 200),
                                         ({"value": "a"}, {"exists": True},
                                          {"stored": True}, {"deleted": True})):
            result(self, self.future(job), status, expected)
        self.check("GET", "/keys/k", 404, error("KEY_NOT_FOUND"))
        self.assert_single_executor()

    def submit_ordered(self, commands):
        # Provisional observation seam; queued command metadata is not public API.
        pending = getattr(self.server, "_test_pending_commands", None)
        if pending is None:
            self.fail("Adapt provisional _test_pending_commands to the command submission boundary")
        jobs = []
        for operation, method, path, body in commands:
            before = len(pending())
            jobs.append(self.run_async(method, path, body=body,
                                       headers={"Content-Type": "application/json"} if body else None))
            self.assertTrue(self._until(lambda: len(pending()) > before, 3),
                            f"{operation} was not submitted")
            self.assertEqual(pending()[before].operation, operation)
        return jobs

    def test_i_005_unordered_same_key_results_are_serializable(self):
        self.put("other", "safe")
        barrier = threading.Barrier(5)
        actions = [("PUT", "/keys/k", b'{"value":""}'),
                   ("PUT", "/keys/k", b'{"value":"new"}'),
                   ("GET", "/keys/k", None), ("GET", "/keys/k/exists", None),
                   ("DELETE", "/keys/k", None)]
        def send(action):
            method, path, body = action
            barrier.wait(timeout=3)
            return request(self.url, method, path, body=body,
                           headers={"Content-Type": "application/json"} if body else None)
        jobs = [self.pool.submit(send, action) for action in actions]
        responses = [self.future(job) for job in jobs]
        with self.store.lock:
            calls = [call for call in self.store.executions if call[1] == "k"]
        self.assertEqual(len(calls), len(actions))
        # Replay the observed execution order, including each PUT's distinct value.
        remaining = list(range(len(actions)))
        state = None
        for name, key, detail in calls:
            index = next((i for i in remaining if
                          (actions[i][0] == "PUT" and name == "set" and
                           json.loads(actions[i][2])["value"] == detail) or
                          (actions[i][1].endswith("/exists") and name == "exists") or
                          (actions[i][0] == "GET" and name == "get") or
                          (actions[i][0] == "DELETE" and name == "delete")), None)
            if index is None:
                self.fail(f"unexpected store command: {name}, {key}, {detail}")
            remaining.remove(index)
            method, path, body = actions[index]
            if method == "PUT":
                state = json.loads(body)["value"]
                expected = (200, {"stored": True})
            elif path.endswith("/exists"):
                expected = (200, {"exists": state is not None})
            elif method == "GET":
                expected = ((200, {"value": state}) if state is not None
                            else (404, error("KEY_NOT_FOUND")))
            else:
                expected = (200, {"deleted": state is not None})
                state = None
            status, headers, data = responses[index]
            self.assertEqual((status, json.loads(data)), expected)
            self.assertEqual(headers.get("cache-control"), "no-store")
            for field in ("stored", "exists", "deleted"):
                if field in expected[1]:
                    self.assertIs(type(json.loads(data)[field]), bool)
        self.assertEqual(remaining, [])
        final_status, final_payload = ((200, {"value": state}) if state is not None
                                       else (404, error("KEY_NOT_FOUND")))
        self.check("GET", "/keys/k", final_status, final_payload)
        self.check("GET", "/keys/other", 200, {"value": "safe"})
        self.assert_single_executor()


    def test_i_006_rehash_precedes_queued_delete_and_expiration(self):
        for index in range(8):
            self.put(f"seed{index}", str(index))
        self.ttl("seed1")
        self.assertEqual((len(self.store._buckets), self.store._size), (8, 8))
        self.store.hold("get", "gate")
        gate = self.run_async("GET", "/keys/gate")
        self.wait_entered()
        self.store.unblock()
        self.future(gate)
        self.assertEqual(self.store._size, 8, "expired item was swept before expansion")
        self.store.hold("rehash", None)
        ninth = self.run_async("PUT", "/keys/ninth", body=b'{"value":"9"}',
                               headers={"Content-Type": "application/json"})
        self.wait_entered()
        try:
            waiting = self.submit_ordered([
                ("delete", "DELETE", "/keys/seed0", None),
                ("exists", "GET", "/keys/seed1/exists", None),
            ])
            self.clock.now += 3 * SECOND
        finally:
            self.store.unblock()
        result(self, self.future(ninth), 200, {"stored": True})
        for task in waiting:
            self.future(task)
        self.assertEqual((len(self.store._buckets), self.store._size), (16, 7))
        self.assertEqual(sum(map(len, self.store._buckets)), self.store._size)
        self.assert_single_executor()
        self.check("GET", "/keys/ninth", 200, {"value": "9"})

    def test_i_007_ttl_refresh_and_boundary_with_parallel_clients(self):
        self.put("k", "v")
        self.ttl("k")
        old = self.clock.now + 2 * SECOND
        self.clock.now += SECOND
        self.ttl("k")
        new = self.clock.now + 2 * SECOND
        self.clock.now = old + 1
        self.check("GET", "/keys/k", 200, {"value": "v"})
        self.clock.now = new - 1
        self.check("GET", "/keys/k/exists", 200, {"exists": True})
        self.clock.now = new
        self.check("GET", "/keys/k", 404, error("KEY_NOT_FOUND"))
        self.assert_single_executor()

    def test_i_008_overwrite_or_delete_does_not_restore_old_deadline(self):
        self.put("k", "old")
        self.ttl("k")
        deadline = self.clock.now + 2 * SECOND
        self.put("k", "")
        self.clock.now = deadline + 1
        self.check("GET", "/keys/k", 200, {"value": ""})
        self.ttl("k")
        self.check("DELETE", "/keys/k", 200, {"deleted": True})
        self.put("k", "new")
        self.clock.now += 3 * SECOND
        self.check("GET", "/keys/k", 200, {"value": "new"})
        self.assert_single_executor()

    def test_i_009_separate_put_and_ttl_have_visible_intermediate_state(self):
        self.put("k", "a")
        self.store.hold("get", "k")
        getter = self.run_async("GET", "/keys/k")
        self.wait_entered()
        try:
            put_async, = self.submit_ordered([("set", "PUT", "/keys/k", b'{"value":"b"}')])
        finally:
            self.store.unblock()
        result(self, self.future(getter), 200, {"value": "a"})
        result(self, self.future(put_async), 200, {"stored": True})
        self.ttl("k")
        self.check("DELETE", "/keys/k/ttl", 200, {"ttl_removed": True})
        self.check("GET", "/keys/k", 200, {"value": "b"})

    def test_i_010_sweep_and_new_value_do_not_remove_each_other(self):
        self.put("k", "old")
        self.ttl("k")
        self.clock.now += 3 * SECOND
        self.store.hold("sweep_expired", None)
        self.wait_entered()
        try:
            successor, = self.submit_ordered([("set", "PUT", "/keys/k", b'{"value":"new"}')])
        finally:
            self.store.unblock()
        result(self, self.future(successor), 200, {"stored": True})
        self.check("GET", "/keys/k", 200, {"value": "new"})
        self.assertEqual(self.store._size, sum(map(len, self.store._buckets)))
        self.assert_single_executor()

    def test_i_011_due_sweep_precedes_next_queued_command(self):
        original = self.store.sweep_expired
        def long_sweep():
            time.sleep(1.1)  # Several scheduling ticks pass during this one sweep.
            return original()
        with patch.object(self.store, "sweep_expired", side_effect=long_sweep):
            self.store.hold("get", "held")
            first = self.run_async("GET", "/keys/held")
            self.wait_entered()
            try:
                second, = self.submit_ordered([("get", "GET", "/keys/next", None)])
                time.sleep(1.1)
            finally:
                self.store.unblock()
            result(self, self.future(first), 404, error("KEY_NOT_FOUND"))
            result(self, self.future(second), 404, error("KEY_NOT_FOUND"))
            order = [(n, k) for n, k, _, p in self.store.calls if p == "enter"]
            self.assertLess(order.index(("get", "held")), order.index(("sweep_expired", None)))
            self.assertLess(order.index(("sweep_expired", None)), order.index(("get", "next")))
            self.assertEqual(order.count(("sweep_expired", None)), 1)
        self.assert_single_executor()

    def test_i_012_sweep_failure_and_diagnostic_failure_are_isolated(self):
        original = self.store.sweep_expired
        attempts = []
        def failing_once():
            attempts.append(time.monotonic())
            if len(attempts) == 1:
                raise RuntimeError("sweep failure")
            return original()
        with patch.object(self.store, "sweep_expired", side_effect=failing_once), \
                patch("builtins.print", side_effect=RuntimeError("diagnostic failed")):
            self.assertTrue(self._until(lambda: len(attempts) == 1, 3), "no idle sweep")
            self.check("GET", "/keys/none", 404, error("KEY_NOT_FOUND"))
            self.assertEqual(len(attempts), 1, "immediate retry after sweep failure")
            self.assertTrue(self._until(lambda: len(attempts) == 2, 3), "no next-period sweep")
            self.assertGreaterEqual(attempts[1] - attempts[0], 0.9)
        self.assert_single_executor()

    def _until(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    def occupy_slots(self):
        """Sixteen accepted but incomplete requests, without submitting commands."""
        sockets = [self.connect(wire("PUT", f"/keys/slot{i}", body=b'{', length=100))
                   for i in range(16)]
        accepted = getattr(self.server, "_test_accepted_requests", None)
        if accepted is None:
            self.fail("Adapt provisional _test_accepted_requests to observe 16 occupied slots")
        self.assertTrue(self._until(lambda: accepted() == 16, 3), "not all 16 slots occupied")
        return sockets

    def test_i_013_bounded_admission_and_rejection_before_validation(self):
        sockets = self.occupy_slots()
        before = len(self.entries())
        thread_count = threading.active_count()
        for payload in (wire("PUT", "/keys/rejected", body=b'{"value":"no"}'),
                        b"GET /other HTTP/1.1\r\nHost: localhost\r\n\r\n") * 8:
            response = raw(self.url, payload)
            self.assert_busy(response)
        self.assertEqual(len(self.entries()), before)
        self.assertLessEqual(threading.active_count() - thread_count, 3,
                             "rejected requests accumulated threads")
        for sock in sockets:
            sock.close()
        self.check("GET", "/keys/rejected", 404, error("KEY_NOT_FOUND"))

    def test_i_014_busy_head_has_no_body_and_incomplete_method_closes(self):
        self.occupy_slots()
        self.assert_busy(raw(self.url, b"HEAD /keys/no HTTP/1.1\r\nHost: localhost\r\n\r\n"), head=True)
        self.assert_busy(raw(self.url, b"GET /keys/no HTTP/1.1\r\nHost: localhost\r\n\r\n"))
        response = raw(self.url, b"HE")
        self.assertEqual(response, b"", "ambiguous method must not guess a body response")

    def test_i_015_capacity_recovers_and_accepted_errors_keep_priority(self):
        sockets = self.occupy_slots()
        self.assert_busy(raw(self.url, wire("PUT", "/keys/overflow", body=b'{"value":"x"}')))
        sockets[0].close()
        accepted = getattr(self.server, "_test_accepted_requests")
        self.assertTrue(self._until(lambda: accepted() == 15, 3), "slot was not returned")
        self.put("accepted", "ok")
        self.check("PUT", "/keys/accepted", 400, error("INVALID_BODY"), body=b'{}',
                   headers={"Content-Type": "application/json"})
        self.check("GET", "/keys/accepted", 200, {"value": "ok"})

    def test_i_016_accepted_http_contract_and_prior_suite(self):
        self.put("empty", "")
        self.check("GET", "/keys/empty", 200, {"value": ""})
        self.check("GET", "/keys/empty/exists", 200, {"exists": True})
        self.ttl("empty")
        self.check("DELETE", "/keys/empty/ttl", 200, {"ttl_removed": True})
        self.check("DELETE", "/keys/empty", 200, {"deleted": True})
        self.check("GET", "/keys/empty", 404, error("KEY_NOT_FOUND"))
        self.check("GET", "/other", 404, error("ROUTE_NOT_FOUND"))
        self.check("POST", "/keys/empty", 405, error("METHOD_NOT_ALLOWED"))
        self.check("GET", "/keys/a?x=1", 400, error("INVALID_QUERY"))
        self.check("PUT", "/keys/a", 400, error("INVALID_BODY"), body=b'{}',
                   headers={"Content-Type": "application/json"})
        head = raw(self.url, b"HEAD /keys/a HTTP/1.1\r\nHost: localhost\r\n\r\n")
        status, headers, body = parsed(head)
        self.assertEqual((status, headers.get("allow"), headers.get("cache-control"), body),
                         (405, "GET, PUT, DELETE", "no-store", b""))
        self.assert_single_executor()
        # Existing tests remain separate, not silently counted as this case.

    def test_i_017_oversize_rejected_before_body_and_no_followup(self):
        self.put("kept", "old")
        before = len(self.entries())
        reads = []
        handler = self.server.RequestHandlerClass

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

        class ProbedHandler(handler):
            def parse_request(self):
                accepted = super().parse_request()
                if accepted:
                    self.rfile = ReadProbe(self.rfile)
                return accepted

        self.server.RequestHandlerClass = ProbedHandler
        try:
            response = early_rejection(
                self.url, wire("PUT", "/keys/kept", length=65537),
                wire("PUT", "/keys/kept", body=b'{"value":"wrong"}'))
        finally:
            self.server.RequestHandlerClass = handler
        status, headers, body = parsed(response)
        self.assertEqual((status, json.loads(body)), (400, error("INVALID_BODY")))
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(response.count(b"HTTP/1.1 "), 1)
        self.assertEqual(reads, [], "oversize body was read before rejection")
        self.assertEqual(len(self.entries()), before)
        self.check("GET", "/keys/kept", 200, {"value": "old"})
        self.server.RequestHandlerClass = ProbedHandler
        try:
            self.put("observer", "working")
        finally:
            self.server.RequestHandlerClass = handler
        self.assertIn("read", reads, "read observer did not detect a real body read")
        for payload, half_close in ((wire("PUT", "/keys/kept"), False),
                                    (wire("PUT", "/keys/kept", body=b'{', length=30), True)):
            with self.subTest(payload=payload, half_close=half_close):
                before = len(self.entries())
                response = raw(self.url, payload, half_close=half_close)
                if response:
                    status, headers, body = parsed(response)
                    self.assertEqual(status, 400)
                    self.assertEqual(json.loads(body), error("INVALID_BODY"))
                    self.assertEqual(headers.get("cache-control"), "no-store")
                self.assertEqual(len(self.entries()), before)
                self.check("GET", "/keys/kept", 200, {"value": "old"})

    def test_i_018_trickled_input_has_total_deadline(self):
        deadline_seconds = getattr(self.server, "_test_request_deadline_seconds", None)
        if deadline_seconds is None:
            self.fail("Adapt provisional _test_request_deadline_seconds(stage) to configured total deadlines")
        self.put("kept", "old")
        for stage, prefix, trickle in (
            ("request-line", b"P", b"U"),
            ("headers", b"PUT /keys/kept HTTP/1.1\r\nHost: localhost\r\nX-Fill: ", b"a"),
            ("body", wire("PUT", "/keys/kept", body=b'{', length=100), b" "),
        ):
            with self.subTest(stage=stage):
                sock = self.connect(prefix)
                until = time.monotonic() + deadline_seconds(stage) + 0.5
                while time.monotonic() < until:
                    try:
                        sock.sendall(trickle)
                    except OSError:
                        break
                    time.sleep(0.1)
                sock.settimeout(1)
                try:
                    response = self.receive(sock)
                except TimeoutError:
                    self.fail(f"{stage} held a slot beyond the total deadline")
                if response:
                    _, headers, _ = parsed(response)
                    self.assertEqual(headers.get("cache-control"), "no-store")
                sock.close()
                self.check("GET", "/keys/kept", 200, {"value": "old"})

    def test_i_019_disconnect_before_or_after_submission(self):
        seam = getattr(self.server, "_test_submission_gate", None)
        if seam is None:
            self.fail("Adapt provisional _test_submission_gate to submission-confirmation boundary")
        self.put("base", "old")
        # Gate blocks before confirmation; a disconnected request must not submit.
        with seam("before", "before") as entered:
            sock = self.connect(wire("PUT", "/keys/before", body=b'{"value":"x"}'))
            self.assertTrue(entered.wait(3))
            sock.close()
        self.check("GET", "/keys/before", 404, error("KEY_NOT_FOUND"))
        self.store.hold("set", "after")
        sock = self.connect(wire("PUT", "/keys/after", body=b'{"value":"x"}'))
        self.wait_entered()
        sock.close()
        try:
            self.assertEqual(len(self.entries("after")), 1)
        finally:
            self.store.unblock()
        self.assertTrue(self._until(lambda: self.store._size == 2, 3))
        self.check("GET", "/keys/after", 200, {"value": "x"})
        self.assertEqual(len([x for x in self.entries("after") if x[0] == "set"]), 1)

    def test_i_020_response_write_failure_does_not_retry_put(self):
        seam = getattr(self.server, "_test_fail_response_write", None)
        if seam is None:
            self.fail("Adapt provisional _test_fail_response_write to one request response writer")
        with seam("k"):
            response = raw(self.url, wire("PUT", "/keys/k", body=b'{"value":"once"}'))
        self.assertNotIn(b'"stored":true', response)
        self.assertEqual(len([x for x in self.entries("k") if x[0] == "set"]), 1)
        self.check("GET", "/keys/k", 200, {"value": "once"})
        self.put("other", "ok")

    def test_i_021_pre_submit_failure_and_post_submit_delivery_failure(self):
        seam = getattr(self.server, "_test_fail_delivery", None)
        if seam is None:
            self.fail("Adapt provisional _test_fail_delivery to pre-submit/post-execution delivery faults")
        with seam("before", "early"):
            self.check("PUT", "/keys/early", 500, error("INTERNAL_ERROR"),
                       body=b'{"value":"no"}', headers={"Content-Type": "application/json"})
        self.assertEqual(self.entries("early"), [])
        self.check("GET", "/keys/early", 404, error("KEY_NOT_FOUND"))
        with seam("after", "k"):
            failed = self.run_async("PUT", "/keys/k", body=b'{"value":"once"}',
                                    headers={"Content-Type": "application/json"})
            other = self.run_async("PUT", "/keys/other", body=b'{"value":"other"}',
                                   headers={"Content-Type": "application/json"})
            result(self, self.future(failed), 500, error("INTERNAL_ERROR"))
            result(self, self.future(other), 200, {"stored": True})
        self.assertEqual(len([x for x in self.entries("k") if x[0] == "set"]), 1)
        self.check("GET", "/keys/k", 200, {"value": "once"})
        self.check("GET", "/keys/other", 200, {"value": "other"})

    def test_i_022_store_failure_is_500_and_next_request_survives(self):
        def fail(key, value):
            raise RuntimeError("do not expose this")
        with patch.object(self.store, "set", side_effect=fail):
            self.check("PUT", "/keys/bad", 500, error("INTERNAL_ERROR"),
                       body=b'{"value":"x"}', headers={"Content-Type": "application/json"})
        self.check("GET", "/keys/bad", 404, error("KEY_NOT_FOUND"))
        self.put("good", "ok")
        self.assert_single_executor()

    def test_i_023_executor_death_completes_waiters_and_stops_admission(self):
        if self.run_isolated():
            return
        seam = getattr(self.server, "_test_crash_executor", None)
        if seam is None:
            self.fail("Adapt provisional _test_crash_executor to unexpected executor failure")
        with seam("k"):
            waiting = self.run_async("GET", "/keys/k")
            result(self, self.future(waiting), 500, error("INTERNAL_ERROR"))
        response = raw(self.url, wire("PUT", "/keys/new", body=b'{"value":"x"}'))
        self.assertTrue(response == b"" or parsed(response)[0] in (500, 503))
        self.assertFalse(any(name == "set" and key == "new" for name, key, _, _ in self.store.calls))

    def test_i_024_shutdown_drains_accepted_requests_but_refuses_new(self):
        if self.run_isolated():
            return
        self.store.hold("get", "held")
        first = self.run_async("GET", "/keys/held")
        self.wait_entered()
        second, = self.submit_ordered([("set", "PUT", "/keys/accepted", b'{"value":"yes"}')])
        shutting_down = self.shutdown_async(self.server)
        try:
            draining = getattr(self.server, "_test_draining", None)
            if draining is None:
                self.fail("Adapt provisional _test_draining to observe the shutdown transition")
            self.assertTrue(self._until(draining, 3), "shutdown did not enter draining")
            self.assertFalse(shutting_down.done(), "shutdown discarded in-flight work")
            rejected = raw(self.url, wire("PUT", "/keys/rejected", body=b'{"value":"no"}'))
            if rejected:
                self.assert_busy(rejected)
        finally:
            self.store.unblock()
        result(self, self.future(first), 404, error("KEY_NOT_FOUND"))
        result(self, self.future(second), 200, {"stored": True})
        self.future(shutting_down)
        self.assertEqual(len([x for x in self.entries("accepted") if x[0] == "set"]), 1)
        self.assertFalse(any(x for x in self.entries("rejected") if x[0] == "set"))

    def test_i_025_admission_shutdown_race_and_sweep_drain(self):
        if self.run_isolated():
            return
        # Each ordering needs its own server: shutdown is terminal.
        for first in ("accept", "shutdown"):
            with self.subTest(first=first):
                store = ObservedStore(Clock())
                server = create_server(HOST, 0, store)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    seam = getattr(server, "_test_admission_gate", None)
                    if seam is None:
                        self.fail("Adapt provisional _test_admission_gate to atomic admission/shutdown transition")
                    url = f"http://{HOST}:{server.server_address[1]}"
                    with seam(first) as observed:
                        incoming = self.pool.submit(request, url, "PUT", "/keys/race",
                                                    body=b'{"value":"x"}',
                                                    headers={"Content-Type": "application/json"})
                        shutdown = self.shutdown_async(server)
                        observed.release()
                        try:
                            reply = self.future(incoming)
                        except (ConnectionError, TimeoutError, OSError):
                            if first == "accept":
                                raise
                            reply = None  # No application response on a rejected connection.
                        if first == "accept":
                            result(self, reply, 200, {"stored": True})
                        elif reply is not None:
                            self.assertEqual(reply[0], 503)
                        self.future(shutdown)
                        calls = [x for x in store.calls if x[0:2] == ("set", "race") and x[3] == "enter"]
                        self.assertEqual(len(calls), 1 if first == "accept" else 0)
                        sweeps = len([x for x in store.calls if x[0] == "sweep_expired" and x[3] == "enter"])
                        time.sleep(1.1)
                        self.assertEqual(len([x for x in store.calls
                                              if x[0] == "sweep_expired" and x[3] == "enter"]), sweeps,
                                         "sweep continued after shutdown")
                finally:
                    try:
                        self.shutdown_bounded(server)
                        thread.join(timeout=5)
                        self.assertFalse(thread.is_alive())
                    finally:
                        server.server_close()
