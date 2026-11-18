"""Separate local origin API that reads demo data from a SQLite file."""

import argparse
import json
import os
import sqlite3
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from examples.seed_db import DEMO_ID, seed


def create_server(host, port, db_path=None):
    """Serve GET /items/demo from db_path; without one, reseed one shared file in the temp dir."""
    if db_path is None:
        # Fixed path so servers stopped by a signal leave at most this one file behind.
        db_path = os.path.join(tempfile.gettempdir(), "mini-redis-origin.db")
        seed(db_path)
    # Read-only so a missing file fails at startup instead of creating an empty database.
    connection = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True,
                                 check_same_thread=False)
    try:
        connection.execute("SELECT 1 FROM items LIMIT 1")
    except BaseException:
        connection.close()
        raise
    calls = 0

    def read_demo():
        try:
            row = connection.execute("SELECT value FROM items WHERE id = ?", (DEMO_ID,)).fetchone()
        except sqlite3.Error:
            return 500, {"error": {"code": "ORIGIN_DB_ERROR"}}
        if row is None:
            return 404, {"error": {"code": "NOT_FOUND"}}
        return 200, {"value": row[0]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal calls
            if self.path == "/items/demo":
                calls += 1
                status, payload = read_demo()
            elif self.path == "/origin-calls":
                payload = {"count": calls}
                status = 200
            else:
                payload = {"error": {"code": "NOT_FOUND"}}
                status = 404
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    class Server(HTTPServer):
        def server_close(self):
            super().server_close()
            connection.close()

    try:
        return Server((host, port), Handler)
    except BaseException:
        connection.close()
        raise


def main():
    parser = argparse.ArgumentParser(description="Run the local example origin API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--db", help="SQLite file from examples.seed_db (default: reseeded temp-dir file)")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.db)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
