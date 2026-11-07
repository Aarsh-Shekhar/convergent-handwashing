"""Bounded queues with observable drops (stdlib only – shared with the Pi agent)."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class DropOldestQueue(Generic[T]):
    """Thread-safe bounded queue; when full the oldest item is discarded (latest-wins)."""

    def __init__(self, maxsize: int = 2) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self.maxsize = maxsize
        self._dq: deque[T] = deque()
        self._cv = threading.Condition()
        self.dropped = 0
        self.pushed = 0
        self._closed = False

    def push(self, item: T) -> None:
        with self._cv:
            if len(self._dq) >= self.maxsize:
                self._dq.popleft()
                self.dropped += 1
            self._dq.append(item)
            self.pushed += 1
            self._cv.notify()

    def pop(self, timeout: float | None = None) -> T | None:
        with self._cv:
            if not self._dq and not self._closed:
                self._cv.wait(timeout)
            if not self._dq:
                return None
            return self._dq.popleft()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def __len__(self) -> int:
        with self._cv:
            return len(self._dq)

    def stats(self) -> dict[str, Any]:
        return {"depth": len(self), "dropped": self.dropped, "pushed": self.pushed, "maxsize": self.maxsize}


class AsyncDropOldestQueue(Generic[T]):
    """asyncio flavour of :class:`DropOldestQueue` for the transport coroutines."""

    def __init__(self, maxsize: int = 2) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self.maxsize = maxsize
        self._dq: deque[T] = deque()
        self._event = asyncio.Event()
        self.dropped = 0
        self.pushed = 0
        self._closed = False

    def push(self, item: T) -> None:
        if len(self._dq) >= self.maxsize:
            self._dq.popleft()
            self.dropped += 1
        self._dq.append(item)
        self.pushed += 1
        self._event.set()

    async def pop(self, timeout: float | None = None) -> T | None:
        while not self._dq:
            if self._closed:
                return None
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout)
            except TimeoutError:
                return None
        return self._dq.popleft()

    def close(self) -> None:
        self._closed = True
        self._event.set()

    def __len__(self) -> int:
        return len(self._dq)

    def stats(self) -> dict[str, Any]:
        return {"depth": len(self._dq), "dropped": self.dropped, "pushed": self.pushed, "maxsize": self.maxsize}
