import importlib
import sys
import threading
import unittest
from unittest.mock import patch

from mini_redis.store import MiniRedisStore, fnv1a_64
from test_ttl import FakeClock


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = MiniRedisStore(clock_ns=self.clock)

    def test_t11_expired_only_and_one_full_pass(self):
        self.store.set("expired", "old", ttl_ms=1)
        self.store.set("live", "new", ttl_ms=2)
        self.store.set("permanent", "keep")
        self.clock.now = 1000000
        result = self.store.cleanup()
        self.assertEqual(result.keys_checked, 3)
        self.assertEqual(result.buckets_visited, 16)
        self.assertEqual(result.deleted, 1)
        self.assertEqual(len(self.store), 2)
        self.assertEqual(self.store.get("live"), "new")
        self.assertEqual(self.store.get("permanent"), "keep")

    def test_t11_invalid_limits_do_not_mutate_store(self):
        self.store.set("key", "keep")
        for name in ("key_limit", "bucket_limit"):
            for value, error in ((0, ValueError), (-1, ValueError),
                                 (True, TypeError), (1.5, TypeError)):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(error):
                        self.store.cleanup(**{name: value})
                    self.assertEqual(self.store.get("key"), "keep")

    def test_t11_renew_before_cleanup_preserves_new_deadline(self):
        self.store.set("key", "old", ttl_ms=1)
        self.clock.now = 1000000
        self.store.set("key", "new", ttl_ms=10)
        self.assertEqual(self.store.cleanup().deleted, 0)
        self.assertEqual(self.store.get("key"), "new")
        self.clock.now = 11000000
        self.assertEqual(self.store.cleanup().deleted, 1)
        self.assertEqual(len(self.store), 0)

    def test_t11_default_100_key_limit_in_long_chain(self):
        keys = []
        candidate = 0
        while len(keys) < 101:
            key = str(candidate)
            if fnv1a_64(key.encode()) % 256 == 0:
                keys.append(key)
            candidate += 1
        for key in keys:
            self.store.set(key, "expired", ttl_ms=1)
        self.clock.now = 1000000
        result = self.store.cleanup()
        self.assertEqual(result.keys_checked, 100)
        self.assertEqual(result.buckets_visited, 1)
        self.assertEqual(result.deleted, 100)
        self.assertEqual(len(self.store), 1)
        result = self.store.cleanup()
        self.assertEqual(result.deleted, 1)
        self.assertEqual(len(self.store), 0)

    def test_t11_empty_bucket_limit_and_progress(self):
        for index in range(100):
            self.store.set(str(index), "value")
        for index in range(100):
            self.store.delete(str(index))
        self.assertEqual(len(self.store._buckets), 256)
        for expected in (100, 200, 44):
            result = self.store.cleanup()
            self.assertEqual(result.keys_checked, 0)
            self.assertEqual(result.buckets_visited, 100)
            self.assertEqual(self.store._scan_bucket, expected)

    def test_t11_multiple_rounds_reach_later_buckets(self):
        for index in range(200):
            self.store.set(str(index), "old", ttl_ms=1)
        self.store.set("live", "keep")
        self.clock.now = 1000000
        deleted = 0
        for _ in range(10):
            result = self.store.cleanup()
            self.assertLessEqual(result.keys_checked, 100)
            self.assertLessEqual(result.buckets_visited, 100)
            deleted += result.deleted
        self.assertEqual(deleted, 200)
        self.assertEqual(len(self.store), 1)
        self.assertEqual(self.store.get("live"), "keep")

    def make_partial_chain(self):
        for key in ("a", "q", "A"):
            self.store.set(key, key, ttl_ms=1)
        result = self.store.cleanup(key_limit=1)
        self.assertEqual(result.keys_checked, 1)
        self.assertEqual(self.store._scan_node.key, "q")

    def test_t11_deleted_cursor_target_and_predecessor(self):
        for removed in ("q", "A"):
            with self.subTest(removed=removed):
                self.setUp()
                self.make_partial_chain()
                self.assertIs(self.store.delete(removed), True)
                self.clock.now = 1000000
                for _ in range(2):
                    self.store.cleanup()
                self.assertEqual(len(self.store), 0)

    def test_t11_passive_expiration_repairs_cursor(self):
        self.make_partial_chain()
        self.clock.now = 1000000
        self.assertIsNone(self.store.get("q"))
        self.store.cleanup()
        self.assertIsNone(self.store.get("A"))
        self.assertIsNone(self.store.get("a"))
        self.assertEqual(len(self.store), 0)

    def test_t11_head_insert_during_partial_scan(self):
        self.store.set("a", "a", ttl_ms=1)
        self.store.set("q", "q", ttl_ms=1)
        self.store.cleanup(key_limit=1)
        self.store.delete("q")
        self.assertIsNone(self.store._scan_previous)
        self.store.set("A", "new")
        self.clock.now = 1000000
        for _ in range(3):
            self.store.cleanup()
        self.assertEqual(len(self.store), 1)
        self.assertEqual(self.store.get("A"), "new")

    def test_t11_resize_resets_cursor_and_keeps_new_table_valid(self):
        self.make_partial_chain()
        for index in range(10):
            self.store.set(str(index), "value", ttl_ms=1)
        self.assertEqual(len(self.store._buckets), 32)
        self.assertEqual(self.store._scan_bucket, 0)
        self.assertIsNone(self.store._scan_node)
        self.clock.now = 1000000
        self.assertEqual(self.store.cleanup().deleted, 13)
        self.assertEqual(len(self.store), 0)


class WorkerTests(unittest.TestCase):
    def test_t12_invalid_interval(self):
        from mini_redis.expiration import ExpirationWorker
        for value, error in ((0, ValueError), (-1, ValueError),
                             (float("nan"), ValueError),
                             (float("inf"), ValueError),
                             (True, TypeError), ("0.1", TypeError)):
            with self.subTest(value=value):
                with self.assertRaises(error):
                    ExpirationWorker(MiniRedisStore(), interval_seconds=value)

    def test_t12_import_does_not_start_thread(self):
        with patch.object(threading.Thread, "start") as start:
            sys.modules.pop("mini_redis.expiration", None)
            importlib.import_module("mini_redis.expiration")
            start.assert_not_called()

    def test_t12_start_once_and_cleanup_without_requests(self):
        from mini_redis.expiration import ExpirationWorker
        clock = FakeClock()
        store = MiniRedisStore(clock_ns=clock)
        store.set("key", "expired", ttl_ms=1)
        clock.now = 1000000
        cleaned = threading.Event()
        original = store.cleanup

        def observed_cleanup():
            result = original()
            cleaned.set()
            return result

        with patch.object(store, "cleanup", observed_cleanup):
            worker = ExpirationWorker(store, interval_seconds=0.005)
            self.assertFalse(worker.is_running)
            try:
                worker.start()
                first = worker._thread
                worker.start()
                self.assertIs(worker._thread, first)
                self.assertTrue(cleaned.wait(2))
                self.assertEqual(len(store), 0)
            finally:
                worker.stop()
            self.assertFalse(worker.is_running)

    def test_t12_stop_wakes_wait_without_waiting_for_interval(self):
        from mini_redis.expiration import ExpirationWorker
        store = MiniRedisStore()
        worker = ExpirationWorker(store, interval_seconds=60)
        worker.start()
        stopper = threading.Thread(target=worker.stop, daemon=True)
        with store._lock:
            stopper.start()
            stopper.join(2)
            stopped_without_storage_lock = not stopper.is_alive()
        if stopper.is_alive():
            worker._stop.set()
            stopper.join(2)
        self.assertFalse(stopper.is_alive())
        self.assertTrue(stopped_without_storage_lock)
        self.assertFalse(worker.is_running)

    def test_t11_renewal_waits_for_atomic_check_and_delete(self):
        store = MiniRedisStore(clock_ns=lambda: 1000000)
        store.set("key", "old", ttl_ms=1)
        store._clock_ns = lambda: 2000000
        checked = threading.Event()
        release = threading.Event()
        attempted = threading.Event()
        finished = threading.Event()
        original_expired = store._expired
        real_lock = threading.Lock()
        errors = []
        results = []

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread().name == "renewal":
                    attempted.set()
                real_lock.acquire()

            def __exit__(self, *args):
                real_lock.release()

        store._lock = ObservedLock()

        def paused_expired(node):
            result = original_expired(node)
            checked.set()
            if not release.wait(2):
                raise TimeoutError("test did not release cleanup")
            return result

        def renew():
            try:
                store.set("key", "new", ttl_ms=10)
                finished.set()
            except BaseException as error:
                errors.append(error)

        def clean():
            try:
                results.append(store.cleanup())
            except BaseException as error:
                errors.append(error)

        with patch.object(store, "_expired", paused_expired):
            cleaner = threading.Thread(target=clean, daemon=True)
            updater = threading.Thread(target=renew, name="renewal", daemon=True)
            cleaner.start()
            try:
                self.assertTrue(checked.wait(2))
                updater.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.is_set())
            finally:
                release.set()
                cleaner.join(2)
                if updater.ident is not None:
                    updater.join(2)
            self.assertFalse(cleaner.is_alive())
            self.assertFalse(updater.is_alive())
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].deleted, 1)
        self.assertEqual(store.get("key"), "new")
        self.assertEqual(len(store), 1)


if __name__ == "__main__":
    unittest.main()
