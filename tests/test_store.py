import unittest

from mini_redis.store import MiniRedisStore, fnv1a_64


class StoreTests(unittest.TestCase):
    COLLIDING_KEYS = ("a", "q", "A")

    def setUp(self):
        self.store = MiniRedisStore()

    def populate_collision_chain(self):
        # Independent low-nibble calculation: ((5 XOR 1) * 3) % 16 = 12.
        for key in self.COLLIDING_KEYS:
            self.assertEqual(fnv1a_64(key.encode("utf-8")) % 16, 12)
            self.store.set(key, "value:" + key)

    def test_t01_save_and_get(self):
        self.store.set("name", "JYE")
        self.assertEqual(self.store.get("name"), "JYE")
        self.assertEqual(len(self.store), 1)

    def test_t02_overwrite_preserves_count(self):
        self.store.set("name", "old")
        self.store.set("name", "new")
        self.assertEqual(self.store.get("name"), "new")
        self.assertEqual(len(self.store), 1)

    def test_t03_delete_then_get(self):
        self.store.set("name", "JYE")
        self.assertIs(self.store.delete("name"), True)
        self.assertIsNone(self.store.get("name"))
        self.assertEqual(len(self.store), 0)

    def test_t04_missing_key_preserves_existing_data(self):
        self.store.set("keep", "value")
        self.assertIsNone(self.store.get("missing"))
        self.assertIs(self.store.delete("missing"), False)
        self.assertEqual(self.store.get("keep"), "value")
        self.assertEqual(len(self.store), 1)

    def test_t05_collisions_remain_distinct(self):
        self.populate_collision_chain()
        for key in self.COLLIDING_KEYS:
            self.assertEqual(self.store.get(key), "value:" + key)
        self.store.set("q", "updated")
        self.assertEqual(self.store.get("q"), "updated")
        self.assertEqual(self.store.get("a"), "value:a")
        self.assertEqual(self.store.get("A"), "value:A")
        self.assertEqual(len(self.store), 3)

    def test_t06_delete_each_position_in_collision_chain(self):
        # Fresh chains cover all three positions without fixing insertion order.
        for removed in self.COLLIDING_KEYS:
            with self.subTest(removed=removed):
                self.store = MiniRedisStore()
                self.populate_collision_chain()
                self.assertIs(self.store.delete(removed), True)
                self.assertIsNone(self.store.get(removed))
                for key in self.COLLIDING_KEYS:
                    if key != removed:
                        self.assertEqual(self.store.get(key), "value:" + key)
                self.assertEqual(len(self.store), 2)
                self.assertIs(self.store.delete(removed), False)
                self.assertEqual(len(self.store), 2)


if __name__ == "__main__":
    unittest.main()
