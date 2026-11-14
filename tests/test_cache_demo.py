"""U7 functional checks using three real HTTP servers."""

from contextlib import ExitStack, contextmanager
import json
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from waitress import create_server, wasyncore

from examples.cache_demo import create_demo_app, create_origin_app
from mini_redis.api import create_app
from mini_redis.store import MiniRedisStore


def http_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


@contextmanager
def running_server(app):
    sockets = {}
    server = create_server(app, host='127.0.0.1', port=0, threads=4, map=sockets)
    thread = Thread(target=server.run)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.effective_port}'
    finally:
        server.task_dispatcher.shutdown()
        wasyncore.close_all(map=sockets)
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError('Test HTTP server did not stop')


@contextmanager
def running_demo(*, ttl_ms=1000, clock_ns=None):
    store = MiniRedisStore() if clock_ns is None else MiniRedisStore(clock_ns=clock_ns)
    with ExitStack() as stack:
        redis = stack.enter_context(running_server(create_app(store)))
        origin = stack.enter_context(running_server(create_origin_app()))
        app = create_demo_app(redis, origin, ttl_ms=ttl_ms)
        demo = stack.enter_context(running_server(app))
        yield demo


class CacheDemoTests(unittest.TestCase):
    def test_bypass_miss_hit_and_original_calls(self):
        with running_demo() as base:
            bypass = [http_json(base + '/product?cache=0') for _ in range(2)]
            self.assertEqual([r['source'] for r in bypass], ['BYPASS', 'BYPASS'])
            self.assertEqual(http_json(base + '/stats')['origin_calls'], 2)
            miss = http_json(base + '/product')
            hit = http_json(base + '/product')
            self.assertEqual([miss['source'], hit['source']], ['MISS', 'HIT'])
            self.assertEqual(http_json(base + '/stats')['origin_calls'], 3)
            for response in [*bypass, miss, hit]:
                self.assertEqual(response['product'], {'id': 1, 'name': '키보드', 'price': 50000})
                self.assertGreaterEqual(response['elapsed_ms'], 0)
                self.assertTrue(response['steps'])

    def test_expiration_and_delete_fetch_again(self):
        now = [0]
        with running_demo(clock_ns=lambda: now[0]) as base:
            self.assertEqual(http_json(base + '/product')['source'], 'MISS')
            now[0] = 999999999
            self.assertEqual(http_json(base + '/product')['source'], 'HIT')
            now[0] = 1000000000
            self.assertEqual(http_json(base + '/product')['source'], 'MISS')
            self.assertEqual(http_json(base + '/cache/delete', {})['deleted'], True)
            self.assertEqual(http_json(base + '/product')['source'], 'MISS')
            self.assertEqual(http_json(base + '/stats')['origin_calls'], 3)

    def test_html_no_store_and_dependency_failure(self):
        with running_demo() as base:
            with urlopen(base + '/', timeout=5) as response:
                self.assertIn('no-store', response.headers['Cache-Control'])
                html = response.read().decode('utf-8')
                for label in ['캐시 없이 조회', '캐시로 조회', '캐시 삭제', '원본 호출']:
                    self.assertIn(label, html)
        # A running HTTP server returning 404 gives a deterministic upstream error.
        with running_server(create_app(MiniRedisStore())) as upstream:
            with running_server(create_demo_app(upstream + '/missing', upstream)) as base:
                with self.assertRaises(HTTPError) as caught:
                    http_json(base + '/product')
                self.assertEqual(caught.exception.code, 502)
                self.assertEqual(json.load(caught.exception)['error'], '의존 서버 요청에 실패했습니다.')
                caught.exception.close()


if __name__ == '__main__':
    unittest.main()
