"""U1: locked, string key/value storage with separate chaining."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


def fnv1a_64(data: bytes) -> int:
    result = 14695981039346656037
    for byte in data:
        result = ((result ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return result


@dataclass(slots=True)
class _Node:
    key: str
    value: str
    next: _Node | None = None


class MiniRedisStore:
    def __init__(self) -> None:
        # shortcut: fixed 16 buckets in U1; add the agreed resize policy in U2.
        self._buckets: list[_Node | None] = [None] * 16
        self._size = 0
        self._lock = Lock()

    def _bucket_index(self, key: str) -> int:
        return fnv1a_64(key.encode("utf-8")) % len(self._buckets)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            index = self._bucket_index(key)
            node = self._buckets[index]
            while node is not None:
                if node.key == key:
                    node.value = value
                    return
                node = node.next
            self._buckets[index] = _Node(key, value, self._buckets[index])
            self._size += 1

    def get(self, key: str) -> str | None:
        with self._lock:
            node = self._buckets[self._bucket_index(key)]
            while node is not None:
                if node.key == key:
                    return node.value
                node = node.next
            return None

    def delete(self, key: str) -> bool:
        with self._lock:
            index = self._bucket_index(key)
            previous = None
            node = self._buckets[index]
            while node is not None:
                if node.key == key:
                    if previous is None:
                        self._buckets[index] = node.next
                    else:
                        previous.next = node.next
                    self._size -= 1
                    return True
                previous = node
                node = node.next
            return False

    def __len__(self) -> int:
        with self._lock:
            return self._size
