import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, get_ident

from mini_redis.store import MiniRedisStore


class ConcurrencyTests(unittest.TestCase):
    def test_t13_new_writes_preserved_across_resize(self):
        store = MiniRedisStore()
        start = Barrier(4)

        def save(worker):
            start.wait(timeout=3)
            for slot in range(10):
                store.set(f"{worker}:{slot}", f"value:{worker}:{slot}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = [pool.submit(save, worker) for worker in range(4)]
            for future in pending:
                future.result(timeout=3)
        self.assertEqual(len(store), 40)
        self.assertEqual(len(store._buckets), 64)
        for worker in range(4):
            for slot in range(10):
                self.assertEqual(store.get(f"{worker}:{slot}"),
                                 f"value:{worker}:{slot}")

    def test_t13_distinct_keys_wait_then_store_read_delete(self):
        store = MiniRedisStore()
        actual_lock = store._lock
        monitor = Lock()
        all_waiting = Event()
        attempted = entered = active = maximum_active = 0
        callers = set()

        class ObservedLock:
            def __enter__(self):
                nonlocal attempted, entered, active, maximum_active
                with monitor:
                    attempted += 1
                    callers.add(get_ident())
                    if attempted == 4:
                        all_waiting.set()
                actual_lock.acquire()
                with monitor:
                    entered += 1
                    active += 1
                    maximum_active = max(maximum_active, active)

            def __exit__(self, *args):
                nonlocal active
                with monitor:
                    active -= 1
                actual_lock.release()

        store._lock = ObservedLock()
        start = Barrier(4)

        def save(worker):
            start.wait(timeout=3)
            for slot in range(2):
                store.set(f"{worker}:{slot}", f"value:{worker}:{slot}")

        def read(worker):
            return [store.get(f"{worker}:{slot}") for slot in range(2)]

        def delete(worker):
            return store.delete(f"{worker}:0")

        with ThreadPoolExecutor(max_workers=4) as pool:
            # Hold the real lock only in the test to make waiting observable.
            with actual_lock:
                pending = [pool.submit(save, worker) for worker in range(4)]
                self.assertTrue(all_waiting.wait(3))
                self.assertTrue(all(not future.done() for future in pending))
                self.assertEqual(entered, 0)
            for future in pending:
                future.result(timeout=3)
            self.assertEqual(len(callers), 4)
            self.assertEqual(len(store), 8)

            pending = [pool.submit(read, worker) for worker in range(4)]
            for worker, future in enumerate(pending):
                self.assertEqual(future.result(timeout=3),
                                 [f"value:{worker}:0", f"value:{worker}:1"])

            pending = [pool.submit(delete, worker) for worker in range(4)]
            for future in pending:
                self.assertIs(future.result(timeout=3), True)
            self.assertEqual(len(store), 4)

            pending = [pool.submit(read, worker) for worker in range(4)]
            for worker, future in enumerate(pending):
                self.assertEqual(future.result(timeout=3),
                                 [None, f"value:{worker}:1"])

        # 8 writes + 8 reads + 4 deletes + 8 final reads + 2 length reads.
        self.assertEqual(entered, 30)
        self.assertEqual(active, 0)
        self.assertEqual(maximum_active, 1)


if __name__ == "__main__":
    unittest.main()
