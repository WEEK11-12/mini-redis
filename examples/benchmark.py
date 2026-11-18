"""Compare sequential latency without cache, on cache miss and on cache hit.

Reads a MongoDB collection seeded by examples.seed_mongo (needs pymongo), starts
Mini Redis and the origin API as separate long-running processes, and gives every
measured call its own item drawn with a fixed random seed. Only the value
acquisition is timed; state preparation and origin-call checks run outside the
timer. Writes every round's raw record and the summary as JSON.
"""

import argparse
import hashlib
import json
import math
import platform
import random
import signal
import socket
import statistics
import subprocess
import sys
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError

from examples.client import fetch, reuse
from examples.seed_mongo import COLLECTION, DATABASE, collection, item_id, value_for

ROOT = Path(__file__).resolve().parent.parent
KEY_SEED = 20261118
CONDITIONS = ("no_cache", "miss", "hit")
ORIGIN_DELTA = {"no_cache": 1, "miss": 1, "hit": 0}
WARMUP = 5
ROUNDS = 100
SOURCES = ("mini_redis/http_api.py", "mini_redis/store.py", "examples/client.py",
           "examples/origin_api.py", "examples/seed_mongo.py", "examples/benchmark.py")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start(module, port, log, *extra):
    process = subprocess.Popen([sys.executable, "-B", "-m", module, "--port", str(port), *extra],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{module} exited with {process.returncode}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return process
        except OSError:
            time.sleep(0.05)
    process.kill()
    process.wait()
    raise RuntimeError(f"{module} did not start")


def stop(process):
    process.send_signal(signal.SIGINT)
    try:
        return {"pid": process.pid, "exit": process.wait(timeout=10), "killed": False}
    except subprocess.TimeoutExpired:
        process.kill()
        return {"pid": process.pid, "exit": process.wait(), "killed": True}


def origin_calls(origin):
    status, body = fetch(origin + "/origin-calls")
    if status != 200 or not isinstance(body, dict) or type(body.get("count")) is not int:
        raise ValueError(f"origin count failed: {status} {body}")
    return body["count"]


def prepare(condition, cache, cache_key, expected):
    if condition == "miss":
        status, body = fetch(f"{cache}/keys/{cache_key}", method="DELETE")
        if status != 200 or not isinstance(body, dict) or type(body.get("deleted")) is not bool:
            raise ValueError(f"miss preparation failed: {status} {body}")
    elif condition == "hit":
        status, body = fetch(f"{cache}/keys/{cache_key}", method="PUT",
                             body=json.dumps({"value": expected}).encode("utf-8"))
        if status != 200 or body != {"stored": True}:
            raise ValueError(f"hit preparation failed: {status} {body}")


def acquire(condition, cache, origin, cache_key, item_path):
    if condition == "no_cache":
        status, body = fetch(origin + item_path)
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("value"), str):
            raise ValueError(f"origin request failed: {status}")
        return body["value"]
    return reuse(cache, origin, cache_key, item_path)


def run_once(condition, cache, origin, number):
    cache_key, item_path, expected = f"bench-{number}", f"/items/{item_id(number)}", value_for(number)
    record = {"condition": condition, "item": item_id(number), "cache_key": cache_key,
              "stage": "prepare", "elapsed_ns": None, "value_ok": None,
              "origin_before": None, "origin_after": None, "success": False, "error": None}
    try:
        prepare(condition, cache, cache_key, expected)
        record["stage"] = "origin_before"
        record["origin_before"] = origin_calls(origin)
        record["stage"] = "acquire"
        start_ns = time.perf_counter_ns()
        try:
            value = acquire(condition, cache, origin, cache_key, item_path)
        finally:
            # failed acquisitions keep the time until the error was raised
            record["elapsed_ns"] = time.perf_counter_ns() - start_ns
        record["value_ok"] = value == expected
        record["stage"] = "origin_after"
        record["origin_after"] = origin_calls(origin)
        record["stage"] = "verify"
        delta = record["origin_after"] - record["origin_before"]
        if not record["value_ok"]:
            raise ValueError(f"unexpected value {value[:32]!r} for {item_path}")
        if delta != ORIGIN_DELTA[condition]:
            raise ValueError(f"origin delta {delta}, expected {ORIGIN_DELTA[condition]}")
        record["success"] = True
        record["stage"] = "done"
    except (URLError, OSError, ValueError, TypeError, HTTPException) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def nearest_rank(sorted_values, percentile):
    return sorted_values[math.ceil(percentile / 100 * len(sorted_values)) - 1]


def summarize(records):
    summary = {}
    for condition in CONDITIONS:
        ok = sorted(r["elapsed_ns"] for r in records if r["condition"] == condition and r["success"])
        failed = sum(1 for r in records if r["condition"] == condition and not r["success"])
        summary[condition] = {
            "successes": len(ok), "failures": failed,
            "median_ms": statistics.median(ok) / 1e6 if ok else None,
            "p90_ms": nearest_rank(ok, 90) / 1e6 if ok else None,
        }
    summary["complete"] = all(summary[c]["successes"] == ROUNDS and summary[c]["failures"] == 0
                              for c in CONDITIONS)
    return summary


def mongo_state(uri):
    """Collection size and WiredTiger cache counters, read outside any timer."""
    client, _ = collection(uri)
    try:
        stats = client[DATABASE].command("collStats", COLLECTION)
        cache = client.admin.command("serverStatus")["wiredTiger"]["cache"]
        return {"count": stats["count"], "data_bytes": stats["size"],
                "storage_bytes": stats["storageSize"], "index_bytes": stats["totalIndexSize"],
                "cache_max_bytes": cache["maximum bytes configured"],
                "cache_used_bytes": cache["bytes currently in the cache"],
                "pages_read_into_cache": cache["pages read into cache"]}
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="Measure no-cache, miss and hit latency")
    parser.add_argument("--output", required=True, help="raw result JSON path")
    parser.add_argument("--mongo-uri", required=True, help="MongoDB seeded by examples.seed_mongo")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    cache_port, origin_port = free_port(), free_port()
    cache, origin = f"http://127.0.0.1:{cache_port}", f"http://127.0.0.1:{origin_port}"
    result = {
        "command": [sys.executable, *sys.argv],
        "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                 text=True).stdout.strip(),
        "sources_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES},
        "cache_url": cache, "origin_url": origin, "warmup_per_condition": WARMUP,
        "rounds": ROUNDS, "timer": "time.perf_counter_ns around value acquisition only",
        "percentile": "median of sorted successes; p90 nearest-rank",
        "mongo_before": mongo_state(args.mongo_uri), "key_seed": KEY_SEED,
    }
    docs = result["mongo_before"]["count"] - 1  # item-0 .. item-(docs-1) plus the demo document
    # Every call reads a distinct item; conditions share one uniform draw over the whole collection.
    numbers = random.Random(KEY_SEED).sample(range(docs), (WARMUP + ROUNDS) * len(CONDITIONS))
    result["key_space"] = docs
    warmup, records, servers = [], [], []
    result["aborted"] = None
    with open(output.with_suffix(".servers.log"), "w") as log:
        try:
            servers.append(start("examples.origin_api", origin_port, log,
                                 "--mongo-uri", args.mongo_uri))
            servers.append(start("mini_redis.http_api", cache_port, log))
            for index in range(WARMUP + ROUNDS):
                order = CONDITIONS[index % 3:] + CONDITIONS[:index % 3]
                for position, condition in enumerate(order):
                    number = numbers[index * len(CONDITIONS) + CONDITIONS.index(condition)]
                    record = run_once(condition, cache, origin, number)
                    record.update(round=index - WARMUP if index >= WARMUP else None,
                                  position=position)
                    (warmup if index < WARMUP else records).append(record)
        except (Exception, KeyboardInterrupt) as exc:
            # keep the rows collected so far instead of losing them with a traceback
            result["aborted"] = f"{type(exc).__name__}: {exc}"
        finally:
            result["servers"] = []
            for process in servers:
                try:
                    result["servers"].append(stop(process))
                except Exception as exc:
                    result["servers"].append({"pid": process.pid, "error": f"{type(exc).__name__}: {exc}"})
    try:
        result["mongo_after"] = mongo_state(args.mongo_uri)
    except Exception as exc:
        result["mongo_after"] = {"error": f"{type(exc).__name__}: {exc}"}
    summary = summarize(records)
    summary["complete"] = summary["complete"] and result["aborted"] is None
    result.update(warmup=warmup, records=records, summary=summary)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if result["aborted"]:
        print(f"aborted: {result['aborted']}", file=sys.stderr)
    return 0 if summary["complete"] else 1

if __name__ == "__main__":
    sys.exit(main())
