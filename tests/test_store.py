"""Iter 02 contract tests. The store and private probe seams do not exist yet.

Provisional implementation seams: mini_redis.store.HashTableStore, _buckets,
_size, _hash(key), _insert(key, value), _rehash(), _replace(key, value).
Adapt the private probes to the real implementation; do not add public APIs for tests.
"""

import importlib
import json
import subprocess
import sys
import unittest
from unittest.mock import patch


MODULE = "mini_redis.store"
CLASS = "HashTableStore"


def store_class():
    try:
        return getattr(importlib.import_module(MODULE), CLASS)
    except (ModuleNotFoundError, AttributeError) as exc:
        raise AssertionError(
            f"Implementation missing: provide {MODULE}.{CLASS}, then adapt "
            "the documented provisional private test seams"
        ) from exc


class StoreContractTests(unittest.TestCase):
    def setUp(self):
        self.store = store_class()()

    def state(self):
        return (len(self.store._buckets), self.store._size,
                self.store.get("kept"))

    def collision(self):
        # Find a real collision under the initial 8-bucket layout, not a guessed pair.
        found = {}
        for i in range(100):
            key = f"collision-{i}"
            bucket = self.store._hash(key) % len(self.store._buckets)
            if bucket in found:
                return found[bucket], key
            found[bucket] = key
        self.fail("no initial-bucket collision found")

    def test_001_set_returns_none_and_gets_value(self):
        self.assertIsNone(self.store.set("k", "v"))
        self.assertEqual(self.store.get("k"), (True, "v"))

    def test_002_overwrite_does_not_resurrect_old_value(self):
        self.store.set("k", "old")
        self.assertIsNone(self.store.set("k", "new"))
        self.assertEqual(self.store.get("k"), (True, "new"))
        self.assertTrue(self.store.delete("k"))
        self.assertEqual(self.store.get("k"), (False, None))
        self.assertEqual(self.store._size, 0)

    def test_003_empty_value_exists(self):
        self.store.set("k", "")
        self.assertEqual(self.store.get("k"), (True, ""))
        self.assertIs(self.store.exists("k"), True)

    def test_004_missing_key(self):
        self.assertEqual(self.store.get("missing"), (False, None))
        self.assertIs(self.store.exists("missing"), False)

    def test_005_delete_once(self):
        self.store.set("k", "v")
        self.assertIs(self.store.delete("k"), True)
        self.assertEqual(self.store.get("k"), (False, None))
        self.assertIs(self.store.exists("k"), False)
        self.assertIs(self.store.delete("k"), False)

    def test_006_delete_preserves_other_key(self):
        self.store.set("a", "first")
        self.store.set("b", "second")
        self.assertTrue(self.store.delete("a"))
        self.assertEqual(self.store.get("b"), (True, "second"))
        self.assertTrue(self.store.exists("b"))

    def test_007_empty_key_rejected_for_every_operation(self):
        self.store.set("kept", "v")
        before = self.state()
        for operation in (lambda: self.store.set("", "v"),
                          lambda: self.store.get(""),
                          lambda: self.store.exists(""),
                          lambda: self.store.delete("")):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation()
            self.assertEqual(self.state(), before)

    def test_008_non_string_key_rejected_for_every_operation(self):
        self.store.set("kept", "v")
        before = self.state()
        for key in (None, 0, [], True):
            for operation in (lambda: self.store.set(key, "v"),
                              lambda: self.store.get(key),
                              lambda: self.store.exists(key),
                              lambda: self.store.delete(key)):
                with self.subTest(key=key, operation=operation), self.assertRaises(TypeError):
                    operation()
                self.assertEqual(self.state(), before)

    def test_009_non_string_value_rejected(self):
        self.store.set("kept", "v")
        before = self.state()
        for value in (None, 0, [], True):
            with self.subTest(value=value), self.assertRaises(TypeError):
                self.store.set("kept", value)
            self.assertEqual(self.state(), before)

    def test_010_missing_required_arguments(self):
        self.store.set("kept", "v")
        before = self.state()
        for operation in (self.store.set,
                          lambda: self.store.set("new"),
                          self.store.get, self.store.exists, self.store.delete):
            with self.subTest(operation=operation), self.assertRaises(TypeError):
                operation()
            self.assertEqual(self.state(), before)

    def test_011_key_validation_precedes_value_validation(self):
        with self.assertRaises(TypeError):
            self.store.set(None, 0)
        with self.assertRaises(ValueError):
            self.store.set("", 0)
        with self.assertRaises(TypeError):
            self.store.set("valid", 0)
        self.assertEqual(self.store._size, 0)

    def test_012_distinct_spelling_and_unicode_forms(self):
        keys = ("k", " k ", "K", "é", "e\u0301")
        for i, key in enumerate(keys):
            self.store.set(key, str(i))
        for i, key in enumerate(keys):
            self.assertEqual(self.store.get(key), (True, str(i)))
        self.assertEqual(self.store._size, len(keys))

    def test_013_colliding_keys_remain_distinct(self):
        a, b = self.collision()
        self.store.set(a, "first")
        self.store.set(b, "second")
        self.assertEqual(self.store.get(a), (True, "first"))
        self.assertEqual(self.store.get(b), (True, "second"))

    def test_014_collision_overwrite_and_delete_independent(self):
        a, b = self.collision()
        self.store.set(a, "old")
        self.store.set(b, "other")
        self.store.set(a, "new")
        self.assertEqual(self.store.get(a), (True, "new"))
        self.assertEqual(self.store.get(b), (True, "other"))
        self.assertTrue(self.store.delete(a))
        self.assertEqual(self.store.get(a), (False, None))
        self.assertEqual(self.store.get(b), (True, "other"))
        self.assertTrue(self.store.exists(b))
        self.assertEqual(self.store._size, 1)

    def test_015_load_factor_exactly_one_does_not_grow(self):
        self.assertEqual(len(self.store._buckets), 8)
        for i in range(8):
            self.store.set(str(i), str(i))
        self.assertEqual((self.store._size, len(self.store._buckets)), (8, 8))
        self.store.set("0", "overwritten")
        self.assertEqual((self.store._size, len(self.store._buckets)), (8, 8))
        self.assertEqual(self.store.get("0"), (True, "overwritten"))

    def test_016_ninth_new_key_grows_and_preserves_values(self):
        for i in range(9):
            self.store.set(str(i), str(i))
        self.assertEqual((self.store._size, len(self.store._buckets)), (9, 16))
        for i in range(9):
            self.assertEqual(self.store.get(str(i)), (True, str(i)))

    def test_017_repeated_growth_preserves_all_keys(self):
        for i in range(33):
            self.store.set(str(i), str(i))
        self.assertEqual((self.store._size, len(self.store._buckets)), (33, 64))
        for i in range(33):
            self.assertEqual(self.store.get(str(i)), (True, str(i)))

    def test_018_overwrite_and_delete_do_not_change_capacity(self):
        for i in range(9):
            self.store.set(str(i), str(i))
        self.store.set("0", "changed")
        self.assertEqual((self.store._size, len(self.store._buckets)), (9, 16))
        self.assertTrue(self.store.delete("0"))
        self.assertFalse(self.store.delete("absent"))
        self.assertEqual((self.store._size, len(self.store._buckets)), (8, 16))
        self.assertEqual(self.store.get("0"), (False, None))

    def test_019_instances_do_not_share_data(self):
        other = store_class()()
        self.store.set("k", "v")
        self.assertEqual(other.get("k"), (False, None))
        other.set("k", "other")
        self.assertEqual(self.store.get("k"), (True, "v"))

    def test_020_hash_is_deterministic_across_processes(self):
        keys = ("prefix-A", "prefix-B")
        local = [self.store._hash(key) for key in keys]
        script = ("from mini_redis.store import HashTableStore; "
                  "import json; s=HashTableStore(); "
                  "print(json.dumps([s._hash(k) for k in " + repr(keys) + "]))")
        remote = subprocess.check_output([sys.executable, "-c", script], text=True)
        self.assertEqual(json.loads(remote), local)

    def test_021_failed_non_growing_insert_preserves_state(self):
        self.store.set("kept", "v")
        before = self.state()
        original = self.store._insert

        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected")

        with patch.object(self.store, "_insert", side_effect=fail_after_insert):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.store.set("new", "v")
        self.assertEqual(self.state(), before)
        self.assertEqual(self.store.get("new"), (False, None))
        self.store.set("later", "ok")
        self.assertEqual(self.store.get("later"), (True, "ok"))

    def test_022_failed_rehash_preserves_structure_and_use(self):
        for i in range(8):
            self.store.set(str(i), str(i))
        original = self.store._rehash

        def fail_after_rehash():
            original()
            raise RuntimeError("injected")

        with patch.object(self.store, "_rehash", side_effect=fail_after_rehash):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.store.set("new", "v")
        self.assertEqual((self.store._size, len(self.store._buckets)), (8, 8))
        self.assertEqual(self.store.get("new"), (False, None))
        for i in range(8):
            self.assertEqual(self.store.get(str(i)), (True, str(i)))
        self.store.set("later", "ok")
        self.assertEqual(self.store.get("later"), (True, "ok"))

    def test_023_memory_error_during_insert_and_growth(self):
        self.store.set("kept", "v")
        before = self.state()
        original = self.store._insert

        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise MemoryError("injected")

        with patch.object(self.store, "_insert", side_effect=fail_after_insert):
            with self.assertRaises(MemoryError):
                self.store.set("new", "v")
        self.assertEqual(self.state(), before)
        self.assertEqual(self.store.get("new"), (False, None))
        for i in range(7):
            self.store.set(str(i), str(i))
        before = (self.store._size, len(self.store._buckets))
        with patch.object(self.store, "_rehash", side_effect=MemoryError("injected")):
            with self.assertRaises(MemoryError):
                self.store.set("new", "v")
        self.assertEqual((self.store._size, len(self.store._buckets)), before)
        self.assertEqual(self.store.get("new"), (False, None))
        self.assertEqual(self.store.get("kept"), (True, "v"))
        for i in range(7):
            self.assertEqual(self.store.get(str(i)), (True, str(i)))
        self.store.set("later", "ok")
        self.assertEqual(self.store.get("later"), (True, "ok"))

    def test_024_failed_overwrite_preserves_old_value(self):
        self.store.set("kept", "old")
        before = self.state()
        original = self.store._replace

        def fail_after_replace(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected")

        with patch.object(self.store, "_replace", side_effect=fail_after_replace):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.store.set("kept", "new")
        self.assertEqual(self.state(), before)
        self.store.set("kept", "later")
        self.assertEqual(self.store.get("kept"), (True, "later"))


if __name__ == "__main__":
    unittest.main()
