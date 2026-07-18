"""Screening result cache with TTL."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class CacheEntry:
    value: bool
    expires_at: float


class ScreeningCache:
    def __init__(self, max_size: int = 1024, default_ttl: float = 600.0):
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._store: Dict[str, CacheEntry] = {}
        self._order: list[str] = []

    def _make_key(self, source_id: str, term: str, kind: str) -> str:
        return f"{kind}::{source_id}::{term.lower()}"

    def _evict_expired(self) -> None:
        now = time.time()
        keys = [k for k, v in self._store.items() if v.expires_at <= now]
        for key in keys:
            self._store.pop(key, None)
            if key in self._order:
                self._order.remove(key)

    def get(self, source_id: str, term: str, kind: str) -> Optional[bool]:
        self._evict_expired()
        key = self._make_key(source_id, term, kind)
        if key not in self._store:
            return None
        return self._store[key].value

    def set(self, source_id: str, term: str, value: bool, kind: str, ttl: Optional[float] = None) -> None:
        if ttl is None:
            ttl = self.default_ttl
        key = self._make_key(source_id, term, kind)
        self._store[key] = CacheEntry(value=value, expires_at=time.time() + ttl)
        if key not in self._order:
            self._order.append(key)
        if len(self._order) > self.max_size:
            evict = self._order.pop(0)
            self._store.pop(evict, None)
