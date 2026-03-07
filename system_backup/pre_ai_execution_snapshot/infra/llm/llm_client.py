"""
infra/llm/llm_client.py — Public LLM generation interface with multi-provider fallback.

Routing:
  • Provider selected from env var LLM_PROVIDER_DEFAULT (or LANDING_LLM_PROVIDER)
  • If primary provider fails (timeout / rate-limit / provider error) →
    automatic fallback to the secondary provider
  • Auth errors are NOT retried via fallback (key issue must be fixed)
  • Max 1 fallback attempt per call (no infinite loops)

Constitutional guarantees:
  • No Orchestrator dependency
  • No Radar dependency
  • No global state mutation
  • Never raises unhandled exceptions
  • API key never logged or exposed
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from infra.llm.llm_providers import openai_provider, gemini_provider
from infra.llm.llm_response_normalizer import normalize_response
from infra.llm.llm_errors import LLMAuthError

logger = logging.getLogger("infra.llm.client")

# ---------------------------------------------------------------------------
# Provider registry (add new providers here)
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, object] = {
    "openai": openai_provider,
    "gemini": gemini_provider,
}

_FALLBACK_MAP: dict[str, str] = {
    "openai": "gemini",
    "gemini": "openai",
}

# Errors that trigger fallback (transient/service-side)
_FALLBACK_TRIGGERS = {
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMProviderError",
    "LLMUnknownError",
}

# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def _resolve_provider(override: Optional[str] = None) -> str:
    """
    Determine the primary provider, in priority order:
      1. explicit override passed by caller
      2. LANDING_LLM_PROVIDER env var
      3. LLM_PROVIDER_DEFAULT env var
      4. hardcoded default: "openai"
    """
    candidates = [
        override,
        os.environ.get("LANDING_LLM_PROVIDER"),
        os.environ.get("LLM_PROVIDER_DEFAULT"),
        "openai",
    ]
    for c in candidates:
        if c and c in _PROVIDERS:
            return c
    return "openai"


def _err_result(provider: str, model: str, error_type: str) -> dict:
    return normalize_response({
        "provider":    provider,
        "model":       model,
        "status":      "error",
        "content":     "",
        "tokens_used": 0,
        "latency_ms":  0,
        "error_type":  error_type,
    })


# ---------------------------------------------------------------------------
# Core generate (single call with fallback)
# ---------------------------------------------------------------------------

def generate(
    prompt: str,
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    max_tokens: int = 1000,
    timeout: int = 15,
    provider: Optional[str] = None,
    max_retries: int = 2,
    system_prompt: Optional[str] = None,
) -> dict:
    """
    Generate a completion using the resolved primary provider.
    On transient failure, automatically falls back to the secondary provider.
    On auth failure, returns error immediately (no fallback).

    Returns a normalized response dict. Never raises.
    """
    primary   = _resolve_provider(provider)
    secondary = _FALLBACK_MAP.get(primary)

    # ── Primary attempt ───────────────────────────────────────
    try:
        raw = _PROVIDERS[primary].call(
            prompt        = prompt,
            model         = _adapt_model(model, primary),
            temperature   = temperature,
            max_tokens    = max_tokens,
            timeout       = float(timeout),
            max_retries   = max_retries,
            system_prompt = system_prompt,
        )
    except Exception as exc:
        raw = {
            "provider": primary, "model": model, "status": "error",
            "content": "", "tokens_used": 0, "latency_ms": 0,
            "error_type": "LLMUnknownError",
        }

    result = normalize_response(raw)

    if result["status"] == "ok":
        logger.debug(
            "LLM ok primary=%s model=%s latency=%dms tokens=%d",
            primary, model, result["latency_ms"], result["tokens_used"],
        )
        return result

    error_type = result.get("error_type", "")

    # Auth errors → never fall back
    if error_type == "LLMAuthError" or not secondary:
        logger.warning("LLM auth/no-fallback primary=%s error=%s", primary, error_type)
        return result

    # Non-fallback errors → return immediately
    if error_type not in _FALLBACK_TRIGGERS:
        return result

    # ── Fallback attempt ──────────────────────────────────────
    logger.warning(
        "LLM fallback primary=%s -> secondary=%s reason=%s",
        primary, secondary, error_type,
    )
    try:
        raw2 = _PROVIDERS[secondary].call(
            prompt        = prompt,
            model         = _adapt_model(model, secondary),
            temperature   = temperature,
            max_tokens    = max_tokens,
            timeout       = float(timeout),
            max_retries   = max_retries,
            system_prompt = system_prompt,
        )
    except Exception as exc:
        raw2 = {
            "provider": secondary, "model": model, "status": "error",
            "content": "", "tokens_used": 0, "latency_ms": 0,
            "error_type": "LLMUnknownError",
        }

    result2 = normalize_response(raw2)

    # Tag the result with fallback metadata
    if result2["status"] == "ok":
        logger.info(
            "LLM fallback ok secondary=%s latency=%dms",
            secondary, result2["latency_ms"],
        )
    return result2


def _adapt_model(model: str, target_provider: str) -> str:
    """
    Map a model name to an appropriate equivalent for the target provider.
    Falls back to sensible defaults if the model is provider-specific.
    """
    _openai_defaults  = {"gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo", "gpt-4"}
    _gemini_defaults  = {
        "gemini-pro", "gemini-flash", "gemini-1.5-pro",
        "gemini-1.5-flash", "gemini-1.5-pro-latest", "gemini-1.5-flash-latest",
    }

    if target_provider == "openai" and model in _gemini_defaults:
        return "gpt-4o-mini"
    if target_provider == "gemini" and model in _openai_defaults:
        return "gemini-1.5-flash"
    return model


# ---------------------------------------------------------------------------
# Batch generate (concurrent)
# ---------------------------------------------------------------------------

def generate_batch(
    prompts: list[str],
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    max_tokens: int = 1000,
    timeout: int = 15,
    provider: Optional[str] = None,
    max_workers: int = 10,
    max_retries: int = 2,
    system_prompt: Optional[str] = None,
) -> list[dict]:
    """
    Generate completions for multiple prompts concurrently.
    Each prompt goes through the same primary → fallback logic.
    Returns results in the same order as input prompts. Never raises.
    """
    if not prompts:
        return []

    workers = min(max_workers, len(prompts))
    results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {
            executor.submit(
                generate,
                prompt        = p,
                model         = model,
                temperature   = temperature,
                max_tokens    = max_tokens,
                timeout       = timeout,
                provider      = provider,
                max_retries   = max_retries,
                system_prompt = system_prompt,
            ): i
            for i, p in enumerate(prompts)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = _err_result(
                    provider or _resolve_provider(), model, "LLMUnknownError"
                )

    return [results[i] for i in range(len(prompts))]
