import unittest

from mini_redis.store import MiniRedisStore


class CleanupFocusTest(unittest.TestCase):
    def test_resume_then_remove_only_expired_middle_node(self):
        now = [0]
        store = MiniRedisStore(clock_ns=lambda: now[0])
        store.set("a", "tail")
        store.set("q", "expired-middle", ttl_ms=1)
        store.set("A", "head")
        # The three keys share bucket 12: A -> q -> a.
        first = store.cleanup(key_limit=1)
        self.assertEqual(first.keys_checked, 1)
        self.assertEqual(first.deleted, 0)
        self.assertEqual(store._scan_bucket, 12)
        self.assertEqual(store._scan_node.key, "q")
        self.assertEqual(store._scan_previous.key, "A")

        now[0] = 1000000
        second = store.cleanup(key_limit=1)
        self.assertEqual(second.keys_checked, 1)
        self.assertEqual(second.deleted, 1)
        self.assertEqual(store._scan_node.key, "a")
        self.assertEqual(store._scan_previous.key, "A")
        self.assertEqual(store._buckets[12].key, "A")
        self.assertEqual(store._buckets[12].next.key, "a")
        self.assertEqual(len(store), 2)
        self.assertEqual(store.get("A"), "head")
        self.assertEqual(store.get("a"), "tail")

        third = store.cleanup(key_limit=1)
        self.assertEqual(third.keys_checked, 1)
        self.assertEqual(third.deleted, 0)
        self.assertEqual(store.get("A"), "head")
        self.assertEqual(store.get("a"), "tail")


if __name__ == "__main__":
    unittest.main()
