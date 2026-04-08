"""apt_scrape.retry — Tenacity retry policies and error classification."""

from __future__ import annotations

import logging
from enum import Enum, auto

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


class ErrorClass(Enum):
    TRANSIENT = auto()     # Retry with backoff
    BLOCKED = auto()       # Rotate proxy, then retry
    RATE_LIMITED = auto()  # Wait longer, then retry
    PERMANENT = auto()     # Do not retry


class HttpError(Exception):
    """HTTP error with status code."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {message}")


class BlockDetectedError(Exception):
    """Raised when bot detection (CAPTCHA, DataDome) is encountered."""


def classify_error(exc: BaseException) -> ErrorClass:
    """Classify an exception to determine retry strategy."""
    if isinstance(exc, HttpError):
        if exc.status == 404:
            return ErrorClass.PERMANENT
        if exc.status == 429:
            return ErrorClass.RATE_LIMITED
        if exc.status in (403, 406):
            return ErrorClass.BLOCKED
        return ErrorClass.TRANSIENT
    if isinstance(exc, BlockDetectedError):
        return ErrorClass.BLOCKED
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return ErrorClass.TRANSIENT
    return ErrorClass.TRANSIENT


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the error should trigger a retry."""
    return classify_error(exc) != ErrorClass.PERMANENT


# Pre-built retry decorator for fetch operations
fetch_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential_jitter(initial=2, max=60, jitter=5),
    stop=stop_after_attempt(4),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
