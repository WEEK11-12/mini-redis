"""Locked string storage with separate chaining and full rehashing."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from threading import Lock
from time import monotonic_ns


MAX_KEY_BYTES = 1024
MAX_VALUE_BYTES = 1024 * 1024
_UNSET = object()


def _validate_text(text: str, name: str, limit: int) -> None:
    if not isinstance(text, str):
        raise TypeError(f"{name} must be a string")
    if len(text.encode("utf-8")) > limit:
        raise ValueError(f"{name} exceeds {limit} UTF-8 bytes")


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
    expires_at_ns: int | None = None


@dataclass(frozen=True, slots=True)
class CleanupResult:
    keys_checked: int
    buckets_visited: int
    deleted: int


class MiniRedisStore:
    def __init__(self, *, clock_ns: Callable[[], int] = monotonic_ns) -> None:
        self._buckets: list[_Node | None] = [None] * 16
        self._size = 0
        self._lock = Lock()
        self._clock_ns = clock_ns
        self._scan_bucket = 0
        self._scan_node: _Node | None = None
        self._scan_previous: _Node | None = None

    def _bucket_index(self, key: str) -> int:
        return fnv1a_64(key.encode("utf-8")) % len(self._buckets)

    def _resize(self) -> None:
        buckets: list[_Node | None] = [None] * (len(self._buckets) * 2)
        for head in self._buckets:
            node = head
            while node is not None:
                index = fnv1a_64(node.key.encode("utf-8")) % len(buckets)
                # Preserve the original chains until the new table is ready.
                buckets[index] = _Node(
                    node.key, node.value, buckets[index], node.expires_at_ns
                )
                node = node.next
        self._buckets = buckets
        self._scan_bucket = 0
        self._scan_node = None
        self._scan_previous = None

    def _expired(self, node: _Node) -> bool:
        return (node.expires_at_ns is not None
                and self._clock_ns() >= node.expires_at_ns)

    def _unlink(self, index: int, previous: _Node | None, node: _Node) -> None:
        if index == self._scan_bucket:
            if self._scan_node is node:
                self._scan_node = node.next
            if self._scan_previous is node:
                self._scan_previous = previous
        if previous is None:
            self._buckets[index] = node.next
        else:
            previous.next = node.next
        self._size -= 1

    def set(self, key: str, value: str, *, ttl_ms: object = _UNSET) -> None:
        _validate_text(key, "key", MAX_KEY_BYTES)
        _validate_text(value, "value", MAX_VALUE_BYTES)
        if ttl_ms is not _UNSET:
            if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int):
                raise TypeError("ttl_ms must be an integer")
            if ttl_ms <= 0:
                raise ValueError("ttl_ms must be positive")
        with self._lock:
            index = self._bucket_index(key)
            node = self._buckets[index]
            while node is not None:
                if node.key == key:
                    deadline = (None if ttl_ms is _UNSET else
                                self._clock_ns() + ttl_ms * 1000000)
                    node.value = value
                    node.expires_at_ns = deadline
                    return
                node = node.next
            new_node = _Node(key, value)
            if (self._size + 1) * 4 > len(self._buckets) * 3:
                self._resize()
                index = self._bucket_index(key)
            new_node.next = self._buckets[index]
            new_node.expires_at_ns = (None if ttl_ms is _UNSET else
                                      self._clock_ns() + ttl_ms * 1000000)
            if (index == self._scan_bucket and self._scan_node is not None
                    and self._scan_previous is None):
                self._scan_previous = new_node
            self._buckets[index] = new_node
            self._size += 1

    def get(self, key: str) -> str | None:
        _validate_text(key, "key", MAX_KEY_BYTES)
        with self._lock:
            index = self._bucket_index(key)
            previous = None
            node = self._buckets[index]
            while node is not None:
                if node.key == key:
                    if self._expired(node):
                        self._unlink(index, previous, node)
                        return None
                    return node.value
                previous = node
                node = node.next
            return None

    def delete(self, key: str) -> bool:
        _validate_text(key, "key", MAX_KEY_BYTES)
        with self._lock:
            index = self._bucket_index(key)
            previous = None
            node = self._buckets[index]
            while node is not None:
                if node.key == key:
                    was_valid = not self._expired(node)
                    self._unlink(index, previous, node)
                    return was_valid
                previous = node
                node = node.next
            return False

    def cleanup(self, *, key_limit: int = 100, bucket_limit: int = 100) -> CleanupResult:
        for limit in (key_limit, bucket_limit):
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("cleanup limits must be integers")
            if limit <= 0:
                raise ValueError("cleanup limits must be positive")
        with self._lock:
            checked = visited = deleted = 0
            while (checked < key_limit
                   and visited < min(bucket_limit, len(self._buckets))):
                index = self._scan_bucket
                visited += 1
                if self._scan_node is None:
                    self._scan_node = self._buckets[index]
                    self._scan_previous = None
                while self._scan_node is not None and checked < key_limit:
                    node = self._scan_node
                    checked += 1
                    if self._expired(node):
                        self._unlink(index, self._scan_previous, node)
                        deleted += 1
                    else:
                        self._scan_previous = node
                        self._scan_node = node.next
                if self._scan_node is not None:
                    break
                self._scan_bucket = (index + 1) % len(self._buckets)
                self._scan_previous = None
            return CleanupResult(checked, visited, deleted)

    def __len__(self) -> int:
        with self._lock:
            return self._size
