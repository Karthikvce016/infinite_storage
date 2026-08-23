"""
rate_limiter.py – Async token-bucket rate limiter for Telegram API calls.

Prevents bot bans by enforcing:
    - A minimum delay between consecutive API calls (default 2s)
    - A maximum number of calls per minute (token bucket, default 20/min)
    - Exponential backoff on FloodWaitError with clear system logging
"""

import asyncio
import logging
import time

from config.settings import RATE_LIMIT_DELAY, MAX_REQUESTS_PER_MINUTE

log = logging.getLogger(__name__)


class RateLimiter:
    """
    Per-client rate limiter using a simple token-bucket approach.

    Usage::

        limiter = RateLimiter()
        async with limiter:
            await client.send_file(...)
    """

    def __init__(
        self,
        min_delay: float = RATE_LIMIT_DELAY,
        max_per_minute: int = MAX_REQUESTS_PER_MINUTE,
    ) -> None:
        self._min_delay = min_delay
        self._max_per_minute = max_per_minute
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0
        self._total_calls: int = 0
        self._total_waits: int = 0
        # Token bucket
        self._tokens = float(max_per_minute)
        self._max_tokens = float(max_per_minute)
        self._last_refill: float = time.monotonic()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._max_tokens,
            self._tokens + elapsed * (self._max_per_minute / 60.0),
        )
        self._last_refill = now

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        async with self._lock:
            self._refill()

            # Wait for token availability
            while self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) / (self._max_per_minute / 60.0)
                log.debug(
                    "SYSTEM: Rate limiter — bucket empty, waiting %.1fs for token replenish "
                    "(total calls: %d, total waits: %d)",
                    wait_time, self._total_calls, self._total_waits,
                )
                self._total_waits += 1
                await asyncio.sleep(wait_time)
                self._refill()

            # Enforce minimum delay between calls
            now = time.monotonic()
            since_last = now - self._last_call
            if since_last < self._min_delay:
                delay = self._min_delay - since_last
                log.debug(
                    "SYSTEM: Rate limiter — enforcing %.1fs inter-call delay", delay
                )
                await asyncio.sleep(delay)

            # Consume a token
            self._tokens -= 1.0
            self._last_call = time.monotonic()
            self._total_calls += 1

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *exc):
        pass

    def stats(self) -> dict:
        """Return rate limiter statistics."""
        return {
            "total_calls": self._total_calls,
            "total_waits": self._total_waits,
            "remaining_tokens": round(self._tokens, 1),
            "min_delay": self._min_delay,
            "max_per_minute": self._max_per_minute,
        }


async def handle_flood_wait(e, context: str = "") -> None:
    """
    Sleep on FloodWaitError with a 1.5x safety multiplier.
    Call this from except blocks wrapping Telegram API calls.

    Logs a clear SYSTEM message for monitoring.
    """
    wait = int(e.seconds * 1.5) + 2
    log.warning(
        "SYSTEM: FloodWaitError during '%s' — "
        "Telegram demanded %ds wait, sleeping %ds (1.5x safety margin). "
        "This is normal rate-limit behavior.",
        context, e.seconds, wait,
    )
    await asyncio.sleep(wait)
    log.info("SYSTEM: FloodWait sleep complete for '%s', resuming.", context)
