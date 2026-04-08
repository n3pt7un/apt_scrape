import pytest
from apt_scrape.retry import classify_error, ErrorClass


def test_classify_timeout():
    assert classify_error(TimeoutError("page load")) == ErrorClass.TRANSIENT


def test_classify_connection_reset():
    assert classify_error(ConnectionError("reset")) == ErrorClass.TRANSIENT


def test_classify_404():
    from apt_scrape.retry import HttpError
    assert classify_error(HttpError(404, "Not Found")) == ErrorClass.PERMANENT


def test_classify_403():
    from apt_scrape.retry import HttpError
    assert classify_error(HttpError(403, "Forbidden")) == ErrorClass.BLOCKED


def test_classify_429():
    from apt_scrape.retry import HttpError
    assert classify_error(HttpError(429, "Too Many Requests")) == ErrorClass.RATE_LIMITED


def test_classify_unknown():
    assert classify_error(RuntimeError("something")) == ErrorClass.TRANSIENT
