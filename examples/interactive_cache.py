"""Local interactive cache domain workflow, private cache child, and timing log."""
import json
import http.client
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


_KEY = re.compile(r"[A-Za-z0-9_.~-]+\Z")


class CacheUnavailable(RuntimeError):
    pass


class TimingLog:
    """Append-only local timing record; summaries read the whole valid history."""
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, row):
        raw = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A previous interrupted append may have left an unterminated line.
            with self.path.open("ab+") as stream:
                stream.seek(0, os.SEEK_END)
                if stream.tell():
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b"\n":
                        stream.write(b"\n")
                stream.write(raw.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())

    def snapshot(self):
        with self._lock:
            try:
                lines = self.path.read_bytes().splitlines()
            except FileNotFoundError:
                lines = []
        rows, invalid = [], 0
        for line in lines:
            try:
                row = json.loads(line)
                if (type(row) is not dict or type(row.get("at")) is not str or
                    type(row.get("key")) is not str or
                    row.get("operation") not in ("save", "read", "read_db") or
                    row.get("status") not in ("success", "failure", "not_found") or
                    row.get("source") not in ("cache", "db_then_cache", "db_fallback", "db_direct", None) or
                    type(row.get("elapsed_ms")) not in (int, float) or
                    not math.isfinite(row["elapsed_ms"]) or row["elapsed_ms"] < 0):
                    raise ValueError("invalid timing row")
                rows.append(row)
            except (ValueError, TypeError, UnicodeError):
                invalid += 1
        summary = {}
        for source in ("cache", "db_then_cache", "db_fallback", "db_direct"):
            times = [r["elapsed_ms"] for r in rows
                     if r["status"] == "success" and r["operation"] in ("read", "read_db") and r["source"] == source]
            if times:
                summary[source] = {"count": len(times), "mean_ms": statistics.mean(times),
                                   "median_ms": statistics.median(times)}
        return {"recent": rows[-50:][::-1], "summary": summary,
                "failure_count": sum(r["status"] == "failure" for r in rows),
                "not_found_count": sum(r["status"] == "not_found" for r in rows),
                "invalid_count": invalid}


class CacheChild:
    def __init__(self, process, port):
        self.process = process
        self.port = port

    def _request(self, method, key, value=None):
        if self.process.poll() is not None:
            raise CacheUnavailable("cache child exited")
        data = None if value is None else json.dumps({"value": value}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, f"/keys/{key}", body=data,
                               headers={"Content-Type": "application/json"} if data is not None else {})
            response = connection.getresponse()
            raw = response.read(262145)
            if len(raw) > 262144:
                raise CacheUnavailable("cache response too large")
            # A parsable JSON prefix of an unfinished message is not a confirmed result.
            if response.length or response.read(1):
                raise CacheUnavailable("incomplete cache response")
            payload = json.loads(raw.decode("utf-8"))
            if method == "GET" and response.status == 404 and payload == {"error": {"code": "KEY_NOT_FOUND"}}:
                return None
            if response.status != 200 or type(payload) is not dict:
                raise CacheUnavailable("unexpected cache response")
            field = {"GET": "value", "PUT": "stored", "DELETE": "deleted"}[method]
            if set(payload) != {field} or (type(payload[field]) is not str if method == "GET" else type(payload[field]) is not bool):
                raise CacheUnavailable("invalid cache response")
            return payload[field]
        except (OSError, ValueError, UnicodeError) as exc:
            raise CacheUnavailable("cache request failed") from exc
        finally:
            connection.close()

    def get(self, key):
        return self._request("GET", key)

    def put(self, key, value):
        return self._request("PUT", key, value)

    def delete(self, key):
        return self._request("DELETE", key)

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        for stream in (self.process.stdout, self.process.stderr):
            if stream:
                stream.close()


def launch_cache():
    """Start only a new empty child; never attach to an existing cache port."""
    import select
    process = subprocess.Popen([sys.executable, "-B", "-m", "examples.interactive_cache", "--cache-child"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               bufsize=0)
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 5)
        if not ready:
            raise CacheUnavailable("cache child startup timeout")
        line = process.stdout.readline().strip()
        port = int(line)
        if not 0 < port < 65536 or process.poll() is not None:
            raise CacheUnavailable("cache child did not start")
        return CacheChild(process, port)
    except Exception:
        CacheChild(process, 0).close()
        raise


class Demo:
    """Serialized page-server operations; Mongo collection is injected for isolation."""
    def __init__(self, collection, cache, timings=None):
        self.collection = collection
        self.cache = cache
        self.timings = timings
        self._lock = threading.Lock()
        self.cache_enabled = cache is not None

    def _record(self, key, operation, source, status, elapsed_ms):
        if self.timings is None:
            return False
        try:
            self.timings.append({"at": datetime.now(timezone.utc).isoformat(), "key": key,
                                 "operation": operation, "source": source,
                                 "elapsed_ms": elapsed_ms, "status": status})
            return True
        except Exception:
            # Losing the auxiliary timing file must not falsify the DB result.
            return False

    @staticmethod
    def _validate(key):
        if not isinstance(key, str) or not _KEY.fullmatch(key) or key in (".", "..") or len(key) > 200:
            raise ValueError("키는 영문·숫자와 -_.~만 사용해 200자 이하로 입력하세요")

    @staticmethod
    def _validate_value(value):
        if type(value) is not str:
            raise ValueError("값은 문자열이어야 해요")
        size = len(json.dumps({"value": value}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size > 65536:
            raise ValueError("값은 약 64KB까지 저장할 수 있어요")

    def keys(self):
        with self._lock:
            cursor = self.collection.find({}, {"_id": 1})
            rows = list(cursor.limit(201)) if hasattr(cursor, "limit") else list(cursor)[:201]
            keys = sorted(row["_id"] for row in rows)
            return {"keys": keys[:200], "truncated": len(keys) > 200}

    def save(self, key, value):
        self._validate(key)
        self._validate_value(value)
        with self._lock:
            start = time.perf_counter_ns()
            try:
                result = self.collection.update_one({"_id": key}, {"$set": {"value": value, "updated_at": datetime.now(timezone.utc)}}, upsert=True)
            except Exception:
                self.cache_enabled = False
                self._record(key, "save", None, "failure", (time.perf_counter_ns() - start) / 1_000_000)
                raise
            if self.cache_enabled:
                try:
                    self.cache.delete(key)
                except Exception:
                    self.cache_enabled = False
            created = result.matched_count == 0
            message = "저장했어요" if created else "수정했어요"
            if not self.cache_enabled:
                message += ". 다음에 읽을 때는 조금 더 걸릴 수 있어요."
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            return {"status": "created" if created else "updated", "message": message,
                    "elapsed_ms": elapsed, "timing_saved": self._record(key, "save", "db_direct", "success", elapsed)}

    def read(self, key, mode):
        self._validate(key)
        if mode not in ("cache_first", "db_direct"):
            raise ValueError("읽기 방식을 확인해 주세요")
        with self._lock:
            start = time.perf_counter_ns()
            operation = "read_db" if mode == "db_direct" else "read"
            try:
                result = self._read_locked(key, mode, start)
            except Exception as exc:
                status = "not_found" if isinstance(exc, KeyError) else "failure"
                self._record(key, operation, None, status, (time.perf_counter_ns() - start) / 1_000_000)
                raise
            result["timing_saved"] = self._record(key, operation, result["source"],
                                                   "success", result["elapsed_ms"])
            return result

    def _read_locked(self, key, mode, start):
        if mode == "cache_first" and self.cache_enabled:
            try:
                value = self.cache.get(key)
                if value is not None:
                    return self._read_result(value, "cache", "캐시에서 읽어왔어요", start)
            except Exception:
                self.cache_enabled = False
        row = self.collection.find_one({"_id": key}, {"value": 1})
        if row is None:
            raise KeyError(key)
        value = row["value"]
        if mode == "db_direct":
            return self._read_result(value, "db_direct", "DB에서 직접 읽어왔어요", start)
        if self.cache_enabled:
            try:
                if self.cache.put(key, value) is not True:
                    raise CacheUnavailable("cache write unconfirmed")
                return self._read_result(value, "db_then_cache", "DB에서 읽어와 캐시에 담았어요", start)
            except Exception:
                self.cache_enabled = False
        return self._read_result(value, "db_fallback", "캐시를 쓸 수 없어 DB에서 읽었어요", start)

    @staticmethod
    def _read_result(value, source, message, start):
        return {"value": value, "source": source, "message": message,
                "elapsed_ms": (time.perf_counter_ns() - start) / 1_000_000}


def _child():
    from mini_redis.http_api import create_server
    from mini_redis.store import HashTableStore
    server = create_server("127.0.0.1", 0, HashTableStore())
    def watch_parent():
        sys.stdin.buffer.read()
        server.shutdown()
    threading.Thread(target=watch_parent, daemon=True).start()
    print(server.server_address[1], flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


if __name__ == "__main__" and sys.argv[1:] == ["--cache-child"]:
    _child()
