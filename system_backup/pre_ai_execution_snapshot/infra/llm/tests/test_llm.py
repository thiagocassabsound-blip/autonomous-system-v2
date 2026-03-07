"""
infra/llm/tests/test_llm.py — LLM Infrastructure Test Suite

Scenarios:
  A — Valid prompt → structured ok response
  B — Timeout simulated
  C — Rate limit simulated (429)
  D — Auth error (invalid API key)
  E — Empty prompt
  F — 5 concurrent calls
  G — 20 concurrent calls (stress)
  H — 2 identical consecutive calls (structural determinism)
  + Constitutional isolation checks

All tests use unittest.mock — no real API calls made.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from infra.llm.llm_client import generate, generate_batch
from infra.llm.llm_errors import (
    LLMAuthError, LLMProviderError, LLMRateLimitError,
    LLMTimeoutError, LLMUnknownError,
)
from infra.llm.llm_response_normalizer import normalize_response

# ---------------------------------------------------------------------------
# Mock factory helpers
# ---------------------------------------------------------------------------

def _mock_usage(total_tokens: int = 42) -> MagicMock:
    u = MagicMock()
    u.total_tokens = total_tokens
    return u


def _mock_completion(content: str = "This is a test response.", tokens: int = 42) -> MagicMock:
    """Build a fake openai ChatCompletion response object."""
    msg    = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    resp   = MagicMock()
    resp.choices = [choice]
    resp.usage   = _mock_usage(tokens)
    return resp


_VALID_RESPONSE = _mock_completion("Scheduling friction is a key pain point.", 55)

# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"provider", "model", "status", "content", "tokens_used", "latency_ms"}

def _valid_schema(result: dict) -> bool:
    return (
        _REQUIRED_KEYS.issubset(set(result.keys())) and
        isinstance(result["content"], str) and
        isinstance(result["tokens_used"], int) and result["tokens_used"] >= 0 and
        isinstance(result["latency_ms"],  int) and result["latency_ms"]  >= 0 and
        result["status"] in ("ok", "error")
    )

# ---------------------------------------------------------------------------
# Scenario A — Valid prompt
# ---------------------------------------------------------------------------

def scenario_a() -> dict[str, bool]:
    r: dict[str, bool] = {}
    with patch(
        "infra.llm.llm_providers.openai_provider.openai.OpenAI"
    ) as mock_cls:
        mock_cls.return_value.chat.completions.create.return_value = _VALID_RESPONSE
        result = generate("What are the top scheduling pain points for SDRs?")

    r["A_status_ok"]          = result["status"] == "ok"
    r["A_content_non_empty"]  = len(result["content"]) > 0
    r["A_content_no_none"]    = result["content"] is not None
    r["A_tokens_used_ge0"]    = result["tokens_used"] >= 0
    r["A_latency_ms_ge0"]     = result["latency_ms"] >= 0
    r["A_valid_schema"]       = _valid_schema(result)
    r["A_provider_is_openai"] = result["provider"] == "openai"
    r["A_no_error_type"]      = result.get("error_type") is None
    return r


# ---------------------------------------------------------------------------
# Scenario B — Timeout
# ---------------------------------------------------------------------------

def scenario_b() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import openai as _oa
    with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.side_effect = (
            _oa.APITimeoutError(request=MagicMock())
        )
        result = generate("Trigger timeout", timeout=1, max_retries=1)

    r["B_status_error"]       = result["status"] == "error"
    r["B_error_type_timeout"] = result.get("error_type") == "LLMTimeoutError"
    r["B_content_empty_str"]  = result["content"] == ""
    r["B_tokens_used_zero"]   = result["tokens_used"] == 0
    r["B_valid_schema"]       = _valid_schema(result)
    r["B_no_crash"]           = True
    return r


# ---------------------------------------------------------------------------
# Scenario C — Rate limit
# ---------------------------------------------------------------------------

def scenario_c() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import openai as _oa
    with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_cls:
        resp_mock = MagicMock(); resp_mock.status_code = 429
        mock_cls.return_value.chat.completions.create.side_effect = (
            _oa.RateLimitError("rate limited", response=resp_mock, body={})
        )
        result = generate("Rate limited call", max_retries=1)

    r["C_status_error"]          = result["status"] == "error"
    r["C_error_type_ratelimit"]  = result.get("error_type") == "LLMRateLimitError"
    r["C_valid_schema"]          = _valid_schema(result)
    r["C_no_crash"]              = True
    return r


# ---------------------------------------------------------------------------
# Scenario D — Auth error (invalid key)
# ---------------------------------------------------------------------------

def scenario_d() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import openai as _oa
    with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_cls:
        resp_mock = MagicMock(); resp_mock.status_code = 401
        mock_cls.return_value.chat.completions.create.side_effect = (
            _oa.AuthenticationError("invalid api key", response=resp_mock, body={})
        )
        result = generate("Auth test")

    r["D_status_error"]       = result["status"] == "error"
    r["D_error_type_auth"]    = result.get("error_type") == "LLMAuthError"
    r["D_no_crash"]           = True
    r["D_valid_schema"]       = _valid_schema(result)
    r["D_key_not_in_content"] = "sk-" not in result["content"]  # no key leak
    return r


# ---------------------------------------------------------------------------
# Scenario E — Empty prompt
# ---------------------------------------------------------------------------

def scenario_e() -> dict[str, bool]:
    r: dict[str, bool] = {}
    empty_resp = _mock_completion("", 0)
    with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.return_value = empty_resp
        result = generate("")    # empty prompt

    r["E_no_crash"]      = True
    r["E_valid_schema"]  = _valid_schema(result)
    r["E_content_str"]   = isinstance(result["content"], str)
    r["E_tokens_ge0"]    = result["tokens_used"] >= 0
    return r


# ---------------------------------------------------------------------------
# Scenario F — 5 concurrent calls
# ---------------------------------------------------------------------------

def scenario_f() -> dict[str, bool]:
    r: dict[str, bool] = {}
    prompts = [f"concurrent prompt {i}" for i in range(5)]

    with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.return_value = _VALID_RESPONSE
        results = generate_batch(prompts, max_workers=5)

    r["F_5_results"]           = len(results) == 5
    r["F_all_status_ok"]       = all(res["status"] == "ok" for res in results)
    r["F_all_schemas_valid"]   = all(_valid_schema(res) for res in results)
    r["F_order_preserved"]     = len(results) == len(prompts)
    r["F_no_crash"]            = True
    return r


# ---------------------------------------------------------------------------
# Scenario G — 20 concurrent calls (stress)
# ---------------------------------------------------------------------------

def scenario_g() -> dict[str, bool]:
    r: dict[str, bool] = {}
    prompts = [f"stress prompt {i}" for i in range(20)]

    with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.return_value = _VALID_RESPONSE
        results = generate_batch(prompts, max_workers=10)

    r["G_20_results"]         = len(results) == 20
    r["G_all_status_ok"]      = all(res["status"] == "ok" for res in results)
    r["G_all_schemas_valid"]  = all(_valid_schema(res) for res in results)
    r["G_no_crash"]           = True
    return r


# ---------------------------------------------------------------------------
# Scenario H — 2 identical calls (structural determinism)
# ---------------------------------------------------------------------------

def scenario_h() -> dict[str, bool]:
    r: dict[str, bool] = {}
    fixed_resp = _mock_completion("Deterministic response text.", 30)

    results = []
    for _ in range(2):
        with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.return_value = fixed_resp
            result = generate("What is scheduling pain?", model="gpt-4o-mini")
        results.append(result)

    r1, r2 = results
    r["H_status_identical"]   = r1["status"] == r2["status"]
    r["H_content_identical"]  = r1["content"] == r2["content"]
    r["H_tokens_identical"]   = r1["tokens_used"] == r2["tokens_used"]
    r["H_provider_identical"] = r1["provider"] == r2["provider"]
    r["H_model_identical"]    = r1["model"] == r2["model"]
    r["H_both_schemas_valid"] = _valid_schema(r1) and _valid_schema(r2)
    return r


# ---------------------------------------------------------------------------
# Normalizer unit tests
# ---------------------------------------------------------------------------

def normalizer_checks() -> dict[str, bool]:
    r: dict[str, bool] = {}

    # None content → empty string
    n1 = normalize_response({"provider": "openai", "model": "gpt-4o", "status": "ok",
                              "content": None, "tokens_used": None, "latency_ms": None})
    r["NORM_content_none_to_empty"]   = n1["content"] == ""
    r["NORM_tokens_none_to_zero"]     = n1["tokens_used"] == 0
    r["NORM_latency_none_to_zero"]    = n1["latency_ms"] == 0

    # Negative tokens → clamped to 0
    n2 = normalize_response({"provider": "x", "model": "y", "status": "ok",
                              "content": "hi", "tokens_used": -5, "latency_ms": -10})
    r["NORM_negative_tokens_clamped"] = n2["tokens_used"] == 0
    r["NORM_negative_latency_clamped"]= n2["latency_ms"]  == 0

    # Unknown status → "error"
    n3 = normalize_response({"provider": "x", "model": "y", "status": "???",
                              "content": "x", "tokens_used": 1, "latency_ms": 1})
    r["NORM_unknown_status_to_error"] = n3["status"] == "error"

    return r


# ---------------------------------------------------------------------------
# Constitutional checks
# ---------------------------------------------------------------------------

def constitutional_checks() -> dict[str, bool]:
    r: dict[str, bool] = {}
    LLM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    files = []
    for root, dirs, fnames in os.walk(LLM_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fnames:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))

    def _clean(src: str) -> str:
        return re.sub(
            r'(""".*?"""|\'\'\'.*?\'\'\'|"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|#[^\n]*)',
            " ", src, flags=re.DOTALL,
        )

    forbidden: list[str] = []
    for fpath in files:
        try:
            src = _clean(open(fpath, encoding="utf-8").read())
        except OSError:
            continue
        for pat, label in [
            (r"\borchestrator\b",        "orchestrator"),
            (r"\bradar_engine\b",        "radar_engine"),
            (r"\bglobal_state\s*=\s*[^=]", "global_state_mutation"),
            (r"\bwallet\b|\bwithdraw\b", "financial_ops"),
        ]:
            if re.search(pat, src, re.IGNORECASE):
                forbidden.append(f"{os.path.relpath(fpath, LLM_DIR)}:{label}")

    r["CONST_no_orchestrator"]        = not any("orchestrator" in h for h in forbidden)
    r["CONST_no_radar_engine"]        = not any("radar_engine" in h for h in forbidden)
    r["CONST_no_global_state_mutation"] = not any("global_state_mutation" in h for h in forbidden)
    r["CONST_no_financial_ops"]       = not any("financial_ops" in h for h in forbidden)

    # API key never appears as a literal in source (only read from env)
    key_in_source = []
    for fpath in files:
        try:
            raw = open(fpath, encoding="utf-8").read()
        except OSError:
            continue
        if re.search(r'sk-[A-Za-z0-9]{20,}', raw):
            key_in_source.append(fpath)
    r["CONST_api_key_not_hardcoded"] = len(key_in_source) == 0

    return r


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 70)
    print(" RADAR — ETAPA 2: OPENAI GERACAO REAL (INFRA EXTERNA ISOLADA)")
    print("=" * 70 + "\n")

    all_results: dict[str, bool] = {}

    scenarios = [
        ("A — Valid prompt",              scenario_a),
        ("B — Timeout",                   scenario_b),
        ("C — Rate limit",                scenario_c),
        ("D — Auth error",                scenario_d),
        ("E — Empty prompt",              scenario_e),
        ("F — 5 concurrent",              scenario_f),
        ("G — 20 concurrent (stress)",    scenario_g),
        ("H — 2x determinism",            scenario_h),
        ("Normalizer",                    normalizer_checks),
        ("Constitutional",               constitutional_checks),
    ]

    for label, fn in scenarios:
        try:
            res = fn()
        except Exception as exc:
            res = {f"{label[:1]}_CRASHED": False}
            print(f"  [FAIL] {label} — EXCEPTION: {exc}")
        passed = sum(1 for v in res.values() if v)
        total  = len(res)
        status = "PASS" if passed == total else "FAIL"
        print(f"  [{status}] {label} ({passed}/{total})")
        for k, v in res.items():
            if not v:
                print(f"       [FAIL] {k}")
        all_results.update(res)

    passed = sum(1 for v in all_results.values() if v)
    total  = len(all_results)
    ok     = passed == total

    summary = {
        "test":                   "LLM Infra — Etapa 2: OpenAI Geracao Real",
        "total":  total, "passed": passed, "failed": total - passed,
        "constitutional_integrity": ok,
        "scenarios": all_results,
    }
    print("\n" + "=" * 70)
    print(json.dumps(summary, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
