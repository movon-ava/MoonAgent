"""A semaphore whose limit can be raised or lowered while tasks are waiting."""

from __future__ import annotations

import asyncio


class DynamicSemaphore:
    """Like ``asyncio.Semaphore`` but ``set_limit()`` works at runtime.

    Lowering the limit below the number of running tasks is allowed: the extra
    tasks finish normally and no new task starts until the count drops below the
    limit again.
    """

    def __init__(self, limit: int = 1) -> None:
        self._limit = max(1, int(limit))
        self._active = 0
        self._cond = asyncio.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        return self._active

    async def acquire(self) -> None:
        async with self._cond:
            while self._active >= self._limit:
                await self._cond.wait()
            self._active += 1

    async def release(self) -> None:
        async with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify_all()

    async def set_limit(self, limit: int) -> int:
        async with self._cond:
            self._limit = max(1, int(limit))
            self._cond.notify_all()
            return self._limit

    async def __aenter__(self) -> DynamicSemaphore:
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.release()
