"""U6: real Waitress socket, shared store, limits, and entrypoint cleanup."""

from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import importlib
import json
import threading
import unittest
from unittest.mock import patch

from waitress import create_server, wasyncore

from mini_redis import server
from mini_redis.api import MAX_BODY_BYTES
from mini_redis.expiration import ExpirationWorker


class ServerTests(unittest.TestCase):
    def test_import_does_not_start_threads_or_server(self):
        with patch('waitress.serve') as serve, patch('threading.Thread.start') as start:
            importlib.reload(server)
        serve.assert_not_called()
        start.assert_not_called()

    def test_actual_waitress_requests_limits_and_worker_lifecycle(self):
        workers = []
        def worker_factory(store):
            worker = ExpirationWorker(store)
            workers.append(worker)
            return worker

        def live_serve(app, **options):
            self.assertTrue(workers[0].is_running)
            self.assertEqual(options, {'host': '127.0.0.1', 'port': 8080,
                                      'threads': 4, 'max_request_body_size': MAX_BODY_BYTES + 1})
            # Isolate sockets and choose an OS-assigned port; product defaults stay unchanged.
            options['port'] = 0
            sockets = {}
            http_server = create_server(app, map=sockets, **options)
            thread = threading.Thread(target=http_server.run)
            thread.start()
            port = http_server.effective_port

            def post(path, payload):
                connection = HTTPConnection('127.0.0.1', port, timeout=5)
                try:
                    connection.request('POST', path, json.dumps(payload),
                                       {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()

            try:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(lambda n: post('/set', {
                        'key': f'key-{n}', 'value': f'value-{n}'}), range(4)))
                self.assertEqual(results, [(200, {'ok': True})] * 4)
                for n in range(4):
                    self.assertEqual(post('/get', {'key': f'key-{n}'}),
                                     (200, {'found': True, 'value': f'value-{n}'}))
                self.assertEqual(post('/delete', {'key': 'key-0'}),
                                 (200, {'deleted': True}))
                self.assertEqual(post('/get', {'key': 'key-0'}),
                                 (200, {'found': False, 'value': None}))
                self.assertEqual(post('/get', {'key': 1})[0], 400)
                connection = HTTPConnection('127.0.0.1', port, timeout=5)
                try:
                    raw = b'{"key":"key-1"}'
                    raw += b' ' * (MAX_BODY_BYTES - len(raw))
                    connection.request('POST', '/get', raw,
                                       {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read()),
                                     {'found': True, 'value': 'value-1'})
                finally:
                    connection.close()
                connection = HTTPConnection('127.0.0.1', port, timeout=5)
                try:
                    connection.putrequest('POST', '/set')
                    connection.putheader('Content-Type', 'application/json')
                    connection.putheader('Content-Length', str(MAX_BODY_BYTES + 1))
                    connection.endheaders()
                    response = connection.getresponse()
                    body = response.read().decode('utf-8')
                    self.assertEqual(response.status, 413)
                    self.assertTrue(response.getheader('Content-Type').startswith('text/plain'))
                    self.assertIn('exceeds max_body', body)
                    print('Waitress pre-Flask rejection: 413 text/plain, exceeds max_body')
                finally:
                    connection.close()
                self.assertEqual(post('/get', {'key': 'key-1'})[0], 200)
            finally:
                http_server.task_dispatcher.shutdown()
                wasyncore.close_all(map=sockets)
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            raise KeyboardInterrupt

        with patch.object(server, 'ExpirationWorker', side_effect=worker_factory), \
                patch.object(server, 'serve', side_effect=live_serve):
            with self.assertRaises(KeyboardInterrupt):
                server.main()
        self.assertEqual(len(workers), 1)
        self.assertFalse(workers[0].is_running)

    def test_worker_stops_even_if_server_start_fails(self):
        workers = []
        def worker_factory(store):
            worker = ExpirationWorker(store)
            workers.append(worker)
            return worker
        with patch.object(server, 'ExpirationWorker', side_effect=worker_factory), \
                patch.object(server, 'serve', side_effect=OSError('port in use')):
            with self.assertRaises(OSError):
                server.main()
        self.assertFalse(workers[0].is_running)


if __name__ == '__main__':
    unittest.main()
