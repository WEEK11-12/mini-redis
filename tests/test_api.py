"""U6: HTTP contract, validation, and preservation of stored data."""

import unittest
from unittest.mock import patch

from mini_redis.api import MAX_BODY_BYTES, create_app
from mini_redis.store import MAX_KEY_BYTES, MAX_VALUE_BYTES, MiniRedisStore


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.store = MiniRedisStore(clock_ns=lambda: self.now)
        self.app = create_app(self.store)
        self.client = self.app.test_client()

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.json['error']['code'], code)
        self.assertIsInstance(response.json['error']['message'], str)

    def test_round_trip_empty_and_unicode(self):
        for key, value in [('', ''), (' 한글/\n', ' 값\n🙂 ')]:
            with self.subTest(key=key):
                self.assertEqual(self.client.post('/set', json={
                    'key': key, 'value': value}).json, {'ok': True})
                self.assertEqual(self.client.post('/get', json={'key': key}).json,
                                 {'found': True, 'value': value})
                self.assertEqual(self.store.get(key), value)
                self.assertEqual(self.client.post('/delete', json={'key': key}).json,
                                 {'deleted': True})
                self.assertEqual(self.client.post('/get', json={'key': key}).json,
                                 {'found': False, 'value': None})
                self.assertEqual(self.client.post('/delete', json={'key': key}).json,
                                 {'deleted': False})

    def test_ttl_boundary_delete_and_overwrite(self):
        self.client.post('/set', json={'key': 'k', 'value': 'v', 'ttl_ms': 1})
        self.now = 999999
        self.assertTrue(self.client.post('/get', json={'key': 'k'}).json['found'])
        self.now = 1000000
        self.assertEqual(self.client.post('/delete', json={'key': 'k'}).json,
                         {'deleted': False})
        self.client.post('/set', json={'key': 'k', 'value': 'v', 'ttl_ms': 1})
        self.now += 1000000
        self.assertFalse(self.client.post('/get', json={'key': 'k'}).json['found'])
        self.client.post('/set', json={'key': 'k', 'value': 'v', 'ttl_ms': 1})
        self.client.post('/set', json={'key': 'k', 'value': 'permanent'})
        self.now += 1000000
        self.assertEqual(self.store.get('k'), 'permanent')

    def test_invalid_fields_types_and_ttl_preserve_data_and_deadline(self):
        cases = [{}, {'key': 'k'}, {'key': 'k', 'value': 1},
                 {'key': False, 'value': 'x'},
                 {'key': 'k', 'value': 'x', 'ttl': 1}]
        cases += [{'key': 'k', 'value': 'x', 'ttl_ms': ttl}
                  for ttl in [None, True, 0, -1, 1.5, '1']]
        for payload in cases:
            with self.subTest(payload=payload):
                self.now = 0
                self.store.set('k', 'old', ttl_ms=1)
                self.assert_error(self.client.post('/set', json=payload),
                                  400, 'INVALID_INPUT')
                self.assertEqual(self.store.get('k'), 'old')
                self.now = 1000000
                self.assertIsNone(self.store.get('k'))
        for route in ['/get', '/delete']:
            for payload in [{}, {'key': 1}, {'key': 'k', 'ttl_ms': 1}]:
                self.assert_error(self.client.post(route, json=payload),
                                  400, 'INVALID_INPUT')

    def test_malformed_duplicate_and_non_object_json(self):
        for raw in ['{', '[]', 'null', '1', '"text"',
                    '{"key":"a","key":"b"}', '{"key":NaN}',
                    '{"key":"\\ud800"}', '{"key":"\\udfff"}']:
            with self.subTest(raw=raw):
                self.assert_error(self.client.post('/get', data=raw,
                                  content_type='application/json'), 400, 'INVALID_INPUT')
        self.assert_error(self.client.post('/get', data=b'\xff',
                          content_type='application/json'), 400, 'INVALID_INPUT')
        self.assert_error(self.client.post('/set', data='{"key":"k","value":"\\ud800"}',
                          content_type='application/json'), 400, 'INVALID_INPUT')

    def test_utf8_size_boundaries_and_preservation(self):
        key = 'é' * (MAX_KEY_BYTES // 2)
        value = 'é' * (MAX_VALUE_BYTES // 2)
        response = self.client.post('/set', json={'key': key, 'value': value})
        self.assertEqual(response.status_code, 200)
        for payload in [{'key': key + 'x', 'value': 'new'},
                        {'key': key, 'value': value + 'x'}]:
            self.assert_error(self.client.post('/set', json=payload),
                              413, 'PAYLOAD_TOO_LARGE')
            self.assertEqual(self.store.get(key), value)
        for route in ['/get', '/delete']:
            self.assert_error(self.client.post(route, json={'key': key + 'x'}),
                              413, 'PAYLOAD_TOO_LARGE')

    def test_body_limit_and_content_type(self):
        raw = b'{"key":"k"}'
        # JSON whitespace lets the body reach the limit without an oversized key.
        raw += b' ' * (MAX_BODY_BYTES - len(raw))
        self.assertEqual(self.client.post('/get', data=raw,
                         content_type='application/json').status_code, 200)
        self.assert_error(self.client.post('/get', data=raw + b' ',
                          content_type='application/json'), 413, 'PAYLOAD_TOO_LARGE')
        self.assert_error(self.client.post('/get', data='{"key":"k"}'),
                          415, 'UNSUPPORTED_MEDIA_TYPE')

    def test_routing_and_internal_errors_are_json(self):
        self.assert_error(self.client.post('/missing'), 404, 'NOT_FOUND')
        response = self.client.get('/set')
        self.assert_error(response, 405, 'METHOD_NOT_ALLOWED')
        self.assertIn('POST', response.headers['Allow'])
        with patch.object(self.store, 'get', side_effect=RuntimeError('private detail')):
            with self.assertLogs(self.app.logger, level='ERROR'):
                response = self.client.post('/get', json={'key': 'k'})
        self.assert_error(response, 500, 'INTERNAL_ERROR')
        self.assertNotIn('private detail', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
