"""Run one shared store with four request workers and one cleanup worker."""

from waitress import serve

from mini_redis.api import MAX_BODY_BYTES, create_app
from mini_redis.expiration import ExpirationWorker
from mini_redis.store import MiniRedisStore


def main() -> None:
    store = MiniRedisStore()
    app = create_app(store)
    worker = ExpirationWorker(store)
    try:
        worker.start()
        serve(app, host='127.0.0.1', port=8080, threads=4,
              # Waitress 3.0.2 rejects >= its limit; Flask rejects > its limit.
              max_request_body_size=MAX_BODY_BYTES + 1)
    finally:
        worker.stop()


if __name__ == '__main__':
    main()
