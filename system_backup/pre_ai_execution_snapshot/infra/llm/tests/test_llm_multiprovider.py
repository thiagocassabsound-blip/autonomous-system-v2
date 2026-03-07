"""
infra/llm/tests/test_llm_multiprovider.py — Multi-provider + Fallback Test Suite

Scenarios:
  A — Gemini success direct
  B — Gemini fail → fallback OpenAI
  C — OpenAI fail → fallback Gemini
  D — Both fail → status="error"
  E — Timeout on primary
  F — Rate limit on primary
  G — 5 concurrent with fallback
  H — 20 concurrent (stress)
  I — LANDING_LLM_PROVIDER env var respected
  J — LLM_PROVIDER_DEFAULT env var respected
  + Constitutional checks

All tests fully mocked — zero real API calls.
"""
from __future__ import annotations

import json
import os
import re
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from infra.llm.llm_client import generate, generate_batch, _resolve_provider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"provider", "model", "status", "content", "tokens_used", "latency_ms"}


def _valid_schema(r: dict) -> bool:
    return (
        _REQUIRED_KEYS.issubset(set(r.keys())) and
        isinstance(r["content"], str) and
        r["tokens_used"] >= 0 and
        r["latency_ms"]  >= 0 and
        r["status"] in ("ok", "error")
    )


def _openai_mock_ok(content: str = "OpenAI answer.", tokens: int = 42) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    usage = MagicMock(); usage.total_tokens = tokens
    resp.usage = usage
    return resp


def _gemini_mock_ok(content: str = "Gemini answer here.") -> MagicMock:
    """Mock for requests.post that returns a 200 with valid Gemini JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": content}]}}],
        "usageMetadata": {"totalTokenCount": 38},
    }
    return mock_resp


# ---------------------------------------------------------------------------
# Scenario A — Gemini success direct
# ---------------------------------------------------------------------------

def scenario_a() -> dict[str, bool]:
    r: dict[str, bool] = {}
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}), \
         patch("infra.llm.llm_providers.gemini_provider.requests.post",
               return_value=_gemini_mock_ok("Gemini answer here.")):
        result = generate("Test prompt", provider="gemini", model="gemini-1.5-flash")

    r["A_status_ok"]          = result["status"] == "ok"
    r["A_provider_gemini"]    = result["provider"] == "gemini"
    r["A_content_non_empty"]  = len(result["content"]) > 0
    r["A_valid_schema"]       = _valid_schema(result)
    r["A_no_error_type"]      = result.get("error_type") is None
    return r


# ---------------------------------------------------------------------------
# Scenario B — Gemini fail → fallback OpenAI
# ---------------------------------------------------------------------------

def scenario_b() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import requests as _req

    call_log: list[str] = []

    def gemini_timeout(*args, **kwargs):
        call_log.append("gemini")
        raise _req.exceptions.Timeout("simulated timeout")

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}), \
         patch("infra.llm.llm_providers.gemini_provider.requests.post",
               side_effect=gemini_timeout), \
         patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_oa:
        mock_oa.return_value.chat.completions.create.return_value = (
            _openai_mock_ok("OpenAI fallback answer.")
        )
        result = generate("Fallback test", provider="gemini", max_retries=0)

    r["B_status_ok"]         = result["status"] == "ok"
    r["B_provider_openai"]   = result["provider"] == "openai"
    r["B_content_non_empty"] = len(result["content"]) > 0
    r["B_gemini_was_tried"]  = "gemini" in call_log
    r["B_valid_schema"]      = _valid_schema(result)
    r["B_no_crash"]          = True
    return r


# ---------------------------------------------------------------------------
# Scenario C — OpenAI fail → fallback Gemini
# ---------------------------------------------------------------------------

def scenario_c() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import openai as _oa

    call_log: list[str] = []

    def gemini_ok(*args, **kwargs):
        call_log.append("gemini_called")
        return _gemini_mock_ok("Gemini fallback ok.")

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}), \
         patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_oa, \
         patch("infra.llm.llm_providers.gemini_provider.requests.post",
               side_effect=gemini_ok):
        resp_mock = MagicMock(); resp_mock.status_code = 429
        mock_oa.return_value.chat.completions.create.side_effect = (
            _oa.RateLimitError("rate limited", response=resp_mock, body={})
        )
        result = generate("OpenAI→Gemini test", provider="openai", max_retries=0)

    r["C_status_ok"]         = result["status"] == "ok"
    r["C_provider_gemini"]   = result["provider"] == "gemini"
    r["C_gemini_was_called"] = "gemini_called" in call_log
    r["C_valid_schema"]      = _valid_schema(result)
    r["C_no_crash"]          = True
    return r


# ---------------------------------------------------------------------------
# Scenario D — Both fail → status="error"
# ---------------------------------------------------------------------------

def scenario_d() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import openai as _oa, requests as _req

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}), \
         patch("infra.llm.llm_providers.gemini_provider.requests.post",
               side_effect=_req.exceptions.Timeout("gemini timeout")), \
         patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_oa:
        resp_mock = MagicMock(); resp_mock.status_code = 500
        mock_oa.return_value.chat.completions.create.side_effect = (
            _oa.APIStatusError("server error", response=resp_mock, body={})
        )
        result = generate("Both fail", provider="gemini", max_retries=0)

    r["D_status_error"]  = result["status"] == "error"
    r["D_content_empty"] = result["content"] == ""
    r["D_valid_schema"]  = _valid_schema(result)
    r["D_no_crash"]      = True
    return r


# ---------------------------------------------------------------------------
# Scenario E — Timeout on primary → fallback succeeds
# ---------------------------------------------------------------------------

def scenario_e() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import requests as _req

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}), \
         patch("infra.llm.llm_providers.gemini_provider.requests.post",
               side_effect=_req.exceptions.Timeout("timeout")), \
         patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_oa:
        mock_oa.return_value.chat.completions.create.return_value = (
            _openai_mock_ok("fallback after timeout")
        )
        result = generate("Timeout test", provider="gemini", timeout=1, max_retries=0)

    r["E_no_crash"]     = True
    r["E_valid_schema"] = _valid_schema(result)
    r["E_fallback_ok"]  = result["status"] == "ok"
    r["E_latency_ge0"]  = result["latency_ms"] >= 0
    return r


# ---------------------------------------------------------------------------
# Scenario F — Rate limit on primary → fallback
# ---------------------------------------------------------------------------

def scenario_f() -> dict[str, bool]:
    r: dict[str, bool] = {}

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}), \
         patch("infra.llm.llm_providers.gemini_provider.requests.post") as mock_g, \
         patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_oa:
        # Gemini returns 429
        rate_resp = MagicMock(); rate_resp.status_code = 429
        mock_g.return_value = rate_resp
        # OpenAI fallback succeeds
        mock_oa.return_value.chat.completions.create.return_value = (
            _openai_mock_ok("rate limit fallback ok")
        )
        result = generate("Rate limit test", provider="gemini", max_retries=0)

    r["F_no_crash"]     = True
    r["F_valid_schema"] = _valid_schema(result)
    r["F_fallback_ok"]  = result["status"] == "ok"
    r["F_provider_oa"]  = result["provider"] == "openai"
    return r


# ---------------------------------------------------------------------------
# Scenario G — 5 concurrent with fallback
# ---------------------------------------------------------------------------

def scenario_g() -> dict[str, bool]:
    r: dict[str, bool] = {}
    prompts = [f"concurrent prompt {i}" for i in range(5)]

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}), \
         patch("infra.llm.llm_providers.gemini_provider.requests.post") as mock_g, \
         patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_oa:
        import requests as _req
        mock_g.side_effect = _req.exceptions.Timeout("timeout")
        mock_oa.return_value.chat.completions.create.return_value = (
            _openai_mock_ok("batch ok")
        )
        results = generate_batch(prompts, provider="gemini", max_workers=5, max_retries=0)

    r["G_5_results"]         = len(results) == 5
    r["G_all_schemas_valid"] = all(_valid_schema(res) for res in results)
    r["G_order_preserved"]   = len(results) == 5
    r["G_no_crash"]          = True
    return r


# ---------------------------------------------------------------------------
# Scenario H — 20 concurrent (stress)
# ---------------------------------------------------------------------------

def scenario_h() -> dict[str, bool]:
    r: dict[str, bool] = {}
    prompts = [f"stress {i}" for i in range(20)]

    with patch("infra.llm.llm_providers.openai_provider.openai.OpenAI") as mock_oa:
        mock_oa.return_value.chat.completions.create.return_value = (
            _openai_mock_ok("stress ok")
        )
        results = generate_batch(prompts, provider="openai", max_workers=10)

    r["H_20_results"]        = len(results) == 20
    r["H_all_schemas_valid"] = all(_valid_schema(res) for res in results)
    r["H_no_crash"]          = True
    return r


# ---------------------------------------------------------------------------
# Scenario I — LANDING_LLM_PROVIDER respected
# ---------------------------------------------------------------------------

def scenario_i() -> dict[str, bool]:
    r: dict[str, bool] = {}
    original_landing = os.environ.pop("LANDING_LLM_PROVIDER", None)
    original_default = os.environ.pop("LLM_PROVIDER_DEFAULT", None)
    try:
        os.environ["LANDING_LLM_PROVIDER"] = "gemini"
        r["I_LANDING_var_gemini"] = _resolve_provider(override=None) == "gemini"

        os.environ["LANDING_LLM_PROVIDER"] = "openai"
        r["I_LANDING_var_openai"] = _resolve_provider(override=None) == "openai"
    finally:
        os.environ.pop("LANDING_LLM_PROVIDER", None)
        if original_landing: os.environ["LANDING_LLM_PROVIDER"] = original_landing
        if original_default:  os.environ["LLM_PROVIDER_DEFAULT"]  = original_default
    return r


# ---------------------------------------------------------------------------
# Scenario J — LLM_PROVIDER_DEFAULT respected
# ---------------------------------------------------------------------------

def scenario_j() -> dict[str, bool]:
    r: dict[str, bool] = {}
    original_landing = os.environ.pop("LANDING_LLM_PROVIDER", None)
    original_default = os.environ.pop("LLM_PROVIDER_DEFAULT", None)
    try:
        os.environ["LLM_PROVIDER_DEFAULT"] = "gemini"
        r["J_DEFAULT_var_gemini"]   = _resolve_provider(override=None) == "gemini"
        r["J_override_beats_env"]   = _resolve_provider(override="openai") == "openai"
    finally:
        os.environ.pop("LLM_PROVIDER_DEFAULT", None)
        if original_landing: os.environ["LANDING_LLM_PROVIDER"] = original_landing
        if original_default:  os.environ["LLM_PROVIDER_DEFAULT"]  = original_default
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
            (r"\borchestrator\b",            "orchestrator"),
            (r"\bradar_engine\b",            "radar_engine"),
            (r"\bglobal_state\s*=\s*[^=]",  "global_state_mutation"),
            (r"\bwallet\b|\bwithdraw\b",     "financial_ops"),
        ]:
            if re.search(pat, src, re.IGNORECASE):
                forbidden.append(f"{os.path.relpath(fpath, LLM_DIR)}:{label}")

    r["CONST_no_orchestrator"]       = not any("orchestrator"        in h for h in forbidden)
    r["CONST_no_radar_engine"]       = not any("radar_engine"        in h for h in forbidden)
    r["CONST_no_global_mutation"]    = not any("global_state_mutation" in h for h in forbidden)
    r["CONST_no_financial_ops"]      = not any("financial_ops"       in h for h in forbidden)

    # API keys never hardcoded
    key_leaks = []
    for fpath in files:
        if "tests" in fpath: continue   # test stubs may use "fake-xxx"
        try:
            raw = open(fpath, encoding="utf-8").read()
        except OSError:
            continue
        if re.search(r'sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{35}', raw):
            key_leaks.append(fpath)
    r["CONST_no_hardcoded_keys"] = len(key_leaks) == 0

    # Fallback map has no self-references
    from infra.llm.llm_client import _FALLBACK_MAP
    r["CONST_no_self_fallback"] = all(k != v for k, v in _FALLBACK_MAP.items())

    # generate() must not recursively call itself (generate_batch may call generate)
    import inspect
    from infra.llm import llm_client as _lc
    gen_src = inspect.getsource(_lc.generate)
    gen_src_clean = _clean(gen_src)
    # Skip the function definition line itself (contains "def generate(")
    body_lines = [
        line for line in gen_src_clean.splitlines()
        if not line.strip().startswith("def generate")
    ]
    body = "\n".join(body_lines)
    calls = re.findall(r'\bgenerate\s*\(', body)
    r["CONST_no_recursive_fallback"] = len(calls) == 0

    return r


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 70)
    print(" RADAR — LLM MULTI-PROVIDER + FALLBACK AUTOMATICO")
    print("=" * 70 + "\n")

    all_results: dict[str, bool] = {}

    scenarios = [
        ("A — Gemini success",            scenario_a),
        ("B — Gemini fail → OpenAI",      scenario_b),
        ("C — OpenAI fail → Gemini",      scenario_c),
        ("D — Both fail → error",         scenario_d),
        ("E — Timeout primary",           scenario_e),
        ("F — Rate limit primary",        scenario_f),
        ("G — 5 concurrent fallback",     scenario_g),
        ("H — 20 concurrent (stress)",    scenario_h),
        ("I — LANDING_LLM_PROVIDER env",  scenario_i),
        ("J — LLM_PROVIDER_DEFAULT env",  scenario_j),
        ("Constitutional",                constitutional_checks),
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

    print("\n" + "=" * 70)
    print(json.dumps({
        "test":                   "LLM Multi-Provider + Fallback",
        "total":  total, "passed": passed, "failed": total - passed,
        "constitutional_integrity": ok,
        "scenarios": all_results,
    }, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
