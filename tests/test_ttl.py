import unittest

from mini_redis.store import MiniRedisStore


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class TTLTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = MiniRedisStore(clock_ns=self.clock)

    def test_t10_exact_expiration_boundary(self):
        for now, expected in ((999999, "value"), (1000000, None),
                              (1000001, None)):
            with self.subTest(now=now):
                clock = FakeClock()
                store = MiniRedisStore(clock_ns=clock)
                store.set("key", "value", ttl_ms=1)
                clock.now = now
                self.assertEqual(store.get("key"), expected)
                self.assertEqual(len(store), 1 if expected is not None else 0)

    def test_t10_omitted_ttl_never_expires(self):
        self.store.set("key", "value")
        self.clock.now = 10 ** 100
        self.assertEqual(self.store.get("key"), "value")

    def test_t10_overwrite_removes_previous_ttl(self):
        self.store.set("key", "old", ttl_ms=1)
        self.store.set("key", "new")
        self.clock.now = 1000000
        self.assertEqual(self.store.get("key"), "new")
        self.assertEqual(len(self.store), 1)

    def test_t10_new_ttl_starts_at_new_write(self):
        self.store.set("key", "old", ttl_ms=1)
        self.clock.now = 500000
        self.store.set("key", "new", ttl_ms=2)
        self.clock.now = 1000000
        self.assertEqual(self.store.get("key"), "new")
        self.clock.now = 2500000
        self.assertIsNone(self.store.get("key"))

    def test_t10_invalid_ttl_preserves_value_and_deadline(self):
        cases = ((None, TypeError), (True, TypeError), (False, TypeError),
                 ("1", TypeError), (1.0, TypeError), ([], TypeError),
                 (0, ValueError), (-1, ValueError))
        for ttl, error in cases:
            with self.subTest(ttl=ttl):
                clock = FakeClock()
                store = MiniRedisStore(clock_ns=clock)
                store.set("key", "old", ttl_ms=1)
                clock.now = 500000
                with self.assertRaises(error):
                    store.set("key", "bad", ttl_ms=ttl)
                self.assertEqual(store.get("key"), "old")
                self.assertEqual(len(store), 1)
                clock.now = 1000000
                self.assertIsNone(store.get("key"))

    def test_t10_expired_delete_is_false_but_removes_node(self):
        for removed in ("a", "q", "A"):
            with self.subTest(removed=removed):
                clock = FakeClock()
                store = MiniRedisStore(clock_ns=clock)
                for key in ("a", "q", "A"):
                    if key == removed:
                        store.set(key, key, ttl_ms=1)
                    else:
                        store.set(key, key)
                clock.now = 1000000
                self.assertEqual(len(store), 3)
                self.assertIs(store.delete(removed), False)
                self.assertEqual(len(store), 2)
                self.assertIsNone(store.get(removed))
                for key in ("a", "q", "A"):
                    if key != removed:
                        self.assertEqual(store.get(key), key)

    def test_t10_live_delete_is_true(self):
        self.store.set("key", "value", ttl_ms=1)
        self.assertIs(self.store.delete("key"), True)
        self.assertEqual(len(self.store), 0)

    def test_t10_len_counts_expired_nodes_until_access(self):
        self.store.set("key", "value", ttl_ms=1)
        self.clock.now = 1000000
        self.assertEqual(len(self.store), 1)
        self.assertIsNone(self.store.get("key"))
        self.assertEqual(len(self.store), 0)

    def test_t10_reinsert_expired_key_and_preserve_ttl_during_resize(self):
        self.store.set("key", "old", ttl_ms=1)
        self.clock.now = 1000000
        self.store.set("key", "new", ttl_ms=2)
        for index in range(12):
            self.store.set(str(index), "keep")
        self.assertEqual(len(self.store), 13)
        self.assertEqual(len(self.store._buckets), 32)
        self.clock.now = 2999999
        self.assertEqual(self.store.get("key"), "new")
        self.clock.now = 3000000
        self.assertIsNone(self.store.get("key"))
        for index in range(12):
            self.assertEqual(self.store.get(str(index)), "keep")

    def test_t10_arbitrarily_large_positive_ttl(self):
        ttl = 10 ** 100
        self.store.set("key", "value", ttl_ms=ttl)
        self.clock.now = ttl * 1000000 - 1
        self.assertEqual(self.store.get("key"), "value")
        self.clock.now += 1
        self.assertIsNone(self.store.get("key"))


if __name__ == "__main__":
    unittest.main()
