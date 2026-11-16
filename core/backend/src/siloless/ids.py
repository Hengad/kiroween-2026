"""Sortable identifiers (ULIDs), generated from an injected clock."""

import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from siloless.clock import Clock

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)
_RANDOM_BYTES = 10
_MAX_RANDOM = (1 << (8 * _RANDOM_BYTES)) - 1


class IdGenerator(Protocol):
    def new(self) -> str: ...


def _encode(value: int) -> str:
    chars: list[str] = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


class UlidGenerator:
    """Monotonic ULID generator.

    Ids sort in creation order, even within one millisecond and even if the
    clock moves backwards, because the generator never goes below the last
    timestamp it used and increments the random part instead.
    """

    def __init__(
        self,
        clock: Clock,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._clock = clock
        self._random_bytes = random_bytes
        self._lock = threading.Lock()
        self._last_ms = -1
        self._last_random = 0

    def new(self) -> str:
        with self._lock:
            now_ms = (self._clock.now() - _EPOCH) // _MILLISECOND
            ms = max(now_ms, self._last_ms)
            if ms == self._last_ms:
                random_part = self._last_random + 1
                if random_part > _MAX_RANDOM:
                    ms += 1
                    random_part = self._fresh_random()
            else:
                random_part = self._fresh_random()
            self._last_ms = ms
            self._last_random = random_part
            return _encode((ms << (8 * _RANDOM_BYTES)) | random_part)

    def _fresh_random(self) -> int:
        return int.from_bytes(self._random_bytes(_RANDOM_BYTES), "big")
