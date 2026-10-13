"""Einfaches In-Memory-Rate-Limiting (gleitendes Fenster).

Bewusst ohne externe Abhängigkeit (Redis o. ä.). Voraussetzung: das Backend
läuft als EIN Prozess (uvicorn ohne --workers), was für das MVP gilt.
Schlüssel (z. B. IP-Adressen) werden nur für die Dauer des Fensters im RAM
gehalten und nie gespeichert.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 100_000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> bool:
        """Zählt einen Versuch. Gibt False zurück, wenn das Limit überschritten ist."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self.max_keys:
                    self._purge(now)
                q = self._hits[key] = deque()
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _purge(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]:
            del self._hits[k]
        if len(self._hits) >= self.max_keys:  # Notbremse gegen Speicherüberlauf
            self._hits.clear()
