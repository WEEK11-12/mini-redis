"""Local product API and a small web program using Mini Redis over HTTP."""

import argparse
import json
from pathlib import Path
from threading import Lock
from time import perf_counter_ns, sleep
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_file
from waitress import serve

CACHE_KEY = 'demo:product:1'


def _http_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    outgoing = Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(outgoing, timeout=5) as response:
        return json.load(response)


def create_origin_app():
    app = Flask(__name__, static_folder=None)
    calls = 0
    lock = Lock()

    @app.get('/product')
    def product():
        nonlocal calls
        with lock:
            calls += 1
        sleep(0.05)
        return jsonify(id=1, name='키보드', price=50000)

    @app.get('/stats')
    def stats():
        with lock:
            return jsonify(origin_calls=calls)

    return app


def create_demo_app(redis_url, origin_url, *, ttl_ms=1000):
    app = Flask(__name__, static_folder=None)

    @app.after_request
    def no_browser_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    def dependency_error(error):
        app.logger.warning('Demo dependency failed: %s', type(error).__name__)
        return jsonify(error='의존 서버 요청에 실패했습니다.'), 502

    for exception in (URLError, TimeoutError, json.JSONDecodeError):
        app.register_error_handler(exception, dependency_error)

    @app.get('/')
    def index():
        return send_file(Path(__file__).with_name('cache.html'))

    @app.get('/product')
    def product():
        mode = request.args.get('cache', '1')
        if mode not in ('0', '1'):
            return jsonify(error='cache는 0 또는 1이어야 합니다.'), 400
        started = perf_counter_ns()
        steps = []
        if mode == '0':
            source = 'BYPASS'
            steps.append('캐시를 사용하지 않음')
            value = None
        else:
            steps.append('Mini Redis에 상품 정보 조회')
            cached = _http_json(redis_url + '/get', {'key': CACHE_KEY})
            value = json.loads(cached['value']) if cached['found'] else None
            source = 'MISS' if value is None else 'HIT'
        if value is None:
            steps.append('원본 API에서 상품 정보 가져오기 (50ms 대기 포함)')
            value = _http_json(origin_url + '/product')
            if mode == '1':
                _http_json(redis_url + '/set', {'key': CACHE_KEY,
                           'value': json.dumps(value, ensure_ascii=False), 'ttl_ms': ttl_ms})
                steps.append(f'Mini Redis에 {ttl_ms}ms 동안 저장')
        else:
            steps.append('저장된 정보로 응답 — 원본 상품 API 호출 없음')
        elapsed = (perf_counter_ns() - started) / 1000000
        return jsonify(product=value, source=source, steps=steps, elapsed_ms=elapsed)

    @app.get('/stats')
    def stats():
        return jsonify(_http_json(origin_url + '/stats'))

    @app.post('/cache/delete')
    def delete_cache():
        return jsonify(_http_json(redis_url + '/delete', {'key': CACHE_KEY}))

    return app


def main():
    parser = argparse.ArgumentParser(description='Mini Redis 상품 캐시 예제')
    parser.add_argument('role', choices=['origin', 'web'])
    args = parser.parse_args()
    if args.role == 'origin':
        app, port = create_origin_app(), 8082
    else:
        app, port = create_demo_app('http://127.0.0.1:8080', 'http://127.0.0.1:8082'), 8081
    serve(app, host='127.0.0.1', port=port, threads=4)


if __name__ == '__main__':
    main()
