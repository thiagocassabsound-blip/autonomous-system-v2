"""
infra/rss/tests/test_rss.py — RSS Parsing Test Suite

Scenarios:
  A — Valid feed (≥10 entries)
  B — Invalid URL
  C — Timeout simulated
  D — Malformed XML
  E — Empty feed
  F — 2 consecutive runs (dedupe)
  G — 10 concurrent feeds
  H — 50 concurrent feeds (stress)
  + Constitutional checks (isolation)

All scenarios run fully offline using unittest.mock / local XML fixtures.
No real HTTP calls are made.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from infra.rss.rss_cache import RSSCache, _entry_hash
from infra.rss.rss_client import fetch_feed, fetch_feeds
from infra.rss.rss_errors import RSSFetchTimeout, RSSHTTPError, RSSInvalidXML, RSSUnknownError
from infra.rss.rss_normalizer import normalize_entry, normalize_feed

# ---------------------------------------------------------------------------
# RSS XML fixtures
# ---------------------------------------------------------------------------

def _make_rss_xml(n_items: int = 10) -> bytes:
    items = ""
    for i in range(n_items):
        items += f"""
        <item>
          <title>Entry {i}: Scheduling pain in SaaS teams</title>
          <link>https://example.com/entry/{i}</link>
          <pubDate>Tue, 03 Mar 2026 10:00:00 +0000</pubDate>
          <description>&lt;p&gt;Pain point #{i}: calendar scheduling friction.&lt;/p&gt;</description>
        </item>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test RSS Feed</title>
    <link>https://example.com</link>
    <description>Test feed for RSS parsing validation</description>
    {items}
  </channel>
</rss>""".encode("utf-8")


_EMPTY_FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
    <link>https://example.com</link>
    <description>No items</description>
  </channel>
</rss>"""

_MALFORMED_XML = b"<?xml NOT VALID XML <><< broken feed content"


def _mock_response(content: bytes, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    return resp


# ---------------------------------------------------------------------------
# Scenario A — Valid feed with ≥10 entries
# ---------------------------------------------------------------------------

def scenario_a() -> dict[str, bool]:
    r: dict[str, bool] = {}
    xml_content = _make_rss_xml(12)

    with patch("requests.get", return_value=_mock_response(xml_content)):
        result = fetch_feed("https://example.com/feed.rss", timeout=5)

    r["A_status_ok"]           = result["status"] == "ok"
    r["A_entries_ge10"]        = len(result["entries"]) >= 10
    r["A_no_error_type"]       = result["error_type"] is None
    r["A_each_has_title"]      = all("title" in e for e in result["entries"])
    r["A_each_has_link"]       = all("link" in e for e in result["entries"])
    r["A_published_at_utc"]    = all(
        e.get("published_at", "").endswith("Z")
        for e in result["entries"]
        if "published_at" in e
    )
    r["A_html_stripped"]       = all(
        "<" not in e.get("summary", "") for e in result["entries"]
    )
    r["A_source_url_preserved"] = all(
        e.get("source") == "https://example.com/feed.rss"
        for e in result["entries"]
    )
    return r


# ---------------------------------------------------------------------------
# Scenario B — Invalid URL (connection error)
# ---------------------------------------------------------------------------

def scenario_b() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import requests as _req

    with patch("requests.get", side_effect=_req.exceptions.ConnectionError("no route to host")):
        result = fetch_feed("https://invalid-url-xyz.example.com/feed", timeout=2, max_retries=1)

    r["B_status_error"]           = result["status"] == "error"
    r["B_entries_empty"]          = result["entries"] == []
    r["B_error_type_set"]         = result["error_type"] in ("RSSUnknownError",)
    r["B_no_crash"]               = True  # reaching here proves no exception leaked
    return r


# ---------------------------------------------------------------------------
# Scenario C — Timeout simulated
# ---------------------------------------------------------------------------

def scenario_c() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import requests as _req

    with patch("requests.get", side_effect=_req.exceptions.Timeout("timed out")):
        result = fetch_feed("https://example.com/slow-feed", timeout=1, max_retries=1)

    r["C_status_error"]      = result["status"] == "error"
    r["C_error_type_timeout"] = result["error_type"] == "RSSFetchTimeout"
    r["C_no_crash"]           = True
    r["C_entries_empty"]      = result["entries"] == []
    return r


# ---------------------------------------------------------------------------
# Scenario D — Malformed XML
# ---------------------------------------------------------------------------

def scenario_d() -> dict[str, bool]:
    r: dict[str, bool] = {}
    with patch("requests.get", return_value=_mock_response(_MALFORMED_XML)):
        result = fetch_feed("https://example.com/broken-feed", timeout=5, max_retries=1)

    # feedparser is lenient with some malformed XML; it may still parse partly.
    # The key guarantee: status is either "ok" with 0 entries OR "error" — never a crash.
    r["D_no_crash"]         = True
    r["D_valid_result_shape"] = (
        "status" in result and
        "entries" in result and
        isinstance(result["entries"], list)
    )
    r["D_status_is_ok_or_error"] = result["status"] in ("ok", "error")
    return r


# ---------------------------------------------------------------------------
# Scenario E — Empty feed
# ---------------------------------------------------------------------------

def scenario_e() -> dict[str, bool]:
    r: dict[str, bool] = {}
    with patch("requests.get", return_value=_mock_response(_EMPTY_FEED_XML)):
        result = fetch_feed("https://example.com/empty-feed", timeout=5)

    r["E_status_ok"]       = result["status"] == "ok"
    r["E_entries_empty"]   = len(result["entries"]) == 0
    r["E_no_error_type"]   = result["error_type"] is None
    r["E_no_crash"]        = True
    return r


# ---------------------------------------------------------------------------
# Scenario F — 2 consecutive runs (deduplication)
# ---------------------------------------------------------------------------

def scenario_f() -> dict[str, bool]:
    r: dict[str, bool] = {}
    xml_content = _make_rss_xml(10)

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = os.path.join(tmp, "rss_cache.jsonl")
        cache = RSSCache(cache_path=cache_path)

        # Run 1
        with patch("requests.get", return_value=_mock_response(xml_content)):
            result1 = fetch_feed("https://example.com/feed.rss")
        new1 = cache.filter_new(result1["entries"])

        # Run 2 — same feed, same content
        with patch("requests.get", return_value=_mock_response(xml_content)):
            result2 = fetch_feed("https://example.com/feed.rss")
        new2 = cache.filter_new(result2["entries"])

        r["F_run1_returns_10_new"]   = len(new1) == 10
        r["F_run2_returns_0_new"]    = len(new2) == 0
        r["F_cache_has_10_hashes"]   = cache.size == 10
        cache_lines = []
        with open(cache_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    cache_lines.append(json.loads(line))
        r["F_cache_jsonl_append_only"] = len(cache_lines) == 10  # exactly 10, not 20

    return r


# ---------------------------------------------------------------------------
# Scenario G — 10 concurrent feeds
# ---------------------------------------------------------------------------

def scenario_g() -> dict[str, bool]:
    r: dict[str, bool] = {}
    xml_content = _make_rss_xml(5)

    urls = [f"https://example.com/feed-{i}.rss" for i in range(10)]
    with patch("requests.get", return_value=_mock_response(xml_content)):
        results = fetch_feeds(urls, max_workers=10)

    r["G_all_10_results"]        = len(results) == 10
    r["G_all_status_ok"]         = all(res["status"] == "ok" for res in results)
    r["G_all_have_entries"]      = all(len(res["entries"]) == 5 for res in results)
    r["G_order_preserved"]       = [res["source_url"] for res in results] == urls
    r["G_no_crash"]              = True
    return r


# ---------------------------------------------------------------------------
# Scenario H — 50 concurrent feeds (stress)
# ---------------------------------------------------------------------------

def scenario_h() -> dict[str, bool]:
    r: dict[str, bool] = {}
    xml_content = _make_rss_xml(3)

    urls = [f"https://example.com/stress-{i}.rss" for i in range(50)]
    with patch("requests.get", return_value=_mock_response(xml_content)):
        results = fetch_feeds(urls, max_workers=20)

    r["H_all_50_results"]    = len(results) == 50
    r["H_all_status_ok"]     = all(res["status"] == "ok" for res in results)
    r["H_no_crash"]          = True
    r["H_total_entries_150"] = sum(len(res["entries"]) for res in results) == 150
    return r


# ---------------------------------------------------------------------------
# Constitutional checks
# ---------------------------------------------------------------------------

def constitutional_checks() -> dict[str, bool]:
    r: dict[str, bool] = {}
    import re

    INFRA_RSS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    files = []
    for root, dirs, fnames in os.walk(INFRA_RSS_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fnames:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))

    def _clean(src):
        return re.sub(
            r'(""".*?"""|\'\'\'.*?\'\'\'|"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|#[^\n]*)',
            " ", src, flags=re.DOTALL,
        )

    forbidden_hits: list[str] = []
    for fpath in files:
        try:
            src = _clean(open(fpath, encoding="utf-8").read())
        except OSError:
            continue
        for pat in [
            r"orchestrator",
            r"\bradar\b",
            r"\bwallet\b",
            r"\bcapital\b",
            r"\bglobal_state\s*=\s*[^=]",
        ]:
            if re.search(pat, src, re.IGNORECASE):
                forbidden_hits.append(f"{os.path.relpath(fpath, INFRA_RSS_DIR)}:{pat}")

    r["CONST_no_orchestrator_refs"]     = not any("orchestrator" in h for h in forbidden_hits)
    r["CONST_no_radar_import"]          = not any(":.*\\bradar\\b" in h for h in forbidden_hits)
    r["CONST_no_financial_ops"]         = not any(("\\bwallet\\b" in h or "\\bcapital\\b" in h)
                                                    for h in forbidden_hits)
    r["CONST_no_global_state_mutation"] = not any("global_state" in h for h in forbidden_hits)
    return r


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 70)
    print(" RADAR — ETAPA 2: RSS PARSING REAL (INFRA EXTERNA ISOLADA)")
    print("=" * 70 + "\n")

    all_results: dict[str, bool] = {}

    scenarios = [
        ("A — Valid feed (≥10 entries)",        scenario_a),
        ("B — Invalid URL",                      scenario_b),
        ("C — Timeout simulated",                scenario_c),
        ("D — Malformed XML",                    scenario_d),
        ("E — Empty feed",                       scenario_e),
        ("F — 2 runs dedupe",                    scenario_f),
        ("G — 10 concurrent feeds",              scenario_g),
        ("H — 50 concurrent feeds (stress)",     scenario_h),
        ("Constitutional",                       constitutional_checks),
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
        "test":                   "RSS Parsing — Etapa 2",
        "total":  total, "passed": passed, "failed": total - passed,
        "constitutional_integrity": ok,
        "scenarios": all_results,
    }
    print("\n" + "=" * 70)
    print(json.dumps(summary, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
