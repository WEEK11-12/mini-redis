"""Separate local origin API for demonstrating cache reuse."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def create_server(host, port):
    calls = 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal calls
            if self.path == "/items/demo":
                calls += 1
                payload = {"value": "sample-response"}
                status = 200
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

    return HTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Run the local example origin API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
