"""
infra/landing/landing_llm_executor.py — LLM execution layer for Bloco 30.

Uses infra/llm/llm_client.py exclusively.
Never uses core/landing_generation_engine.py.

Fallback chain (explicit, 3 stages):
  Stage 1 — Primary provider   (from LANDING_LLM_PROVIDER, default: gemini)
  Stage 2 — Fallback provider  (opposite of primary)
  Stage 3 — Secondary safe     (gpt-4o-mini via openai — lightest reliable model)

  Max 1 retry per stage. No loops. No recursion.
  If all 3 stages fail — returns structured error dict. Never raises.

Etapa 2.6 additions:
  - Budget guard: check_budget() called before any LLM call
  - Regen loop:   execute_with_regen() retries up to MAX_LANDING_REGEN_ATTEMPTS

Constitutional guarantees:
  - No global state mutation
  - No Orchestrator dependency (except for budget event emission)
  - API keys never logged
  - Never raises — returns error dict on total failure
"""
from __future__ import annotations

import hashlib
import logging
import os
import time

from infra.llm import llm_client

logger = logging.getLogger("infra.landing.llm_executor")

# Valid provider names
_VALID_PROVIDERS = {"gemini", "openai"}
_DEFAULT_PROVIDER = "gemini"

# Model identifiers
_GEMINI_MODEL = "gemini-1.5-pro"
_OPENAI_MODEL = "gpt-4o-mini"

# Stage 3 — Secondary safe model (lightest reliable, used as absolute last resort)
_SECONDARY_SAFE_PROVIDER = "openai"
_SECONDARY_SAFE_MODEL    = "gpt-4o-mini"

# Generation settings
_MAX_TOKENS        = 4000
_TEMPERATURE       = 0.6
_TIMEOUT           = 30
_MAX_RETRIES_STAGE = 1   # retries per stage — keeps total attempt count bounded

# Etapa 2.6 — Controlled regeneration
MAX_LANDING_REGEN_ATTEMPTS = int(os.getenv("MAX_LANDING_REGEN_ATTEMPTS", "3"))


def _resolve_provider() -> tuple[str, str]:
    """
    Resolve primary and fallback provider from LANDING_LLM_PROVIDER env var.

    Returns:
        (primary_provider, fallback_provider)

    Env var values:
        "gemini"  → primary=gemini,  fallback=openai  (default)
        "openai"  → primary=openai,  fallback=gemini
        absent    → same as "gemini"
        invalid   → same as "gemini" (silent fallback to default)
    """
    raw = os.getenv("LANDING_LLM_PROVIDER", _DEFAULT_PROVIDER).strip().lower()
    provider = raw if raw in _VALID_PROVIDERS else _DEFAULT_PROVIDER

    if provider == "openai":
        return ("openai", "gemini")
    return ("gemini", "openai")


def _model_for(provider: str) -> str:
    """Map provider name to its preferred landing generation model."""
    return _OPENAI_MODEL if provider == "openai" else _GEMINI_MODEL

def _call_provider(prompt: str, provider: str, model: str, stage: int) -> dict:
    """
    Single-stage LLM call. Returns llm_client result dict. Never raises.
    Logs the attempt clearly for auditability.
    """
    logger.info(
        "[LandingLLMExecutor] Stage %d: provider=%s model=%s",
        stage, provider, model,
    )
    try:
        return llm_client.generate(
            prompt      = prompt,
            model       = model,
            temperature = _TEMPERATURE,
            max_tokens  = _MAX_TOKENS,
            timeout     = _TIMEOUT,
            provider    = provider,
            max_retries = _MAX_RETRIES_STAGE,
        )
    except Exception as exc:
        logger.error(
            "[LandingLLMExecutor] Stage %d unexpected exception: %s", stage, exc
        )
        return {
            "status":      "error",
            "content":     "",
            "provider":    provider,
            "latency_ms":  0,
            "tokens_used": 0,
            "error_type":  "LLMUnknownError",
        }


def execute_landing_generation(prompt: str) -> dict:
    """
    Execute landing page HTML generation with a 3-stage explicit fallback chain.

    Chain (resolved dynamically from LANDING_LLM_PROVIDER env var):
      Stage 1 — Primary provider  (default: gemini-1.5-pro)
      Stage 2 — Fallback provider (default: gpt-4o-mini via openai)
      Stage 3 — Secondary safe   (gpt-4o-mini — absolute last resort)

    Per-stage max_retries = 1 (bounds total attempts to ≤3 per chain execution).
    No loops. No recursion. Never raises.

    Returns:
      {
        "status":         "ok" | "error",
        "html":           str,
        "model_used":     str,
        "latency_ms":     int,
        "prompt_hash":    str,
        "html_hash":      str,
        "error_type":     str | None,
        "fallback_used":  bool,
        "stage_reached":  int,       # 1, 2, or 3
      }
    """
    primary, fallback = _resolve_provider()
    prompt_hash       = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    # ── Etapa 2.6: Budget guard ───────────────────────────────────────────
    try:
        from infra.llm import llm_budget_guard
        budget = llm_budget_guard.check_budget()
        if not budget["allowed"]:
            logger.warning(
                "[LandingLLMExecutor] BLOCKED by budget guard: %s", budget["reason"]
            )
            return {
                "status":        "error",
                "html":          "",
                "model_used":    "none",
                "latency_ms":    0,
                "prompt_hash":   prompt_hash,
                "html_hash":     "",
                "error_type":    "LLMBudgetExceeded",
                "fallback_used": False,
                "stage_reached": 0,
            }
    except ImportError:
        pass  # budget guard not available — non-fatal
    except Exception as exc:
        logger.warning("[LandingLLMExecutor] Budget guard check failed (non-blocking): %s", exc)

    # Build the 3-stage chain
    stages = [
        {"stage": 1, "provider": primary,                  "model": _model_for(primary)},
        {"stage": 2, "provider": fallback,                 "model": _model_for(fallback)},
        {"stage": 3, "provider": _SECONDARY_SAFE_PROVIDER, "model": _SECONDARY_SAFE_MODEL},
    ]

    t0 = time.monotonic()

    for attempt in stages:
        result = _call_provider(
            prompt   = prompt,
            provider = attempt["provider"],
            model    = attempt["model"],
            stage    = attempt["stage"],
        )

        if result.get("status") == "ok" and result.get("content"):
            latency_ms = int((time.monotonic() - t0) * 1000)
            html       = result["content"]
            html_hash  = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]

            logger.info(
                "[LandingLLMExecutor] OK at stage=%d provider=%s latency=%dms len=%d",
                attempt["stage"], result.get("provider", attempt["provider"]),
                latency_ms, len(html),
            )
            return {
                "status":        "ok",
                "html":          html,
                "model_used":    result.get("provider", attempt["provider"]),
                "latency_ms":    latency_ms,
                "prompt_hash":   prompt_hash,
                "html_hash":     html_hash,
                "error_type":    None,
                "fallback_used": attempt["stage"] > 1,
                "stage_reached": attempt["stage"],
            }

        # Stage failed — log and continue to next stage
        logger.warning(
            "[LandingLLMExecutor] Stage %d FAILED provider=%s error=%s%s",
            attempt["stage"],
            result.get("provider", attempt["provider"]),
            result.get("error_type", "?"),
            " — trying next stage" if attempt["stage"] < 3 else " — all stages exhausted",
        )

    # All 3 stages failed— return structured error. Never raises.
    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.error(
        "[LandingLLMExecutor] TOTAL FAILURE: all 3 stages exhausted. latency=%dms",
        latency_ms,
    )
    return {
        "status":        "error",
        "html":          "",
        "model_used":    "none",
        "latency_ms":    latency_ms,
        "prompt_hash":   prompt_hash,
        "html_hash":     "",
        "error_type":    "LLMTotalFailure",
        "fallback_used": True,
        "stage_reached": 3,
    }


def execute_with_regen(
    prompt: str,
    orchestrator=None,
    cluster_id: str = "",
) -> dict:
    """
    Controlled regeneration loop (Etapa 2.6.4).

    Calls execute_landing_generation() up to MAX_LANDING_REGEN_ATTEMPTS times.
    Stops as soon as a successful result is returned.
    If all attempts fail, emits product_generation_aborted_event via orchestrator.

    Guarantees:
      - No infinite loop — bounded by MAX_LANDING_REGEN_ATTEMPTS
      - Each attempt independently logged
      - Never raises

    Returns the last result dict (ok or error).
    """
    last_result: dict = {}
    for attempt in range(1, MAX_LANDING_REGEN_ATTEMPTS + 1):
        logger.info(
            "[LandingLLMExecutor] Regen attempt %d/%d cluster_id=%s",
            attempt, MAX_LANDING_REGEN_ATTEMPTS, cluster_id,
        )
        last_result = execute_landing_generation(prompt)

        if last_result.get("status") == "ok":
            logger.info(
                "[LandingLLMExecutor] Regen succeeded at attempt %d cluster_id=%s",
                attempt, cluster_id,
            )
            return last_result

        logger.warning(
            "[LandingLLMExecutor] Regen attempt %d FAILED error=%s%s",
            attempt,
            last_result.get("error_type", "?"),
            " — retrying" if attempt < MAX_LANDING_REGEN_ATTEMPTS else " — all attempts exhausted",
        )

    # All attempts exhausted — emit abort event
    logger.error(
        "[LandingLLMExecutor] All %d regen attempts failed. Emitting product_generation_aborted_event.",
        MAX_LANDING_REGEN_ATTEMPTS,
    )
    if orchestrator is not None:
        try:
            from datetime import datetime, timezone
            orchestrator.receive_event(
                event_type="product_generation_aborted_event",
                payload={
                    "cluster_id":   cluster_id,
                    "attempts":     MAX_LANDING_REGEN_ATTEMPTS,
                    "error_type":   last_result.get("error_type", "LLMTotalFailure"),
                    "prompt_hash":  last_result.get("prompt_hash", ""),
                    "timestamp":    datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.error("[LandingLLMExecutor] Failed to emit abort event: %s", exc)

    return last_result
