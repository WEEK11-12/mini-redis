"""JSON command API; creating an app starts no server or worker."""

import json

from flask import Flask, jsonify, request
from werkzeug.exceptions import (
    BadRequest, HTTPException, RequestEntityTooLarge, UnsupportedMediaType,
)

from mini_redis.store import MAX_KEY_BYTES, MAX_VALUE_BYTES, MiniRedisStore

MAX_BODY_BYTES = 8 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('invalid JSON constant')


def _read_input(allowed, required):
    if not request.is_json:
        raise UnsupportedMediaType('Content-Type must be application/json')
    raw = request.get_data()
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise BadRequest('Body must be valid UTF-8 JSON with unique fields') from None
    if not isinstance(data, dict):
        raise BadRequest('Body must be a JSON object')
    if data.keys() - allowed or required - data.keys():
        raise BadRequest('Missing required fields or unknown fields')
    for name, limit in [('key', MAX_KEY_BYTES), ('value', MAX_VALUE_BYTES)]:
        if name not in data:
            continue
        if not isinstance(data[name], str):
            raise BadRequest(f'{name} must be a string')
        try:
            size = len(data[name].encode('utf-8'))
        except UnicodeEncodeError:
            raise BadRequest(f'{name} must be valid UTF-8') from None
        if size > limit:
            raise RequestEntityTooLarge(f'{name} exceeds {limit} UTF-8 bytes')
    if 'ttl_ms' in data:
        ttl = data['ttl_ms']
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise BadRequest('ttl_ms must be a positive integer')
    return data


def create_app(store: MiniRedisStore) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = MAX_BODY_BYTES

    @app.errorhandler(HTTPException)
    def http_error(error):
        codes = {400: 'INVALID_INPUT', 404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED',
                 413: 'PAYLOAD_TOO_LARGE', 415: 'UNSUPPORTED_MEDIA_TYPE',
                 500: 'INTERNAL_ERROR'}
        message = 'Internal server error' if error.code == 500 else error.description
        response = error.get_response()
        response.set_data(app.json.dumps({'error': {
            'code': codes.get(error.code, error.name.upper().replace(' ', '_')),
            'message': message}}))
        response.content_type = 'application/json'
        return response

    @app.post('/set')
    def set_value():
        data = _read_input({'key', 'value', 'ttl_ms'}, {'key', 'value'})
        store.set(**data)
        return jsonify(ok=True)

    @app.post('/get')
    def get_value():
        data = _read_input({'key'}, {'key'})
        value = store.get(data['key'])
        return jsonify(found=value is not None, value=value)

    @app.post('/delete')
    def delete_value():
        data = _read_input({'key'}, {'key'})
        return jsonify(deleted=store.delete(data['key']))

    return app
