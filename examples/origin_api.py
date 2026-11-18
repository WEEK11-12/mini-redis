"""Separate local origin API: a fixed demo response by default, or items from MongoDB."""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

DEMO_ID = "demo"
DEMO_VALUE = "sample-response"
_ITEM = re.compile(r"/items/([A-Za-z0-9_.~-]+)\Z")
_DEMO = re.compile(r"/items/(demo)\Z")


def _mongo_reader(uri):
    from examples.seed_mongo import collection  # pymongo only when this backend is chosen
    from pymongo.errors import PyMongoError

    client, items = collection(uri)
    try:
        client.admin.command("ping")
    except BaseException:
        client.close()
        raise

    def read(item_id):
        document = items.find_one({"_id": item_id}, {"value": 1})
        return None if document is None else document["value"]

    return read, client.close, PyMongoError


def create_server(host, port, mongo_uri=None):
    """Serve the fixed demo item by default, or GET /items/<id> from MongoDB."""
    if mongo_uri:
        read, close, db_error = _mongo_reader(mongo_uri)
        item_route = _ITEM
    else:
        # Default contract: only /items/demo exists and counts; other paths are uncounted 404s.
        read, close, db_error = (lambda item_id: DEMO_VALUE), (lambda: None), ()
        item_route = _DEMO
    calls = 0

    def read_item(item_id):
        try:
            value = read(item_id)
        except db_error:
            return 500, {"error": {"code": "ORIGIN_DB_ERROR"}}
        if value is None:
            return 404, {"error": {"code": "NOT_FOUND"}}
        return 200, {"value": value}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal calls
            item = item_route.match(self.path)
            if item:
                calls += 1
                status, payload = read_item(item.group(1))
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
            close()

    try:
        return Server((host, port), Handler)
    except BaseException:
        close()
        raise


def main():
    parser = argparse.ArgumentParser(description="Run the local example origin API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--mongo-uri", help="MongoDB seeded by examples.seed_mongo (needs pymongo)")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.mongo_uri)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
