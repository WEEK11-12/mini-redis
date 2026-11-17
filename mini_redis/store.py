"""Sequential, in-memory hash table for string keys and values."""

import time


class HashTableStore:
    """Owns separate chains of entries and their optional monotonic deadlines."""

    def __init__(self, clock=None):
        self._buckets = [[] for _ in range(8)]
        self._size = 0
        self._clock = clock if clock is not None else time.monotonic_ns

    @staticmethod
    def _validate_key(key):
        if not isinstance(key, str):
            raise TypeError("key must be a string")
        if not key:
            raise ValueError("key must not be empty")

    @staticmethod
    def _hash(key):
        # 64-bit polynomial hash over Unicode code points, independent of hash randomization.
        result = 0
        for char in key:
            result = (result * 31 + ord(char)) & 0xFFFFFFFFFFFFFFFF
        return result

    def _locate(self, key):
        bucket_index = self._hash(key) % len(self._buckets)
        for entry_index, (stored_key, _, _) in enumerate(self._buckets[bucket_index]):
            if stored_key == key:
                return bucket_index, entry_index
        return bucket_index, None

    @staticmethod
    def _insert(chain, key, value):
        chain.append((key, value, None))

    @staticmethod
    def _replace(bucket, entry_index, key, value, deadline=None):
        bucket[entry_index] = (key, value, deadline)

    def _rehash(self):
        buckets = [[] for _ in range(len(self._buckets) * 2)]
        for chain in self._buckets:
            for key, value, deadline in chain:
                index = self._hash(key) % len(buckets)
                buckets[index].append((key, value, deadline))
        return buckets

    def _remove_expired(self, bucket_index, entry_index):
        chain = self._buckets[bucket_index].copy()
        del chain[entry_index]
        return chain

    def _active_index(self, bucket_index, entry_index, now=None):
        if entry_index is None:
            return None
        deadline = self._buckets[bucket_index][entry_index][2]
        if deadline is not None and (self._clock() if now is None else now) >= deadline:
            chain = self._remove_expired(bucket_index, entry_index)
            new_size = self._size - 1
            self._buckets[bucket_index] = chain
            self._size = new_size
            return None
        return entry_index

    def set(self, key: str, value: str) -> None:
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        bucket_index, entry_index = self._locate(key)
        if entry_index is not None:
            chain = self._buckets[bucket_index].copy()
            self._replace(chain, entry_index, key, value)
            self._buckets[bucket_index] = chain
            return

        new_size = self._size + 1
        if new_size > len(self._buckets):
            buckets = self._rehash()
            chain = buckets[self._hash(key) % len(buckets)]
            self._insert(chain, key, value)
            self._buckets = buckets
        else:
            chain = self._buckets[bucket_index].copy()
            self._insert(chain, key, value)
            self._buckets[bucket_index] = chain
        self._size = new_size

    def get(self, key: str) -> tuple[bool, str | None]:
        self._validate_key(key)
        bucket_index, entry_index = self._locate(key)
        entry_index = self._active_index(bucket_index, entry_index)
        if entry_index is None:
            return False, None
        return True, self._buckets[bucket_index][entry_index][1]

    def exists(self, key: str) -> bool:
        self._validate_key(key)
        bucket_index, entry_index = self._locate(key)
        return self._active_index(bucket_index, entry_index) is not None

    def delete(self, key: str) -> bool:
        self._validate_key(key)
        bucket_index, entry_index = self._locate(key)
        entry_index = self._active_index(bucket_index, entry_index)
        if entry_index is None:
            return False
        chain = self._buckets[bucket_index].copy()
        del chain[entry_index]
        new_size = self._size - 1
        self._buckets[bucket_index] = chain
        self._size = new_size
        return True

    def set_ttl(self, key: str, ttl_seconds: int) -> bool:
        self._validate_key(key)
        if type(ttl_seconds) is not int:
            raise TypeError("ttl must be an integer")
        if ttl_seconds <= 0:
            raise ValueError("ttl must be positive")
        bucket_index, entry_index = self._locate(key)
        if entry_index is None:
            return False
        now = self._clock()
        entry_index = self._active_index(bucket_index, entry_index, now)
        if entry_index is None:
            return False
        deadline = now + ttl_seconds * 1_000_000_000
        stored_key, value, _ = self._buckets[bucket_index][entry_index]
        chain = self._buckets[bucket_index].copy()
        self._replace(chain, entry_index, stored_key, value, deadline)
        self._buckets[bucket_index] = chain
        return True

    def clear_ttl(self, key: str) -> bool:
        self._validate_key(key)
        bucket_index, entry_index = self._locate(key)
        entry_index = self._active_index(bucket_index, entry_index)
        if entry_index is None:
            return False
        stored_key, value, deadline = self._buckets[bucket_index][entry_index]
        if deadline is None:
            return False
        chain = self._buckets[bucket_index].copy()
        self._replace(chain, entry_index, stored_key, value)
        self._buckets[bucket_index] = chain
        return True

    def sweep_expired(self) -> int:
        removed = 0
        now = self._clock()
        for bucket_index in range(len(self._buckets)):
            entry_index = 0
            while entry_index < len(self._buckets[bucket_index]):
                deadline = self._buckets[bucket_index][entry_index][2]
                if deadline is not None and now >= deadline:
                    chain = self._remove_expired(bucket_index, entry_index)
                    new_size = self._size - 1
                    self._buckets[bucket_index] = chain
                    self._size = new_size
                    removed += 1
                else:
                    entry_index += 1
        return removed
