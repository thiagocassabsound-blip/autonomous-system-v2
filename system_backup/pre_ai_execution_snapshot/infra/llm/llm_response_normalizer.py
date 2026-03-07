"""
infra/llm/llm_response_normalizer.py — Normalize raw LLM provider output.

Guarantees:
  • content is always a str (empty string if provider returned None/empty)
  • tokens_used is always int >= 0
  • latency_ms is always int >= 0
  • No None values in the returned dict
  • provider and model are always present strings
"""
from __future__ import annotations


def normalize_response(raw: dict) -> dict:
    """
    Accept a raw result dict (possibly containing None/missing fields)
    and return a fully normalized, always-valid LLM response dict.

    Output schema:
      provider     : str
      model        : str
      status       : "ok" | "error"
      content      : str          (never None; "" on error/empty)
      tokens_used  : int          (>= 0)
      latency_ms   : int          (>= 0)
      error_type   : str | None   (only present on error)
    """
    provider    = str(raw.get("provider", "unknown") or "unknown")
    model       = str(raw.get("model",    "unknown") or "unknown")
    status      = raw.get("status", "error")
    if status not in ("ok", "error"):
        status = "error"

    content_raw = raw.get("content")
    content = str(content_raw).strip() if content_raw is not None else ""

    try:
        tokens_used = max(0, int(raw.get("tokens_used") or 0))
    except (TypeError, ValueError):
        tokens_used = 0

    try:
        latency_ms = max(0, int(raw.get("latency_ms") or 0))
    except (TypeError, ValueError):
        latency_ms = 0

    error_type = raw.get("error_type")
    if error_type is not None:
        error_type = str(error_type)

    result: dict = {
        "provider":    provider,
        "model":       model,
        "status":      status,
        "content":     content,
        "tokens_used": tokens_used,
        "latency_ms":  latency_ms,
    }
    if error_type:
        result["error_type"] = error_type

    return result
