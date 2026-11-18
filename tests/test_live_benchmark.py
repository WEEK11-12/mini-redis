"""Iteration 07 checkpoint 3 tests: local preparation/run server (TC-07-U/I).

Docker, MongoDB and the measurement/seed processes are test doubles or isolated
temporary processes. Nothing here starts Docker, seeds MongoDB or runs benchmark.py.
"""

import contextlib
import errno
import http.client
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from examples import live_benchmark as lb
from examples.benchmark import CONDITIONS, KEY_SEED, ROUNDS, WARMUP
from examples.seed_mongo import item_id, value_for

READ_METHODS = {"ping", "cache_max_bytes", "collection_exists", "coll_stats", "values", "close"}


class FakeReader:
    """Read-only Mongo double; records every call so writes would be visible."""

    def __init__(self, world):
        self.world = world

    def __getattr__(self, name):
        raise AssertionError(f"unexpected Mongo call: {name}")

    def _call(self, name):
        self.world.calls.append(name)
        if self.world.events is not None:
            self.world.events.append(("mongo", name))
        if name in self.world.hooks:
            self.world.hooks[name]()
        if name in self.world.fail:
            raise RuntimeError(f"injected {name} failure")

    def ping(self):
        self._call("ping")

    def cache_max_bytes(self):
        self._call("cache_max_bytes")
        return self.world.cache_max

    def collection_exists(self):
        self._call("collection_exists")
        return self.world.seeded()

    def coll_stats(self):
        self._call("coll_stats")
        return {"count": self.world.count, "storage_bytes": self.world.storage}

    def values(self, ids):
        self._call("values")
        self.world.read_ids.append(list(ids))
        out = {}
        for key in ids:
            if key in self.world.overrides:
                if self.world.overrides[key] is not None:
                    out[key] = self.world.overrides[key]
            elif key == "demo":
                out[key] = "sample-response"
            else:
                out[key] = value_for(int(key.split("-", 1)[1]))
        return out

    def close(self):
        self.world.calls.append("close")


class MongoWorld:
    def __init__(self, seeded=True, flag=None, events=None):
        self._seeded, self.flag, self.events = seeded, flag, events
        self.count, self.storage, self.cache_max = lb.EXPECTED_COUNT, 2 * lb.CACHE_MAX_BYTES, lb.CACHE_MAX_BYTES
        self.overrides, self.fail, self.calls, self.read_ids, self.hooks = {}, set(), [], [], {}

    def seeded(self):
        return self._seeded or (self.flag is not None and Path(self.flag).exists())

    def reader(self, uri=None):
        return FakeReader(self)


def expected_numbers():
    return random.Random(KEY_SEED).sample(range(lb.EXPECTED_COUNT - 1),
                                          (WARMUP + ROUNDS) * len(CONDITIONS))


class SeedInspectionTests(unittest.TestCase):
    def test_u_001_valid_seed_checks_every_measured_key_read_only(self):
        world = MongoWorld()
        report = lb.inspect_seed(world.reader())
        self.assertEqual(report["status"], "ok")
        self.assertTrue(set(world.calls) <= READ_METHODS, world.calls)
        ids = [i for batch in world.read_ids for i in batch]
        expected = ["demo", item_id(0), item_id(999_999)] + [item_id(n) for n in expected_numbers()]
        self.assertEqual(ids, expected)
        self.assertEqual(report["keys"]["order"], expected[:3] + ["<315 measurement keys in draw order>"])
        self.assertEqual(report["keys"]["measurement_keys"], 315)
        self.assertEqual(report["keys"]["key_seed"], KEY_SEED)
        self.assertEqual((report["count"], report["storage_bytes"]), (world.count, world.storage))

    def test_u_001_count_alone_is_not_enough(self):
        world = MongoWorld()
        world.overrides[item_id(expected_numbers()[200])] = "x" * 1024
        report = lb.inspect_seed(world.reader())
        self.assertEqual(report["status"], "mismatch")
        self.assertIn(item_id(expected_numbers()[200]), report["detail"])

    def test_u_002_classification(self):
        numbers = expected_numbers()
        cases = {
            "missing": ("missing", lambda w: setattr(w, "_seeded", False)),
            "count": ("mismatch", lambda w: setattr(w, "count", lb.EXPECTED_COUNT - 1)),
            "demo": ("mismatch", lambda w: w.overrides.update(demo="other")),
            "first": ("mismatch", lambda w: w.overrides.update({item_id(0): None})),
            "last": ("mismatch", lambda w: w.overrides.update({item_id(999_999): "short"})),
            "sample": ("mismatch", lambda w: w.overrides.update({item_id(numbers[314]): value_for(1)})),
            "query": ("check_failed", lambda w: w.fail.add("values")),
            "stats": ("check_failed", lambda w: w.fail.add("coll_stats")),
            "cache": ("resource_mismatch", lambda w: setattr(w, "cache_max", lb.CACHE_MAX_BYTES * 2)),
            "storage": ("condition_unmet", lambda w: setattr(w, "storage", 2 * lb.CACHE_MAX_BYTES - 1)),
        }
        for name, (status, mutate) in cases.items():
            with self.subTest(name):
                world = MongoWorld()
                mutate(world)
                report = lb.inspect_seed(world.reader())
                self.assertEqual(report["status"], status, report)
                self.assertTrue(set(world.calls) <= READ_METHODS, world.calls)
                self.assertEqual(lb.SEED_STATUS_CODE[status], {
                    "missing": None, "mismatch": None, "check_failed": "SEED_CHECK_FAILED",
                    "resource_mismatch": "RESOURCE_MISMATCH",
                    "condition_unmet": "MEASUREMENT_CONDITION_UNMET"}[status])


def valid_results(output):
    """benchmark.py-shaped raw result for `output` (fields as the real writer emits them)."""
    summary = {c: {"successes": ROUNDS, "failures": 0, "median_ms": 1.5 + i, "p90_ms": 2.5 + i}
               for i, c in enumerate(CONDITIONS)}
    summary["complete"] = True
    records = [{"condition": c, "round": r, "success": True, "elapsed_ns": 1_500_000}
               for r in range(ROUNDS) for c in CONDITIONS]
    return {
        "command": [sys.executable, "/repo/examples/benchmark.py", "--output", str(output),
                    "--mongo-uri", "mongodb://127.0.0.1:27018"],
        "python": "3.14.5", "platform": "macOS-26", "machine": "arm64", "commit": "abc",
        "sources_sha256": {"examples/benchmark.py": "0" * 64},
        "cache_url": "http://127.0.0.1:1", "origin_url": "http://127.0.0.1:2",
        "warmup_per_condition": WARMUP, "rounds": ROUNDS,
        "timer": "time.perf_counter_ns around value acquisition only",
        "percentile": "median of sorted successes; p90 nearest-rank",
        "mongo_before": {"count": lb.EXPECTED_COUNT, "cache_max_bytes": lb.CACHE_MAX_BYTES,
                         "storage_bytes": 600_000_000, "pages_read_into_cache": 10},
        "key_seed": KEY_SEED, "key_space": lb.EXPECTED_COUNT - 1, "aborted": None,
        "servers": [{"pid": 1, "exit": 0, "killed": False}],
        "mongo_after": {"count": lb.EXPECTED_COUNT, "cache_max_bytes": lb.CACHE_MAX_BYTES},
        "warmup": [], "records": records, "summary": summary,
    }


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="i07-judge-"))
        self.out = self.dir / "results.json"

    def write(self, data):
        self.out.write_text(data if isinstance(data, str) else json.dumps(data))

    def judge(self, exit_code=0, timed_out=False, reaped=True, spawn_error=False):
        return lb.judge_run(self.dir, exit_code=exit_code, timed_out=timed_out,
                            reaped=reaped, spawn_error=spawn_error)

    def test_u_003_success_uses_this_runs_summary(self):
        data = valid_results(self.out)
        self.write(data)
        verdict = self.judge()
        self.assertEqual(verdict["state"], "succeeded")
        self.assertIsNone(verdict["error"])
        for c in CONDITIONS:
            self.assertEqual(verdict["result"]["conditions"][c],
                             {k: data["summary"][c][k] for k in ("median_ms", "p90_ms", "successes", "failures")})
        self.assertEqual(verdict["result"]["method"]["rounds"], ROUNDS)
        self.assertEqual(verdict["result"]["method"]["warmup_per_condition"], WARMUP)
        self.assertEqual(verdict["result"]["environment"]["mongo_before"], data["mongo_before"])
        self.assertFalse(verdict["result"]["environment"]["mongo_after_unavailable"])

    def test_u_003_mongo_after_error_keeps_success_but_is_flagged(self):
        data = valid_results(self.out)
        data["mongo_after"] = {"error": "ServerSelectionTimeoutError: x"}
        self.write(data)
        verdict = self.judge()
        self.assertEqual(verdict["state"], "succeeded")
        self.assertTrue(verdict["result"]["environment"]["mongo_after_unavailable"])

    def test_u_004_each_invalid_field_is_result_invalid(self):
        other = str(self.dir.parent / "other" / "results.json")

        def cond(field, value, c="miss"):
            return lambda d: d["summary"][c].__setitem__(field, value)

        mutations = {
            "complete_1": lambda d: d["summary"].__setitem__("complete", 1),
            "aborted_empty": lambda d: d.__setitem__("aborted", ""),
            "missing_condition": lambda d: d["summary"].pop("hit"),
            "successes_float": cond("successes", 100.0),
            "successes_99": cond("successes", 99),
            "failures_false": cond("failures", False),
            "failures_1": cond("failures", 1),
            "median_bool": cond("median_ms", True),
            "median_nan": cond("median_ms", float("nan")),
            "p90_inf": cond("p90_ms", float("inf")),
            "p90_negative": cond("p90_ms", -0.1),
            "rounds_bool": lambda d: d.__setitem__("rounds", True),
            "rounds_wrong": lambda d: d.__setitem__("rounds", 99),
            "warmup_bool": lambda d: d.__setitem__("warmup_per_condition", True),
            "method_missing": lambda d: d.pop("timer"),
            "environment_missing": lambda d: d.pop("sources_sha256"),
            "before_count": lambda d: d["mongo_before"].__setitem__("count", lb.EXPECTED_COUNT - 1),
            "before_cache": lambda d: d["mongo_before"].__setitem__("cache_max_bytes", 1),
            "output_other_run": lambda d: d.__setitem__("command", [
                sys.executable, "benchmark.py", "--note", str(self.out), "--output", other]),
            "output_missing": lambda d: d.__setitem__("command", [sys.executable, str(self.out)]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                data = valid_results(self.out)
                mutate(data)
                self.write(data)
                verdict = self.judge()
                self.assertEqual((verdict["state"], verdict["error"]["code"]), ("failed", "RESULT_INVALID"))
                self.assertIsNone(verdict["result"])
                if name in {"aborted_empty", "missing_condition", "successes_float", "failures_false",
                            "output_other_run", "output_missing"}:
                    self.assertIsNone(verdict["partial"])
        with self.subTest("broken_json"):
            self.write("{not json")
            verdict = self.judge()
            self.assertEqual(verdict["error"]["code"], "RESULT_INVALID")
            self.assertIsNone(verdict["partial"])

    def test_u_005_failures_and_timeouts(self):
        incomplete = valid_results(self.out)
        incomplete["aborted"] = "KeyboardInterrupt: "
        incomplete["summary"]["complete"] = False
        incomplete["summary"]["hit"].update(successes=40, failures=2)
        cases = [
            ("spawn", dict(exit_code=None, spawn_error=True), None, ("failed", "BENCHMARK_FAILED"), None),
            ("nonzero_no_file", dict(exit_code=1), None, ("failed", "BENCHMARK_FAILED"), None),
            ("nonzero_partial", dict(exit_code=1), incomplete, ("failed", "BENCHMARK_FAILED"), "partial"),
            ("nonzero_broken", dict(exit_code=1), "{broken", ("failed", "BENCHMARK_FAILED"), None),
            ("timeout_partial", dict(exit_code=0, timed_out=True), incomplete, ("timed_out", "TIMED_OUT"), "partial"),
            ("timeout_complete", dict(exit_code=0, timed_out=True), valid_results(self.out),
             ("timed_out", "TIMED_OUT"), "partial"),
            ("timeout_no_file", dict(exit_code=-9, timed_out=True), None, ("timed_out", "TIMED_OUT"), None),
            ("unreaped_success", dict(exit_code=0, reaped=False), valid_results(self.out),
             ("failed", "BENCHMARK_FAILED"), "partial"),
        ]
        for name, kwargs, content, (state, code), partial in cases:
            with self.subTest(name):
                self.out.unlink(missing_ok=True)
                if content is not None:
                    self.write(content)
                verdict = self.judge(**kwargs)
                self.assertEqual((verdict["state"], verdict["error"]["code"]), (state, code))
                self.assertIsNone(verdict["result"])
                if partial is None:
                    self.assertIsNone(verdict["partial"])
                else:
                    expect = content["summary"]
                    self.assertEqual(verdict["partial"]["aborted"], content["aborted"])
                    for c in CONDITIONS:
                        self.assertEqual(verdict["partial"]["conditions"][c],
                                         {"successes": expect[c]["successes"],
                                          "failures": expect[c]["failures"]})


MUTATING = {"pull", "create_volume", "run_container", "start", "restart"}


def good_container(labels, running=True, started="2026-11-19T00:00:00.000000001Z"):
    return {"Name": "/" + lb.CONTAINER, "Image": "sha256:img",
            "Config": {"Image": lb.IMAGE, "Cmd": list(lb.MONGO_ARGS), "Labels": dict(labels)},
            "HostConfig": {"PortBindings": json.loads(json.dumps(lb.PORT_BINDING)),
                           "Memory": lb.MEMORY_BYTES},
            "Mounts": [{"Type": "volume", "Name": name, "Destination": dest}
                       for dest, name in lb.MOUNTS.items()],
            "State": {"Running": running, "StartedAt": started}}


OWNED = {"mongo": {"io.mini-redis.owner": "live-benchmark-ui", "io.mini-redis.role": "mongo"},
         "data": {"io.mini-redis.owner": "live-benchmark-ui", "io.mini-redis.role": "data"},
         "config": {"io.mini-redis.owner": "live-benchmark-ui", "io.mini-redis.role": "config"}}


class FakeDocker:
    """Docker double. With `path`, state is a JSON file shared across processes."""

    def __init__(self, path=None, events=None):
        self.path, self.events = path, events if events is not None else []
        self.state = {"images": {lb.IMAGE: {"Id": "sha256:img"}}, "volumes": {}, "containers": {},
                      "restarts": 0}
        self.ops, self.fail, self.hooks, self.envs = [], {}, {}, []
        if path and Path(path).exists():
            self.state = json.loads(Path(path).read_text())

    def __call__(self, env):
        self.envs.append(env)
        return self

    def save(self):
        if self.path:
            # durable like the product: a plain write was observed empty after SIGKILL on macOS
            lb.write_json_durable(self.path, self.state)

    def _op(self, name, *args):
        self.ops.append((name, *args))
        self.events.append(("docker", name, *args))
        if name in self.hooks:
            self.hooks[name]()
        if name in self.fail:
            raise lb.DockerError(self.fail[name])

    def mutations(self):
        return [op for op in self.ops if op[0] in MUTATING]

    def context(self):
        return "test-context"

    def info(self):
        self._op("info")

    def inspect(self, kind, name):
        self._op("inspect", kind, name)
        store = {"image": "images", "volume": "volumes", "container": "containers"}[kind]
        found = self.state[store].get(name)
        return json.loads(json.dumps(found)) if found is not None else None

    def pull(self, image):
        self._op("pull", image)
        self.state["images"][image] = {"Id": "sha256:pulled"}
        self.save()

    def create_volume(self, name, labels):
        self._op("create_volume", name)
        self.state["volumes"].setdefault(name, {"Name": name, "Labels": dict(labels)})
        self.save()

    def run_container(self, labels):
        self._op("run_container")
        self.state["containers"][lb.CONTAINER] = good_container(labels)
        self.save()

    def start(self):
        self._op("start")
        self.state["containers"][lb.CONTAINER]["State"]["Running"] = True
        self.save()

    def restart(self):
        self._op("restart")
        self.state["restarts"] += 1
        c = self.state["containers"][lb.CONTAINER]
        c["State"].update(Running=True, StartedAt=f"2026-11-19T01:00:{self.state['restarts']:02d}.0Z")
        self.save()

    def own_everything(self, running=True):
        self.state["volumes"] = {lb.DATA_VOLUME: {"Name": lb.DATA_VOLUME, "Labels": OWNED["data"]},
                                 lb.CONFIG_VOLUME: {"Name": lb.CONFIG_VOLUME, "Labels": OWNED["config"]}}
        self.state["containers"] = {lb.CONTAINER: good_container(OWNED["mongo"], running)}
        self.save()


class Harness:
    """One in-process server on an ephemeral loopback port with injected doubles."""

    def __init__(self, tc, *, root=None, docker=None, world=None, shared=None, write=None,
                 bench=None, seed=None, timeouts=None, new_id=None, start=True):
        self.tc = tc
        self.root = Path(root or tempfile.mkdtemp(prefix="i07-"))
        self.shared = Path(shared) if shared else self.root / "shared"
        self.docker = docker or FakeDocker()
        self.world = world or MongoWorld()
        kwargs = dict(port=0, run_root=self.root / "var", shared_dir=self.shared,
                      docker=self.docker, mongo=self.world.reader,
                      timeouts={"bench": 2, "seed": 2, "grace": 1, "leftover": 1, "mongo": 0.5,
                                **(timeouts or {})})
        if write:
            kwargs["write"] = write
        if bench:
            kwargs["bench_cmd"] = bench
        if seed:
            kwargs["seed_cmd"] = seed
        if new_id:
            kwargs["new_id"] = new_id
        self.app = lb.LiveBenchmark(**kwargs)
        if start:
            self.start()

    def start(self):
        self.app.start()
        self.app.serve_in_thread()
        self.tc.addCleanup(self.close)

    def close(self):
        self.app.close()

    @property
    def host(self):
        return f"127.0.0.1:{self.app.port}"

    def request(self, method, path, body=b"{}", headers=None, token=True, raw_headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=10)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        base = {"Host": self.host, "Origin": f"http://{self.host}"}
        if method != "GET":
            base["Content-Type"] = "application/json"
            if token:
                base["X-Live-Bench-Token"] = self.app.token
            if body is not None:
                body = body if isinstance(body, bytes) else json.dumps(body).encode()
                base["Content-Length"] = str(len(body))
        base.update(headers or {})
        for name, value in base.items():
            if value is not None:
                conn.putheader(name, value)
        for name, value in raw_headers or []:
            conn.putheader(name, value)
        conn.endheaders()
        if method != "GET" and body:
            conn.send(body)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        parsed = json.loads(data) if response.getheader("Content-Type") == "application/json" else data
        return response.status, response, parsed

    def get(self, path, **kw):
        return self.request("GET", path, body=None, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body={} if body is None else body, **kw)

    def status(self):
        return self.get("/api/setup")[2]

    def wait(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.status()
            if predicate(current):
                return current
            time.sleep(0.05)
        self.tc.fail(f"condition not reached; last status {current}")

    def idle(self, timeout=15):
        return self.wait(lambda s: s["active_job"] is None, timeout)


class HttpContractTests(unittest.TestCase):
    def assert_json_error(self, response, status, code, expected_status):
        self.assertEqual(status, expected_status)
        self.assertEqual(response[1].getheader("Content-Type"), "application/json")
        self.assertEqual(response[1].getheader("Cache-Control"), "no-store")
        self.assertIsNone(response[1].getheader("Access-Control-Allow-Origin"))
        self.assertEqual(set(response[2]), {"error"})
        self.assertEqual(response[2]["error"]["code"], code)
        self.assertIsInstance(response[2]["error"]["message"], str)

    def check(self, response, status, code):
        self.assert_json_error(response, response[0], code, status)

    def test_i_006_get_page_and_setup_status(self):
        h = Harness(self)
        status, response, page = h.get("/")
        self.assertEqual(status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("text/html"))
        self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertIn(h.app.token.encode(), page)
        status, response, body = h.get("/api/setup")
        self.assertEqual(status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(set(body) >= {"state", "step", "message", "error", "active_job",
                                      "last_run_id", "resources"}, True)
        self.assertEqual((body["state"], body["active_job"], body["last_run_id"]), ("not_ready", None, None))
        self.assertEqual(body["resources"]["container"], lb.CONTAINER)

    def test_i_006_run_lookup_rejects_unknown_and_malformed_ids(self):
        h = Harness(self)
        for rid in ("20261119T000000Z-0123456789abcdef", "nope", "..%2F..%2Fetc",
                    "20261119T000000Z-0123456789ABCDEF", "20261119T000000Z-0123456789abcdef/../x"):
            with self.subTest(rid):
                self.check(h.get("/api/runs/" + rid), 404, "RUN_NOT_FOUND")
        self.assertEqual(h.docker.ops, [("inspect", "container", lb.CONTAINER),
                                        ("inspect", "volume", lb.DATA_VOLUME),
                                        ("inspect", "volume", lb.CONFIG_VOLUME)])

    def test_i_007_listens_on_loopback_only_and_guards_requests(self):
        h = Harness(self)
        self.assertEqual(h.app.httpd.server_address[0], "127.0.0.1")
        port = h.app.port
        cases = [
            ("GET", "/api/setup", {"Host": f"localhost:{port}"}, True),
            ("GET", "/", {"Host": f"evil.example:{port}"}, True),
            ("GET", "/api/setup", {"Origin": "http://evil.example"}, True),
            ("GET", "/api/setup", {"Origin": "null"}, True),
            ("POST", "/api/setup", {"Host": f"localhost:{port}"}, True),
            ("POST", "/api/setup", {"Origin": "null"}, True),
            ("POST", "/api/setup", {"Origin": f"http://localhost:{port}"}, True),
            ("POST", "/api/setup", {}, False),
            ("POST", "/api/setup", {"X-Live-Bench-Token": "wrong"}, True),
            ("OPTIONS", "/api/setup", {"Access-Control-Request-Method": "POST"}, False),
        ]
        for method, path, headers, token in cases:
            with self.subTest(method=method, headers=headers, token=token):
                response = h.request(method, path, body=None if method == "GET" else {},
                                     headers=headers, token=token)
                self.check(response, 403, "FORBIDDEN_REQUEST")
        self.assertEqual(h.docker.mutations(), [])
        self.assertEqual(h.status()["active_job"], None)

    def test_i_007_previous_server_token_is_rejected(self):
        root = Path(tempfile.mkdtemp(prefix="i07-"))
        first = Harness(self, root=root)
        old = first.app.token
        first.close()
        second = Harness(self, root=root, docker=first.docker)
        self.assertNotEqual(old, second.app.token)
        self.check(second.post("/api/setup", headers={"X-Live-Bench-Token": old}), 403, "FORBIDDEN_REQUEST")

    def test_i_008_format_errors_in_order(self):
        h = Harness(self)
        self.check(h.get("/nope"), 404, "NOT_FOUND")
        self.check(h.post("/nope"), 404, "NOT_FOUND")
        status, response, body = h.request("PUT", "/api/setup", body={})
        self.check((status, response, body), 405, "METHOD_NOT_ALLOWED")
        self.check(h.get("/api/runs"), 405, "METHOD_NOT_ALLOWED")
        self.check(h.post("/api/setup", headers={"Content-Type": "text/plain"}), 415, "UNSUPPORTED_MEDIA_TYPE")
        self.check(h.post("/api/setup", headers={"Content-Type": None}), 415, "UNSUPPORTED_MEDIA_TYPE")
        for body in (b"", b"[]", b"{bad", b'{"extra": 1}', b'"x"'):
            with self.subTest(body=body):
                self.check(h.post("/api/setup", body=body), 400, "INVALID_BODY")
        self.check(h.post("/api/setup", body=b"{" + b" " * 1100 + b"}"), 413, "BODY_TOO_LARGE")
        self.check(h.post("/api/setup/seed", body={}), 400, "CONFIRMATION_REQUIRED")
        self.check(h.post("/api/setup/seed", body={"confirm_replace": False}), 400, "CONFIRMATION_REQUIRED")
        self.check(h.post("/api/setup/seed", body={"confirm_replace": 1}), 400, "CONFIRMATION_REQUIRED")
        self.check(h.post("/api/setup/seed", body={"confirm_replace": True, "uri": "x"}), 400, "INVALID_BODY")
        self.check(h.post("/api/runs", body={"command": "rm"}), 400, "INVALID_BODY")
        self.assertEqual(h.docker.mutations(), [])
        self.assertEqual(list((h.root / "var" / "runs").iterdir()), [])

    def test_i_008_oversized_body_is_rejected_before_reading(self):
        h = Harness(self)
        import socket
        with socket.create_connection(("127.0.0.1", h.app.port), timeout=5) as sock:
            sock.sendall((f"POST /api/setup HTTP/1.1\r\nHost: {h.host}\r\nOrigin: http://{h.host}\r\n"
                          f"X-Live-Bench-Token: {h.app.token}\r\nContent-Type: application/json\r\n"
                          "Content-Length: 4096\r\n\r\n").encode())
            # body never sent and write side left open: only a pre-read rejection answers
            data = b""
            while chunk := sock.recv(4096):
                data += chunk
        self.assertIn(b" 413 ", data.split(b"\r\n", 1)[0] + b" ")
        self.assertIn(b"BODY_TOO_LARGE", data)


ROOT = Path(__file__).resolve().parent.parent
UI_TESTS = ROOT / "tests" / "live_benchmark_ui.test.js"


class ScreenPageTests(unittest.TestCase):
    """TC-07-I-017 (page level): what the server ships to the browser."""

    def page(self):
        h = Harness(self)
        status, response, page = h.get("/")
        self.assertEqual(status, 200)
        return h, response, page.decode("utf-8")

    def test_i_017_page_has_contract_controls_and_notices(self):
        _, _, page = self.page()
        for element_id in ("setup-button", "seed-button", "seed-confirm", "run-button",
                           "status-state", "status-step", "run-view", "error-view"):
            self.assertIn(f'id="{element_id}"', page)
        buttons = re.findall(r"<button[^>]*>(.*?)</button>", page, re.S)
        self.assertEqual(len(buttons), 3, buttons)
        for label in buttons:
            self.assertNotRegex(label, "정리|삭제|cleanup|remove")
        for phrase in ("한 로컬 호스트의 순차 HTTP 전체 흐름", "OS/Docker 파일 캐시", "동시 부하",
                       "원격 DB", "디스크 I/O", "측정 수치에 포함하지 않습니다",
                       "자동으로 중지·삭제되지 않습니다", "약 1GB", lb.CONTAINER, lb.DATA_VOLUME):
            self.assertIn(phrase, page)
        self.assertNotRegex(page, r"https?://")  # no external CDN or network resource

    def test_i_017_script_is_inline_nonce_bound_and_never_parses_html(self):
        h, response, page = self.page()
        csp = response.getheader("Content-Security-Policy")
        nonce = re.search(r"script-src 'nonce-([A-Za-z0-9_-]+)'", csp).group(1)
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'self'", csp)
        scripts = re.findall(r"<script([^>]*)>(.*?)</script>", page, re.S)
        self.assertEqual(len(scripts), 1)
        self.assertIn(f'nonce="{nonce}"', scripts[0][0])
        self.assertNotIn("src=", scripts[0][0])
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                     "new Function"):
            self.assertNotIn(sink, scripts[0][1])
        self.assertNotEqual(nonce, re.search(r"'nonce-([A-Za-z0-9_-]+)'",
                                             h.get("/")[1].getheader("Content-Security-Policy")).group(1))

    def test_i_017_screen_logic_node_tests(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node not installed: screen logic tests not run")
        done = subprocess.run([node, "--test", str(UI_TESTS)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-2000:])


class FailingWrite:
    """Durable writer that records order and fails on chosen paths/occurrences."""

    def __init__(self, events):
        self.events, self.fail = events, []  # list of (predicate, remaining)

    def __call__(self, path, data):
        path = Path(path)
        for rule in self.fail:
            if rule[0](path, data) and rule[1] > 0:
                rule[1] -= 1
                self.events.append(("write_failed", path.name))
                raise OSError(errno.EIO, "injected write failure")
        lb.write_json_durable(path, data)
        self.events.append(("write", path.name))

    def fail_on(self, name, times=1, when=lambda data: True):
        self.fail.append([lambda p, d: p.name == name and when(d), times])


def open_job(shared, detail_path, kind="run", children=(), marker=None, status="open"):
    data = lb.read_json(shared / lb.SHARED_NAME) if (shared / lb.SHARED_NAME).exists() else \
        {"version": 1, "initialized_at": "x", "jobs": {}}
    job_id = Path(detail_path).parent.name
    data["jobs"][job_id] = {"kind": kind, "status": status, "created_at": "x",
                            "marker": marker or os.urandom(16).hex(), "detail_path": str(detail_path),
                            "checkout": "elsewhere", "server_pid": 1, "children": list(children)}
    shared.mkdir(parents=True, exist_ok=True)
    lb.write_json_durable(shared / lb.SHARED_NAME, data)
    return job_id, data["jobs"][job_id]


def make_detail(root, kind="run", state="running"):
    job_id = lb.new_id()
    parent = root / "var" / ("runs" if kind == "run" else "jobs") / job_id
    parent.mkdir(parents=True)
    path = parent / ("runner.json" if kind == "run" else "job.json")
    detail = {"id": job_id, "run_id": job_id, "kind": kind, "state": state, "step": "running_benchmark",
              "created_at": "x", "started_at": "x", "finished_at": None, "error": None, "children": []}
    lb.write_json_durable(path, detail)
    return path


def spawn_group(marker=None):
    env = dict(os.environ)
    if marker:
        env[lb.MARKER_ENV] = marker
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], env=env,
                            start_new_session=True)
    return proc


def kill_group(proc):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def launch_server(config, tc):
    """Separate server process (another checkout) using file-backed test doubles."""
    proc = subprocess.Popen(
        [sys.executable, "-B", "-c",
         "import json, sys; from tests.test_live_benchmark import serve_from_config; "
         "serve_from_config(json.loads(sys.argv[1]))", json.dumps(config)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def cleanup():
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()

    tc.addCleanup(cleanup)
    line = proc.stdout.readline()
    if not line:
        proc.wait(5)
        raise AssertionError(f"server did not start: {proc.returncode}")
    return proc, json.loads(line)


def serve_from_config(config):
    docker = FakeDocker(config["docker_state"])
    crash = config.get("crash_on_docker")
    if crash:
        docker.hooks[crash] = lambda: os.kill(os.getpid(), signal.SIGKILL)
    world = MongoWorld(seeded=config.get("seeded", True), flag=config.get("seed_flag"))
    kwargs = {}
    if config.get("bench"):
        kwargs["bench_cmd"] = lambda out: [*config["bench"], "--output", str(out), "--mongo-uri", lb.MONGO_URI]
    if config.get("seed"):
        kwargs["seed_cmd"] = lambda: list(config["seed"])
    app = lb.LiveBenchmark(port=0, run_root=config["run_root"], shared_dir=config["shared"],
                           docker=docker, mongo=world.reader,
                           timeouts={"bench": 60, "seed": 60, "grace": 1, "leftover": 1, "mongo": 1},
                           **kwargs)
    spawn_crash = config.get("crash_on_spawn")
    if spawn_crash:
        original = app._record_spawn

        def record_spawn(*args, **kw):
            if spawn_crash == "before_record":
                os.kill(os.getpid(), signal.SIGKILL)
            original(*args, **kw)
            os.kill(os.getpid(), signal.SIGKILL)

        app._record_spawn = record_spawn
    app.start()
    print(json.dumps({"port": app.port, "token": app.token}), flush=True)
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        app.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()


class RecordAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="i07-rec-"))
        self.shared = self.root / "shared"

    def harness(self, **kw):
        kw.setdefault("root", self.root)
        kw.setdefault("shared", self.shared)
        return Harness(self, **kw)

    def initialized(self):
        self.shared.mkdir(parents=True, exist_ok=True)
        lb.write_json_durable(self.shared / lb.SHARED_NAME, {"version": 1, "initialized_at": "x", "jobs": {}})

    def test_i_010_shared_record_initialised_only_after_read_only_absence_check(self):
        events = []
        h = self.harness(docker=FakeDocker(events=events), write=FailingWrite(events))
        self.assertEqual(events, [("docker", "inspect", "container", lb.CONTAINER),
                                  ("docker", "inspect", "volume", lb.DATA_VOLUME),
                                  ("docker", "inspect", "volume", lb.CONFIG_VOLUME),
                                  ("write", lb.SHARED_NAME)])
        self.assertEqual(h.status()["state"], "not_ready")

    def test_i_010_missing_shared_record_with_existing_resource_or_unknown_docker_blocks(self):
        for name in ("existing_volume", "docker_error"):
            with self.subTest(name):
                root = Path(tempfile.mkdtemp(prefix="i07-rec-"))
                docker = FakeDocker()
                if name == "existing_volume":
                    docker.state["volumes"][lb.DATA_VOLUME] = {"Name": lb.DATA_VOLUME, "Labels": OWNED["data"]}
                else:
                    docker.fail["inspect"] = "Cannot connect to the Docker daemon"
                h = Harness(self, root=root, docker=docker)
                status = h.status()
                self.assertEqual(status["state"], "recovery_required")
                self.assertEqual(status["error"]["code"],
                                 "SHARED_RECORD_MISSING" if name == "existing_volume" else "SHARED_RECORD_UNVERIFIED")
                self.assertFalse((root / "shared" / lb.SHARED_NAME).exists())
                response = h.post("/api/setup")
                self.assertEqual((response[0], response[2]["error"]["code"]), (409, "RECOVERY_REQUIRED"))
                self.assertEqual(docker.mutations(), [])

    def test_i_010_first_intent_write_failure_is_500_without_external_work(self):
        for kind, path, body, state in (("setup", "/api/setup", {}, "not_ready"),
                                        ("seed", "/api/setup/seed", {"confirm_replace": True}, "seed_required"),
                                        ("run", "/api/runs", {}, "ready")):
            for target in (lb.SHARED_NAME, "detail"):
                with self.subTest(kind=kind, target=target):
                    root = Path(tempfile.mkdtemp(prefix="i07-rec-"))
                    events = []
                    write = FailingWrite(events)
                    docker = FakeDocker(events=events)
                    h = Harness(self, root=root, docker=docker, write=write)
                    h.app.state = state  # provisional seam: reach the admission state directly
                    if target == lb.SHARED_NAME:
                        write.fail_on(lb.SHARED_NAME, when=lambda d: bool(d["jobs"]))
                    else:
                        write.fail_on("runner.json" if kind == "run" else "job.json")
                    before = len(docker.ops)
                    status, _, payload = h.post(path, body)
                    self.assertEqual((status, payload["error"]["code"]), (500, "RECORD_UNAVAILABLE"))
                    self.assertNotIn("run_id", json.dumps(payload))
                    self.assertEqual(docker.ops[before:], [])
                    self.assertIsNone(h.app.thread)
                    self.assertEqual(h.status()["state"], "recovery_required")
                    if target == "detail":
                        # shared intent survived alone: still blocked after a restart
                        h.close()
                        again = Harness(self, root=root, docker=docker)
                        self.assertEqual(again.status()["state"], "recovery_required")
                        self.assertEqual(again.post(path, body)[2]["error"]["code"], "RECOVERY_REQUIRED")

    def test_i_011_restart_with_open_job_blocks_and_marks_interrupted(self):
        self.initialized()
        detail = make_detail(self.root)
        job_id, _ = open_job(self.shared, detail)
        for attempt in range(3):
            with self.subTest(attempt=attempt):
                h = self.harness()
                status = h.status()
                self.assertEqual(status["state"], "recovery_required")
                self.assertIn(job_id, status["message"])
                self.assertEqual(h.post("/api/setup", body=b"[]")[2]["error"]["code"], "INVALID_BODY")
                self.assertEqual(h.post("/api/setup")[2]["error"]["code"], "RECOVERY_REQUIRED")
                code, _, run = h.get(f"/api/runs/{job_id}")
                self.assertEqual((code, run["state"], run["error"]["code"]), (200, "failed", "SERVER_INTERRUPTED"))
                self.assertEqual(h.docker.mutations(), [])
                h.close()
        self.assertEqual(lb.read_json(self.shared / lb.SHARED_NAME)["jobs"][job_id]["status"], "open")

    def test_i_011_corrupt_shared_record_or_failed_interrupt_mark_keeps_blocking(self):
        self.shared.mkdir(parents=True)
        (self.shared / lb.SHARED_NAME).write_text("{broken")
        h = self.harness()
        self.assertEqual(h.status()["error"]["code"], "SHARED_RECORD_UNREADABLE")
        h.close()
        (self.shared / lb.SHARED_NAME).unlink()
        self.initialized()
        detail = make_detail(self.root)
        open_job(self.shared, detail)
        events = []
        write = FailingWrite(events)
        write.fail_on("runner.json")
        h = self.harness(write=write)
        self.assertEqual(h.status()["state"], "recovery_required")
        self.assertIsNone(lb.read_json(detail)["finished_at"])

    def recover(self, **kw):
        return lb.run_recover(self.shared, **kw)

    def test_i_013_release_requires_group_and_marker_absence_then_not_ready(self):
        self.initialized()
        detail = make_detail(self.root)
        dead = spawn_group()
        kill_group(dead)
        job_id, entry = open_job(self.shared, detail, children=[{"role": "benchmark", "pid": dead.pid,
                                                                  "pgid": dead.pid, "started_at": "x"}])
        report = self.recover()
        self.assertEqual((report["exit"], report["released"], report["blocked"]), (0, [job_id], {}))
        shared = lb.read_json(self.shared / lb.SHARED_NAME)["jobs"][job_id]
        self.assertEqual(shared["status"], "released")
        self.assertEqual(shared["release"]["groups"], {str(dead.pid): "ESRCH"})
        self.assertEqual(shared["release"]["marker_processes"], [])
        self.assertEqual(lb.read_json(detail)["recovery"]["groups"], {str(dead.pid): "ESRCH"})
        self.assertEqual(lb.read_json(detail)["error"]["code"], "SERVER_INTERRUPTED")
        h = self.harness()
        self.assertEqual(h.status()["state"], "not_ready")

    def test_i_013_live_or_unidentifiable_targets_stay_blocked_without_signals(self):
        cases = ["live_marked_group", "pid_reuse_unrelated_group", "marker_without_pid",
                 "scan_failed", "detail_dir_missing", "detail_write_fails", "shared_write_fails"]
        for name in cases:
            with self.subTest(name):
                root = Path(tempfile.mkdtemp(prefix="i07-rec-"))
                shared = root / "shared"
                marker = os.urandom(16).hex()
                detail = make_detail(root)
                procs, children, kw = [], [], {}
                if name == "live_marked_group":
                    procs.append(spawn_group(marker))
                    children.append({"pid": procs[0].pid, "pgid": procs[0].pid})
                elif name == "pid_reuse_unrelated_group":
                    procs.append(spawn_group())
                    children.append({"pid": procs[0].pid, "pgid": procs[0].pid})
                elif name == "marker_without_pid":
                    procs.append(spawn_group(marker))
                    time.sleep(0.3)
                elif name == "scan_failed":
                    kw["scan"] = lambda marker: None
                elif name == "detail_dir_missing":
                    detail.unlink()
                    detail.parent.rmdir()
                elif name == "detail_write_fails":
                    write = FailingWrite([])
                    write.fail_on(detail.name)
                    kw["write"] = write
                else:
                    write = FailingWrite([])
                    write.fail_on(lb.SHARED_NAME)
                    kw["write"] = write
                job_id, _ = open_job(shared, detail, children=children, marker=marker)
                try:
                    report = lb.run_recover(shared, **kw)
                    self.assertEqual(report["exit"], 1)
                    self.assertIn(job_id, report["blocked"])
                    self.assertEqual(lb.read_json(shared / lb.SHARED_NAME)["jobs"][job_id]["status"], "open")
                    for proc in procs:
                        self.assertIsNone(proc.poll(), "recovery must not signal any process")
                    h = Harness(self, root=root, shared=shared)
                    self.assertEqual(h.status()["state"], "recovery_required")
                finally:
                    for proc in procs:
                        kill_group(proc)

    def test_i_013_missing_or_unverifiable_detail_record_is_never_fabricated(self):
        def no_runner(detail):
            detail.unlink()

        def artifacts_without_runner(detail):
            detail.unlink()
            (detail.parent / "results.json").write_text(json.dumps(valid_results(detail.parent / "results.json")))
            (detail.parent / "benchmark.stdout.log").write_text("partial log\n")

        def broken_symlink(detail):
            detail.unlink()
            os.symlink(detail.parent / "gone.json", detail)

        def not_object(detail):
            detail.write_text("[]")

        cases = {"A_dir_only": no_runner, "B_artifacts_only": artifacts_without_runner,
                 "C_broken_symlink": broken_symlink, "not_object": not_object}
        for name, damage in cases.items():
            with self.subTest(name):
                root = Path(tempfile.mkdtemp(prefix="i07-rec-"))
                shared = root / "shared"
                detail = make_detail(root)
                job_id, _ = open_job(shared, detail)
                damage(detail)

                def snapshot():
                    return sorted((p.name, os.path.islink(p), os.readlink(p) if os.path.islink(p) else
                                   p.read_bytes()) for p in detail.parent.iterdir())

                before, shared_before = snapshot(), (shared / lb.SHARED_NAME).read_bytes()
                report = lb.run_recover(shared)
                self.assertEqual(report["exit"], 1, report)
                self.assertIn(job_id, report["blocked"])
                self.assertEqual(snapshot(), before)  # nothing created or replaced
                self.assertEqual((shared / lb.SHARED_NAME).read_bytes(), shared_before)
                self.assertEqual(lb.read_json(shared / lb.SHARED_NAME)["jobs"][job_id]["status"], "open")
                h = Harness(self, root=root, shared=shared)
                self.assertEqual(h.status()["state"], "recovery_required")
                h.close()
                self.assertEqual(snapshot(), before)

    def test_i_013_marker_scan_finds_real_process_environment(self):
        marker = os.urandom(16).hex()
        proc = spawn_group(marker)
        try:
            time.sleep(0.3)
            self.assertIn(proc.pid, lb.marker_processes(marker))
            self.assertNotIn(proc.pid, lb.marker_processes(os.urandom(16).hex()))
        finally:
            kill_group(proc)

    def test_i_012_one_server_per_shared_scope_across_checkouts(self):
        a_root, b_root = self.root / "checkout-a", self.root / "checkout-b"
        proc, info = launch_server({"docker_state": str(self.root / "docker.json"),
                                    "run_root": str(a_root / "var"), "shared": str(self.shared)}, self)
        try:
            b = lb.LiveBenchmark(port=0, run_root=b_root / "var", shared_dir=self.shared,
                                 docker=FakeDocker(str(self.root / "docker.json")))
            with self.assertRaises(lb.LockBusy):
                b.start()
            self.assertEqual(lb.run_recover(self.shared)["exit"], 2)
        finally:
            proc.terminate()
            proc.wait(10)
        self.assertEqual(proc.returncode, 0)

    def test_i_012_other_checkouts_open_job_blocks_this_checkout(self):
        self.initialized()
        a_detail = make_detail(self.root / "checkout-a", kind="seed")
        job_id, _ = open_job(self.shared, a_detail, kind="seed")
        b_root = self.root / "checkout-b"
        for variant in ("open", "a_detail_unreachable", "release_write_fails"):
            with self.subTest(variant):
                if variant == "a_detail_unreachable":
                    hidden = a_detail.parent.with_name(a_detail.parent.name + "-moved")
                    a_detail.parent.rename(hidden)
                    self.assertEqual(lb.run_recover(self.shared)["exit"], 1)
                    hidden.rename(a_detail.parent)
                if variant == "release_write_fails":
                    write = FailingWrite([])
                    write.fail_on(lb.SHARED_NAME)
                    self.assertEqual(lb.run_recover(self.shared, write=write)["exit"], 1)
                b = Harness(self, root=b_root, shared=self.shared)
                self.assertEqual(b.status()["state"], "recovery_required")
                self.assertEqual(b.post("/api/setup")[2]["error"]["code"], "RECOVERY_REQUIRED")
                b.close()
                a = Harness(self, root=self.root / "checkout-a", shared=self.shared)
                self.assertEqual(a.status()["state"], "recovery_required")
                a.close()
        self.assertEqual(lb.run_recover(self.shared)["exit"], 0)
        b = Harness(self, root=b_root, shared=self.shared)
        self.assertEqual(b.status()["state"], "not_ready")


SEED_OK = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    flag = Path(sys.argv[1])
    runs = json.loads(flag.read_text())["runs"] if flag.exists() else 0
    flag.write_text(json.dumps({"runs": runs + 1, "pgid_is_pid": os.getpgid(0) == os.getpid(),
                                "marker": os.environ.get("MINI_REDIS_LIVE_JOB")}))
""")
SEED_FAIL = "import sys; sys.stderr.write('seed boom\\n'); sys.exit(3)"
SEED_HANG = "import time; time.sleep(60)"


def seed_cmd(script, flag):
    return lambda: [sys.executable, "-c", script, str(flag)]


class SetupAndSeedTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="i07-setup-"))
        self.flag = self.root / "seeded.json"

    def harness(self, docker=None, seeded=False, script=SEED_OK, **kw):
        world = MongoWorld(seeded=seeded, flag=self.flag)
        return Harness(self, root=kw.pop("root", self.root), docker=docker, world=world,
                       seed=seed_cmd(script, self.flag), **kw)

    def job(self, h, job_id):
        return lb.read_json(h.root / "var" / "jobs" / job_id / "job.json")

    def setup(self, h, path="/api/setup", body=None):
        status, _, payload = h.post(path, body)
        self.assertEqual(status, 202, payload)
        self.assertEqual(payload["state"], "preparing")
        job_id = payload["active_job"]["job_id"]
        final = h.idle()
        return job_id, final

    def test_i_001_first_setup_creates_owned_resources_and_seeds_new_volume(self):
        docker = FakeDocker()
        del docker.state["images"][lb.IMAGE]
        h = self.harness(docker)
        job_id, final = self.setup(h)
        self.assertEqual((final["state"], final["error"]), ("ready", None))
        detail = self.job(h, job_id)
        for step in ("checking_docker", "pulling_image", "preparing_volumes", "starting_container",
                     "waiting_mongo", "checking_seed", "seeding", "rechecking_seed"):
            self.assertIn(step, detail["steps"])
        self.assertEqual(final["resources"]["image_id"], "sha256:pulled")
        self.assertEqual([op[0] for op in docker.mutations()],
                         ["pull", "create_volume", "create_volume", "run_container"])
        container = docker.state["containers"][lb.CONTAINER]
        self.assertIsNone(lb.container_problem(container))
        self.assertEqual({m["Name"] for m in container["Mounts"]}, {lb.DATA_VOLUME, lb.CONFIG_VOLUME})
        seeded = json.loads(self.flag.read_text())
        self.assertEqual(seeded["runs"], 1)
        self.assertTrue(seeded["pgid_is_pid"])
        self.assertEqual(seeded["marker"], detail["marker"])
        self.assertEqual(detail["children"][0]["pgid"], detail["children"][0]["pid"])
        self.assertFalse(detail["reap"]["seed"]["leftover"])
        shared = lb.read_json(h.shared / lb.SHARED_NAME)["jobs"][job_id]
        self.assertEqual(shared["status"], "released")
        self.assertEqual(shared["children"][0]["pid"], detail["children"][0]["pid"])
        # re-preparing an existing volume keeps the data and does not seed again
        before = len(docker.mutations())
        _, again = self.setup(h)
        self.assertEqual(again["state"], "ready")
        self.assertEqual(docker.mutations()[before:], [])
        self.assertEqual(json.loads(self.flag.read_text())["runs"], 1)

    def test_i_002_foreign_or_mismatched_resources_fail_without_touching_them(self):
        def unlabeled_container(d):
            d.own_everything()
            d.state["containers"][lb.CONTAINER]["Config"]["Labels"] = {}

        def memory_mismatch(d):
            d.own_everything(running=False)
            d.state["containers"][lb.CONTAINER]["HostConfig"]["Memory"] = 2 << 30

        def anonymous_volume(d):
            d.own_everything()
            d.state["containers"][lb.CONTAINER]["Mounts"].append(
                {"Type": "volume", "Name": "f00d" * 16, "Destination": "/extra"})

        def foreign_volume(d):
            d.state["volumes"][lb.DATA_VOLUME] = {"Name": lb.DATA_VOLUME, "Labels": {}}

        def port_taken(d):
            d.fail["run_container"] = "Bind for 127.0.0.1:27018 failed: port is already allocated"
            d.hooks["run_container"] = lambda: d.state["containers"].__setitem__(
                lb.CONTAINER, good_container(OWNED["mongo"], running=False))

        cases = {"unlabeled_container": (unlabeled_container, "RESOURCE_CONFLICT"),
                 "memory_mismatch": (memory_mismatch, "RESOURCE_MISMATCH"),
                 "anonymous_volume": (anonymous_volume, "RESOURCE_MISMATCH"),
                 "foreign_volume": (foreign_volume, "RESOURCE_CONFLICT"),
                 "port_taken": (port_taken, "PORT_CONFLICT")}
        for name, (prepare, code) in cases.items():
            with self.subTest(name):
                root = Path(tempfile.mkdtemp(prefix="i07-setup-"))
                docker = FakeDocker()
                h = self.harness(docker, root=root)  # shared record initialised while Docker is empty
                prepare(docker)
                snapshot = json.dumps(docker.state, sort_keys=True)
                _, final = self.setup(h)
                self.assertEqual((final["state"], final["error"]["code"]), ("failed", code))
                allowed = {"port_taken": ["create_volume", "create_volume", "run_container"],
                           "foreign_volume": []}.get(name, [])
                self.assertEqual([op[0] for op in docker.mutations()], allowed)
                if name != "port_taken":
                    self.assertEqual(json.dumps(docker.state, sort_keys=True), snapshot)
                else:
                    self.assertIn(lb.CONTAINER, docker.state["containers"])  # left for the next attempt
                self.assertFalse(self.flag.exists())

    def test_i_002_volume_create_returning_existing_volume_is_not_new(self):
        docker = FakeDocker()
        h = self.harness(docker)
        # another creator wins the race: create returns the existing volume with a different nonce
        docker.hooks["create_volume"] = lambda: docker.state["volumes"].setdefault(
            lb.DATA_VOLUME, {"Name": lb.DATA_VOLUME, "Labels": {**OWNED["data"], lb.CREATED_LABEL: "other"}})
        _, final = self.setup(h)
        self.assertEqual(final["state"], "seed_required")
        self.assertFalse(self.flag.exists())

    def test_i_003_existing_empty_volume_is_never_auto_seeded(self):
        docker = FakeDocker()
        h = self.harness(docker)
        docker.own_everything()
        _, final = self.setup(h)
        self.assertEqual((final["state"], final["error"]["reason"]), ("seed_required", "missing"))
        self.assertFalse(self.flag.exists())

    def test_i_003_seed_never_starts_when_recheck_before_seed_fails(self):
        docker = FakeDocker()
        h = self.harness(docker)
        h.world.hooks["ping"] = lambda: docker.state["containers"][lb.CONTAINER]["Config"].__setitem__(
            "Labels", {})
        _, final = self.setup(h)
        self.assertEqual((final["state"], final["error"]["code"]), ("failed", "RESOURCE_CONFLICT"))
        self.assertFalse(self.flag.exists())

    def test_i_003_crash_after_volume_creation_blocks_then_needs_confirmation(self):
        shared = self.root / "shared"
        state = self.root / "docker.json"
        FakeDocker(str(state)).save()
        proc, info = launch_server({"docker_state": str(state), "run_root": str(self.root / "var"),
                                    "shared": str(shared), "seeded": False, "seed_flag": str(self.flag),
                                    "crash_on_docker": "run_container",
                                    "seed": [sys.executable, "-c", SEED_OK, str(self.flag)]}, self)
        conn = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=10)
        host = f"127.0.0.1:{info['port']}"
        conn.request("POST", "/api/setup", body=b"{}", headers={
            "Host": host, "Origin": f"http://{host}", "Content-Type": "application/json",
            "X-Live-Bench-Token": info["token"]})
        self.assertEqual(conn.getresponse().status, 202)
        proc.wait(10)
        self.assertEqual(proc.returncode, -signal.SIGKILL)
        self.assertEqual(set(json.loads(state.read_text())["volumes"]), {lb.DATA_VOLUME, lb.CONFIG_VOLUME})
        h = self.harness(FakeDocker(str(state)), shared=shared)
        self.assertEqual(h.status()["state"], "recovery_required")
        self.assertEqual(h.post("/api/setup")[2]["error"]["code"], "RECOVERY_REQUIRED")
        self.assertFalse(self.flag.exists())
        h.close()
        report = lb.run_recover(shared)
        self.assertEqual(report["exit"], 0, report)
        h = self.harness(FakeDocker(str(state)), shared=shared)
        self.assertEqual(h.status()["state"], "not_ready")
        _, final = self.setup(h)
        self.assertEqual(final["state"], "seed_required")
        self.assertFalse(self.flag.exists())

    def test_i_004_seed_endpoint_requires_confirmation_and_seed_required(self):
        docker = FakeDocker()
        h = self.harness(docker)
        for state in ("not_ready", "ready"):
            with self.subTest(state):
                h.app.state = state  # provisional seam for the non-seed states
                self.assertEqual(h.post("/api/setup/seed", {"confirm_replace": True})[2]["error"]["code"],
                                 "SEED_NOT_REQUIRED")
        h.app.state = "not_ready"
        docker.own_everything()
        _, final = self.setup(h)
        self.assertEqual(final["state"], "seed_required")
        for body in ({}, {"confirm_replace": False}):
            self.assertEqual(h.post("/api/setup/seed", body)[2]["error"]["code"], "CONFIRMATION_REQUIRED")
        self.assertFalse(self.flag.exists())
        status, _, accepted = h.post("/api/setup/seed", {"confirm_replace": True})
        self.assertEqual((status, accepted["state"], accepted["step"]), (202, "preparing", "seeding"))
        final = h.idle()
        self.assertEqual(final["state"], "ready")
        self.assertEqual(json.loads(self.flag.read_text())["runs"], 1)
        self.assertEqual(docker.mutations(), [])
        detail = self.job(h, accepted["active_job"]["job_id"])
        self.assertIn("rechecking_seed", detail["steps"])

    def test_i_005_accepted_setup_failures_are_classified(self):
        def no_image(d):
            del d.state["images"][lb.IMAGE]
            d.fail["pull"] = "pull access denied"

        cases = {"docker_down": (lambda d, w: d.fail.__setitem__("info", "Cannot connect"),
                                 SEED_OK, ("failed", "DOCKER_UNAVAILABLE")),
                 "pull_failed": (lambda d, w: no_image(d), SEED_OK, ("failed", "IMAGE_PULL_FAILED")),
                 "mongo_down": (lambda d, w: w.fail.add("ping"), SEED_OK, ("failed", "MONGO_NOT_READY")),
                 "seed_failed": (lambda d, w: None, SEED_FAIL, ("seed_required", "SEED_FAILED")),
                 "seed_timeout": (lambda d, w: None, SEED_HANG, ("seed_required", "SEED_TIMEOUT"))}
        for name, (prepare, script, expected) in cases.items():
            with self.subTest(name):
                root = Path(tempfile.mkdtemp(prefix="i07-setup-"))
                docker = FakeDocker()
                h = self.harness(docker, root=root, script=script, timeouts={"seed": 1})
                prepare(docker, h.world)
                job_id, final = self.setup(h)
                self.assertEqual((final["state"], final["error"]["code"]), expected)
                self.assertNotIn("rm", [op[0] for op in docker.ops])
                detail = self.job(h, job_id)
                if name.startswith("seed"):
                    reap = detail["reap"]["seed"]
                    self.assertFalse(reap["leftover"])
                    self.assertTrue((h.root / "var" / "jobs" / job_id / "seed.stderr.log").exists())
                    if name == "seed_timeout":
                        self.assertEqual(reap["signals"][0], "SIGINT->pid")
                    else:
                        self.assertIn(b"seed boom", (h.root / "var" / "jobs" / job_id / "seed.stderr.log").read_bytes())
                self.assertEqual(lb.read_json(h.shared / lb.SHARED_NAME)["jobs"][job_id]["status"], "released")

    def test_i_009_second_write_is_busy_while_a_job_holds_the_slot(self):
        docker = FakeDocker()
        gate, entered = threading.Event(), threading.Event()
        docker.hooks["info"] = lambda: (entered.set(), gate.wait(10))
        h = self.harness(docker)
        h.app.state = "ready"  # provisional seam: a run would also be admissible without the slot
        status, _, first = h.post("/api/setup")
        self.assertEqual(status, 202)
        self.assertTrue(entered.wait(5))
        ops = len(docker.ops)
        for path, body in (("/api/setup", {}), ("/api/setup/seed", {"confirm_replace": True}),
                           ("/api/runs", {})):
            with self.subTest(path):
                status, response, payload = h.post(path, body)
                self.assertEqual((status, payload["error"]["code"]), (409, "BUSY"))
        self.assertEqual(len(docker.ops), ops)
        self.assertEqual(list((h.root / "var" / "runs").iterdir()), [])
        self.assertEqual(h.status()["active_job"]["job_id"], first["active_job"]["job_id"])
        gate.set()
        self.assertIsNone(h.idle()["active_job"])

    def test_i_011_step_record_failure_stops_setup_and_seed_before_changes(self):
        cases = {"preparing_volumes": ("/api/setup", {}, []),
                 "starting_container": ("/api/setup", {}, ["create_volume", "create_volume"]),
                 "seeding": ("/api/setup/seed", {"confirm_replace": True}, [])}
        for step, (path, body, allowed) in cases.items():
            with self.subTest(step):
                root = Path(tempfile.mkdtemp(prefix="i07-setup-"))
                self.flag = root / "seeded.json"  # per sub-case seed evidence
                write = FailingWrite([])
                docker = FakeDocker()
                h = self.harness(docker, root=root, write=write)
                if step == "seeding":
                    docker.own_everything()
                    self.setup(h)
                    self.assertEqual(h.status()["state"], "seed_required")
                before = len(docker.ops)
                write.fail_on("job.json", when=lambda d, s=step: d.get("step") == s)
                job_id, final = self.setup(h, path, body)
                self.assertEqual(final["state"], "recovery_required")
                self.assertEqual([op[0] for op in docker.ops[before:] if op[0] in MUTATING], allowed)
                self.assertFalse(self.flag.exists())  # no seed child
                detail = self.job(h, job_id)
                self.assertEqual((detail["error"]["code"], detail["children"]), ("RECORD_UNAVAILABLE", []))
                self.assertEqual(lb.read_json(h.shared / lb.SHARED_NAME)["jobs"][job_id]["status"], "open")

    def test_i_010_intent_records_precede_any_docker_call(self):
        events = []
        docker = FakeDocker(events=events)
        h = self.harness(docker, write=FailingWrite(events))
        start = len(events)
        self.setup(h)
        accepted = events[start:]
        first_docker = next(i for i, e in enumerate(accepted) if e[0] == "docker")
        self.assertEqual(accepted[:2], [("write", lb.SHARED_NAME), ("write", "job.json")])
        self.assertGreater(first_docker, 1)


FAKE_BENCH = textwrap.dedent("""
    # stand-in for examples/benchmark.py: same CLI shape, writes a given raw result
    import json, os, signal, subprocess, sys, time
    from pathlib import Path
    mode, template = sys.argv[1], sys.argv[2]
    out = Path(sys.argv[sys.argv.index("--output") + 1])
    data = json.loads(Path(template).read_text())
    data["command"] = [sys.executable, *sys.argv]
    def write(d):
        out.write_text(json.dumps(d))
    def server(ignore_int):
        code = "import signal, time\\n"
        if ignore_int:
            code += "signal.signal(signal.SIGINT, signal.SIG_IGN)\\n"
        code += "time.sleep(60)"
        child = subprocess.Popen([sys.executable, "-c", code])  # same group, like benchmark.py
        with open(out.parent / "child.pid", "a") as f:
            f.write(f"{child.pid}\\n")
        return child
    if mode == "ok":
        write(data); sys.exit(0)
    if mode == "pre_error":
        sys.stderr.write("ServerSelectionTimeoutError: before results\\n"); sys.exit(1)
    if mode == "loop":
        child = server(False)
        def stop(*_):
            child.send_signal(signal.SIGINT); child.wait()
            data["aborted"] = "KeyboardInterrupt: "
            data["summary"]["complete"] = False
            data["summary"]["hit"].update(successes=7, failures=1)
            write(data); sys.exit(1)
        signal.signal(signal.SIGINT, stop)
        time.sleep(60)
    if mode == "stubborn":
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        server(True); time.sleep(60)
    if mode == "orphan":
        server(True); write(data); sys.exit(0)
""")


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class RunTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="i07-run-"))
        self.script = self.root / "fake_bench.py"
        self.script.write_text(FAKE_BENCH)
        self.template = self.root / "template.json"
        self.template.write_text(json.dumps(valid_results("placeholder")))
        self.events = []

    def bench(self, mode):
        return lambda out: [sys.executable, str(self.script), mode, str(self.template),
                            "--output", str(out), "--mongo-uri", lb.MONGO_URI]

    def ready(self, mode="ok", root=None, timeouts=None, **kw):
        docker = kw.pop("docker", None) or FakeDocker(events=self.events)
        world = kw.pop("world", None) or MongoWorld(events=self.events)
        h = Harness(self, root=root or self.root, docker=docker, world=world, bench=self.bench(mode),
                    timeouts=timeouts, **kw)
        docker.own_everything()
        h.post("/api/setup")
        self.assertEqual(h.idle()["state"], "ready")
        return h

    def run_once(self, h, timeout=20):
        status, _, accepted = h.post("/api/runs")
        self.assertEqual((status, set(accepted), accepted["state"]), (202, {"run_id", "state"}, "preparing"))
        h.idle(timeout)
        code, _, view = h.get(f"/api/runs/{accepted['run_id']}")
        self.assertEqual(code, 200)
        return accepted["run_id"], view

    def children(self, h, run_id):
        path = h.root / "var" / "runs" / run_id / "child.pid"
        return [int(x) for x in path.read_text().split()] if path.exists() else []

    def test_i_014_prechecks_restart_once_then_measure_without_reading_documents(self):
        h = self.ready()
        start = len(self.events)
        run_id, view = self.run_once(h)
        self.assertEqual((view["state"], view["error"]), ("succeeded", None))
        events = self.events[start:]
        restart = events.index(("docker", "restart"))
        self.assertEqual(events.count(("docker", "restart")), 1)
        self.assertIn(("mongo", "values"), events[:restart])
        after = {e[1] for e in events[restart + 1:] if e[0] == "mongo"}
        self.assertTrue(after <= {"ping", "cache_max_bytes", "coll_stats", "close"}, after)
        self.assertNotEqual(view["restart"]["started_before"], view["restart"]["started_after"])
        self.assertEqual(view["precheck"]["status"], "ok")
        self.assertEqual(view["precheck"]["keys"]["measurement_keys"], 315)
        steps = list(view["steps"])
        self.assertLess(steps.index("checking_seed"), steps.index("restarting"))
        self.assertLess(steps.index("verifying_restart"), steps.index("running_benchmark"))
        summary = valid_results("x")["summary"]
        for c in CONDITIONS:
            self.assertEqual(view["result"]["conditions"][c]["median_ms"], summary[c]["median_ms"])
        self.assertEqual(view["result"]["environment"]["runner"]["image_id"], "sha256:img")
        self.assertTrue(view["artifacts"]["files"]["results.json"])
        self.assertEqual(h.status()["state"], "ready")

    def test_i_014_precheck_failures_never_start_the_benchmark(self):
        cases = {
            "seed_mismatch": (lambda d, w: w.overrides.update(demo="x"), "SEED_MISMATCH", "seed_required"),
            "seed_query": (lambda d, w: w.fail.add("values"), "SEED_CHECK_FAILED", "failed"),
            "restart": (lambda d, w: d.fail.__setitem__("restart", "boom"), "RESTART_FAILED", "failed"),
            "after_restart_ping": (lambda d, w: d.hooks.__setitem__("restart", lambda: w.fail.add("ping")),
                                   "RESTART_FAILED", "failed"),
        }
        for name, (inject, code, readiness) in cases.items():
            with self.subTest(name):
                self.events = []
                h = self.ready(root=Path(tempfile.mkdtemp(prefix="i07-run-")))
                inject(h.docker, h.world)
                run_id, view = self.run_once(h)
                self.assertEqual((view["state"], view["error"]["code"]), ("failed", code))
                self.assertIsNone(view["result"])
                self.assertIsNone(view["partial"])
                self.assertFalse(view["artifacts"]["files"]["results.json"])
                self.assertNotIn("benchmark", view["reap"])
                self.assertEqual(h.status()["state"], readiness)
                restarts = h.docker.ops.count(("restart",))
                self.assertEqual(restarts, 0 if name.startswith("seed") else 1)

    def test_i_015_runs_get_unique_dirs_and_survive_restart(self):
        h = self.ready()
        first, view1 = self.run_once(h)
        runner1 = (h.root / "var" / "runs" / first / "results.json").read_bytes()
        second, view2 = self.run_once(h)
        self.assertNotEqual(first, second)
        for rid in (first, second):
            self.assertRegex(rid, r"\A[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\Z")
            data = json.loads((h.root / "var" / "runs" / rid / "results.json").read_text())
            arg = data["command"][data["command"].index("--output") + 1]
            self.assertEqual(Path(arg).resolve(), (h.root / "var" / "runs" / rid / "results.json").resolve())
        self.assertEqual((h.root / "var" / "runs" / first / "results.json").read_bytes(), runner1)
        self.assertNotIn(str(h.root), json.dumps(view2))
        self.assertEqual(h.status()["last_run_id"], second)
        h.close()
        again = Harness(self, root=self.root, docker=h.docker)
        code, _, view = again.get(f"/api/runs/{first}")
        self.assertEqual((code, view["state"], view["result"]), (200, "succeeded", view1["result"]))
        self.assertEqual(again.status()["last_run_id"], second)

    def test_i_015_id_collision_never_reuses_an_existing_directory(self):
        ids = iter(["20261119T000000Z-00000000000000aa", "20261119T000000Z-00000000000000aa",
                    "20261119T000001Z-00000000000000bb"])
        h = self.ready(new_id=lambda: next(ids))
        first, _ = self.run_once(h)
        before = {p.name: p.read_bytes() for p in (h.root / "var" / "runs" / first).iterdir()}
        second, view = self.run_once(h)
        self.assertEqual((first, second), ("20261119T000000Z-00000000000000aa",
                                           "20261119T000001Z-00000000000000bb"))
        self.assertEqual({p.name: p.read_bytes() for p in (h.root / "var" / "runs" / first).iterdir()}, before)

    def test_i_016_benchmark_timeout_interrupts_leader_then_group(self):
        for mode, signals in (("loop", ["SIGINT->pid"]), ("stubborn", ["SIGINT->pid", "SIGKILL->group"])):
            with self.subTest(mode):
                h = self.ready(mode, root=Path(tempfile.mkdtemp(prefix="i07-run-")),
                               timeouts={"bench": 1.5, "grace": 1})
                run_id, view = self.run_once(h)
                self.assertEqual((view["state"], view["error"]["code"]), ("timed_out", "TIMED_OUT"))
                reap = view["reap"]["benchmark"]
                self.assertEqual((reap["abort"], reap["signals"][:len(signals)], reap["leftover"]),
                                 ("timeout", signals, False))
                self.assertIsNone(view["result"])
                if mode == "loop":
                    self.assertEqual(view["partial"]["aborted"], "KeyboardInterrupt: ")
                    self.assertEqual(view["partial"]["conditions"]["hit"], {"successes": 7, "failures": 1})
                else:
                    self.assertIsNone(view["partial"])
                for pid in self.children(h, run_id) + [reap["pid"]]:
                    self.assertFalse(pid_alive(pid))
                self.assertEqual(h.status()["state"], "ready")

    def test_i_016_group_leftover_after_normal_exit_is_killed_and_checked(self):
        h = self.ready("orphan")
        run_id, view = self.run_once(h)
        reap = view["reap"]["benchmark"]
        self.assertEqual((reap["exit"], reap["signals"], reap["leftover"]), (0, ["SIGKILL->group"], False))
        self.assertEqual(view["state"], "succeeded")
        self.assertTrue(self.children(h, run_id))
        for pid in self.children(h, run_id):
            self.assertFalse(pid_alive(pid))

    def test_i_016_failures_before_results_and_spawn_errors(self):
        h = self.ready("pre_error")
        run_id, view = self.run_once(h)
        self.assertEqual((view["state"], view["error"]["code"], view["partial"]), ("failed", "BENCHMARK_FAILED", None))
        self.assertIn(b"ServerSelectionTimeoutError",
                      (h.root / "var" / "runs" / run_id / "benchmark.stderr.log").read_bytes())
        h.app.bench_cmd = lambda out: [str(self.root / "missing-interpreter"), "--output", str(out)]
        run_id, view = self.run_once(h)
        reap = view["reap"]["benchmark"]
        self.assertEqual((view["state"], view["error"]["code"]), ("failed", "BENCHMARK_FAILED"))
        self.assertEqual((reap["pid"], reap["signals"]), (None, []))
        self.assertTrue(reap["spawn_error"])
        self.assertEqual(h.status()["state"], "ready")

    def test_i_016_unconfirmed_reaping_blocks_for_benchmark_and_seed(self):
        h = self.ready()
        with unittest.mock.patch.object(lb, "group_gone", lambda pgid: False):
            run_id, view = self.run_once(h)
        self.assertEqual(view["state"], "failed")
        self.assertIsNone(view["result"])
        self.assertTrue(view["reap"]["benchmark"]["leftover"])
        self.assertEqual(h.status()["state"], "recovery_required")
        self.assertEqual(lb.read_json(h.shared / lb.SHARED_NAME)["jobs"][run_id]["status"], "open")
        self.assertEqual(h.post("/api/runs")[2]["error"]["code"], "RECOVERY_REQUIRED")
        # seed path
        root = Path(tempfile.mkdtemp(prefix="i07-run-"))
        flag = root / "seeded.json"
        docker = FakeDocker()
        s = Harness(self, root=root, docker=docker, world=MongoWorld(seeded=False, flag=flag),
                    seed=seed_cmd(SEED_OK, flag))
        with unittest.mock.patch.object(lb, "group_gone", lambda pgid: False):
            s.post("/api/setup")
            final = s.idle()
        self.assertEqual(final["state"], "recovery_required")
        job_id = [j for j in lb.read_json(s.shared / lb.SHARED_NAME)["jobs"]][0]
        self.assertEqual(lb.read_json(s.shared / lb.SHARED_NAME)["jobs"][job_id]["status"], "open")

    def test_i_016_graceful_stop_reaps_then_records_server_stopped(self):
        h = self.ready("loop", timeouts={"bench": 60})
        status, _, accepted = h.post("/api/runs")
        run_dir = h.root / "var" / "runs" / accepted["run_id"]
        deadline = time.monotonic() + 10
        while not (run_dir / "child.pid").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        h.close()
        detail = lb.read_json(run_dir / "runner.json")
        self.assertEqual((detail["state"], detail["error"]["code"]), ("failed", "SERVER_STOPPED"))
        self.assertEqual(detail["reap"]["benchmark"]["signals"][0], "SIGINT->pid")
        self.assertFalse(detail["reap"]["benchmark"]["leftover"])
        self.assertEqual(lb.read_json(h.shared / lb.SHARED_NAME)["jobs"][accepted["run_id"]]["status"], "released")
        for pid in self.children(h, accepted["run_id"]):
            self.assertFalse(pid_alive(pid))

    def test_i_011_pid_record_failure_reaps_in_memory_identity_and_blocks(self):
        write = FailingWrite([])
        h = self.ready("loop", write=write, timeouts={"bench": 60})
        write.fail_on("runner.json", when=lambda d: bool(d.get("children")))
        run_id, view = self.run_once(h)
        reap = view["reap"]["benchmark"]
        self.assertEqual((reap["abort"], reap["record_error"], reap["leftover"]), ("record", True, False))
        self.assertFalse(pid_alive(reap["pid"]))
        self.assertEqual(h.status()["state"], "recovery_required")
        self.assertEqual(lb.read_json(h.shared / lb.SHARED_NAME)["jobs"][run_id]["status"], "open")

    def test_i_011_step_record_failure_stops_before_restart_or_benchmark(self):
        write = FailingWrite([])
        h = self.ready(write=write)
        write.fail_on("runner.json", when=lambda d: d.get("step") == "restarting")
        before = len(h.docker.ops)
        run_id, view = self.run_once(h)
        self.assertEqual((view["state"], view["error"]["code"]), ("failed", "RECORD_UNAVAILABLE"))
        self.assertEqual([op for op in h.docker.ops[before:] if op[0] in MUTATING], [])
        self.assertNotIn("benchmark", view["reap"])
        self.assertFalse(view["artifacts"]["files"]["results.json"])
        self.assertIsNone(view["result"])
        self.assertEqual(h.status()["state"], "recovery_required")
        self.assertEqual(lb.read_json(h.shared / lb.SHARED_NAME)["jobs"][run_id]["status"], "open")

    def test_i_011_i_012_crash_points_in_checkout_a_block_checkout_b_until_recovered(self):
        for point in ("before_spawn", "before_record", "after_record"):
            with self.subTest(point):
                base = Path(tempfile.mkdtemp(prefix="i07-run-"))
                shared, state = base / "shared", base / "docker.json"
                # resources made by an earlier, recorded setup: the shared record already exists
                shared.mkdir()
                lb.write_json_durable(shared / lb.SHARED_NAME, {"version": 1, "initialized_at": "x", "jobs": {}})
                seed_docker = FakeDocker(str(state))
                seed_docker.own_everything()
                config = {"docker_state": str(state), "run_root": str(base / "a" / "var"),
                          "shared": str(shared),
                          "bench": [sys.executable, str(self.script), "loop", str(self.template)]}
                if point == "before_spawn":
                    config["crash_on_docker"] = "restart"
                else:
                    config["crash_on_spawn"] = point
                proc, info = launch_server(config, self)
                host = f"127.0.0.1:{info['port']}"
                headers = {"Host": host, "Origin": f"http://{host}", "Content-Type": "application/json",
                           "X-Live-Bench-Token": info["token"]}

                def post(path):
                    conn = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=10)
                    conn.request("POST", path, body=b"{}", headers=headers)
                    response = conn.getresponse()
                    return response.status, json.loads(response.read())

                def setup_state():
                    conn = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=10)
                    conn.request("GET", "/api/setup", headers={"Host": host})
                    return json.loads(conn.getresponse().read())

                self.assertEqual(post("/api/setup")[0], 202)
                deadline = time.monotonic() + 10
                while setup_state()["state"] != "ready" and time.monotonic() < deadline:
                    time.sleep(0.05)
                code, accepted = post("/api/runs")
                self.assertEqual(code, 202)
                proc.wait(15)
                self.assertEqual(proc.returncode, -signal.SIGKILL)
                run_id = accepted["run_id"]
                entry = lb.read_json(shared / lb.SHARED_NAME)["jobs"][run_id]
                self.assertEqual(entry["status"], "open")
                orphans = []
                if point != "before_spawn":
                    time.sleep(0.5)
                    orphans = lb.marker_processes(entry["marker"])
                    self.assertTrue(orphans, "the measurement process outlived its server")
                self.assertEqual(bool(entry["children"]), point == "after_record")
                try:
                    for attempt in range(2):
                        b = Harness(self, root=base / "b", shared=shared, docker=FakeDocker(str(state)))
                        self.assertEqual(b.status()["state"], "recovery_required")
                        self.assertEqual(b.post("/api/setup")[2]["error"]["code"], "RECOVERY_REQUIRED")
                        b.close()
                    view = lb.read_json(base / "a" / "var" / "runs" / run_id / "runner.json")
                    self.assertEqual(view["error"]["code"], "SERVER_INTERRUPTED")
                    if orphans:
                        self.assertEqual(lb.run_recover(shared)["exit"], 1)
                        for pid in orphans:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(os.getpgid(pid), signal.SIGKILL)
                        deadline = time.monotonic() + 5
                        while lb.marker_processes(entry["marker"]) and time.monotonic() < deadline:
                            time.sleep(0.05)
                    report = lb.run_recover(shared)
                    self.assertEqual(report["exit"], 0, report)
                    b = Harness(self, root=base / "b", shared=shared, docker=FakeDocker(str(state)))
                    self.assertEqual(b.status()["state"], "not_ready")
                finally:
                    for pid in lb.marker_processes(entry["marker"]) or []:
                        with contextlib.suppress(ProcessLookupError):
                            os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
