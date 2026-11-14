"""Run explicitly: python -m tests.load_cleanup (not auto-discovered)."""

import json
import platform
from pathlib import Path
from threading import Event
from time import perf_counter
from unittest.mock import patch

from mini_redis.expiration import ExpirationWorker
from mini_redis.store import MiniRedisStore


def main():
    total, expired = 10000, 7000
    now = [0]
    store = MiniRedisStore(clock_ns=lambda: now[0])
    for index in range(total):
        store.set(f"key:{index}", f"{index:06d}:" + "x" * 121,
                  ttl_ms=1 if index < expired else 60000)
    now[0] = 1000000
    rounds, errors = [], []
    complete = Event()
    removed = 0
    original_cleanup = store.cleanup

    def observed_cleanup():
        nonlocal removed
        started = perf_counter()
        try:
            result = original_cleanup()
            rounds.append({"keys_checked": result.keys_checked,
                           "buckets_visited": result.buckets_visited,
                           "deleted": result.deleted,
                           "duration_ms": (perf_counter() - started) * 1000})
            removed += result.deleted
            if removed >= expired:
                complete.set()
            return result
        except BaseException as error:
            errors.append(repr(error))
            complete.set()

    worker = ExpirationWorker(store)
    started = perf_counter()
    with patch.object(store, "cleanup", observed_cleanup):
        worker.start()
        try:
            completed = complete.wait(30)
        finally:
            worker.stop()
    elapsed = perf_counter() - started
    assert not errors, errors
    assert completed, "cleanup did not finish within the 30-second test guard"
    assert removed == expired, removed
    assert len(store) == total - expired, len(store)
    assert all(r["keys_checked"] <= 100 and r["buckets_visited"] <= 100
               for r in rounds)
    for index in range(expired, total):
        assert store.get(f"key:{index}") == f"{index:06d}:" + "x" * 121
    for index in range(expired):
        assert store.get(f"key:{index}") is None
    assert not worker.is_running

    summary = {"result": "PASS", "python": platform.python_version(),
               "platform": platform.platform(), "total_keys": total,
               "expired_keys": expired, "valid_keys_preserved": total - expired,
               "value_utf8_bytes": 128, "bucket_count": len(store._buckets),
               "interval_seconds": 0.1, "round_count": len(rounds),
               "cleanup_elapsed_seconds": elapsed,
               "max_keys_checked": max(r["keys_checked"] for r in rounds),
               "max_buckets_visited": max(r["buckets_visited"] for r in rounds),
               "max_cleanup_duration_ms": max(r["duration_ms"] for r in rounds),
               "clock": "fixed injected nanoseconds; real worker and waits",
               "scope": "cleanup only; no HTTP or concurrent request workload"}
    output = Path(__file__).resolve().parents[1] / "history/U4-cleanup-load-result.json"
    output.write_text(json.dumps({**summary, "rounds": rounds}, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
