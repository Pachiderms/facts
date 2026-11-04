"""Cache TTL en mémoire, borné. Économise les quotas gratuits (recherche + LLM).

Pour plusieurs instances : même interface, implémentation Redis (offre gratuite).
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(self, ttl_seconds: float, max_entries: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if self._clock() >= expires_at:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: V) -> None:
        self._data.pop(key, None)
        self._data[key] = (self._clock() + self._ttl, value)
        while len(self._data) > self._max:
            self._data.popitem(last=False)  # évince la plus ancienne : mémoire bornée

    def __len__(self) -> int:
        return len(self._data)
