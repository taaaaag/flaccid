import asyncio
import time


class AsyncRateLimiter:
    """A simple async rate limiter using a token bucket approach.

    Allows up to `rate` events per `per` seconds.
    """

    def __init__(self, rate: int, per: float = 1.0) -> None:
        self.rate = max(1, int(rate))
        self.per = float(per)
        self._tokens = self.rate
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._updated
            # Refill tokens based on elapsed time
            refill = int(elapsed * (self.rate / self.per))
            if refill > 0:
                self._tokens = min(self.rate, self._tokens + refill)
                self._updated = now
            if self._tokens == 0:
                # Sleep long enough for 1 token
                sleep_for = max(0.0, (1 / (self.rate / self.per)))
                await asyncio.sleep(sleep_for)
                self._tokens = 0  # recalc on next loop
                return await self.acquire()
            self._tokens -= 1
