"""Inference concurrency and quota management."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class InferenceSemaphore:
    """Manages inference worker concurrency and dynamic quota limits."""

    def __init__(self, max_concurrency: int = 1) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._max_concurrency: int = max_concurrency
        self._active_workers: int = 0
        self._waiters: list[asyncio.Future[None]] = []

    @property
    def max_concurrency(self) -> int:
        """Return the maximum allowed concurrent workers."""
        return self._max_concurrency

    @property
    def active_workers(self) -> int:
        """Return the count of actively executing workers."""
        return self._active_workers

    def set_max_concurrency(self, n: int) -> None:
        """Dynamically update maximum concurrency and wake waiting tasks if capacity expands."""
        if n < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._max_concurrency = n
        self._wake_up_waiters()

    def _wake_up_waiters(self) -> None:
        """Wake up pending waiters while capacity permits."""
        while self._waiters and self._active_workers < self._max_concurrency:
            waiter = self._waiters.pop(0)
            if not waiter.done():
                self._active_workers += 1
                waiter.set_result(None)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """Async context manager to acquire an execution slot."""
        if self._active_workers < self._max_concurrency:
            self._active_workers += 1
        else:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[None] = loop.create_future()
            self._waiters.append(fut)
            try:
                await fut
            except BaseException:
                if fut in self._waiters:
                    self._waiters.remove(fut)
                elif fut.done() and not fut.cancelled():
                    self._active_workers -= 1
                    self._wake_up_waiters()
                raise

        try:
            yield
        finally:
            self._active_workers -= 1
            self._wake_up_waiters()
