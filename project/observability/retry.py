"""Bounded retry policies for transient technical operations only."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential-backoff policy for infrastructure failures."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.25
    multiplier: float = 2.0
    max_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if self.initial_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("Retry delays cannot be negative.")
        if self.multiplier < 1:
            raise ValueError("Retry multiplier must be at least 1.")

    def delay_for_retry(self, failed_attempt: int) -> float:
        return min(
            self.initial_delay_seconds * self.multiplier ** (failed_attempt - 1),
            self.max_delay_seconds,
        )


def run_with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    retryable: Callable[[Exception], bool],
    operation_name: str,
    logger: logging.Logger,
) -> tuple[T, int]:
    """Run an operation and retry only exceptions classified as transient."""
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation(), attempt
        except Exception as error:
            if not retryable(error) or attempt >= policy.max_attempts:
                raise
            delay = policy.delay_for_retry(attempt)
            logger.warning(
                "Transient technical operation failed; retry scheduled",
                extra={
                    "event": "technical_retry_scheduled",
                    "stage": "TECHNICAL_RETRY",
                    "operation": operation_name,
                    "attempt": attempt,
                    "max_attempts": policy.max_attempts,
                    "delay_seconds": delay,
                    "error_code": type(error).__name__,
                },
            )
            if delay:
                time.sleep(delay)
    raise AssertionError("Unreachable retry loop state.")
