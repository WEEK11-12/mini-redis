"""Explicitly started TTL cleanup worker; import has no thread side effects."""

from math import isfinite
from threading import Event, Lock, Thread

from mini_redis.store import MiniRedisStore


class ExpirationWorker:
    def __init__(self, store: MiniRedisStore, *, interval_seconds: float = 0.1):
        if (isinstance(interval_seconds, bool)
                or not isinstance(interval_seconds, (int, float))):
            raise TypeError("interval_seconds must be a number")
        if not isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("interval_seconds must be finite and positive")
        self._store = store
        self._interval = interval_seconds
        self._stop = Event()
        self._state_lock = Lock()
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None:
                return
            self._thread = Thread(target=self._run, name="mini-redis-expiration")
            self._thread.start()

    def stop(self) -> None:
        with self._state_lock:
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._store.cleanup()
