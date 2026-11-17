"""Sequential, in-memory hash table for string keys and values."""


class HashTableStore:
    """Owns separate chains of entries; no HTTP, expiry, or concurrency policy."""

    def __init__(self):
        self._buckets = [[] for _ in range(8)]
        self._size = 0

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
        for entry_index, (stored_key, _) in enumerate(self._buckets[bucket_index]):
            if stored_key == key:
                return bucket_index, entry_index
        return bucket_index, None

    @staticmethod
    def _insert(chain, key, value):
        chain.append((key, value))

    @staticmethod
    def _replace(bucket, entry_index, key, value):
        bucket[entry_index] = (key, value)

    def _rehash(self):
        buckets = [[] for _ in range(len(self._buckets) * 2)]
        for chain in self._buckets:
            for key, value in chain:
                self._insert(buckets[self._hash(key) % len(buckets)], key, value)
        return buckets

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
        if entry_index is None:
            return False, None
        return True, self._buckets[bucket_index][entry_index][1]

    def exists(self, key: str) -> bool:
        self._validate_key(key)
        _, entry_index = self._locate(key)
        return entry_index is not None

    def delete(self, key: str) -> bool:
        self._validate_key(key)
        bucket_index, entry_index = self._locate(key)
        if entry_index is None:
            return False
        del self._buckets[bucket_index][entry_index]
        self._size -= 1
        return True
