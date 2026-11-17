"""One-shot client that reuses an origin response via Mini Redis HTTP."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(NoRedirect)


def fetch(url, *, method="GET", body=None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as response:
        with response:
            return response.code, json.load(response) if response.code == 404 else None


def reuse(cache_url, origin_url):
    status, result = fetch(cache_url.rstrip("/") + "/keys/example-demo")
    if status == 200 and isinstance(result, dict) and isinstance(result.get("value"), str):
        return result["value"]
    if status != 404 or result != {"error": {"code": "KEY_NOT_FOUND"}}:
        raise ValueError("cache lookup failed")

    status, result = fetch(origin_url.rstrip("/") + "/items/demo")
    if status != 200 or not isinstance(result, dict) or not isinstance(result.get("value"), str):
        raise ValueError("origin request failed")
    value = result["value"]
    status, result = fetch(cache_url.rstrip("/") + "/keys/example-demo", method="PUT",
                           body=json.dumps({"value": value}).encode("utf-8"))
    if status != 200 or not isinstance(result, dict) or set(result) != {"stored"} or result["stored"] is not True:
        raise ValueError("cache write failed")
    return value


def main():
    parser = argparse.ArgumentParser(description="Fetch demo data through Mini Redis")
    parser.add_argument("--cache-url", required=True)
    parser.add_argument("--origin-url", required=True)
    args = parser.parse_args()
    try:
        value = reuse(args.cache_url, args.origin_url)
    except (HTTPError, URLError, OSError, ValueError, TypeError) as exc:
        print(f"Example request failed: {exc}", file=sys.stderr)
        return 1
    print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
