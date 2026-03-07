"""
infra/system/tests/test_etapa26.py — Etapa 2.6 system hardening test suite.

T1: Radar → product flow (3 unique opportunities pass gates)
T2: Product limit gate blocks 11th product
T3: LLM total failure → abort event emitted
T4: LLM daily budget limit blocks calls
T5: Health monitor detects stalled Radar component
T6: Product GC emits purge event for archived product
T7: Restart preserves state (snapshot-based idempotency)
T8: Regen loop succeeds on 2nd attempt, aborts on all failures
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# T1: 3 unique opportunities pass the handler successfully
# ─────────────────────────────────────────────────────────────────────────────
class TestUniqueOpportunitiesFlow(unittest.TestCase):
    """T1 — 3 distinct opportunities pass gates and emit product_creation_requested."""

    def setUp(self):
        import infra.landing.landing_recommendation_handler as mod
        mod._cluster_index.clear()
        mod._recommendation_payload_store.clear()
        mod._bootstrapped = False
        # Reset opportunity gate index
        from infra.radar import opportunity_gate
        opportunity_gate.reset_index()

    def _make_payload(self, cluster_id: str, summary: str, score: float = 75.0) -> dict:
        return {
            "cluster_id":           cluster_id,
            "ice":                  "ALTO",
            "emotional_score":      score,
            "monetization_score":   70.0,
            "growth_percent":       20.0,
            "score_final":          score,
            "justification_summary": summary,
        }

    def test_three_unique_opportunities_all_pass(self):
        import infra.landing.landing_recommendation_handler as mod
        mock_orch = MagicMock()

        payloads = [
            self._make_payload("c1", "Bitcoin investment course for safety-conscious beginners"),
            self._make_payload("c2", "SaaS platform for automating social media scheduling"),
            self._make_payload("c3", "English language learning guide for Brazilian professionals"),
        ]

        # ALL must pass (unique texts, sufficient scores)
        for p in payloads:
            mod.handle(orchestrator=mock_orch, payload=p)

        # 3 product_creation_requested events emitted
        calls_types = [c.kwargs.get("event_type") for c in mock_orch.receive_event.call_args_list]
        product_requests = [t for t in calls_types if t == "product_creation_requested"]
        self.assertEqual(len(product_requests), 3)


# ─────────────────────────────────────────────────────────────────────────────
# T2: Product limit gate blocks 11th product
# ─────────────────────────────────────────────────────────────────────────────
class TestProductLimitGate(unittest.TestCase):
    """T2 — MAX_ACTIVE_PRODUCTS=10: 11th call emits product_creation_blocked_event."""

    def setUp(self):
        import infra.landing.landing_recommendation_handler as mod
        mod._cluster_index.clear()
        mod._recommendation_payload_store.clear()
        mod._bootstrapped = False
        from infra.radar import opportunity_gate
        opportunity_gate.reset_index()

    def test_eleventh_product_blocked(self):
        import infra.landing.landing_recommendation_handler as mod
        mock_orch = MagicMock()

        # Simulate 10 active products in snapshot
        fake_snapshots = [
            {"product_id": f"prod-{i}", "cluster_id": f"cX-{i}"}
            for i in range(10)
        ]

        with patch("infra.landing.landing_recommendation_handler.load_snapshots",
                   return_value=fake_snapshots):
            payload = {
                "cluster_id":           "cluster-NEW",
                "ice":                  "ALTO",
                "emotional_score":      80.0,
                "monetization_score":   75.0,
                "growth_percent":       25.0,
                "score_final":          80.0,
                "justification_summary": "Brand new unique product idea",
            }
            with patch.dict(os.environ, {"MAX_ACTIVE_PRODUCTS": "10"}):
                mod.handle(orchestrator=mock_orch, payload=payload)

        event_types = [c.kwargs.get("event_type")
                       for c in mock_orch.receive_event.call_args_list]
        self.assertIn("product_creation_blocked_event", event_types)
        self.assertNotIn("product_creation_requested", event_types)


# ─────────────────────────────────────────────────────────────────────────────
# T3: LLM total failure → product_generation_aborted_event emitted
# ─────────────────────────────────────────────────────────────────────────────
class TestLLMTotalFailureAbort(unittest.TestCase):
    """T3 — All regen attempts fail → abort event emitted, no crash."""

    def test_all_attempts_fail_abort_event_emitted(self):
        from infra.landing import landing_llm_executor
        from infra.llm import llm_budget_guard
        llm_budget_guard.reset_for_testing()

        mock_orch = MagicMock()
        error_result = {
            "status": "error", "content": "", "provider": "?",
            "latency_ms": 0, "tokens_used": 0, "error_type": "LLMProviderError",
        }

        with patch("infra.landing.landing_llm_executor.llm_client.generate",
                   return_value=error_result):
            with patch.dict(os.environ, {"MAX_LANDING_REGEN_ATTEMPTS": "3"}):
                result = landing_llm_executor.execute_with_regen(
                    prompt="test prompt",
                    orchestrator=mock_orch,
                    cluster_id="cluster-Z",
                )

        self.assertEqual(result["status"], "error")
        # abort event must be emitted
        event_types = [c.kwargs.get("event_type")
                       for c in mock_orch.receive_event.call_args_list]
        self.assertIn("product_generation_aborted_event", event_types)

    def test_no_crash_without_orchestrator(self):
        from infra.landing import landing_llm_executor
        from infra.llm import llm_budget_guard
        llm_budget_guard.reset_for_testing()

        error_result = {
            "status": "error", "content": "", "provider": "?",
            "latency_ms": 0, "tokens_used": 0, "error_type": "LLMProviderError",
        }
        with patch("infra.landing.landing_llm_executor.llm_client.generate",
                   return_value=error_result):
            result = landing_llm_executor.execute_with_regen("test", orchestrator=None)
        self.assertEqual(result["status"], "error")


# ─────────────────────────────────────────────────────────────────────────────
# T4: LLM daily budget limit blocks execution
# ─────────────────────────────────────────────────────────────────────────────
class TestLLMBudgetGuard(unittest.TestCase):
    """T4 — Daily call and cost limits are enforced."""

    def setUp(self):
        from infra.llm import llm_budget_guard
        llm_budget_guard.reset_for_testing()

    def test_budget_allowed_initially(self):
        from infra.llm import llm_budget_guard
        result = llm_budget_guard.check_budget()
        self.assertTrue(result["allowed"])

    def test_call_limit_blocks(self):
        from infra.llm import llm_budget_guard
        with patch.dict(os.environ, {"MAX_LLM_CALLS_PER_DAY": "3"}):
            # Exhaust the limit
            for _ in range(3):
                llm_budget_guard.register_call(0.001)
            # Reload to pick up env var (module-level constant)
            import importlib
            import infra.llm.llm_budget_guard as bg
            bg.MAX_LLM_CALLS_PER_DAY = 3
            result = bg.check_budget()
        self.assertFalse(result["allowed"])
        self.assertIn("calls", result["reason"].lower())

    def test_cost_limit_blocks(self):
        from infra.llm import llm_budget_guard
        with patch.object(llm_budget_guard, "MAX_LLM_COST_PER_DAY", 0.05):
            llm_budget_guard.register_call(0.06)  # exceed limit
            result = llm_budget_guard.check_budget()
        self.assertFalse(result["allowed"])
        self.assertIn("cost", result["reason"].lower())

    def test_executor_blocked_by_budget(self):
        from infra.llm import llm_budget_guard
        from infra.landing import landing_llm_executor
        llm_budget_guard.reset_for_testing()

        # Force budget to be exhausted
        with patch.object(llm_budget_guard, "MAX_LLM_CALLS_PER_DAY", 0):
            result = landing_llm_executor.execute_landing_generation("test")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "LLMBudgetExceeded")

    def test_register_call_increments_counters(self):
        from infra.llm import llm_budget_guard
        llm_budget_guard.register_call(0.05)
        status = llm_budget_guard.get_status()
        self.assertEqual(status["calls_today"], 1)
        self.assertAlmostEqual(status["cost_today_usd"], 0.05, places=4)


# ─────────────────────────────────────────────────────────────────────────────
# T5: Health monitor detects stalled Radar
# ─────────────────────────────────────────────────────────────────────────────
class TestHealthMonitor(unittest.TestCase):
    """T5 — Health monitor correctly detects stalled components."""

    def setUp(self):
        from infra.system import health_monitor
        health_monitor.reset_for_testing()

    def test_no_stall_when_activity_recent(self):
        from infra.system import health_monitor
        health_monitor.update_component("radar")
        mock_orch = MagicMock()
        with patch.object(health_monitor, "SERVICE_TIMEOUT_HOURS", 12):
            stalled = health_monitor.run_health_check(mock_orch)
        self.assertNotIn("radar", stalled)

    def test_detects_stalled_radar(self):
        from infra.system import health_monitor
        # Manually set last activity to 13 hours ago
        old_time = datetime.now(timezone.utc) - timedelta(hours=13)
        with health_monitor._lock:
            health_monitor._last_activity["radar"] = old_time

        mock_orch = MagicMock()
        with patch.object(health_monitor, "SERVICE_TIMEOUT_HOURS", 12):
            stalled = health_monitor.run_health_check(mock_orch)

        self.assertIn("radar", stalled)
        # Event emitted
        event_types = [c.kwargs.get("event_type")
                       for c in mock_orch.receive_event.call_args_list]
        self.assertIn("system_component_stalled_event", event_types)

    def test_never_started_component_not_stalled(self):
        """Components with None (never started) are skipped — not false-alarmed."""
        from infra.system import health_monitor
        mock_orch = MagicMock()
        stalled = health_monitor.run_health_check(mock_orch)
        self.assertEqual(len(stalled), 0)


# ─────────────────────────────────────────────────────────────────────────────
# T6: Product GC emits purge event for old snapshots
# ─────────────────────────────────────────────────────────────────────────────
class TestProductGC(unittest.TestCase):
    """T6 — GC identifies and emits purge event for aged records."""

    def _write_snapshot(self, path: Path, product_id: str, created_at: str) -> None:
        record = {
            "product_id": product_id,
            "cluster_id": f"c-{product_id}",
            "created_at": created_at,
            "version": 1,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def test_gc_emits_purge_for_old_record(self):
        from infra.system import product_gc
        mock_orch = MagicMock()

        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "landing_snapshots.jsonl"
            # Old record: 400 days ago
            old_dt = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
            self._write_snapshot(snap, "old-product", old_dt)

            with patch.object(product_gc, "ARCHIVE_RETENTION_DAYS", 365):
                stats = product_gc.run_product_gc(mock_orch, snapshot_path=snap)

        self.assertEqual(stats["purged"], 1)
        event_types = [c.kwargs.get("event_type")
                       for c in mock_orch.receive_event.call_args_list]
        self.assertIn("product_purge_event", event_types)

    def test_gc_skips_recent_records(self):
        from infra.system import product_gc
        mock_orch = MagicMock()

        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "landing_snapshots.jsonl"
            # Recent record: 10 days ago
            recent_dt = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            self._write_snapshot(snap, "new-product", recent_dt)

            with patch.object(product_gc, "ARCHIVE_RETENTION_DAYS", 365):
                stats = product_gc.run_product_gc(mock_orch, snapshot_path=snap)

        self.assertEqual(stats["purged"], 0)
        mock_orch.receive_event.assert_not_called()

    def test_gc_dry_run_no_events(self):
        from infra.system import product_gc
        mock_orch = MagicMock()

        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "landing_snapshots.jsonl"
            old_dt = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
            self._write_snapshot(snap, "old-product-dry", old_dt)

            with patch.object(product_gc, "ARCHIVE_RETENTION_DAYS", 365):
                stats = product_gc.run_product_gc(mock_orch, snapshot_path=snap, dry_run=True)

        self.assertEqual(stats["purged"], 1)
        mock_orch.receive_event.assert_not_called()  # dry_run = no events


# ─────────────────────────────────────────────────────────────────────────────
# T7: Restart preserves idempotency state (snapshot-based)
# ─────────────────────────────────────────────────────────────────────────────
class TestRestartIdempotency(unittest.TestCase):
    """T7 — System restart reconstructs cluster_index; second call for same cluster skipped."""

    def test_restart_reconstructs_index(self):
        import infra.landing.landing_recommendation_handler as mod
        mod._cluster_index.clear()
        mod._recommendation_payload_store.clear()
        mod._bootstrapped = False

        existing = [
            {"cluster_id": "c-persist-1", "product_id": "prod-aaa", "version": 1},
            {"cluster_id": "c-persist-2", "product_id": "prod-bbb", "version": 1},
        ]

        mock_bus  = MagicMock()
        mock_orch = MagicMock()

        with patch("infra.landing.landing_recommendation_handler.load_snapshots",
                   return_value=existing):
            with patch("infra.landing.landing_recommendation_handler.build_cluster_index",
                       return_value={"c-persist-1": "prod-aaa", "c-persist-2": "prod-bbb"}):
                mod.bootstrap(event_bus=mock_bus, orchestrator=mock_orch)

        self.assertIn("c-persist-1", mod._cluster_index)
        self.assertIn("c-persist-2", mod._cluster_index)

    def test_duplicate_after_restart_is_skipped(self):
        import infra.landing.landing_recommendation_handler as mod
        mod._cluster_index.clear()
        mod._cluster_index["c-known"] = "prod-existing"
        mod._bootstrapped = True

        mock_orch = MagicMock()
        mod.handle(
            orchestrator=mock_orch,
            payload={
                "cluster_id": "c-known",
                "ice": "ALTO",
                "emotional_score": 75.0,
                "monetization_score": 70.0,
            },
        )
        mock_orch.receive_event.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# T8: Regen loop behavior
# ─────────────────────────────────────────────────────────────────────────────
class TestRegenLoop(unittest.TestCase):
    """T8 — Regen loop succeeds on 2nd attempt; all-fail case verified in T3."""

    def setUp(self):
        from infra.llm import llm_budget_guard
        llm_budget_guard.reset_for_testing()

    def test_regen_succeeds_on_second_attempt(self):
        from infra.landing import landing_llm_executor

        ok = {
            "status": "ok", "content": "<html><body>ok</body></html>",
            "provider": "gemini", "latency_ms": 200, "tokens_used": 80, "error_type": None,
        }
        err = {
            "status": "error", "content": "", "provider": "?",
            "latency_ms": 0, "tokens_used": 0, "error_type": "LLMProviderError",
        }
        call_n = {"n": 0}
        def se(**kwargs):
            call_n["n"] += 1
            return err if call_n["n"] == 1 else ok

        with patch("infra.landing.landing_llm_executor.llm_client.generate", side_effect=se):
            result = landing_llm_executor.execute_with_regen("prompt", orchestrator=None)
        self.assertEqual(result["status"], "ok")

    def test_regen_bounded_by_max_attempts(self):
        """Regen must not exceed MAX_LANDING_REGEN_ATTEMPTS calls."""
        from infra.landing import landing_llm_executor

        err = {
            "status": "error", "content": "", "provider": "?",
            "latency_ms": 0, "tokens_used": 0, "error_type": "LLMProviderError",
        }
        with patch.dict(os.environ, {"MAX_LANDING_REGEN_ATTEMPTS": "3"}):
            with patch("infra.landing.landing_llm_executor.llm_client.generate",
                       return_value=err) as mock_gen:
                # Reload to pick up env var
                landing_llm_executor.MAX_LANDING_REGEN_ATTEMPTS = 3
                landing_llm_executor.execute_with_regen("prompt", orchestrator=None)
        # Each regen attempt calls generate up to 3x internally (3-stage chain)
        # But outer regen is bounded to MAX_LANDING_REGEN_ATTEMPTS
        self.assertLessEqual(mock_gen.call_count, 9)  # 3 regen × 3 stages max


if __name__ == "__main__":
    unittest.main(verbosity=2)
