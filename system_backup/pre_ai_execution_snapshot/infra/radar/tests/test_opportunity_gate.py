"""
infra/radar/tests/test_opportunity_gate.py — Tests for OpportunityGate (Etapa 2.6.1).

Covers:
  - Cosine similarity computation
  - Score threshold rejection
  - Similarity threshold blocking
  - Unique texts pass through
  - Index registration and retrieval
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestOpportunityGate(unittest.TestCase):

    def setUp(self):
        from infra.radar import opportunity_gate
        opportunity_gate.reset_index()

    def test_low_score_blocked(self):
        """Score below MIN_OPPORTUNITY_SCORE must be blocked."""
        from infra.radar import opportunity_gate
        result = opportunity_gate.should_block_opportunity(
            opportunity_text="Great investment opportunity",
            opportunity_score=0.30,  # < 0.40
            cluster_id="c-low",
        )
        self.assertTrue(result["blocked"])
        self.assertIn("minimum", result["reason"].lower())

    def test_unique_text_passes(self):
        """A genuinely unique text with good score must pass."""
        from infra.radar import opportunity_gate
        result = opportunity_gate.should_block_opportunity(
            opportunity_text="Python programming course for complete beginners",
            opportunity_score=0.75,
            cluster_id="c-unique",
        )
        self.assertFalse(result["blocked"])

    def test_duplicate_text_blocked(self):
        """Near-identical text must be blocked after registering the first."""
        from infra.radar import opportunity_gate

        text = "Learn Python programming from scratch with step by step lessons"
        opportunity_gate.register_opportunity("c-first", text)

        # Almost identical phrasing
        duplicate = "Learn Python programming from scratch with step by step video lessons"
        result = opportunity_gate.should_block_opportunity(
            opportunity_text=duplicate,
            opportunity_score=0.80,
            cluster_id="c-second",
        )
        self.assertTrue(result["blocked"])
        self.assertGreater(result["similarity"], 0.50)

    def test_different_domain_passes(self):
        """Text from a completely different domain must not be blocked."""
        from infra.radar import opportunity_gate
        opportunity_gate.register_opportunity(
            "c-cooking",
            "Master French cuisine recipes with chef guided lessons",
        )
        result = opportunity_gate.should_block_opportunity(
            opportunity_text="Cryptocurrency portfolio management for retail investors",
            opportunity_score=0.70,
            cluster_id="c-crypto",
        )
        self.assertFalse(result["blocked"])

    def test_register_increases_index_size(self):
        from infra.radar import opportunity_gate
        self.assertEqual(opportunity_gate.index_size(), 0)
        opportunity_gate.register_opportunity("c-a", "first opportunity text here")
        opportunity_gate.register_opportunity("c-b", "second opportunity text here")
        self.assertEqual(opportunity_gate.index_size(), 2)

    def test_emit_blocked_event_calls_orchestrator(self):
        """When blocking, opportunity_similarity_blocked_event must be emitted."""
        from infra.radar import opportunity_gate
        from unittest.mock import MagicMock

        text = "Social media automation tool for small business owners"
        opportunity_gate.register_opportunity("c-first", text)

        mock_orch = MagicMock()
        opportunity_gate.should_block_opportunity(
            opportunity_text=text,
            opportunity_score=0.80,
            cluster_id="c-dup",
            orchestrator=mock_orch,
        )
        mock_orch.receive_event.assert_called_once()
        event_type = mock_orch.receive_event.call_args.kwargs.get("event_type")
        self.assertEqual(event_type, "opportunity_similarity_blocked_event")

    def test_self_not_blocked(self):
        """A cluster must not block itself when re-checked."""
        from infra.radar import opportunity_gate
        text = "Email marketing automation course for digital entrepreneurs"
        opportunity_gate.register_opportunity("c-self", text)
        result = opportunity_gate.should_block_opportunity(
            opportunity_text=text,
            opportunity_score=0.75,
            cluster_id="c-self",  # same cluster_id = skipped in comparison
        )
        self.assertFalse(result["blocked"])

    def test_cosine_similarity_identical_texts(self):
        """Internal: identical texts should have similarity close to 1.0."""
        from infra.radar.opportunity_gate import _vectorize, _cosine
        v = _vectorize("machine learning deep neural networks classification")
        sim = _cosine(v, v)
        self.assertAlmostEqual(sim, 1.0, places=4)

    def test_cosine_similarity_orthogonal_texts(self):
        """Internal: completely unrelated texts should have similarity near 0."""
        from infra.radar.opportunity_gate import _vectorize, _cosine
        v1 = _vectorize("quantum physics electromagnetic radiation spectrum")
        v2 = _vectorize("pastry baking chocolate soufflé vanilla custard")
        sim = _cosine(v1, v2)
        self.assertLess(sim, 0.15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
