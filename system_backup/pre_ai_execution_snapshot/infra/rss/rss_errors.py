"""
infra/rss/rss_errors.py — Standardized RSS Error Types

All errors are non-fatal by design: callers catch them and return an
"error" result record rather than letting the process crash.
"""
from __future__ import annotations


class RSSBaseError(Exception):
    """Base class for all RSS errors."""
    def __init__(self, message: str, url: str = ""):
        super().__init__(message)
        self.url = url
        self.message = message

    def __str__(self) -> str:
        return f"[{self.__class__.__name__}] url={self.url!r} — {self.message}"


class RSSFetchTimeout(RSSBaseError):
    """Raised when the HTTP request exceeds the configured timeout."""


class RSSInvalidXML(RSSBaseError):
    """Raised when the feed body cannot be parsed as valid RSS/Atom XML."""


class RSSHTTPError(RSSBaseError):
    """Raised when the server returns a non-2xx HTTP status code."""
    def __init__(self, message: str, url: str = "", status_code: int = 0):
        super().__init__(message, url)
        self.status_code = status_code

    def __str__(self) -> str:
        return (
            f"[{self.__class__.__name__}] url={self.url!r} "
            f"status={self.status_code} — {self.message}"
        )


class RSSUnknownError(RSSBaseError):
    """Raised for any unexpected error during fetch or parsing."""
