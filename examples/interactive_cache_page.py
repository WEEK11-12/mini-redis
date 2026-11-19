"""Local-only HTTP/UI shell for iteration 07's interactive cache demo.

Run `python3 -B -m examples.interactive_cache_page` only with an intentionally prepared
8-stage MongoDB at 127.0.0.1:27019; tests inject an isolated collection instead.
"""
import argparse
import fcntl
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from examples.interactive_cache import CacheUnavailable, Demo, TimingLog, launch_cache

PAGE = Path(__file__).with_name("interactive_cache_page.html")

class PageLease:
    """Reject a second page server from the same checkout (macOS flock)."""
    def __init__(self, path):
        self.path = Path(path)
        self.fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise RuntimeError("이미 이 프로젝트의 시연 페이지가 실행 중입니다.") from exc
        self.fd = fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def start_demo(collection, cache_factory=launch_cache, timings=None):
    """A failed cache launch must not prevent DB-only local use."""
    try:
        cache = cache_factory()
    except (CacheUnavailable, OSError):
        cache = None
    return Demo(collection, cache, timings=timings)


def create_page_server(demo, port=0):
    token = secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def send_json(self, status, data):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/":
                nonce = secrets.token_urlsafe(16)
                html = PAGE.read_text().replace("__TOKEN__", token).replace("__NONCE__", nonce).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", f"default-src 'none'; script-src 'nonce-{nonce}'; "
                                 f"style-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(html)
            elif self.path == "/api/keys":
                try:
                    self.send_json(200, demo.keys())
                except Exception:
                    self.send_json(503, {"error": {"code": "DB_UNAVAILABLE", "message": "목록을 읽을 수 없습니다."}})
            elif self.path == "/api/timings":
                try:
                    self.send_json(200, demo.timings.snapshot() if demo.timings is not None else
                                   {"recent": [], "summary": {}, "failure_count": 0,
                                    "not_found_count": 0, "invalid_count": 0})
                except Exception:
                    self.send_json(503, {"error": {"code": "TIMINGS_UNAVAILABLE", "message": "기록을 읽을 수 없습니다."}})
            else:
                self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "없는 경로입니다."}})

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_address[1]}"
            if (self.headers.get("Host") != origin.removeprefix("http://") or
                self.headers.get("Origin") != origin or
                self.headers.get("X-Demo-Token") != token):
                self.send_json(403, {"error": {"code": "FORBIDDEN", "message": "로컬 화면에서만 요청할 수 있습니다."}})
                return
            if self.path not in ("/api/entries", "/api/reads"):
                self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "없는 경로입니다."}})
                return
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal()
                    or len(lengths[0]) > 6 or int(lengths[0]) > 131072
                    or self.headers.get_all("Transfer-Encoding")
                    or self.headers.get_all("Content-Type", []) != ["application/json"]):
                    raise ValueError("요청 형식이 올바르지 않습니다.")
                body = self.rfile.read(int(lengths[0]))
                data = json.loads(body.decode("utf-8"))
                if type(data) is not dict:
                    raise ValueError("요청 형식이 올바르지 않습니다.")
                if self.path == "/api/entries" and set(data) == {"key", "value"}:
                    answer = demo.save(data["key"], data["value"])
                elif self.path == "/api/reads" and set(data) == {"key", "mode"}:
                    answer = demo.read(data["key"], data["mode"])
                else:
                    raise ValueError("요청 형식이 올바르지 않습니다.")
                self.send_json(200, answer)
            except (ValueError, UnicodeError) as exc:
                self.send_json(400, {"error": {"code": "INVALID_INPUT", "message": str(exc)}})
            except KeyError:
                self.send_json(404, {"error": {"code": "KEY_NOT_FOUND", "message": "저장된 키가 없습니다."}})
            except Exception:
                self.send_json(503, {"error": {"code": "DB_UNAVAILABLE", "message": "지금 처리할 수 없습니다."}})

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Local interactive Mini Redis demo")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise SystemExit("선택 의존성 pymongo가 없습니다: pip install -r examples/requirements-mongo.txt") from exc
    work_dir = Path(__file__).resolve().parent.parent / "var" / "interactive-cache-demo"
    lease = PageLease(work_dir / "page.lock")
    lease.acquire()
    try:
        client = MongoClient("mongodb://127.0.0.1:27019", serverSelectionTimeoutMS=3000,
                             socketTimeoutMS=3000, timeoutMS=3000)
        demo = None
        try:
            # Never create a collection on startup; the first save touches only this database.
            demo = start_demo(client["mini_redis_demo"]["entries"], timings=TimingLog(work_dir / "timings.jsonl"))
            server = create_page_server(demo, args.port)
            try:
                print(f"http://127.0.0.1:{server.server_address[1]}/", flush=True)
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        finally:
            if demo is not None and demo.cache is not None:
                demo.cache.close()
            client.close()
    finally:
        lease.close()


if __name__ == "__main__":
    main()
