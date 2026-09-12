import asyncio


class InMemoryIdempotencyStore:
    """Single-process MVP store. Replace with a DB unique constraint in Phase 2."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = asyncio.Lock()

    async def claim(self, key: str) -> bool:
        async with self._lock:
            if key in self._claimed:
                return False
            self._claimed.add(key)
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            self._claimed.discard(key)
