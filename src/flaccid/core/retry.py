import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_with_backoff(
    func: Callable[[], T],
    *,
    retries: int = 3,
    base: float = 0.5,
    cap: float = 5.0,
    jitter: float = 0.25,
) -> T:
    """Run a callable with exponential backoff and jitter.

    Args:
        func: Callable without args to invoke.
        retries: Maximum retry attempts on exception.
        base: Base delay seconds.
        cap: Maximum backoff seconds.
        jitter: Random jitter added up to this many seconds.

    Returns:
        The function's return value.

    Raises:
        The last exception if all retries are exhausted.
    """
    attempt = 0
    while True:
        try:
            return func()
        except Exception:
            attempt += 1
            if attempt > retries:
                raise
            delay = min(base * (2 ** (attempt - 1)), cap) + random.uniform(0, jitter)
            time.sleep(delay)

