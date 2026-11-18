"""Retry with exponential backoff + jitter, used around every external call."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")
log = logging.getLogger("lead_intake.retry")


class TransientError(Exception):
    """A failure worth retrying (timeouts, 429s, 5xx)."""


class PermanentError(Exception):
    """A failure that will not fix itself (bad input, 4xx). Goes straight to the dead-letter queue."""


def backoff_delay(attempt: int, base: float, cap: float = 30.0, jitter: bool = True) -> float:
    delay = min(cap, base * (2 ** (attempt - 1)))
    return delay * random.uniform(0.5, 1.0) if jitter else delay


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 0.5,
    step: str = "call",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn`` and retry on TransientError. PermanentError and unknown errors are not retried."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except TransientError as exc:
            if attempt == attempts:
                log.error("retries exhausted", extra={"step": step, "attempt": attempt, "error": str(exc)})
                raise
            delay = backoff_delay(attempt, base_delay)
            log.warning(
                "transient failure, retrying",
                extra={"step": step, "attempt": attempt, "next_delay_s": round(delay, 2), "error": str(exc)},
            )
            sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def classify_http_status(status: int) -> type[Exception]:
    return TransientError if status == 429 or status >= 500 else PermanentError
