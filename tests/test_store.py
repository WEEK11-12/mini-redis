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


class InputAndResizeTests(unittest.TestCase):
    def setUp(self):
        self.store = MiniRedisStore()

    def test_t07_empty_and_original_text(self):
        pairs = (("", ""), ("name", "plain"), (" name ", " spaced "),
                 ("이름\n", "한글\n값"))
        for key, value in pairs:
            self.store.set(key, value)
        for key, value in pairs:
            self.assertEqual(self.store.get(key), value)
        self.assertEqual(len(self.store), len(pairs))

    def test_t07_non_string_keys_rejected_in_all_operations(self):
        self.store.set("keep", "original")
        for key in (None, 123, True, b"bytes", [], {}):
            for operation in ("set", "get", "delete"):
                with self.subTest(key=repr(key), operation=operation):
                    with self.assertRaises(TypeError):
                        if operation == "set":
                            self.store.set(key, "value")
                        else:
                            getattr(self.store, operation)(key)
                    self.assertEqual(self.store.get("keep"), "original")
                    self.assertEqual(len(self.store), 1)

    def test_t07_non_string_values_preserve_existing_data(self):
        self.store.set("keep", "original")
        for value in (None, 123, True, b"bytes", [], {}):
            with self.subTest(value=repr(value)):
                with self.assertRaises(TypeError):
                    self.store.set("keep", value)
                self.assertEqual(self.store.get("keep"), "original")
                self.assertEqual(len(self.store), 1)

    def test_t07_key_utf8_byte_boundary(self):
        accepted = "가" * 341 + "a"
        rejected = accepted + "b"
        self.assertEqual(len(accepted.encode("utf-8")), 1024)
        self.store.set(accepted, "limit")
        for operation in ("set", "get", "delete"):
            with self.subTest(operation=operation):
                with self.assertRaises(ValueError):
                    if operation == "set":
                        self.store.set(rejected, "too long")
                    else:
                        getattr(self.store, operation)(rejected)
                self.assertEqual(self.store.get(accepted), "limit")
                self.assertEqual(len(self.store), 1)

    def test_t07_value_utf8_byte_boundary(self):
        accepted = "가" * (1048576 // 3) + "a"
        self.assertEqual(len(accepted.encode("utf-8")), 1048576)
        self.store.set("keep", accepted)
        with self.assertRaises(ValueError):
            self.store.set("keep", accepted + "b")
        self.assertEqual(self.store.get("keep"), accepted)
        self.assertEqual(len(self.store), 1)

    def test_t08_known_fnv1a_64_vectors(self):
        # IETF draft-eastlake-fnv-25, section 6.2, Test64 FNV64svalues.
        vectors = ((b"", 0xCBF29CE484222325),
                   (b"a", 0xAF63DC4C8601EC8C),
                   (b"foobar", 0x85944171F73967E8),
                   (b"Hello!\x01\xff\xed", 0xBD51EA7094EE6FA1))
        for data, expected in vectors:
            with self.subTest(data=data):
                self.assertEqual(fnv1a_64(data), expected)

    def test_t09_thirteenth_new_key_resizes_and_preserves_values(self):
        for index in range(12):
            self.store.set(str(index), "value:" + str(index))
        self.assertEqual(len(self.store._buckets), 16)
        self.store.set("12", "value:12")
        self.assertEqual(len(self.store._buckets), 32)
        self.assertEqual(len(self.store), 13)
        for index in range(13):
            self.assertEqual(self.store.get(str(index)), "value:" + str(index))

    def test_t09_overwrite_at_threshold_does_not_resize(self):
        for index in range(12):
            self.store.set(str(index), "old")
        self.store.set("0", "new")
        self.assertEqual(len(self.store._buckets), 16)
        self.assertEqual(len(self.store), 12)
        self.assertEqual(self.store.get("0"), "new")

    def test_t09_invalid_insert_does_not_trigger_resize(self):
        for index in range(12):
            self.store.set(str(index), "old")
        with self.assertRaises(ValueError):
            self.store.set("invalid", "x" * 1048577)
        self.assertEqual(len(self.store._buckets), 16)
        self.assertEqual(len(self.store), 12)
        self.assertIsNone(self.store.get("invalid"))
        for index in range(12):
            self.assertEqual(self.store.get(str(index)), "old")

    def test_t09_repeated_resize_then_update_and_delete(self):
        for index in range(65):
            self.store.set(str(index), "value:" + str(index))
        self.assertEqual(len(self.store._buckets), 128)
        self.assertEqual(len(self.store), 65)
        for index in range(65):
            self.assertEqual(self.store.get(str(index)), "value:" + str(index))
            self.store.set(str(index), "updated:" + str(index))
        self.assertEqual(len(self.store), 65)
        for index in range(65):
            self.assertEqual(self.store.get(str(index)), "updated:" + str(index))
            self.assertIs(self.store.delete(str(index)), True)
        self.assertEqual(len(self.store), 0)
        for index in range(65):
            self.assertIsNone(self.store.get(str(index)))


if __name__ == "__main__":
    unittest.main()
