"""
infra/llm/llm_errors.py — Standardized LLM Error Types

All errors are non-fatal by design. Callers must catch them and
return a structured "error" result rather than letting the process crash.
"""
from __future__ import annotations


class LLMBaseError(Exception):
    """Base class for all LLM infrastructure errors."""

    def __init__(self, message: str, provider: str = "", model: str = ""):
        super().__init__(message)
        self.message  = message
        self.provider = provider
        self.model    = model

    def __str__(self) -> str:
        return (
            f"[{self.__class__.__name__}] "
            f"provider={self.provider!r} model={self.model!r} — {self.message}"
        )


class LLMTimeoutError(LLMBaseError):
    """Raised when the API request exceeds the configured timeout."""


class LLMRateLimitError(LLMBaseError):
    """Raised when the provider returns a rate-limit (429) response."""


class LLMAuthError(LLMBaseError):
    """Raised when the API key is missing, invalid, or rejected (401/403)."""


class LLMProviderError(LLMBaseError):
    """Raised for provider-side server errors (5xx) or upstream failures."""
    def __init__(self, message: str, provider: str = "", model: str = "",
                 status_code: int = 0):
        super().__init__(message, provider, model)
        self.status_code = status_code

    def __str__(self) -> str:
        return (
            f"[{self.__class__.__name__}] "
            f"provider={self.provider!r} model={self.model!r} "
            f"status={self.status_code} — {self.message}"
        )


class LLMUnknownError(LLMBaseError):
    """Raised for any unexpected or unclassified error."""
