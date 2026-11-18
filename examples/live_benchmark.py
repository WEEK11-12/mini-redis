"""Local live-benchmark runner for iteration 07 (loopback only).

Prepares the dedicated Docker MongoDB, runs examples.benchmark unchanged in its
own process group and serves each run's own results over 127.0.0.1 HTTP.

    python -B -m examples.live_benchmark [--port 8765]
    python -B -m examples.live_benchmark --recover   # with the server stopped
"""

import argparse
import contextlib
import copy
import errno
import fcntl
import hashlib
import html
import json
import math
import os
import random
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from examples.benchmark import CONDITIONS, KEY_SEED, ROUNDS, WARMUP
from examples.origin_api import DEMO_ID, DEMO_VALUE
from examples.seed_mongo import item_id, value_for

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
CONTAINER = "mini-redis-live-mongo"
DATA_VOLUME = "mini-redis-live-mongo-data"
CONFIG_VOLUME = "mini-redis-live-mongo-config"
OWNER_LABEL, OWNER = "io.mini-redis.owner", "live-benchmark-ui"
ROLE_LABEL = "io.mini-redis.role"
CREATED_LABEL = "io.mini-redis.created-by"
IMAGE = "mongo:7"
MONGO_URI = "mongodb://127.0.0.1:27018"
PORT_BINDING = {"27017/tcp": [{"HostIp": "127.0.0.1", "HostPort": "27018"}]}
MEMORY_BYTES = 1 << 30
MONGO_ARGS = ["--wiredTigerCacheSizeGB", "0.25"]
MOUNTS = {"/data/db": DATA_VOLUME, "/data/configdb": CONFIG_VOLUME}
MARKER_ENV = "MINI_REDIS_LIVE_JOB"
# provisional limits from design 6 (seconds)
TIMEOUTS = {"docker": 30, "pull": 600, "mongo": 60, "seed": 600, "bench": 300, "grace": 30, "leftover": 5}
ID_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}")
MAX_BODY = 1024
DEFAULT_RUN_ROOT = ROOT / "var" / "live-benchmark"
SHARED_NAME, LOCK_NAME = "recovery.json", "lock"
RUN_FILES = ("runner.json", "results.json", "results.servers.log",
             "benchmark.stdout.log", "benchmark.stderr.log")
RECOVERY_HINT = (" 서버를 멈춘 뒤 `python -B -m examples.live_benchmark --recover`로 대상 작업과 "
                 "프로세스 그룹의 종료를 확인·기록해야 다시 준비할 수 있습니다.")

EXPECTED_COUNT = 1_000_001
CACHE_MAX_BYTES = 268_435_456
RESULTS_NAME = "results.json"
# status -> accepted-job error code; None means the readiness becomes seed_required
SEED_STATUS_CODE = {"ok": None, "missing": None, "mismatch": None,
                    "check_failed": "SEED_CHECK_FAILED", "resource_mismatch": "RESOURCE_MISMATCH",
                    "condition_unmet": "MEASUREMENT_CONDITION_UNMET"}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def measurement_numbers():
    """The same draw benchmark.py makes for a correctly seeded collection."""
    return random.Random(KEY_SEED).sample(range(EXPECTED_COUNT - 1),
                                          (WARMUP + ROUNDS) * len(CONDITIONS))


def inspect_seed(reader):
    """Read-only seed check (design 4.5); never writes or drops anything."""
    numbers = measurement_numbers()
    ids = [DEMO_ID, item_id(0), item_id(EXPECTED_COUNT - 2)] + [item_id(n) for n in numbers]
    report = {"checked_at": utc_now(), "status": None, "detail": None, "count": None,
              "storage_bytes": None, "cache_max_bytes": None,
              "keys": {"order": ids[:3] + ["<315 measurement keys in draw order>"],
                       "measurement_keys": len(numbers), "key_seed": KEY_SEED,
                       "range": [0, EXPECTED_COUNT - 2], "read_before_restart": True}}

    def done(status, detail=None):
        report.update(status=status, detail=detail)
        return report

    try:
        report["cache_max_bytes"] = reader.cache_max_bytes()
        if report["cache_max_bytes"] != CACHE_MAX_BYTES:
            return done("resource_mismatch", f"cache max bytes {report['cache_max_bytes']}")
        if not reader.collection_exists():
            return done("missing", "collection")
        stats = reader.coll_stats()
        report.update(count=stats["count"], storage_bytes=stats["storage_bytes"])
        if report["count"] != EXPECTED_COUNT:
            return done("mismatch", f"count {report['count']}")
        found = reader.values(ids)
        expected = {DEMO_ID: DEMO_VALUE, **{item_id(n): value_for(n)
                                            for n in [0, EXPECTED_COUNT - 2, *numbers]}}
        bad = [key for key in ids if found.get(key) != expected[key]]
        if bad:
            return done("mismatch", "values: " + ", ".join(bad[:5]))
        if report["storage_bytes"] < 2 * CACHE_MAX_BYTES:
            return done("condition_unmet", f"storage bytes {report['storage_bytes']}")
    except Exception as exc:
        return done("check_failed", type(exc).__name__)
    return done("ok")


def _int(value, expected=None):
    return type(value) is int and (expected is None or value == expected)


def _ms(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _output_matches(data, results_path):
    command = data.get("command")
    if not isinstance(command, list) or not all(isinstance(a, str) for a in command):
        return False
    positions = [i for i, arg in enumerate(command) if arg == "--output"]
    return (len(positions) == 1 and positions[0] + 1 < len(command)
            and Path(command[positions[0] + 1]).resolve() == Path(results_path).resolve())


def _partial(data, results_path):
    """Per-condition counts only when the raw file is this run's and structurally valid."""
    summary = data.get("summary")
    if (not _output_matches(data, results_path) or not isinstance(summary, dict)
            or not isinstance(data.get("records"), list)
            or not (data.get("aborted") is None or (isinstance(data["aborted"], str) and data["aborted"]))):
        return None
    conditions = {}
    for c in CONDITIONS:
        row = summary.get(c)
        if not isinstance(row, dict) or not (_int(row.get("successes")) and _int(row.get("failures"))):
            return None
        if row["successes"] < 0 or row["failures"] < 0:
            return None
        conditions[c] = {"successes": row["successes"], "failures": row["failures"]}
    return {"conditions": conditions, "aborted": data["aborted"]}


def _complete_result(data, results_path, runner):
    """design 3.4 items 2-5; returns the screen result or None when anything is off."""
    summary = data.get("summary")
    if (not isinstance(summary, dict) or summary.get("complete") is not True
            or "aborted" not in data or data["aborted"] is not None
            or not _output_matches(data, results_path)
            or not _int(data.get("rounds"), ROUNDS) or not _int(data.get("warmup_per_condition"), WARMUP)):
        return None
    for c in CONDITIONS:
        row = summary.get(c)
        if (not isinstance(row, dict) or not _int(row.get("successes"), ROUNDS)
                or not _int(row.get("failures"), 0) or not _ms(row.get("median_ms"))
                or not _ms(row.get("p90_ms"))):
            return None
    strings = ("timer", "percentile", "python", "platform", "machine", "commit")
    sources, before, after = data.get("sources_sha256"), data.get("mongo_before"), data.get("mongo_after")
    if (not all(isinstance(data.get(k), str) for k in strings)
            or not _int(data.get("key_seed")) or not _int(data.get("key_space"))
            or not isinstance(sources, dict) or not sources
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in sources.items())
            or not isinstance(before, dict) or not _int(before.get("count"), EXPECTED_COUNT)
            or not _int(before.get("cache_max_bytes"), CACHE_MAX_BYTES) or not isinstance(after, dict)):
        return None
    return {
        "conditions": {c: {k: summary[c][k] for k in ("median_ms", "p90_ms", "successes", "failures")}
                       for c in CONDITIONS},
        "method": {k: data[k] for k in ("warmup_per_condition", "rounds", "timer", "percentile",
                                         "key_seed", "key_space")},
        "environment": {**{k: data[k] for k in ("python", "platform", "machine", "commit",
                                                 "sources_sha256", "mongo_before", "mongo_after")},
                        "mongo_after_unavailable": "error" in after, "runner": runner or {}},
    }


def judge_run(run_dir, *, exit_code, timed_out, reaped, spawn_error=False, runner=None):
    """Classify one benchmark run from its own results.json (design 3.4)."""
    path = Path(run_dir) / RESULTS_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else None
    except (OSError, ValueError):
        data = None
    partial = _partial(data, path) if data is not None else None

    def verdict(state, code, message, result=None):
        error = None if code is None else {"code": code, "message": message}
        return {"state": state, "error": error, "result": result,
                "partial": None if result is not None else partial}

    if timed_out:
        return verdict("timed_out", "TIMED_OUT", "측정기 제한 시간을 넘었습니다.")
    if spawn_error or exit_code != 0:
        return verdict("failed", "BENCHMARK_FAILED", "측정기가 정상 종료하지 않았습니다.")
    if data is None:
        if not path.exists():
            return verdict("failed", "BENCHMARK_FAILED", "결과 파일이 없습니다.")
        return verdict("failed", "RESULT_INVALID", "결과 파일을 읽을 수 없습니다.")
    result = _complete_result(data, path, runner)
    if result is None:
        return verdict("failed", "RESULT_INVALID", "결과 파일이 성공 조건을 만족하지 않습니다.")
    if not reaped:
        return verdict("failed", "BENCHMARK_FAILED", "측정기·자식 서버 회수를 확인하지 못했습니다.")
    return verdict("succeeded", None, None, result)


# ---------------------------------------------------------------- records

class RecordError(Exception):
    pass


def write_json_durable(path, data):
    """Temp file + fsync + rename + parent fsync; any failure propagates as OSError."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def new_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(8)


def valid_shared(data):
    return (isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("jobs"), dict)
            and all(isinstance(job, dict) and job.get("status") in ("open", "released")
                    and job.get("kind") in ("setup", "seed", "run")
                    and isinstance(job.get("detail_path"), str) and isinstance(job.get("marker"), str)
                    and isinstance(job.get("children"), list)
                    for job in data["jobs"].values()))


class LockBusy(Exception):
    pass


def acquire_lock(shared_dir):
    """Exclusive flock held for the process lifetime; the OS drops it when we exit."""
    Path(shared_dir).mkdir(parents=True, exist_ok=True)
    fd = os.open(Path(shared_dir) / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise LockBusy() from None
    return fd


def default_shared_dir(docker):
    """Same directory for every checkout with the same user, Docker target and resource names."""
    try:
        context = docker.context()
    except DockerError:
        # shortcut: no CLI means no Docker change is possible; init then stays blocked until it works
        context = "unavailable"
    scope = json.dumps([os.getuid(), context, os.environ.get("DOCKER_HOST", ""),
                        CONTAINER, DATA_VOLUME, CONFIG_VOLUME])
    return Path.home() / ".mini-redis-live-benchmark" / hashlib.sha256(scope.encode()).hexdigest()[:16]


def mark_interrupted(entry, write):
    """Close an unfinished detail record as SERVER_INTERRUPTED (state only, not recovery)."""
    path = Path(entry["detail_path"])
    if path.is_symlink():
        return None  # never write through or replace a link; the job stays blocked
    detail = read_json(path)
    if not isinstance(detail, dict) or detail.get("finished_at") is not None:
        return detail
    detail.update(state="failed" if entry["kind"] == "run" else "finished", finished_at=utc_now(),
                  error={"code": "SERVER_INTERRUPTED", "message": "서버가 작업 도중 종료됐습니다."})
    write(path, detail)
    return detail


def group_gone(pgid):
    """True only when the kernel reports no process in the group (ESRCH); never signals it."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def marker_processes(marker):
    """PIDs whose environment carries this job's marker, or None when that cannot be determined."""
    token = f"{MARKER_ENV}={marker}"
    proc = Path("/proc")
    if (proc / "self" / "environ").exists():
        found = []
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                env = (entry / "environ").read_bytes()
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue  # gone, or another user's process (outside the trust boundary)
            except OSError:
                return None
            if token.encode() in env.split(b"\0"):
                found.append(int(entry.name))
        return found
    # shortcut: macOS `ps -E` hides the environment of SIP-protected binaries; our children are
    # python/docker processes. Upgrade if jobs ever start protected system binaries.
    try:
        done = subprocess.run(["ps", "-E", "-ww", "-A", "-o", "pid=,command="], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return [int(line.split(None, 1)[0]) for line in done.stdout.splitlines()
            if token in line.split()]


def run_recover(shared_dir, *, write=write_json_durable, scan=marker_processes):
    """Release unsettled jobs only with evidence that their processes are gone (design 3.3)."""
    report = {"exit": 1, "released": [], "blocked": {}, "error": None}
    try:
        fd = acquire_lock(shared_dir)
    except LockBusy:
        report.update(exit=2, error="실행 서버가 잠금을 갖고 있습니다. 서버를 먼저 멈추세요.")
        return report
    try:
        path = Path(shared_dir) / SHARED_NAME
        try:
            data = read_json(path)
        except FileNotFoundError:
            report.update(exit=0, error="공유 복구 기록이 없어 해제할 작업이 없습니다. 서버 시작 때 "
                                        "Docker 전용 자원 부재를 확인한 뒤에만 초기화합니다.")
            return report
        except (OSError, ValueError):
            data = None
        if not valid_shared(data):
            report["error"] = "공유 복구 기록을 읽을 수 없습니다. 수동 조사가 필요합니다."
            return report
        for job_id, entry in data["jobs"].items():
            if entry["status"] == "released":
                continue
            reason = _release(job_id, entry, data, path, write, scan)
            if reason is None:
                report["released"].append(job_id)
            else:
                report["blocked"][job_id] = reason
        report["exit"] = 0 if not report["blocked"] else 1
        return report
    finally:
        os.close(fd)


def _release(job_id, entry, data, shared_path, write, scan):
    detail_path = Path(entry["detail_path"])
    if not detail_path.parent.is_dir():
        return "상세 기록 위치에 접근할 수 없습니다."
    # missing, dangling or replaced detail records are never recreated: release needs the original
    if not os.path.lexists(detail_path):
        return "상세 기록 파일이 없습니다. 수동 조사가 필요합니다."
    if detail_path.is_symlink():
        return "상세 기록이 심볼릭 링크라 원본으로 확인할 수 없습니다."
    try:
        detail = read_json(detail_path)
    except (OSError, ValueError):
        return "상세 기록을 읽을 수 없습니다."
    if not isinstance(detail, dict) or detail.get("id") != job_id or detail.get("kind") != entry["kind"]:
        return "상세 기록이 공유 기록의 작업과 일치하지 않습니다."
    groups = {}
    for child in entry["children"]:
        pgid = child.get("pgid")
        if type(pgid) is not int or pgid <= 1:
            return "기록된 프로세스 그룹 신원이 올바르지 않습니다."
        groups[str(pgid)] = "ESRCH" if group_gone(pgid) else "alive"
    if "alive" in groups.values():
        return f"프로세스 그룹이 아직 있습니다: {groups}"
    found = scan(entry["marker"])
    if found is None:
        return "작업 표지를 가진 프로세스를 조사하지 못했습니다."
    if found:
        return f"작업 표지를 가진 프로세스가 남아 있습니다: {found}"
    evidence = {"checked_at": utc_now(), "groups": groups, "marker_processes": [],
                "method": "killpg(pgid, 0) == ESRCH for every recorded group; "
                          "no process environment carries the job marker"}
    if detail.get("finished_at") is None:
        detail.update(state="failed" if entry["kind"] == "run" else "finished", finished_at=utc_now(),
                      error={"code": "SERVER_INTERRUPTED", "message": "서버가 작업 도중 종료됐습니다."})
    detail["recovery"] = evidence
    try:
        write(detail_path, detail)
    except OSError:
        return "상세 기록에 해제 증거를 저장하지 못했습니다."
    entry.update(status="released", release={**evidence, "by": "recover"})
    try:
        write(shared_path, data)
    except OSError:
        entry["status"] = "open"
        entry.pop("release")
        return "공유 기록에 해제 증거를 저장하지 못했습니다."
    return None


# ---------------------------------------------------------------- docker / mongo

class DockerError(Exception):
    pass


def _labels(labels):
    return [arg for key, value in labels.items() for arg in ("--label", f"{key}={value}")]


class DockerCli:
    """Fixed-argument docker CLI calls; no shell and nothing taken from the browser."""

    def __init__(self, env=None, timeouts=None):
        self.env, self.timeouts = env, {**TIMEOUTS, **(timeouts or {})}

    def _run(self, args, timeout=None):
        try:
            return subprocess.run(["docker", *args], capture_output=True, text=True, env=self.env,
                                  timeout=timeout or self.timeouts["docker"])
        except FileNotFoundError as exc:
            raise DockerError("docker CLI not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise DockerError("docker command timed out") from exc

    def _ok(self, args, timeout=None):
        done = self._run(args, timeout)
        if done.returncode != 0:
            raise DockerError(done.stderr.strip()[-300:])
        return done.stdout

    def context(self):
        return self._ok(["context", "show"]).strip()

    def info(self):
        self._ok(["info", "--format", "{{.ServerVersion}}"])

    def inspect(self, kind, name):
        """Parsed inspect object, or None only when Docker says the object does not exist."""
        done = self._run([kind, "inspect", name])
        if done.returncode == 0:
            try:
                return json.loads(done.stdout)[0]
            except (ValueError, IndexError) as exc:
                raise DockerError("unreadable inspect output") from exc
        if "no such" in done.stderr.lower():
            return None
        raise DockerError(done.stderr.strip()[-300:])

    def pull(self, image):
        self._ok(["pull", image], self.timeouts["pull"])

    def create_volume(self, name, labels):
        self._ok(["volume", "create", *_labels(labels), name])

    def run_container(self, labels):
        self._ok(["run", "-d", "--name", CONTAINER, *_labels(labels),
                  "-p", "127.0.0.1:27018:27017", "--memory", "1g",
                  "-v", f"{DATA_VOLUME}:/data/db", "-v", f"{CONFIG_VOLUME}:/data/configdb",
                  IMAGE, *MONGO_ARGS])

    def start(self):
        self._ok(["start", CONTAINER])

    def restart(self):
        self._ok(["restart", CONTAINER])


class MongoReader:
    """Read-only access used by the seed and restart checks (needs pymongo)."""

    def __init__(self, uri=MONGO_URI):
        from pymongo import MongoClient  # optional dependency, as in seed_mongo.py
        from examples.seed_mongo import COLLECTION, DATABASE

        self.client = MongoClient(uri, serverSelectionTimeoutMS=3000, socketTimeoutMS=3000,
                                  connectTimeoutMS=3000)
        self.db, self.name = self.client[DATABASE], COLLECTION

    def ping(self):
        self.client.admin.command("ping")

    def cache_max_bytes(self):
        return self.client.admin.command("serverStatus")["wiredTiger"]["cache"]["maximum bytes configured"]

    def collection_exists(self):
        return self.name in self.db.list_collection_names()

    def coll_stats(self):
        stats = self.db.command("collStats", self.name)
        return {"count": stats["count"], "storage_bytes": stats["storageSize"]}

    def values(self, ids):
        return {doc["_id"]: doc.get("value")
                for doc in self.db[self.name].find({"_id": {"$in": list(ids)}}, {"value": 1})}

    def close(self):
        self.client.close()


def volume_owned(info, role):
    labels = (info or {}).get("Labels") or {}
    return labels.get(OWNER_LABEL) == OWNER and labels.get(ROLE_LABEL) == role


def container_problem(info):
    """None when the container is ours and configured as design 3.1, else (code, detail)."""
    config, host = info.get("Config") or {}, info.get("HostConfig") or {}
    labels = config.get("Labels") or {}
    if labels.get(OWNER_LABEL) != OWNER or labels.get(ROLE_LABEL) != "mongo":
        return "RESOURCE_CONFLICT", f"container {CONTAINER} is not labelled as ours"
    mounts = info.get("Mounts") or []
    by_dest = {m.get("Destination"): (m.get("Type"), m.get("Name")) for m in mounts}
    if (config.get("Image") != IMAGE or host.get("PortBindings") != PORT_BINDING
            or host.get("Memory") != MEMORY_BYTES or config.get("Cmd") != MONGO_ARGS
            or len(mounts) != len(MOUNTS)
            or by_dest != {dest: ("volume", name) for dest, name in MOUNTS.items()}):
        return "RESOURCE_MISMATCH", f"container {CONTAINER} configuration differs"
    return None


def start_error_code(exc):
    text = str(exc).lower()
    return ("PORT_CONFLICT" if "port is already allocated" in text or "address already in use" in text
            else "CONTAINER_START_FAILED")


# ---------------------------------------------------------------- child processes

def run_child(cmd, *, env, stdout, stderr, timeout, grace, leftover_wait, on_spawn, stop_event):
    """Run one child in its own session and confirm its whole process group is gone (design 5)."""
    reap = {"pid": None, "pgid": None, "exit": None, "abort": None, "signals": [], "leftover": False,
            "spawn_error": None, "record_error": False}
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                start_new_session=True)
    except OSError as exc:
        reap["spawn_error"] = type(exc).__name__  # nothing was created, so nothing is signalled
        return reap
    reap["pid"] = reap["pgid"] = proc.pid
    try:
        on_spawn(proc.pid, proc.pid)
    except Exception:
        # identity not durable: reap now with the in-memory identity; the job stays unsettled
        reap["record_error"], reap["abort"] = True, "record"
    deadline = time.monotonic() + timeout
    while reap["abort"] is None:
        try:
            proc.wait(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                reap["abort"] = "timeout"
            elif stop_event.is_set():
                reap["abort"] = "stopped"
    if reap["abort"]:
        # the leader first, so benchmark.py can record `aborted` and stop its own servers
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(signal.SIGINT)
            reap["signals"].append("SIGINT->pid")
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
                reap["signals"].append("SIGKILL->group")
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=leftover_wait)
    reap["exit"] = proc.returncode
    # shortcut: probing by PGID after the leader is reaped could see a reused id only if an
    # unrelated new session leader got that pid within this short window.
    if not group_gone(proc.pid):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
            reap["signals"].append("SIGKILL->group")
        deadline = time.monotonic() + leftover_wait
        while not group_gone(proc.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
    reap["leftover"] = proc.returncode is None or not group_gone(proc.pid)
    return reap


# ---------------------------------------------------------------- server

class Stopped(Exception):
    pass


class RecordUnavailable(Exception):
    pass


READINESS_MESSAGE = {"not_ready": "준비 전입니다.", "ready": "측정 요청을 받을 수 있습니다.",
                     "seed_required": "시드가 없거나 예상과 다릅니다. 삭제 영향을 확인한 뒤 재생성할 수 있습니다.",
                     "failed": "준비에 실패했습니다.", "preparing": "준비 중입니다."}


def _error(code, message):
    return {"error": {"code": code, "message": message}}


UI_DIR = Path(__file__).resolve().parent
PAGE_TEMPLATE = (UI_DIR / "live_benchmark_ui.html").read_text(encoding="utf-8")
PAGE_SCRIPT = (UI_DIR / "live_benchmark_ui.js").read_text(encoding="utf-8")
assert "</script" not in PAGE_SCRIPT.lower()


def render_page(token, nonce):
    """Static screen; only server constants and the per-start token are substituted."""
    page = PAGE_TEMPLATE
    for key, value in (("__CONTAINER__", CONTAINER), ("__DATA__", DATA_VOLUME), ("__CONFIG__", CONFIG_VOLUME),
                       ("__TOKEN__", html.escape(token)), ("__NONCE__", nonce)):
        page = page.replace(key, value)
    return page.replace("__SCRIPT__", PAGE_SCRIPT)


def page_csp(nonce):
    return (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; img-src 'none'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")


class LiveBenchmark:
    def __init__(self, *, port=DEFAULT_PORT, run_root=DEFAULT_RUN_ROOT, shared_dir=None,
                 docker=None, mongo=MongoReader, seed_cmd=None, bench_cmd=None, timeouts=None,
                 new_id=new_id, write=write_json_durable):
        self.port, self.run_root = port, Path(run_root).resolve()
        self.shared_dir = Path(shared_dir) if shared_dir else None
        self.timeouts = {**TIMEOUTS, **(timeouts or {})}
        self.docker_factory = docker or (lambda env: DockerCli(env, self.timeouts))
        self.mongo_factory = mongo
        self.seed_cmd = seed_cmd or (lambda: [sys.executable, "-B", "-m", "examples.seed_mongo",
                                              "--mongo-uri", MONGO_URI])
        self.bench_cmd = bench_cmd or (lambda out: [sys.executable, "-B", "-m", "examples.benchmark",
                                                    "--output", str(out), "--mongo-uri", MONGO_URI])
        self.new_id, self.write = new_id, write
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.state, self.step, self.message, self.error = "not_ready", None, "준비 전입니다.", None
        self.blocked = None
        self.active = self.thread = self.httpd = self.lock_fd = self.shared = None
        self.last_run_id = None
        self.image_id = None
        self._serve_thread = None

    # -- lifecycle

    @property
    def shared_path(self):
        return self.shared_dir / SHARED_NAME

    def start(self):
        if self.shared_dir is None:
            self.shared_dir = default_shared_dir(self.docker_factory(None))
        self.lock_fd = acquire_lock(self.shared_dir)
        try:
            for sub in ("runs", "jobs"):
                (self.run_root / sub).mkdir(parents=True, exist_ok=True)
            self._load_shared()
            self.last_run_id = self._latest_run()
            self.httpd = ThreadingHTTPServer((HOST, self.port), make_handler(self))
            self.httpd.daemon_threads = True
            self.port = self.httpd.server_address[1]
        except BaseException:
            self._release_lock()
            raise

    def _latest_run(self):
        """IDs share a second-resolution prefix, so order by the recorded creation time."""
        def created(path):
            try:
                return str(read_json(path / "runner.json").get("created_at") or ""), path.name
            except (OSError, ValueError, AttributeError):
                return "", path.name

        runs = [p for p in (self.run_root / "runs").iterdir() if ID_RE.fullmatch(p.name)]
        return max(runs, key=created).name if runs else None

    def serve_in_thread(self):
        self._serve_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._serve_thread.start()

    def close(self):
        """Graceful stop: no new requests, reap the active job, then drop the lock."""
        self.stop_event.set()
        if self.httpd is not None:
            if self._serve_thread is not None:
                self.httpd.shutdown()
                self._serve_thread.join()
            self.httpd.server_close()
            self.httpd = None
        if self.thread is not None:
            self.thread.join()
        self._release_lock()

    def _release_lock(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def _block(self, code, message, hint=RECOVERY_HINT):
        self.blocked = {"code": code, "message": message + hint}

    def _load_shared(self):
        try:
            data = read_json(self.shared_path)
        except FileNotFoundError:
            data = self._init_shared()
            if data is None:
                return
        except (OSError, ValueError):
            return self._block("SHARED_RECORD_UNREADABLE", "공유 복구 기록을 읽을 수 없습니다.")
        if not valid_shared(data):
            return self._block("SHARED_RECORD_UNREADABLE", "공유 복구 기록 형식이 올바르지 않습니다.")
        self.shared = data
        unsettled = [job_id for job_id, job in data["jobs"].items() if job["status"] != "released"]
        for job_id in unsettled:
            # failure close-out is best effort and never counts as recovery evidence
            with contextlib.suppress(OSError, ValueError, TypeError):
                mark_interrupted(data["jobs"][job_id], self.write)
        if unsettled:
            self._block("RECOVERY_REQUIRED", "종료가 확인되지 않은 작업이 있습니다: " + ", ".join(unsettled) + ".")

    def _init_shared(self):
        """Create the shared record only after Docker confirms no dedicated resource exists."""
        docker = self.docker_factory(None)
        try:
            found = [name for kind, name in (("container", CONTAINER), ("volume", DATA_VOLUME),
                                             ("volume", CONFIG_VOLUME))
                     if docker.inspect(kind, name) is not None]
        except DockerError:
            self._block("SHARED_RECORD_UNVERIFIED",
                        "공유 복구 기록이 없고 Docker에서 전용 자원 부재를 확인하지 못했습니다.",
                        " Docker를 사용할 수 있게 한 뒤 서버를 다시 시작하세요.")
            return None
        if found:
            self._block("SHARED_RECORD_MISSING",
                        "공유 복구 기록이 없는데 전용 자원이 이미 있습니다: " + ", ".join(found) + ".",
                        " 이전 작업이 남아 있지 않은지 수동으로 확인해야 합니다.")
            return None
        data = {"version": 1, "initialized_at": utc_now(), "jobs": {}}
        try:
            self.write(self.shared_path, data)
        except OSError:
            self._block("RECORD_UNAVAILABLE", "공유 복구 기록을 만들지 못했습니다.")
            return None
        return data

    # -- status and admission

    def setup_status(self):
        with self.lock:
            active = None if self.active is None else {
                "kind": self.active["kind"], "job_id": self.active["id"],
                "run_id": self.active["id"] if self.active["kind"] == "run" else None}
            state, error, message = self.state, self.error, self.message
            if self.blocked:
                state, error, message = "recovery_required", dict(self.blocked), self.blocked["message"]
            return {"state": state, "step": self.step, "message": message, "error": error,
                    "active_job": active, "last_run_id": self.last_run_id,
                    "resources": {"container": CONTAINER, "data_volume": DATA_VOLUME,
                                  "config_volume": CONFIG_VOLUME, "image": IMAGE,
                                  "image_id": self.image_id, "mongo": "127.0.0.1:27018",
                                  "retained_on_exit": True}}

    def submit(self, kind):
        with self.lock:
            if self.blocked:
                return 409, _error("RECOVERY_REQUIRED", self.blocked["message"])
            if self.active is not None or self.stop_event.is_set():
                return 409, _error("BUSY", "현재 준비 또는 측정 중입니다.")
            if kind == "seed" and self.state != "seed_required":
                return 409, _error("SEED_NOT_REQUIRED", "시드 재생성이 필요한 상태가 아닙니다.")
            if kind == "run" and self.state != "ready":
                return 409, _error("NOT_READY", "준비가 끝나지 않았습니다.")
            try:
                job = self._record_intent(kind)
            except RecordError:
                return 500, _error("RECORD_UNAVAILABLE", "작업 기록을 저장하지 못해 시작하지 않았습니다.")
            self.active = job
            if kind == "run":
                self.last_run_id = job["id"]
            else:
                self.state, self.error = "preparing", None
                self.step = "seeding" if kind == "seed" else "checking_docker"
                self.message = "시드 재생성 중입니다." if kind == "seed" else "준비 중입니다."
            self.thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
            self.thread.start()
        if kind == "run":
            return 202, {"run_id": job["id"], "state": "preparing"}
        return 202, self.setup_status()

    def _record_intent(self, kind):
        """Shared then detail intent, both durable, before any Docker change or child (design 3.3)."""
        parent = self.run_root / ("runs" if kind == "run" else "jobs")
        for _ in range(3):
            job_id = self.new_id()
            if not ID_RE.fullmatch(job_id):
                continue
            try:
                (parent / job_id).mkdir()
                break
            except FileExistsError:
                continue  # never reuse or overwrite an existing run directory
            except OSError as exc:
                raise RecordError() from exc
        else:
            raise RecordError()
        job_dir = parent / job_id
        detail_path = job_dir / ("runner.json" if kind == "run" else "job.json")
        marker, now = secrets.token_hex(16), utc_now()
        detail = {"id": job_id, "kind": kind, "state": "preparing" if kind == "run" else "running",
                  "step": None, "created_at": now, "started_at": None, "finished_at": None,
                  "steps": {}, "error": None, "marker": marker, "children": [], "reap": {},
                  "result": None, "partial": None}
        if kind == "run":
            detail["run_id"] = job_id
        entry = {"kind": kind, "status": "open", "created_at": now, "marker": marker,
                 "detail_path": str(detail_path), "checkout": str(ROOT), "server_pid": os.getpid(),
                 "children": []}
        shared = copy.deepcopy(self.shared)
        shared["jobs"][job_id] = entry
        try:
            self.write(self.shared_path, shared)
        except OSError as exc:
            self._block("RECORD_UNAVAILABLE", "공유 작업 기록 저장 결과를 확인할 수 없습니다.")
            raise RecordError() from exc
        self.shared = shared
        try:
            self.write(detail_path, detail)
        except OSError as exc:
            self._block("RECORD_UNAVAILABLE", "상세 작업 기록을 저장하지 못했고 공유 기록에는 미완료 의도가 남았습니다.")
            raise RecordError() from exc
        return {"id": job_id, "kind": kind, "dir": job_dir, "detail_path": detail_path,
                "detail": detail, "marker": marker, "env": {**os.environ, MARKER_ENV: marker},
                "record_failed": False, "unreaped": False}

    # -- jobs

    def _run_job(self, job):
        try:
            outcome = {"setup": self._setup, "seed": self._seed, "run": self._bench}[job["kind"]](job)
        except Stopped:
            outcome = self._failure(job, "SERVER_STOPPED", "서버가 정상 종료 요청을 받아 작업을 멈췄습니다.")
        except RecordUnavailable:
            outcome = self._failure(job, "RECORD_UNAVAILABLE",
                                    "작업 기록을 갱신하지 못해 이후 Docker 변경·자식 생성 없이 중단했습니다.")
        except Exception as exc:  # never leave the slot or the shared intent dangling
            outcome = self._failure(job, "INTERNAL_ERROR", f"예상하지 못한 오류: {type(exc).__name__}")
        self._finish(job, outcome)

    def _failure(self, job, code, message, readiness="failed"):
        error = {"code": code, "message": message}
        if job["kind"] == "run":
            return {"readiness": None if code == "SERVER_STOPPED" else readiness,
                    "readiness_error": error, "detail": {"state": "failed", "error": error}}
        return {"readiness": readiness, "readiness_error": error, "detail": {"error": error}}

    def _detail(self, job, **fields):
        """Durable detail update; a failure stops the job before its next external action."""
        if not self._write_detail(job, **fields):
            raise RecordUnavailable()

    def _write_detail(self, job, **fields):
        job["detail"].update(fields)
        try:
            self.write(job["detail_path"], job["detail"])
            return True
        except OSError:
            job["record_failed"] = True  # keeps the shared intent open (design 6)
            return False

    def _set_step(self, job, step, **fields):
        if self.stop_event.is_set():
            raise Stopped()
        job["detail"]["steps"][step] = utc_now()
        self._detail(job, step=step, **fields)
        if job["kind"] != "run":
            with self.lock:
                self.step = step

    def _record_spawn(self, job, role, pid, pgid):
        """PID/PGID into both records right after the child exists; raising aborts the child."""
        child = {"role": role, "pid": pid, "pgid": pgid, "started_at": utc_now()}
        job["detail"]["children"].append(child)
        self.write(job["detail_path"], job["detail"])
        with self.lock:
            shared = copy.deepcopy(self.shared)
            shared["jobs"][job["id"]]["children"].append(child)
        self.write(self.shared_path, shared)
        with self.lock:
            self.shared = shared

    def _spawn(self, job, role, cmd, timeout):
        job["unreaped"] = True
        with open(job["dir"] / f"{role}.stdout.log", "wb") as out, \
                open(job["dir"] / f"{role}.stderr.log", "wb") as err:
            reap = run_child(cmd, env=job["env"], stdout=out, stderr=err, timeout=timeout,
                             grace=self.timeouts["grace"], leftover_wait=self.timeouts["leftover"],
                             on_spawn=lambda pid, pgid: self._record_spawn(job, role, pid, pgid),
                             stop_event=self.stop_event)
        job["unreaped"] = bool(reap["leftover"])
        if reap.get("record_error"):
            job["record_failed"] = True
        job["detail"]["reap"][role] = reap
        self._detail(job)
        return reap

    def _finish(self, job, outcome):
        """Terminal detail record, then shared release only when reaping is confirmed."""
        fields = dict(outcome.get("detail") or {})
        fields.setdefault("state", "finished")
        if job["kind"] != "run":
            fields.update(outcome=outcome.get("readiness"), error=outcome.get("readiness_error"))
        reaped = not job["unreaped"]
        self._write_detail(job, finished_at=utc_now(), reap_confirmed=reaped, **fields)
        released = False
        if reaped and not job["record_failed"]:
            with self.lock:
                shared = copy.deepcopy(self.shared)
                shared["jobs"][job["id"]].update(status="released", release={
                    "by": "job_end", "released_at": utc_now(),
                    "children": [{"pid": r.get("pid"), "pgid": r.get("pgid"), "leftover": r.get("leftover"),
                                  "exit": r.get("exit")} for r in job["detail"]["reap"].values()]})
            try:
                self.write(self.shared_path, shared)
                released = True
            except OSError:
                pass
        with self.lock:
            if released:
                self.shared = shared
            else:
                self._block("RECOVERY_REQUIRED",
                            f"작업 {job['id']}의 종료·회수를 확인하거나 기록하지 못했습니다.")
            if outcome.get("readiness"):
                self.state = outcome["readiness"]
                self.error = outcome.get("readiness_error")
                self.message = READINESS_MESSAGE[self.state]
            self.step, self.active = None, None

    # -- docker / mongo helpers shared by the jobs

    def _reader_call(self, fn):
        reader = self.mongo_factory(MONGO_URI)
        try:
            return fn(reader)
        finally:
            with contextlib.suppress(Exception):
                reader.close()

    def _check_seed(self):
        try:
            return self._reader_call(inspect_seed)
        except Exception as exc:  # e.g. pymongo missing: the check itself failed
            return {"status": "check_failed", "detail": type(exc).__name__, "checked_at": utc_now()}

    def _wait_ping(self):
        deadline = time.monotonic() + self.timeouts["mongo"]
        while True:
            try:
                self._reader_call(lambda reader: reader.ping())
                return True
            except Exception:
                if time.monotonic() >= deadline or self.stop_event.wait(0.2):
                    return False

    def _verify_resources(self, docker):
        """Labels, configuration, mounts and running state right before seeding or measuring."""
        try:
            for name, role in ((DATA_VOLUME, "data"), (CONFIG_VOLUME, "config")):
                if not volume_owned(docker.inspect("volume", name), role):
                    return "RESOURCE_CONFLICT", f"volume {name}", None
            info = docker.inspect("container", CONTAINER)
        except DockerError:
            return "DOCKER_UNAVAILABLE", "docker inspect failed", None
        if info is None:
            return "RESOURCE_CONFLICT", f"container {CONTAINER} missing", None
        problem = container_problem(info)
        if problem:
            return (*problem, info)
        if not (info.get("State") or {}).get("Running"):
            return "MONGO_NOT_READY", f"container {CONTAINER} is not running", info
        return None, None, info

    @staticmethod
    def _seed_outcome(report, *, after_seed=False):
        status = report["status"]
        if status == "ok":
            return {"readiness": "ready", "readiness_error": None}
        if status in ("missing", "mismatch"):
            code = "SEED_FAILED" if after_seed else "SEED_REQUIRED"
            return {"readiness": "seed_required",
                    "readiness_error": {"code": code, "reason": status, "detail": report.get("detail"),
                                        "message": "시드가 없거나 예상 값과 다릅니다. 확인 후 재생성이 필요합니다."}}
        return {"readiness": "failed",
                "readiness_error": {"code": SEED_STATUS_CODE[status], "detail": report.get("detail"),
                                    "message": "시드 검사 또는 측정 조건 확인에 실패했습니다. 시드 재생성으로 "
                                               "해결되지 않을 수 있습니다."}}

    def _setup(self, job):
        docker = self.docker_factory(job["env"])
        self._set_step(job, "checking_docker")
        try:
            docker.info()
        except DockerError:
            return self._failure(job, "DOCKER_UNAVAILABLE", "Docker를 사용할 수 없습니다.")
        try:
            self._set_step(job, "checking_image")
            image = docker.inspect("image", IMAGE)
            if image is None:
                self._set_step(job, "pulling_image")
                try:
                    docker.pull(IMAGE)
                    image = docker.inspect("image", IMAGE)
                except DockerError:
                    image = None
                if image is None:
                    return self._failure(job, "IMAGE_PULL_FAILED", f"{IMAGE} 이미지를 받지 못했습니다.")
            self.image_id = image.get("Id")
            self._set_step(job, "preparing_volumes", image_id=self.image_id)
            created_data = False
            for name, role in ((DATA_VOLUME, "data"), (CONFIG_VOLUME, "config")):
                info = docker.inspect("volume", name)
                if info is None:
                    nonce = secrets.token_hex(16)
                    docker.create_volume(name, {OWNER_LABEL: OWNER, ROLE_LABEL: role, CREATED_LABEL: nonce})
                    info = docker.inspect("volume", name)
                    # create may silently reuse an existing volume: only our nonce proves it is new
                    if volume_owned(info, role) and info["Labels"].get(CREATED_LABEL) == nonce:
                        created_data = created_data or role == "data"
                        continue
                if not volume_owned(info, role):
                    return self._failure(job, "RESOURCE_CONFLICT", f"볼륨 {name}이 이 시연의 자원이 아닙니다.")
            self._set_step(job, "starting_container", created_data_volume=created_data)
            info = docker.inspect("container", CONTAINER)
            if info is None:
                try:
                    docker.run_container({OWNER_LABEL: OWNER, ROLE_LABEL: "mongo"})
                except DockerError as exc:
                    return self._failure(job, start_error_code(exc), "전용 컨테이너를 시작하지 못했습니다.")
                info = docker.inspect("container", CONTAINER)
                if info is None:
                    return self._failure(job, "CONTAINER_START_FAILED", "생성한 컨테이너를 찾지 못했습니다.")
            problem = container_problem(info)
            if problem:
                return self._failure(job, problem[0], problem[1])
            if not (info.get("State") or {}).get("Running"):
                try:
                    docker.start()
                except DockerError as exc:
                    return self._failure(job, start_error_code(exc), "전용 컨테이너를 시작하지 못했습니다.")
        except DockerError:
            return self._failure(job, "DOCKER_UNAVAILABLE", "Docker 명령이 실패했습니다.")
        self._set_step(job, "waiting_mongo")
        if not self._wait_ping():
            return self._failure(job, "MONGO_NOT_READY", "MongoDB가 제한 시간 안에 응답하지 않았습니다.")
        self._set_step(job, "checking_seed")
        report = self._check_seed()
        self._detail(job, seed_check=report)
        if report["status"] == "missing" and created_data:
            return self._seed_and_recheck(job, docker)
        return self._seed_outcome(report)

    def _seed(self, job):
        docker = self.docker_factory(job["env"])
        self._set_step(job, "checking_resources")
        code, detail, _ = self._verify_resources(docker)
        if code:
            return self._failure(job, code, detail)
        if not self._wait_ping():
            return self._failure(job, "MONGO_NOT_READY", "MongoDB가 제한 시간 안에 응답하지 않았습니다.")
        return self._seed_and_recheck(job, docker)

    def _seed_and_recheck(self, job, docker):
        """Destructive seed (collection drop); callers guarantee design 4.2 item 2."""
        self._set_step(job, "seeding")
        code, detail, _ = self._verify_resources(docker)
        if code:
            return self._failure(job, code, detail)
        reap = self._spawn(job, "seed", self.seed_cmd(), self.timeouts["seed"])
        if reap.get("abort") == "stopped":
            raise Stopped()
        if reap.get("abort") == "timeout":
            return self._failure(job, "SEED_TIMEOUT", "시드 생성이 제한 시간을 넘었습니다.", "seed_required")
        if reap.get("spawn_error") or reap.get("abort") or reap["exit"] != 0:
            return self._failure(job, "SEED_FAILED", "시드 생성이 실패했습니다. 로그를 확인하세요.", "seed_required")
        self._set_step(job, "rechecking_seed")
        report = self._check_seed()
        self._detail(job, seed_recheck=report)
        return self._seed_outcome(report, after_seed=True)

    def _bench(self, job):
        """Seed check -> one restart -> metadata-only check -> benchmark.py (design 4.2 item 4)."""
        docker = self.docker_factory(job["env"])
        self._set_step(job, "inspecting_resources")
        code, detail, info = self._verify_resources(docker)
        if code:
            return self._failure(job, code, detail)
        runner = {"image_id": info.get("Image"), "image": IMAGE, "container": CONTAINER,
                  "mongo": "127.0.0.1:27018", "memory_bytes": MEMORY_BYTES, "mongo_args": MONGO_ARGS}
        self._set_step(job, "checking_seed", runner=runner)
        report = self._check_seed()
        self._detail(job, precheck=report)
        if report["status"] in ("missing", "mismatch"):
            return self._failure(job, "SEED_MISMATCH", "측정 전 시드 검사가 일치하지 않습니다.", "seed_required")
        if report["status"] != "ok":
            return self._failure(job, SEED_STATUS_CODE[report["status"]], "측정 전 검사에 실패했습니다.")
        restart = {"started_before": (info.get("State") or {}).get("StartedAt")}
        self._set_step(job, "restarting", restart=restart)
        try:
            docker.restart()
        except DockerError:
            return self._failure(job, "RESTART_FAILED", "측정 전 MongoDB 재시작에 실패했습니다.")
        self._set_step(job, "verifying_restart")
        problem = self._verify_restart(docker, restart)
        self._detail(job, restart=restart)
        if problem:
            return self._failure(job, "RESTART_FAILED", problem)
        runner["measured_at"] = utc_now()
        runner["precheck"] = {"keys": report["keys"], "checked_at": report["checked_at"]}
        self._set_step(job, "running_benchmark", state="running", started_at=runner["measured_at"],
                       runner=runner)
        reap = self._spawn(job, "benchmark", self.bench_cmd(job["dir"] / RESULTS_NAME), self.timeouts["bench"])
        if reap.get("abort") == "stopped":
            raise Stopped()
        self._set_step(job, "judging")
        verdict = judge_run(job["dir"], exit_code=reap["exit"], timed_out=reap.get("abort") == "timeout",
                            reaped=not job["unreaped"] and not reap.get("record_error"),
                            spawn_error=bool(reap.get("spawn_error")), runner=runner)
        if reap.get("record_error") and verdict["state"] != "timed_out":
            verdict.update(state="failed", result=None,
                           error={"code": "RECORD_UNAVAILABLE", "message": "측정기 신원 기록에 실패해 중단했습니다."})
        return {"readiness": None, "detail": {k: verdict[k] for k in ("state", "error", "result", "partial")}}

    def _verify_restart(self, docker, restart):
        """Metadata only after the restart: no collection documents are read (design 4.2 item 4)."""
        try:
            info = docker.inspect("container", CONTAINER) or {}
        except DockerError:
            return "재시작 뒤 컨테이너를 조회하지 못했습니다."
        restart["started_after"] = (info.get("State") or {}).get("StartedAt")
        if not (info.get("State") or {}).get("Running") or restart["started_after"] == restart["started_before"]:
            return "재시작이 확인되지 않았습니다."
        if not self._wait_ping():
            return "재시작 뒤 MongoDB가 응답하지 않았습니다."
        try:
            cache, stats = self._reader_call(lambda r: (r.cache_max_bytes(), r.coll_stats()))
        except Exception:
            return "재시작 뒤 설정을 확인하지 못했습니다."
        restart.update(cache_max_bytes=cache, count=stats["count"], checked_at=utc_now())
        if cache != CACHE_MAX_BYTES or stats["count"] != EXPECTED_COUNT:
            return "재시작 뒤 캐시 한도 또는 문서 수 메타데이터가 다릅니다."
        return None

    # -- run lookup

    def run_view(self, run_id):
        if not ID_RE.fullmatch(run_id):
            return 404, _error("RUN_NOT_FOUND", "실행 기록이 없습니다.")
        run_dir = self.run_root / "runs" / run_id
        try:
            detail = read_json(run_dir / "runner.json")
        except FileNotFoundError:
            return 404, _error("RUN_NOT_FOUND", "실행 기록이 없습니다.")
        except (OSError, ValueError):
            return 500, _error("RECORD_UNAVAILABLE", "실행 기록을 읽을 수 없습니다.")
        try:
            rel = str(run_dir.relative_to(ROOT))
        except ValueError:
            rel = f"runs/{run_id}"
        view = {key: detail.get(key) for key in ("run_id", "state", "step", "created_at", "started_at",
                                                  "finished_at", "steps", "error", "precheck",
                                                  "restart", "reap")}
        view["result"] = detail.get("result") if detail.get("state") == "succeeded" else None
        view["partial"] = detail.get("partial") if detail.get("state") in ("failed", "timed_out") else None
        view["artifacts"] = {"dir": rel, "files": {name: (run_dir / name).is_file() for name in RUN_FILES}}
        return 200, view


def make_handler(app):
    routes = {"/": {"GET"}, "/api/setup": {"GET", "POST"}, "/api/setup/seed": {"POST"},
              "/api/runs": {"POST"}}

    class Handler(BaseHTTPRequestHandler):
        server_version = "MiniRedisLiveBench"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

        def do_PATCH(self):
            self._handle("PATCH")

        def do_OPTIONS(self):
            self._handle("OPTIONS")

        def _send(self, status, payload, headers=()):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _fail(self, status, code, message, headers=()):
            self._send(status, _error(code, message), headers)

        def _guarded(self, method):
            origin = f"http://{HOST}:{app.port}"
            hosts, origins = self.headers.get_all("Host") or [], self.headers.get_all("Origin") or []
            if hosts != [f"{HOST}:{app.port}"] or (origins and origins != [origin]):
                return False
            if method == "GET":
                return True
            tokens = self.headers.get_all("X-Live-Bench-Token") or []
            return len(tokens) == 1 and secrets.compare_digest(tokens[0].encode(), app.token.encode())

        def _body(self):
            """Parsed JSON object, or None after an error response has been sent."""
            media = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if media != "application/json":
                self._fail(415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type은 application/json이어야 합니다.")
                return None
            lengths = self.headers.get_all("Content-Length") or []
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
                self.close_connection = True
                self._fail(400, "INVALID_BODY", "본문 길이를 확인할 수 없습니다.")
                return None
            if int(lengths[0]) > MAX_BODY:
                self.close_connection = True  # not read: the declared body may never arrive
                self._fail(413, "BODY_TOO_LARGE", "본문은 1KiB 이하여야 합니다.", [("Connection", "close")])
                return None
            try:
                body = json.loads(self.rfile.read(int(lengths[0])).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = None
            if not isinstance(body, dict):
                self._fail(400, "INVALID_BODY", "본문은 JSON 객체여야 합니다.")
                return None
            return body

        def _handle(self, method):
            if not self._guarded(method):
                self.close_connection = True
                return self._fail(403, "FORBIDDEN_REQUEST", "로컬 화면의 요청만 허용합니다.")
            path = self.path.split("?", 1)[0]
            if path in routes:
                allowed = routes[path]
            elif path.startswith("/api/runs/"):
                allowed = {"GET"}
            else:
                return self._fail(404, "NOT_FOUND", "경로가 없습니다.")
            if method not in allowed:
                return self._fail(405, "METHOD_NOT_ALLOWED", "허용하지 않는 메서드입니다.",
                                  [("Allow", ", ".join(sorted(allowed)))])
            if method == "GET":
                if path == "/":
                    return self._page()
                if path == "/api/setup":
                    return self._send(200, app.setup_status())
                return self._send(*app.run_view(path[len("/api/runs/"):]))
            body = self._body()
            if body is None:
                return None
            kind = {"/api/setup": "setup", "/api/setup/seed": "seed", "/api/runs": "run"}[path]
            if kind == "seed":
                if not set(body) <= {"confirm_replace"}:
                    return self._fail(400, "INVALID_BODY", "알 수 없는 필드가 있습니다.")
                if body.get("confirm_replace") is not True:
                    return self._fail(400, "CONFIRMATION_REQUIRED",
                                      "컬렉션 삭제 후 재생성(약 1GB)에 대한 확인이 필요합니다.")
            elif body:
                return self._fail(400, "INVALID_BODY", "본문은 {}여야 합니다.")
            return self._send(*app.submit(kind))

        def _page(self):
            nonce = secrets.token_urlsafe(16)
            body = render_page(app.token, nonce).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", page_csp(nonce))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _interrupt(signum, frame):
    raise KeyboardInterrupt()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local live benchmark server (127.0.0.1 only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--recover", action="store_true",
                        help="with the server stopped, release jobs whose processes are proven gone")
    args = parser.parse_args(argv)
    if args.recover:
        report = run_recover(default_shared_dir(DockerCli()))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report["exit"]
    app = LiveBenchmark(port=args.port)
    try:
        app.start()
    except LockBusy:
        print("같은 Docker 자원 범위의 실행 서버가 이미 있습니다.", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"서버를 시작하지 못했습니다: {exc.strerror}", file=sys.stderr)
        return 1
    signal.signal(signal.SIGTERM, _interrupt)
    print(f"http://{HOST}:{app.port}/", flush=True)
    try:
        app.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()  # reaps an active job and records SERVER_STOPPED before exiting
    return 0


if __name__ == "__main__":
    sys.exit(main())
