"""
infra/landing/tests/test_bloco30.py — Test suite for Bloco 30 Landing Engine.

Tests:
  1. Idempotency by cluster_id (no double product creation)
  2. Cluster index reconstruction after restart
  3. Snapshot append-only persistence
  4. Pipeline controlled failure (landing_generation_failed_event emitted)
  5. Structure validator rules
  6. HTML validator rules
  7. Five-second rule evaluator
  8. Version computation
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Ensure the project root is in sys.path for imports
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestLandingSnapshot(unittest.TestCase):
    """Tests for landing_snapshot.py: append-only persistence and index building."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.snapshot_path = Path(self.tmpdir.name) / "landing_snapshots.jsonl"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_snapshots(self, records):
        with open(self.snapshot_path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def test_append_snapshot_creates_file(self):
        from infra.landing.landing_snapshot import append_snapshot, _snapshot_path
        with patch("infra.landing.landing_snapshot._snapshot_path", return_value=self.snapshot_path):
            rec = append_snapshot(
                event_id="evt-001",
                product_id="prod-001",
                cluster_id="cluster-A",
                prompt_hash="abc123",
                model_used="gemini",
                latency_ms=1200,
                validation_passed=True,
                html_hash="def456",
                version=1,
            )
        self.assertTrue(self.snapshot_path.exists())
        self.assertEqual(rec["product_id"], "prod-001")
        self.assertEqual(rec["version"], 1)

    def test_append_snapshot_is_append_only(self):
        from infra.landing.landing_snapshot import append_snapshot
        with patch("infra.landing.landing_snapshot._snapshot_path", return_value=self.snapshot_path):
            for i in range(3):
                append_snapshot(
                    event_id=f"evt-{i}",
                    product_id=f"prod-{i}",
                    cluster_id="cluster-A",
                    prompt_hash="x",
                    model_used="gemini",
                    latency_ms=100,
                    validation_passed=True,
                    html_hash="y",
                    version=i + 1,
                )
        lines = self.snapshot_path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 3)

    def test_load_snapshots_empty_when_file_missing(self):
        from infra.landing.landing_snapshot import load_snapshots
        with patch("infra.landing.landing_snapshot._snapshot_path", return_value=self.snapshot_path):
            result = load_snapshots()
        self.assertEqual(result, [])

    def test_build_cluster_index_last_wins(self):
        from infra.landing.landing_snapshot import build_cluster_index
        records = [
            {"cluster_id": "A", "product_id": "prod-1"},
            {"cluster_id": "A", "product_id": "prod-2"},  # second wins
            {"cluster_id": "B", "product_id": "prod-3"},
        ]
        index = build_cluster_index(records)
        self.assertEqual(index["A"], "prod-2")
        self.assertEqual(index["B"], "prod-3")

    def test_build_cluster_index_skips_incomplete_records(self):
        from infra.landing.landing_snapshot import build_cluster_index
        records = [
            {"cluster_id": "", "product_id": "prod-1"},
            {"cluster_id": "B"},                          # missing product_id
            {"cluster_id": "C", "product_id": "prod-3"},
        ]
        index = build_cluster_index(records)
        self.assertNotIn("", index)
        self.assertNotIn("B", index)
        self.assertEqual(index["C"], "prod-3")


class TestLandingVersioning(unittest.TestCase):
    """Tests for landing_versioning.py."""

    def test_compute_version_starts_at_1(self):
        from infra.landing import landing_versioning
        with patch("infra.landing.landing_versioning.load_snapshots", return_value=[]):
            v = landing_versioning.compute_version("cluster-A")
        self.assertEqual(v, 1)

    def test_compute_version_increments_correctly(self):
        from infra.landing import landing_versioning
        existing = [
            {"cluster_id": "cluster-A", "version": 1},
            {"cluster_id": "cluster-A", "version": 2},
            {"cluster_id": "cluster-B", "version": 1},
        ]
        with patch("infra.landing.landing_versioning.load_snapshots", return_value=existing):
            v_a = landing_versioning.compute_version("cluster-A")
            v_b = landing_versioning.compute_version("cluster-B")
        self.assertEqual(v_a, 3)
        self.assertEqual(v_b, 2)


class TestLandingStructureValidator(unittest.TestCase):
    """Tests for landing_structure_validator.py."""

    def _valid_html(self):
        return """<!DOCTYPE html>
<html><head><title>Test</title></head>
<body>
<h1>Transform Your Life in 30 Days</h1>
<h2>The fastest path to real results</h2>
<ul><li>Benefit one</li><li>Benefit two</li><li>Benefit three</li></ul>
<button id="checkout-btn">Get Started Now</button>
</body></html>"""

    def test_valid_html_passes(self):
        from infra.landing import landing_structure_validator
        result = landing_structure_validator.validate(self._valid_html())
        self.assertTrue(result["valid"])

    def test_missing_h1_fails(self):
        from infra.landing import landing_structure_validator
        html = self._valid_html().replace("<h1>", "<h3>").replace("</h1>", "</h3>")
        result = landing_structure_validator.validate(html)
        self.assertFalse(result["valid"])
        self.assertIn("h1", result["reason"].lower())

    def test_missing_cta_fails(self):
        from infra.landing import landing_structure_validator
        html = self._valid_html().replace('id="checkout-btn"', 'id="other-btn"')
        result = landing_structure_validator.validate(html)
        self.assertFalse(result["valid"])
        self.assertIn("CTA", result["reason"])

    def test_placeholder_text_fails(self):
        from infra.landing import landing_structure_validator
        html = self._valid_html().replace("Benefit one", "[INSERT YOUR BENEFIT]")
        result = landing_structure_validator.validate(html)
        self.assertFalse(result["valid"])
        self.assertIn("Placeholder", result["reason"])

    def test_insufficient_bullets_fails(self):
        from infra.landing import landing_structure_validator
        html = self._valid_html().replace(
            "<ul><li>Benefit one</li><li>Benefit two</li><li>Benefit three</li></ul>",
            "<ul><li>Only one bullet</li></ul>"
        )
        result = landing_structure_validator.validate(html)
        self.assertFalse(result["valid"])


class TestLandingHTMLValidator(unittest.TestCase):
    """Tests for landing_html_validator.py."""

    def test_valid_html_passes(self):
        from infra.landing import landing_html_validator
        html = "<!DOCTYPE html><html><head></head><body><h1>Test</h1></body></html>"
        result = landing_html_validator.validate(html)
        self.assertTrue(result["valid"])

    def test_forbidden_iframe_fails(self):
        from infra.landing import landing_html_validator
        html = "<!DOCTYPE html><html><head></head><body><iframe src='x'></iframe></body></html>"
        result = landing_html_validator.validate(html)
        self.assertFalse(result["valid"])
        self.assertIn("iframe", result["reason"])

    def test_script_injection_fails(self):
        from infra.landing import landing_html_validator
        html = '<!DOCTYPE html><html><head></head><body onclick="evil()"></body></html>'
        result = landing_html_validator.validate(html)
        self.assertFalse(result["valid"])

    def test_javascript_scheme_fails(self):
        from infra.landing import landing_html_validator
        html = '<!DOCTYPE html><html><head></head><body><a href="javascript:alert(1)">x</a></body></html>'
        result = landing_html_validator.validate(html)
        self.assertFalse(result["valid"])


class TestFiveSecondRule(unittest.TestCase):
    """Tests for landing_five_second_rule.py."""

    def _valid_html(self):
        return (
            '<!DOCTYPE html>\n'
            '<html><head></head><body>\n'
            '<h1>Learn Python and Build Your First App in 30 Days</h1>\n'
            '<h2>Proven method for complete beginners without any experience</h2>\n'
            '<p>Get real results in 30 days. Proven by 10000 students.</p>\n'
            '<ul><li>Step-by-step training</li>'
            '<li>Daily practice sessions</li>'
            '<li>Live coaching</li></ul>\n'
            '<button id="checkout-btn">Get Started Now</button>\n'
            '</body></html>'
        )

    def test_valid_html_passes(self):
        from infra.landing import landing_five_second_rule
        result = landing_five_second_rule.validate(self._valid_html())
        self.assertTrue(result["valid"])

    def test_missing_h1_fails(self):
        from infra.landing import landing_five_second_rule
        html = self._valid_html().replace("<h1>", "<h3>").replace("</h1>", "</h3>")
        result = landing_five_second_rule.validate(html)
        self.assertFalse(result["valid"])

    def test_content_too_short_fails(self):
        from infra.landing import landing_five_second_rule
        result = landing_five_second_rule.validate("<html><body><h1>Hi</h1></body></html>")
        self.assertFalse(result["valid"])


class TestIdempotency(unittest.TestCase):
    """Tests for idempotency logic in landing_recommendation_handler.py."""

    def setUp(self):
        # Reset module-level state before each test
        import importlib
        import infra.landing.landing_recommendation_handler as mod
        mod._cluster_index.clear()
        mod._recommendation_payload_store.clear()
        mod._bootstrapped = False

    def test_duplicate_cluster_id_is_ignored(self):
        """Handler must not emit product_creation_requested for a known cluster_id."""
        import infra.landing.landing_recommendation_handler as mod
        mod._cluster_index["cluster-X"] = "existing-product-id"

        mock_orchestrator = MagicMock()
        payload = {
            "cluster_id":        "cluster-X",
            "ice":               "ALTO",
            "emotional_score":   80.0,
            "monetization_score": 75.0,
            "growth_percent":    25.0,
        }
        mod.handle(orchestrator=mock_orchestrator, payload=payload)
        mock_orchestrator.receive_event.assert_not_called()

    def test_bloqueado_ice_is_ignored(self):
        """Handler must not proceed when ICE == BLOQUEADO."""
        import infra.landing.landing_recommendation_handler as mod
        mock_orchestrator = MagicMock()
        payload = {
            "cluster_id": "cluster-Y",
            "ice":        "BLOQUEADO",
        }
        mod.handle(orchestrator=mock_orchestrator, payload=payload)
        mock_orchestrator.receive_event.assert_not_called()

    def test_new_cluster_emits_product_creation_requested(self):
        """Handler must emit product_creation_requested for a new, valid cluster_id."""
        import infra.landing.landing_recommendation_handler as mod
        mock_orchestrator = MagicMock()
        payload = {
            "cluster_id":         "cluster-NEW",
            "ice":                "ALTO",
            "emotional_score":    80.0,
            "monetization_score": 78.0,
            "growth_percent":     30.0,
            "justification_summary": "Strong demand in target market.",
        }
        mod.handle(orchestrator=mock_orchestrator, payload=payload)

        mock_orchestrator.receive_event.assert_called_once()
        call_kwargs = mock_orchestrator.receive_event.call_args
        assert call_kwargs.kwargs.get("event_type") == "product_creation_requested" or \
               (len(call_kwargs.args) > 0 and call_kwargs.args[0] == "product_creation_requested")

    def test_bootstrap_reconstructs_index_from_snapshots(self):
        """Bootstrap must rebuild cluster_index from landing_snapshots.jsonl."""
        import infra.landing.landing_recommendation_handler as mod

        snapshots = [
            {"cluster_id": "cluster-A", "product_id": "prod-111"},
            {"cluster_id": "cluster-B", "product_id": "prod-222"},
        ]
        mock_bus = MagicMock()
        mock_orchestrator = MagicMock()

        with patch("infra.landing.landing_recommendation_handler.load_snapshots", return_value=snapshots):
            with patch("infra.landing.landing_recommendation_handler.build_cluster_index",
                       return_value={"cluster-A": "prod-111", "cluster-B": "prod-222"}):
                mod.bootstrap(event_bus=mock_bus, orchestrator=mock_orchestrator)

        self.assertIn("cluster-A", mod._cluster_index)
        self.assertIn("cluster-B", mod._cluster_index)
        self.assertEqual(mod._cluster_index["cluster-A"], "prod-111")
        mock_bus.subscribe.assert_called_once_with("product_draft_created", unittest.mock.ANY)

    def test_bootstrap_safe_with_empty_snapshots(self):
        """Bootstrap must work correctly when no snapshots exist yet."""
        import infra.landing.landing_recommendation_handler as mod
        mock_bus = MagicMock()
        mock_orchestrator = MagicMock()

        with patch("infra.landing.landing_recommendation_handler.load_snapshots", return_value=[]):
            mod.bootstrap(event_bus=mock_bus, orchestrator=mock_orchestrator)

        self.assertEqual(len(mod._cluster_index), 0)


class TestLandingLLMProviderSelection(unittest.TestCase):
    """
    Tests for LANDING_LLM_PROVIDER env var selection in landing_llm_executor.py.

    Scenario 1: LANDING_LLM_PROVIDER=gemini  -> primary=gemini,  fallback=openai
    Scenario 2: LANDING_LLM_PROVIDER=openai  -> primary=openai,  fallback=gemini
    Scenario 3: Env var absent               -> primary=gemini,  fallback=openai (default)
    """

    def setUp(self):
        from infra.llm import llm_budget_guard
        llm_budget_guard.reset_for_testing()

    def test_scenario1_gemini_explicit(self):
        """LANDING_LLM_PROVIDER=gemini selects gemini as primary, openai as fallback."""
        from infra.landing.landing_llm_executor import _resolve_provider, _model_for
        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "gemini"}):
            primary, fallback = _resolve_provider()
        self.assertEqual(primary,  "gemini")
        self.assertEqual(fallback, "openai")
        self.assertIn("gemini", _model_for(primary))

    def test_scenario2_openai_explicit(self):
        """LANDING_LLM_PROVIDER=openai selects openai as primary, gemini as fallback."""
        from infra.landing.landing_llm_executor import _resolve_provider, _model_for
        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "openai"}):
            primary, fallback = _resolve_provider()
        self.assertEqual(primary,  "openai")
        self.assertEqual(fallback, "gemini")
        self.assertIn("gpt", _model_for(primary))

    def test_scenario3_absent_defaults_to_gemini(self):
        """Absent LANDING_LLM_PROVIDER defaults to gemini primary, openai fallback."""
        from infra.landing.landing_llm_executor import _resolve_provider
        env = {k: v for k, v in os.environ.items() if k != "LANDING_LLM_PROVIDER"}
        with patch.dict(os.environ, env, clear=True):
            primary, fallback = _resolve_provider()
        self.assertEqual(primary,  "gemini")
        self.assertEqual(fallback, "openai")

    def test_invalid_value_defaults_to_gemini(self):
        """Invalid LANDING_LLM_PROVIDER value silently falls back to gemini."""
        from infra.landing.landing_llm_executor import _resolve_provider
        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "anthropic"}):
            primary, fallback = _resolve_provider()
        self.assertEqual(primary, "gemini")

    def test_execute_uses_correct_provider_arg(self):
        """execute_landing_generation() passes the env-var-resolved provider to llm_client."""
        from infra.landing import landing_llm_executor
        mock_result = {
            "status":      "ok",
            "content":     "<html><body>test</body></html>",
            "provider":    "openai",
            "latency_ms":  300,
            "tokens_used": 100,
            "error_type":  None,
        }
        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "openai"}):
            with patch("infra.landing.landing_llm_executor.llm_client.generate",
                       return_value=mock_result) as mock_gen:
                landing_llm_executor.execute_landing_generation("test prompt")

        # Stage 1 succeeds immediately (provider=openai)
        first_call = mock_gen.call_args_list[0].kwargs
        self.assertEqual(first_call.get("provider"), "openai")
        self.assertIn("gpt", first_call.get("model", ""))


class TestFallbackChain(unittest.TestCase):
    """
    Tests for the 3-stage explicit fallback chain in execute_landing_generation().

    Scenario 1: Primary provider fails  -> stage 2 (fallback) activates.
    Scenario 2: Primary + fallback fail -> stage 3 (secondary safe) activates.
    Scenario 3: All 3 stages fail       -> returns structured error dict, no crash.
    """

    _ERROR_RESULT = {
        "status":      "error",
        "content":     "",
        "provider":    "?",
        "latency_ms":  0,
        "tokens_used": 0,
        "error_type":  "LLMProviderError",
    }
    _OK_RESULT = {
        "status":      "ok",
        "content":     "<html><body>ok</body></html>",
        "provider":    "??",
        "latency_ms":  200,
        "tokens_used": 80,
        "error_type":  None,
    }

    def setUp(self):
        from infra.llm import llm_budget_guard
        llm_budget_guard.reset_for_testing()

    def _err(self, provider="?"):
        r = dict(self._ERROR_RESULT)
        r["provider"] = provider
        return r

    def _ok(self, provider="openai"):
        r = dict(self._OK_RESULT)
        r["provider"] = provider
        return r

    def test_scenario1_primary_fails_fallback_activates(self):
        """
        Stage 1 (primary) fails.
        Stage 2 (fallback) succeeds.
        Returns ok with fallback_used=True and stage_reached=2.
        """
        from infra.landing import landing_llm_executor

        call_count = {"n": 0}
        def side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return self._err(kwargs.get("provider", "?"))  # Stage 1 fails
            return self._ok(kwargs.get("provider", "?"))        # Stage 2 ok

        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "gemini"}):
            with patch("infra.landing.landing_llm_executor.llm_client.generate",
                       side_effect=side_effect):
                result = landing_llm_executor.execute_landing_generation("prompt")

        self.assertEqual(result["status"],       "ok")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["stage_reached"], 2)

    def test_scenario2_primary_and_fallback_fail_secondary_activates(self):
        """
        Stage 1 (primary) fails.
        Stage 2 (fallback) fails.
        Stage 3 (secondary safe) succeeds.
        Returns ok with fallback_used=True and stage_reached=3.
        """
        from infra.landing import landing_llm_executor

        call_count = {"n": 0}
        def side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return self._err(kwargs.get("provider", "?"))  # Stages 1+2 fail
            return self._ok("openai")                           # Stage 3 ok

        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "gemini"}):
            with patch("infra.landing.landing_llm_executor.llm_client.generate",
                       side_effect=side_effect):
                result = landing_llm_executor.execute_landing_generation("prompt")

        self.assertEqual(result["status"],       "ok")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["stage_reached"], 3)

    def test_scenario3_all_stages_fail_returns_error_no_crash(self):
        """
        All 3 stages fail.
        Must return structured error dict with error_type=LLMTotalFailure.
        Must NOT raise any exception.
        """
        from infra.landing import landing_llm_executor

        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "gemini"}):
            with patch("infra.landing.landing_llm_executor.llm_client.generate",
                       return_value=self._err("?")):
                result = landing_llm_executor.execute_landing_generation("prompt")

        self.assertEqual(result["status"],     "error")
        self.assertEqual(result["error_type"], "LLMTotalFailure")
        self.assertEqual(result["html"],       "")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["stage_reached"], 3)
        # Must not raise — reaching this line confirms no crash

    def test_stage1_success_does_not_proceed_to_stage2(self):
        """
        When stage 1 succeeds, stages 2 and 3 must not be called.
        fallback_used must be False.
        stage_reached must be 1.
        """
        from infra.landing import landing_llm_executor

        with patch.dict(os.environ, {"LANDING_LLM_PROVIDER": "gemini"}):
            with patch("infra.landing.landing_llm_executor.llm_client.generate",
                       return_value=self._ok("gemini")) as mock_gen:
                result = landing_llm_executor.execute_landing_generation("prompt")

        self.assertEqual(result["status"],        "ok")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["stage_reached"],  1)
        self.assertEqual(mock_gen.call_count,       1)  # Only 1 call, not 3


if __name__ == "__main__":
    unittest.main(verbosity=2)
