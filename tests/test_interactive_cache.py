"""Iteration 07 first vertical slice; isolated fake Mongo, real new Mini Redis child."""
import http.client
import json
import os
import re
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from examples.interactive_cache import CacheChild, CacheUnavailable, Demo, TimingLog, launch_cache
from examples.interactive_cache_page import PageLease, create_page_server, start_demo


class FakeCollection:
    def __init__(self):
        self.rows = {}
        self.calls = []

    def find_one(self, query, projection=None):
        self.calls.append(('find_one', query['_id']))
        row = self.rows.get(query['_id'])
        return row.copy() if row is not None else None

    def update_one(self, query, update, upsert=False):
        self.calls.append(('update_one', query['_id']))
        old = self.rows.get(query['_id'])
        self.rows[query['_id']] = {'_id': query['_id'], **update['$set']}
        class Result: matched_count = int(old is not None)
        return Result()

    def find(self, query, projection):
        self.calls.append(('find', query))
        return [{'_id': k} for k in self.rows]


class NormalFlow(unittest.TestCase):
    def setUp(self):
        self.db = FakeCollection()
        self.cache = launch_cache()
        self.addCleanup(self.cache.close)
        self.demo = Demo(self.db, self.cache)

    def test_07_01_empty_value_and_update_keep_one_db_key(self):
        first = self.demo.save('a', '')
        self.assertEqual(first['status'], 'created')
        self.assertEqual(first['message'], '저장했어요')
        self.assertEqual(self.demo.keys(), {'keys': ['a'], 'truncated': False})
        self.assertEqual(self.demo.save('a', 'v2')['message'], '수정했어요')
        self.assertEqual(self.demo.keys(), {'keys': ['a'], 'truncated': False})
        self.assertEqual(self.db.rows['a']['value'], 'v2')

    def test_07_02_real_child_cache_miss_fill_hit_and_invalidation(self):
        self.demo.save('a', 'v1')
        self.assertIsNone(self.cache.get('a'))
        first = self.demo.read('a', 'cache_first')
        self.assertEqual((first['value'], first['source']), ('v1', 'db_then_cache'))
        self.assertEqual(self.cache.get('a'), 'v1')
        reads = len([call for call in self.db.calls if call[0] == 'find_one'])
        self.assertEqual((self.demo.read('a', 'cache_first')['value'],
                          self.demo.read('a', 'cache_first')['source']), ('v1', 'cache'))
        self.assertEqual(len([call for call in self.db.calls if call[0] == 'find_one']), reads)
        self.demo.save('a', 'v2')
        self.assertIsNone(self.cache.get('a'))
        self.assertEqual(self.demo.read('a', 'cache_first')['source'], 'db_then_cache')
        self.assertEqual((self.demo.read('a', 'cache_first')['value'],
                          self.demo.read('a', 'cache_first')['source']), ('v2', 'cache'))

    def test_07_08_db_direct_does_not_fill_cache(self):
        self.demo.save('a', 'v')
        before = self.cache.get('a')
        self.assertIsNone(before)
        direct = self.demo.read('a', 'db_direct')
        self.assertEqual((direct['value'], direct['source'], direct['message']),
                         ('v', 'db_direct', 'DB에서 직접 읽어왔어요'))
        self.assertGreaterEqual(direct['elapsed_ms'], 0)
        self.assertIsNone(self.cache.get('a'))
        self.assertEqual(self.demo.read('a', 'cache_first')['source'], 'db_then_cache')


class PageFlow(unittest.TestCase):
    def setUp(self):
        self.db = FakeCollection()
        self.cache = launch_cache()
        self.addCleanup(self.cache.close)
        self.server = create_page_server(Demo(self.db, self.cache), 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.server.server_address[1]
        status, page = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.html = page
        self.token = re.search(r'<meta name="demo-token" content="([^"<]+)">', page).group(1)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, *, token=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        headers = {'Host': f'127.0.0.1:{self.port}'}
        if method == 'POST':
            headers.update({'Origin': f'http://127.0.0.1:{self.port}',
                            'Content-Type': 'application/json',
                            'X-Demo-Token': self.token if token is None else token})
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        response = conn.getresponse()
        content = response.read().decode()
        status = response.status
        conn.close()
        return status, content if path == '/' else json.loads(content)

    def test_07_01_page_save_list_and_update(self):
        self.assertIn('무엇을 저장하시겠어요?', self.html)
        self.assertIn('값 읽어오기', self.html)
        self.assertIn('DB에서 직접 읽기', self.html)
        self.assertIn('textContent', self.html)
        status, first = self.request('POST', '/api/entries', {'key': 'a', 'value': ''})
        self.assertEqual((status, first['status'], first['message']), (200, 'created', '저장했어요'))
        self.assertEqual(self.request('GET', '/api/keys'), (200, {'keys': ['a'], 'truncated': False}))
        self.assertEqual(self.request('POST', '/api/entries', {'key': 'a', 'value': 'v2'})[1]['status'], 'updated')
        self.assertEqual(self.request('GET', '/api/keys')[1]['keys'], ['a'])

    def test_07_02_page_cache_miss_hit_after_store(self):
        self.request('POST', '/api/entries', {'key': 'a', 'value': 'v1'})
        first = self.request('POST', '/api/reads', {'key': 'a', 'mode': 'cache_first'})
        second = self.request('POST', '/api/reads', {'key': 'a', 'mode': 'cache_first'})
        self.assertEqual((first[1]['value'], first[1]['source']), ('v1', 'db_then_cache'))
        self.assertEqual((second[1]['value'], second[1]['source']), ('v1', 'cache'))
        self.request('POST', '/api/entries', {'key': 'a', 'value': 'v2'})
        self.assertEqual(self.request('POST', '/api/reads', {'key': 'a', 'mode': 'cache_first'})[1]['source'], 'db_then_cache')
        self.assertEqual(self.request('POST', '/api/reads', {'key': 'a', 'mode': 'cache_first'})[1]['value'], 'v2')

    def test_07_08_page_direct_read_does_not_fill_cache(self):
        self.request('POST', '/api/entries', {'key': 'a', 'value': 'v1'})
        direct = self.request('POST', '/api/reads', {'key': 'a', 'mode': 'db_direct'})
        self.assertEqual((direct[1]['source'], direct[1]['value']), ('db_direct', 'v1'))
        self.assertEqual(self.request('POST', '/api/reads', {'key': 'a', 'mode': 'cache_first'})[1]['source'], 'db_then_cache')

    def test_page_rejects_missing_token_without_writing(self):
        status, _ = self.request('POST', '/api/entries', {'key': 'a', 'value': 'v'}, token='wrong')
        self.assertEqual(status, 403)
        self.assertEqual(self.db.rows, {})

    def test_missing_or_foreign_origin_cannot_write_even_with_page_token(self):
        for origin in (None, 'http://foreign.example'):
            with self.subTest(origin=origin):
                conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
                headers = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json',
                           'X-Demo-Token': self.token}
                if origin is not None:
                    headers['Origin'] = origin
                conn.request('POST', '/api/entries', json.dumps({'key': 'a', 'value': 'v'}), headers)
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                conn.close()
        self.assertEqual(self.db.rows, {})

    def test_foreign_host_cannot_write_even_with_origin_and_token(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('POST', '/api/entries', json.dumps({'key': 'a', 'value': 'v'}),
                     {'Host': 'foreign.example', 'Origin': f'http://127.0.0.1:{self.port}',
                      'Content-Type': 'application/json', 'X-Demo-Token': self.token})
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        conn.close()
        self.assertEqual(self.db.rows, {})


class FailClosed(unittest.TestCase):
    def test_db_read_error_never_returns_a_cached_or_invented_value(self):
        class BrokenDB(FakeCollection):
            def find_one(self, query, projection=None):
                raise OSError('private database detail')
        db = BrokenDB()
        db.rows['a'] = {'_id': 'a', 'value': 'unverified'}
        demo = Demo(db, None)
        with self.assertRaises(OSError):
            demo.read('a', 'cache_first')
        server = create_page_server(demo, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
            conn.request('GET', '/')
            page = conn.getresponse().read().decode()
            conn.close()
            token_match = re.search(r'<meta name="demo-token" content="([^"<]+)">', page)
            if token_match is None:
                raise AssertionError('page token missing')
            token = token_match.group(1)
            port = server.server_address[1]
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            conn.request('POST', '/api/reads', json.dumps({'key': 'a', 'mode': 'cache_first'}),
                         {'Host': f'127.0.0.1:{port}', 'Origin': f'http://127.0.0.1:{port}',
                          'Content-Type': 'application/json', 'X-Demo-Token': token})
            response = conn.getresponse()
            body = response.read().decode()
            conn.close()
            self.assertEqual(response.status, 503)
            self.assertNotIn('unverified', body)
            self.assertNotIn('private database detail', body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_delete_failure_preserves_new_db_value_and_disables_all_cache_calls(self):
        class BrokenCache:
            def __init__(self): self.calls = []
            def delete(self, key):
                self.calls.append(('delete', key))
                raise TimeoutError('uncertain deletion')
            def get(self, key):
                self.calls.append(('get', key))
                return 'old'
            def put(self, key, value):
                self.calls.append(('put', key))
                return True
        db, cache = FakeCollection(), BrokenCache()
        db.rows['a'] = {'_id': 'a', 'value': 'old'}
        demo = Demo(db, cache)
        saved = demo.save('a', 'new')
        self.assertEqual(saved['message'], '수정했어요. 다음에 읽을 때는 조금 더 걸릴 수 있어요.')
        self.assertEqual(demo.read('a', 'cache_first')['value'], 'new')
        self.assertEqual(demo.read('a', 'cache_first')['source'], 'db_fallback')
        self.assertEqual(cache.calls, [('delete', 'a')])

    def test_uncertain_put_disables_cache_for_later_reads_and_saves(self):
        class UncertainCache:
            def __init__(self): self.calls = []
            def get(self, key):
                self.calls.append(('get', key))
                return None
            def put(self, key, value):
                self.calls.append(('put', key, value))
                raise TimeoutError('late PUT may still commit')
            def delete(self, key): self.calls.append(('delete', key))
        db, cache = FakeCollection(), UncertainCache()
        db.rows.update({'a': {'_id': 'a', 'value': 'old'},
                        'b': {'_id': 'b', 'value': 'other'}})
        demo = Demo(db, cache)
        first = demo.read('a', 'cache_first')
        self.assertEqual((first['value'], first['source']), ('old', 'db_fallback'))
        demo.save('a', 'new')
        self.assertEqual((demo.read('a', 'cache_first')['value'],
                          demo.read('b', 'cache_first')['source']), ('new', 'db_fallback'))
        self.assertEqual(cache.calls, [('get', 'a'), ('put', 'a', 'old')])

    def test_uncertain_get_is_not_a_miss_and_never_populates_cache(self):
        class BrokenGet:
            def __init__(self): self.calls = []
            def get(self, key):
                self.calls.append(('get', key))
                raise OSError('bad response')
            def put(self, key, value): self.calls.append(('put', key, value))
            def delete(self, key): self.calls.append(('delete', key))
        db, cache = FakeCollection(), BrokenGet()
        db.rows['a'] = {'_id': 'a', 'value': 'fresh'}
        demo = Demo(db, cache)
        self.assertEqual((demo.read('a', 'cache_first')['value'],
                          demo.read('a', 'cache_first')['source']), ('fresh', 'db_fallback'))
        demo.save('a', 'new')
        self.assertEqual(cache.calls, [('get', 'a')])

    def test_none_value_is_invalid_before_db_or_cache_call(self):
        db, cache = FakeCollection(), object()
        with self.assertRaises(ValueError):
            Demo(db, cache).save('a', None)
        self.assertEqual(db.calls, [])

    def test_db_write_error_disables_cache_without_deleting_it(self):
        class BrokenDB(FakeCollection):
            def update_one(self, query, update, upsert=False):
                raise TimeoutError('write outcome unknown')
        class TrackingCache:
            def __init__(self): self.calls = []
            def get(self, key):
                self.calls.append(('get', key))
                return 'stale'
            def delete(self, key): self.calls.append(('delete', key))
            def put(self, key, value): self.calls.append(('put', key))
        db, cache = BrokenDB(), TrackingCache()
        db.rows['a'] = {'_id': 'a', 'value': 'original'}
        demo = Demo(db, cache)
        with self.assertRaises(TimeoutError):
            demo.save('a', 'new')
        self.assertEqual((demo.read('a', 'cache_first')['value'],
                          demo.read('a', 'cache_first')['source']), ('original', 'db_fallback'))
        self.assertEqual(cache.calls, [])

    def test_new_page_server_uses_new_empty_cache_after_restart(self):
        db = FakeCollection()
        first_cache = launch_cache()
        try:
            first = Demo(db, first_cache)
            first.save('a', 'first')
            self.assertEqual(first.read('a', 'cache_first')['source'], 'db_then_cache')
            self.assertEqual(first_cache.get('a'), 'first')
        finally:
            first_cache.close()
        second_cache = launch_cache()
        self.addCleanup(second_cache.close)
        self.assertIsNone(second_cache.get('a'))
        second = Demo(db, second_cache)
        first_read = second.read('a', 'cache_first')
        self.assertEqual((first_read['value'], first_read['source']), ('first', 'db_then_cache'))
        self.assertEqual(second.read('a', 'cache_first')['source'], 'cache')


class CacheBoundary(unittest.TestCase):
    def test_duplicate_page_server_is_rejected_until_lease_released(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            path = os.path.join(directory, 'page.lock')
            first = PageLease(path)
            first.acquire()
            try:
                second = PageLease(path)
                with self.assertRaises(RuntimeError):
                    second.acquire()
                second.close()
            finally:
                first.close()
            third = PageLease(path)
            third.acquire()
            third.close()

    def test_child_startup_failure_allows_db_only_page(self):
        db = FakeCollection()
        def failed_start():
            raise CacheUnavailable('child readiness failed')
        demo = start_demo(db, failed_start)
        self.assertFalse(demo.cache_enabled)
        self.assertEqual(demo.save('a', 'v')['status'], 'created')
        self.assertEqual((demo.read('a', 'cache_first')['value'],
                          demo.read('a', 'cache_first')['source']), ('v', 'db_fallback'))

    def test_redirect_is_not_followed_to_another_local_service(self):
        target_requests = []
        class Foreign(BaseHTTPRequestHandler):
            def do_GET(self):
                target_requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"value":"foreign"}')
            def log_message(self, *_): pass
        target = ThreadingHTTPServer(('127.0.0.1', 0), Foreign)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()
        self.addCleanup(target.server_close)
        self.addCleanup(target.shutdown)
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{target.server_address[1]}/keys/a')
                self.send_header('Content-Length', '0')
                self.end_headers()
            def log_message(self, *_): pass
        redirect = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        self.addCleanup(redirect.server_close)
        self.addCleanup(redirect.shutdown)
        class Alive:
            def poll(self): return None
        cache = CacheChild(Alive(), redirect.server_address[1])
        with self.assertRaises(CacheUnavailable):
            cache.get('a')
        self.assertEqual(target_requests, [])


class TimingFlow(unittest.TestCase):
    def test_page_shows_record_and_summary_controls(self):
        db = FakeCollection()
        server = create_page_server(Demo(db, None), 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
            conn.request('GET', '/')
            response = conn.getresponse()
            page = response.read().decode()
            conn.close()
            self.assertIn('속도 기록', page)
            self.assertIn("api('/api/timings')", page)
            self.assertIn('중앙값', page)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_jsonl_survives_restart_summarizes_reads_and_ignores_truncated_tail(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            path = os.path.join(directory, 'timings.jsonl')
            log = TimingLog(path)
            log.append({'at': '2026-01-01T00:00:00Z', 'key': 'a', 'operation': 'read',
                        'source': 'cache', 'elapsed_ms': 1.0, 'status': 'success'})
            log.append({'at': '2026-01-01T00:00:01Z', 'key': 'a', 'operation': 'read',
                        'source': 'cache', 'elapsed_ms': 3.0, 'status': 'success'})
            log.append({'at': '2026-01-01T00:00:02Z', 'key': 'b', 'operation': 'read_db',
                        'source': 'db_direct', 'elapsed_ms': 4.0, 'status': 'failure'})
            with open(path, 'ab') as stream:
                stream.write(b'{"at":')
            summary = TimingLog(path).snapshot()
            self.assertEqual(summary['summary']['cache'], {'count': 2, 'mean_ms': 2.0, 'median_ms': 2.0})
            self.assertEqual(summary['failure_count'], 1)
            self.assertEqual(summary['invalid_count'], 1)
            self.assertEqual(len(summary['recent']), 3)

    def test_invalid_utf8_tail_does_not_hide_valid_history(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            path = os.path.join(directory, 'timings.jsonl')
            log = TimingLog(path)
            log.append({'at': '2026-01-01T00:00:00Z', 'key': 'a', 'operation': 'read',
                        'source': 'cache', 'elapsed_ms': 1.0, 'status': 'success'})
            with open(path, 'ab') as stream:
                stream.write(b'\xff\n')
            result = TimingLog(path).snapshot()
            self.assertEqual(result['invalid_count'], 1)
            self.assertEqual(result['summary']['cache']['count'], 1)

    def test_recent_fifty_does_not_limit_summary_history(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            log = TimingLog(os.path.join(directory, 'timings.jsonl'))
            for index in range(51):
                log.append({'at': f'2026-01-01T00:00:{index:02d}Z', 'key': str(index),
                            'operation': 'read', 'source': 'cache',
                            'elapsed_ms': float(index), 'status': 'success'})
            result = TimingLog(log.path).snapshot()
            self.assertEqual(len(result['recent']), 50)
            self.assertEqual(result['recent'][0]['key'], '50')
            self.assertEqual(result['recent'][-1]['key'], '1')
            self.assertEqual(result['summary']['cache']['count'], 51)
            self.assertEqual(result['summary']['cache']['median_ms'], 25.0)

    def test_save_and_reads_record_real_sources_and_missing_key_separately(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            log = TimingLog(os.path.join(directory, 'timings.jsonl'))
            cache = launch_cache()
            self.addCleanup(cache.close)
            demo = Demo(FakeCollection(), cache, timings=log)
            self.assertTrue(demo.save('a', 'v')['timing_saved'])
            self.assertTrue(demo.read('a', 'cache_first')['timing_saved'])
            demo.read('a', 'cache_first')
            demo.read('a', 'db_direct')
            with self.assertRaises(KeyError):
                demo.read('absent', 'db_direct')
            snapshot = TimingLog(log.path).snapshot()
            self.assertEqual([r['operation'] for r in snapshot['recent']],
                             ['read_db', 'read_db', 'read', 'read', 'save'])
            self.assertEqual([r['source'] for r in snapshot['recent'][1:4]],
                             ['db_direct', 'cache', 'db_then_cache'])
            self.assertEqual(snapshot['not_found_count'], 1)
            self.assertEqual(snapshot['summary']['cache']['count'], 1)
            self.assertEqual(snapshot['summary']['db_then_cache']['count'], 1)
            self.assertEqual(snapshot['summary']['db_direct']['count'], 1)

    def test_timing_endpoint_reads_persisted_log_and_write_failure_keeps_db_result(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            path = os.path.join(directory, 'timings.jsonl')
            db = FakeCollection()
            demo = Demo(db, None, timings=TimingLog(path))
            self.assertTrue(demo.save('a', 'v')['timing_saved'])
            server = create_page_server(demo, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
                conn.request('GET', '/api/timings')
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                body = json.loads(response.read())
                conn.close()
                self.assertEqual(len(body['recent']), 1)
                self.assertEqual(body['recent'][0]['operation'], 'save')
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

            class FailedLog:
                def append(self, row): raise OSError('disk unavailable')
            other = Demo(db, None, timings=FailedLog())
            result = other.save('b', 'v2')
            self.assertFalse(result['timing_saved'])
            self.assertEqual(db.rows['b']['value'], 'v2')


class PageCspNonce(unittest.TestCase):
    def test_script_and_style_nonces_match_the_served_page(self):
        server = create_page_server(Demo(FakeCollection(), None), 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
            conn.request('GET', '/')
            response = conn.getresponse()
            policy = response.getheader('Content-Security-Policy') or ''
            page = response.read().decode()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        tags = re.findall(r'<(script|style) nonce="([^"<]+)"', page)
        self.assertEqual(sorted(tag for tag, _ in tags), ['script', 'style'])
        served = {nonce for _, nonce in tags}
        self.assertEqual(len(served), 1)
        nonce = served.pop()
        self.assertNotIn('{nonce}', policy)
        self.assertIn(f"script-src 'nonce-{nonce}'", policy)
        self.assertIn(f"style-src 'nonce-{nonce}'", policy)
        # The protections around those directives stay in place.
        for directive in ("default-src 'none'", "connect-src 'self'", "base-uri 'none'",
                          "frame-ancestors 'none'"):
            self.assertIn(directive, policy)
        self.assertNotIn('unsafe-inline', policy)


class TruncatedCacheResponses(unittest.TestCase):
    """A valid JSON prefix of an unfinished HTTP message is not a confirmed cache result."""

    def start_cache(self, responses):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(4)
        seen = []

        def serve():
            while True:
                try:
                    connection, _ = listener.accept()
                except OSError:
                    return
                with connection:
                    connection.settimeout(3)
                    buffered = b''
                    try:
                        while b'\r\n\r\n' not in buffered:
                            chunk = connection.recv(4096)
                            if not chunk:
                                return
                            buffered += chunk
                        head, _, rest = buffered.partition(b'\r\n\r\n')
                        lines = head.decode('latin-1').split('\r\n')
                        length = next((int(line.split(':', 1)[1]) for line in lines[1:]
                                       if line.lower().startswith('content-length:')), 0)
                        while len(rest) < length:
                            chunk = connection.recv(4096)
                            if not chunk:
                                break
                            rest += chunk
                        seen.append(lines[0].split(' ')[0])
                        connection.sendall(responses[min(len(seen) - 1, len(responses) - 1)])
                    except OSError:
                        return
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(listener.close)

        class StubProcess:
            stdin = stdout = stderr = None
            def poll(self): return None
        return CacheChild(StubProcess(), listener.getsockname()[1]), seen

    @staticmethod
    def truncated(body, status=b'200 OK'):
        # Declares more bytes than it sends, then closes: the prefix alone parses as JSON.
        return (b'HTTP/1.1 ' + status + b'\r\nContent-Type: application/json\r\nContent-Length: '
                + str(len(body) + 10).encode() + b'\r\n\r\n' + body)

    @staticmethod
    def complete(body, status=b'200 OK'):
        return (b'HTTP/1.1 ' + status + b'\r\nContent-Type: application/json\r\nContent-Length: '
                + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)

    def test_truncated_get_is_a_cache_failure_not_a_hit(self):
        cache, seen = self.start_cache([self.truncated(b'{"value":"cached-old"}')])
        with self.assertRaises(CacheUnavailable):
            cache.get('a')
        db = FakeCollection()
        db.rows.update({'a': {'_id': 'a', 'value': 'fresh'}, 'b': {'_id': 'b', 'value': 'other'}})
        demo = Demo(db, cache)
        first = demo.read('a', 'cache_first')
        self.assertEqual((first['value'], first['source']), ('fresh', 'db_fallback'))
        self.assertFalse(demo.cache_enabled)
        demo.save('a', 'new')
        self.assertEqual(demo.read('a', 'cache_first')['source'], 'db_fallback')
        self.assertEqual(demo.read('b', 'cache_first')['source'], 'db_fallback')
        self.assertEqual(db.rows['a']['value'], 'new')
        self.assertEqual(seen, ['GET', 'GET'])  # the probe call plus the single failing read

    def test_truncated_put_after_a_real_miss_disables_the_cache(self):
        cache, seen = self.start_cache([self.complete(b'{"error":{"code":"KEY_NOT_FOUND"}}', b'404 Not Found'),
                                        self.truncated(b'{"stored":true}')])
        db = FakeCollection()
        db.rows.update({'a': {'_id': 'a', 'value': 'fresh'}, 'b': {'_id': 'b', 'value': 'other'}})
        demo = Demo(db, cache)
        first = demo.read('a', 'cache_first')
        self.assertEqual((first['value'], first['source']), ('fresh', 'db_fallback'))
        self.assertFalse(demo.cache_enabled)
        demo.save('a', 'new')
        self.assertEqual(demo.read('a', 'cache_first')['value'], 'new')
        self.assertEqual(demo.read('b', 'cache_first')['source'], 'db_fallback')
        self.assertEqual(seen, ['GET', 'PUT'])

    def test_truncated_delete_keeps_the_save_result_and_stops_cache_calls(self):
        cache, seen = self.start_cache([self.truncated(b'{"deleted":true}')])
        db = FakeCollection()
        db.rows['a'] = {'_id': 'a', 'value': 'old'}
        demo = Demo(db, cache)
        saved = demo.save('a', 'new')
        self.assertEqual(saved['status'], 'updated')
        self.assertEqual(saved['message'], '수정했어요. 다음에 읽을 때는 조금 더 걸릴 수 있어요.')
        self.assertFalse(demo.cache_enabled)
        self.assertEqual(db.rows['a']['value'], 'new')
        self.assertEqual(demo.read('a', 'cache_first')['source'], 'db_fallback')
        demo.save('a', 'newer')
        self.assertEqual(seen, ['DELETE'])

    def test_complete_responses_and_the_size_limit_still_behave(self):
        value = 'x' * 300000
        cache, _ = self.start_cache([self.complete(json.dumps({'value': value}).encode())])
        with self.assertRaises(CacheUnavailable):
            cache.get('a')  # over the existing response size limit
        cache, _ = self.start_cache([self.complete(b'{"value":"kept"}'),
                                     self.complete(b'{"stored":true}'),
                                     self.complete(b'{"deleted":false}')])
        self.assertEqual(cache.get('a'), 'kept')
        self.assertIs(cache.put('a', 'kept'), True)
        self.assertIs(cache.delete('a'), False)


if __name__ == '__main__':
    unittest.main()
