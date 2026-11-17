"""Iteration 04 store contract tests, implementation-first (expected RED).

Provisional seam: HashTableStore(clock=<callable returning integer monotonic ns>).
The design specifies an injectable clock, not its constructor keyword. Failure
probes using private _replace/_remove_expired must be adapted to real mutation
boundaries; they are not product API requirements. No product implementation is
added here.
"""
import unittest
from unittest.mock import patch

from mini_redis.store import HashTableStore


SECOND = 1_000_000_000


class Clock:
    def __init__(self, now=100 * SECOND):
        self.now = now
        self.fail = False

    def __call__(self):
        if self.fail:
            raise RuntimeError("clock")
        return self.now


class ExpirationStoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        try:
            self.store = HashTableStore(clock=self.clock)
        except TypeError as exc:
            raise AssertionError("Implementation missing: injectable monotonic-ns store clock (provisional clock keyword)") from exc

    def put_ttl(self, key="k", value="old", seconds=2):
        self.store.set(key, value)
        self.assertIs(self.store.set_ttl(key, seconds), True)
        return self.clock.now + seconds * SECOND

    def physical(self):
        return (self.store._size, len(self.store._buckets),
                tuple(tuple(chain) for chain in self.store._buckets))

    def test_u_001_no_ttl_and_empty_value(self):
        self.store.set("k", "")
        self.store.set("other", "data")
        self.clock.now += 1000 * SECOND
        self.assertEqual(self.store.get("k"), (True, ""))
        self.assertTrue(self.store.exists("k"))
        self.assertEqual(self.store.get("other"), (True, "data"))

    def test_u_002_exact_expiration_boundary_and_lazy_removal(self):
        for offset, found in ((-1, True), (0, False), (1, False)):
            for operation in ("get", "exists", "delete"):
                with self.subTest(offset=offset, operation=operation):
                    clock = Clock()
                    store = HashTableStore(clock=clock)
                    store.set("k", "")
                    self.assertTrue(store.set_ttl("k", 2))
                    clock.now += 2 * SECOND + offset
                    result = getattr(store, operation)("k")
                    expected = (found, "") if operation == "get" and found else (False, None) if operation == "get" else found
                    self.assertEqual(result, expected)
                    self.assertEqual(store._size, int(found and operation != "delete"))
                    self.assertEqual(store.get("k"), (False, None) if not found or operation == "delete" else (True, ""))

    def test_u_003_ttl_refresh_uses_new_clock_not_old_deadline(self):
        old = self.put_ttl()
        self.clock.now += SECOND
        new = self.clock.now + 2 * SECOND
        self.assertTrue(self.store.set_ttl("k", 2))
        self.clock.now = old + 1
        self.assertEqual(self.store.get("k"), (True, "old"))
        self.clock.now = new - 1
        self.assertTrue(self.store.exists("k"))
        self.clock.now = new
        self.assertEqual(self.store.get("k"), (False, None))

    def test_u_004_overwrite_and_expired_reinsert_clear_old_ttl(self):
        old = self.put_ttl()
        self.store.set("k", "")
        self.clock.now = old + 1
        self.assertEqual(self.store.get("k"), (True, ""))
        self.assertEqual(self.store._size, 1)
        old = self.put_ttl(value="stale")
        self.clock.now = old + 1
        self.store.set("k", "new")
        self.clock.now += 100 * SECOND
        self.assertEqual(self.store.get("k"), (True, "new"))
        self.assertEqual(self.store._size, 1)

    def test_u_005_clear_ttl_is_idempotent_and_never_revives_expired(self):
        old = self.put_ttl()
        self.assertTrue(self.store.clear_ttl("k"))
        self.assertFalse(self.store.clear_ttl("k"))
        self.clock.now = old + 1
        self.assertEqual(self.store.get("k"), (True, "old"))
        self.store.set("plain", "v")
        self.assertFalse(self.store.clear_ttl("plain"))
        self.assertFalse(self.store.clear_ttl("missing"))
        old = self.put_ttl("expired", "gone")
        self.clock.now = old
        self.assertFalse(self.store.clear_ttl("expired"))
        self.assertEqual(self.store.get("expired"), (False, None))

    def test_u_006_invalid_ttl_or_key_preserves_value_and_deadline(self):
        deadline = self.put_ttl()
        for value, error in (("1", TypeError), (1.5, TypeError), (True, TypeError),
                             (None, TypeError), (0, ValueError), (-1, ValueError)):
            with self.subTest(value=value), self.assertRaises(error):
                self.store.set_ttl("k", value)
        for key, error in ((None, TypeError), ("", ValueError)):
            for operation in (lambda: self.store.set_ttl(key, 1), lambda: self.store.clear_ttl(key)):
                with self.subTest(key=key), self.assertRaises(error):
                    operation()
        self.assertEqual(self.store._size, 1)
        self.assertEqual(self.store.get("k"), (True, "old"))
        self.clock.now = deadline
        self.assertEqual(self.store.get("k"), (False, None))

    def test_u_007_large_integer_deadline_is_exact(self):
        for seconds in (2**53 + 1, 10**5000 + 1):
            with self.subTest(seconds=seconds):
                clock = Clock()
                store = HashTableStore(clock=clock)
                store.set("k", "v")
                start = clock.now
                self.assertTrue(store.set_ttl("k", seconds))
                clock.now = start + seconds * SECOND - 1
                self.assertEqual(store.get("k"), (True, "v"))
                clock.now += 1
                self.assertEqual(store.get("k"), (False, None))

    def test_u_008_delete_does_not_revive_old_value_or_affect_other_key(self):
        old = self.put_ttl()
        self.store.set("other", "safe")
        self.assertTrue(self.store.delete("k"))
        self.assertEqual(self.store.get("k"), (False, None))
        self.assertFalse(self.store.exists("k"))
        self.assertFalse(self.store.delete("k"))
        self.store.set("k", "new")
        self.clock.now = old + 1
        self.assertEqual(self.store.get("k"), (True, "new"))
        self.assertEqual(self.store.get("other"), (True, "safe"))

    def test_u_009_sweep_removes_unaccessed_expired_only(self):
        self.put_ttl("a")
        self.put_ttl("b")
        self.put_ttl("live", seconds=4)
        self.store.set("plain", "v")
        capacity = len(self.store._buckets)
        self.assertEqual(self.store._size, 4)
        self.clock.now += 2 * SECOND
        self.assertEqual(self.store._size, 4)
        self.assertEqual(self.store.sweep_expired(), 2)
        self.assertEqual(self.store.sweep_expired(), 0)
        self.assertEqual(self.store._size, sum(map(len, self.store._buckets)))
        self.assertEqual(self.store._size, 2)
        self.assertEqual(len(self.store._buckets), capacity)
        self.assertEqual(self.store.get("live"), (True, "old"))
        self.assertEqual(self.store.get("plain"), (True, "v"))

    def test_u_010_failed_set_and_ttl_changes_preserve_physical_state(self):
        deadline = self.put_ttl()
        before = self.physical()
        original = self.store._replace
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise MemoryError("injected")
        # Provisional mutation seam: adapt if TTL operations use another commit point.
        for action in (lambda: self.store.set("k", "new"),
                       lambda: self.store.set_ttl("k", 5),
                       lambda: self.store.clear_ttl("k")):
            with self.subTest(action=action), patch.object(self.store, "_replace", side_effect=fail):
                with self.assertRaises(MemoryError):
                    action()
            self.assertEqual(self.physical(), before)
            self.assertEqual(self.store.get("k"), (True, "old"))
        self.clock.now = deadline
        self.assertEqual(self.store.get("k"), (False, None))

    def test_u_011_failed_expired_removal_is_not_a_hit_or_delete(self):
        deadline = self.put_ttl()
        self.clock.now = deadline
        before = self.physical()
        # Provisional private seam: inject after a candidate removal, before commit.
        original = self.store._remove_expired
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected")
        for operation in (lambda: self.store.get("k"), lambda: self.store.exists("k"),
                          lambda: self.store.delete("k"), lambda: self.store.set_ttl("k", 1),
                          lambda: self.store.clear_ttl("k")):
            with self.subTest(operation=operation), patch.object(self.store, "_remove_expired", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    operation()
            self.assertEqual(self.physical(), before)
        self.assertEqual(self.store.get("k"), (False, None))

    def test_u_012_sweep_failure_keeps_failed_key_and_retries(self):
        self.put_ttl("a")
        self.put_ttl("b")
        self.clock.now += 2 * SECOND
        original = self.store._remove_expired
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected")
            return original(*args, **kwargs)
        # Provisional seam/order: inject on second actual expired-key removal.
        with patch.object(self.store, "_remove_expired", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.store.sweep_expired()
        self.assertEqual(calls, 2)
        self.assertEqual(self.store._size, sum(map(len, self.store._buckets)))
        self.assertEqual(self.store._size, 1)
        self.assertEqual(self.store.sweep_expired(), 1)
        self.assertEqual(self.store.get("a"), (False, None))
        self.assertEqual(self.store.get("b"), (False, None))

    def test_u_013_clock_failure_propagates_without_guessing(self):
        self.put_ttl()
        before = self.physical()
        self.clock.fail = True
        try:
            for operation in (lambda: self.store.set_ttl("k", 3), lambda: self.store.get("k"),
                              lambda: self.store.exists("k"), lambda: self.store.delete("k"),
                              lambda: self.store.clear_ttl("k"), lambda: self.store.sweep_expired()):
                with self.subTest(operation=operation), self.assertRaisesRegex(RuntimeError, "clock"):
                    operation()
                self.assertEqual(self.physical(), before)
        finally:
            self.clock.fail = False
        self.assertEqual(self.store.get("k"), (True, "old"))

    def test_u_014_physical_load_count_and_no_shrink(self):
        for i in range(8):
            self.put_ttl(str(i))
        self.assertEqual((self.store._size, len(self.store._buckets)), (8, 8))
        self.clock.now += 2 * SECOND
        self.store.set("new", "v")
        self.assertEqual((self.store._size, len(self.store._buckets)), (9, 16))
        self.assertEqual(self.store.sweep_expired(), 8)
        self.assertEqual((self.store._size, len(self.store._buckets)), (1, 16))
        self.assertEqual(self.store._size, sum(map(len, self.store._buckets)))


if __name__ == "__main__":
    unittest.main()
