"""Retry with exponential backoff, rate limiting and a circuit breaker for provider calls."""
import asyncio
import logging
import random
import time
from typing import Awaitable, Callable, TypeVar

from app.providers.errors import CircuitOpenError, ProviderError, ProviderRateLimitError

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitBreaker:
    """Opens after N consecutive failures; allows one probe after the recovery period."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.recovery_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        # A failed half-open probe re-opens immediately.
        if self._failures >= self.failure_threshold or self._opened_at is not None:
            self._opened_at = self._clock()


class RateLimiter:
    """Token bucket: ``rate`` requests per second with a burst of ``capacity``."""

    def __init__(
        self,
        rate: float,
        capacity: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.rate = rate
        self.capacity = capacity
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(capacity)
        self._updated = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await self._sleep((1 - self._tokens) / self.rate)


class ProviderGuard:
    """Wraps provider calls: circuit check, rate limit, retries with backoff."""

    def __init__(
        self,
        name: str,
        limiter: RateLimiter,
        breaker: CircuitBreaker,
        attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.name = name
        self.limiter = limiter
        self.breaker = breaker
        self.attempts = attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep

    def _delay(self, attempt: int, exc: ProviderError) -> float:
        if isinstance(exc, ProviderRateLimitError) and exc.retry_after:
            return min(exc.retry_after, self.max_delay)
        backoff = min(self.base_delay * (2**attempt), self.max_delay)
        return backoff * random.uniform(0.5, 1.0)  # jitter avoids synchronised retries

    async def call(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        if not self.breaker.allow():
            raise CircuitOpenError(f"Circuit open for provider '{self.name}'")
        last: ProviderError | None = None
        for attempt in range(self.attempts):
            await self.limiter.acquire()
            try:
                result = await fn(*args, **kwargs)
            except ProviderError as exc:
                last = exc
                self.breaker.record_failure()
                logger.warning(
                    "Provider call failed",
                    extra={"provider": self.name, "attempt": attempt + 1, "error": str(exc)},
                )
                if not exc.retryable or attempt == self.attempts - 1 or not self.breaker.allow():
                    break
                await self._sleep(self._delay(attempt, exc))
            else:
                self.breaker.record_success()
                return result
        assert last is not None
        raise last
