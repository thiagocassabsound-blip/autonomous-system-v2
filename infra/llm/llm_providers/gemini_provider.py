"""
infra/llm/llm_providers/gemini_provider.py — Google Gemini REST API provider.

Implements the standard provider interface via direct HTTP REST calls
(no google-generativeai SDK required — uses requests, always available).

Constitutional guarantees:
  • API key read from GEMINI_API_KEY env var only (never logged)
  • No Orchestrator / Radar / global state dependency
  • Never raises — all errors converted to typed LLM errors
  • Latency measured per call
  • Retry policy (max 2) with 0.5s back-off
  • Compatible with Gemini API v1 (generateContent endpoint)
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

from infra.llm.llm_errors import (
    LLMAuthError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnknownError,
)

_PROVIDER_NAME         = "gemini"
_GEMINI_API_BASE       = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_RETRIES       = 2
_RETRY_DELAY_SEC       = 0.5
_USER_AGENT            = "AutonomousSystemRadar/2.0"

# Map our generic model names to Gemini model IDs
_MODEL_ALIASES: dict[str, str] = {
    "gemini-pro":          "gemini-1.5-pro-latest",
    "gemini-flash":        "gemini-1.5-flash-latest",
    "gemini-1.5-pro":     "gemini-1.5-pro-latest",
    "gemini-1.5-flash":   "gemini-1.5-flash-latest",
}


def _resolve_model(model: str) -> str:
    return _MODEL_ALIASES.get(model, model)


def _build_url(model_id: str, api_key: str) -> str:
    return f"{_GEMINI_API_BASE}/{model_id}:generateContent?key={api_key}"


def _build_payload(
    prompt: str,
    temperature: float,
    max_tokens: int,
    system_prompt: Optional[str],
) -> dict:
    contents = []
    if system_prompt:
        # Gemini represents system turns as a special "user" message before the real one
        contents.append({"role": "user", "parts": [{"text": system_prompt}]})
        contents.append({"role": "model", "parts": [{"text": "Understood."}]})
    contents.append({"role": "user", "parts": [{"text": prompt or ""}]})
    return {
        "contents": contents,
        "generationConfig": {
            "temperature":   min(max(temperature, 0.0), 2.0),
            "maxOutputTokens": max_tokens,
        },
    }


def call(
    prompt: str,
    model: str = "gemini-1.5-flash",
    temperature: float = 0.7,
    max_tokens: int = 1000,
    timeout: float = 15.0,
    max_retries: int = _DEFAULT_RETRIES,
    retry_delay: float = _RETRY_DELAY_SEC,
    system_prompt: Optional[str] = None,
) -> dict:
    """
    Call the Gemini generateContent REST API.

    Returns a raw result dict (before normalization):
      {
        provider     : "gemini",
        model        : str,
        status       : "ok" | "error",
        content      : str,
        tokens_used  : int,
        latency_ms   : int,
        error_type   : str | None,
      }

    Never raises. Retries up to max_retries on transient errors.
    """
    api_key   = os.environ.get("GEMINI_API_KEY", "")
    model_id  = _resolve_model(model)
    payload   = _build_payload(prompt, temperature, max_tokens, system_prompt)

    attempt    = 0
    last_error: Optional[Exception] = None
    t0         = time.perf_counter()

    while attempt <= max_retries:
        attempt += 1
        t0 = time.perf_counter()
        try:
            if not api_key:
                raise LLMAuthError("GEMINI_API_KEY not set",
                                   provider=_PROVIDER_NAME, model=model)

            url      = _build_url(model_id, api_key)
            response = requests.post(
                url,
                json    = payload,
                timeout = timeout,
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent":   _USER_AGENT,
                },
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)

            if response.status_code == 401 or response.status_code == 403:
                raise LLMAuthError(
                    f"HTTP {response.status_code}",
                    provider=_PROVIDER_NAME, model=model,
                )
            if response.status_code == 429:
                raise LLMRateLimitError(
                    "Rate limited", provider=_PROVIDER_NAME, model=model,
                )
            if response.status_code >= 500:
                raise LLMProviderError(
                    f"Server error HTTP {response.status_code}",
                    provider=_PROVIDER_NAME, model=model,
                    status_code=response.status_code,
                )
            if response.status_code >= 400:
                raise LLMProviderError(
                    f"Client error HTTP {response.status_code}",
                    provider=_PROVIDER_NAME, model=model,
                    status_code=response.status_code,
                )

            data = response.json()
            # Extract generated text
            try:
                content = (
                    data["candidates"][0]["content"]["parts"][0]["text"] or ""
                ).strip()
            except (KeyError, IndexError, TypeError):
                content = ""

            # Extract token usage (Gemini usageMetadata)
            usage = data.get("usageMetadata", {})
            tokens_used = int(
                usage.get("totalTokenCount",
                usage.get("candidatesTokenCount", 0)) or 0
            )

            return {
                "provider":    _PROVIDER_NAME,
                "model":       model,
                "status":      "ok",
                "content":     content,
                "tokens_used": tokens_used,
                "latency_ms":  latency_ms,
                "error_type":  None,
            }

        except LLMAuthError as exc:
            last_error = exc
            break  # Auth errors are never retried

        except LLMRateLimitError as exc:
            last_error = exc
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except LLMProviderError as exc:
            last_error = exc
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except requests.exceptions.Timeout:
            last_error = LLMTimeoutError(
                f"Timeout after {timeout}s",
                provider=_PROVIDER_NAME, model=model,
            )
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except requests.exceptions.ConnectionError as exc:
            last_error = LLMUnknownError(str(exc), provider=_PROVIDER_NAME, model=model)
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except Exception as exc:
            last_error = LLMUnknownError(str(exc), provider=_PROVIDER_NAME, model=model)
            if attempt <= max_retries:
                time.sleep(retry_delay)

    latency_ms = int((time.perf_counter() - t0) * 1000)
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
