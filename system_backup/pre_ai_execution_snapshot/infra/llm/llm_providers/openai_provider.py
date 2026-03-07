"""
infra/llm/llm_providers/openai_provider.py — OpenAI completion provider.

Constitutional guarantees:
  • API key read from environment only (never logged or exposed)
  • No Orchestrator / Radar / global state dependency
  • Never raises — all errors converted to typed LLM error objects
  • Latency measured per call
  • Retry policy (max 2) with 0.5s back-off
  • Compatible with openai >= 1.0.0 (sync client)
"""
from __future__ import annotations

import os
import time
from typing import Optional

import openai
import httpx

from infra.llm.llm_errors import (
    LLMAuthError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnknownError,
)

_PROVIDER_NAME    = "openai"
_DEFAULT_RETRIES  = 2
_RETRY_DELAY_SEC  = 0.5


def _get_client(timeout: float) -> openai.OpenAI:
    """Build a fresh OpenAI sync client. API key from env only."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    return openai.OpenAI(
        api_key=api_key if api_key else "__missing__",
        timeout=httpx.Timeout(timeout, connect=5.0),
        max_retries=0,          # we handle retries ourselves
    )


def call(
    prompt: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    timeout: float = 15.0,
    max_retries: int = _DEFAULT_RETRIES,
    retry_delay: float = _RETRY_DELAY_SEC,
    system_prompt: Optional[str] = None,
) -> dict:
    """
    Call the OpenAI Chat Completions API.

    Returns a raw result dict (before normalization):
      {
        provider     : "openai",
        model        : str,
        status       : "ok" | "error",
        content      : str,
        tokens_used  : int,
        latency_ms   : int,
        error_type   : str | None,
      }

    Never raises. Retries up to max_retries times on transient errors.
    """
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt or ""})

    attempt    = 0
    last_error: Optional[Exception] = None

    while attempt <= max_retries:
        attempt += 1
        t0 = time.perf_counter()
        try:
            client   = _get_client(timeout)
            response = client.chat.completions.create(
                model       = model,
                messages    = messages,
                temperature = temperature,
                max_tokens  = max_tokens,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)

            content     = (response.choices[0].message.content or "").strip()
            tokens_used = response.usage.total_tokens if response.usage else 0

            return {
                "provider":   _PROVIDER_NAME,
                "model":      model,
                "status":     "ok",
                "content":    content,
                "tokens_used": tokens_used,
                "latency_ms": latency_ms,
                "error_type": None,
            }

        except openai.AuthenticationError as exc:
            last_error = LLMAuthError(str(exc), provider=_PROVIDER_NAME, model=model)
            break  # Auth errors are not retried

        except openai.RateLimitError as exc:
            last_error = LLMRateLimitError(str(exc), provider=_PROVIDER_NAME, model=model)
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except openai.APITimeoutError as exc:
            last_error = LLMTimeoutError(str(exc), provider=_PROVIDER_NAME, model=model)
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except openai.APIStatusError as exc:
            last_error = LLMProviderError(
                str(exc), provider=_PROVIDER_NAME, model=model,
                status_code=exc.status_code,
            )
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except openai.APIConnectionError as exc:
            last_error = LLMUnknownError(str(exc), provider=_PROVIDER_NAME, model=model)
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except Exception as exc:
            last_error = LLMUnknownError(str(exc), provider=_PROVIDER_NAME, model=model)
            if attempt <= max_retries:
                time.sleep(retry_delay)

    latency_ms = int((time.perf_counter() - t0) * 1000) if "t0" in dir() else 0
    error_type = type(last_error).__name__ if last_error else "LLMUnknownError"

    return {
        "provider":    _PROVIDER_NAME,
        "model":       model,
        "status":      "error",
        "content":     "",
        "tokens_used": 0,
        "latency_ms":  latency_ms,
        "error_type":  error_type,
    }
