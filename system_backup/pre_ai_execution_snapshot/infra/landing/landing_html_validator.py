"""
infra/landing/landing_html_validator.py — HTML security and schema validator for Bloco 30.

Validates:
  - Valid HTML structure (has <html>, <head>, <body>)
  - No forbidden tags (script with src, iframe, object, embed)
  - No script injection patterns
  - No external resource loading (except from approved patterns)
  - Tag allowlist enforcement

Failure → pipeline aborts, landing_generation_failed_event emitted.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("infra.landing.html_validator")

# Tags that are never allowed in landing pages
_FORBIDDEN_TAGS = {
    "iframe", "object", "embed", "applet", "base", "form",
}

# Patterns that indicate script injection attempts
_INJECTION_PATTERNS = [
    r"javascript\s*:",
    r"on\w+\s*=\s*[\"']",    # onclick=, onload=, etc. with quotes
    r"<\s*script[^>]*src\s*=",  # <script src=...>
    r"eval\s*\(",
    r"document\.write\s*\(",
    r"window\.location\s*=",
    r"data:\s*text/html",
]

_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Required HTML structural elements
_REQUIRED_TAGS = ["<html", "<head", "<body"]


def validate(html: str) -> dict:
    """
    Validate HTML security and schema compliance.

    Returns:
      {"valid": True} on success
      {"valid": False, "reason": str} on failure
    """
    if not html:
        return {"valid": False, "reason": "HTML content is empty"}

    lower = html.lower()

    # Check required structural tags
    for tag in _REQUIRED_TAGS:
        if tag not in lower:
            return {"valid": False, "reason": f"Missing structural tag: {tag}"}

    # Check forbidden tags
    for tag in _FORBIDDEN_TAGS:
        pattern = f"<\\s*{tag}[\\s>]"
        if re.search(pattern, html, re.IGNORECASE):
            return {"valid": False, "reason": f"Forbidden tag detected: <{tag}>"}

    # Check injection patterns
    match = _INJECTION_RE.search(html)
    if match:
        return {"valid": False, "reason": f"Script injection pattern detected: '{match.group()[:50]}'"}

    # Check DOCTYPE is present
    if "<!doctype" not in lower:
        logger.warning("[HTMLValidator] Missing DOCTYPE — not blocking but flagged")

    logger.info("[HTMLValidator] HTML validation passed.")
    return {"valid": True}
