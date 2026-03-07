import sys
import os
import unittest
from unittest.mock import MagicMock
from datetime import datetime, timezone

# Add core to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.product_life_engine import ProductLifeEngine

class TestC5LifeAuthority(unittest.TestCase):
    def setUp(self):
        self.pers = MagicMock()
        self.pers.load.return_value = {}
        self.sm = MagicMock()
        self.engine = ProductLifeEngine(self.pers, state_machine=self.sm)
        self.orchestrator = MagicMock()
        self.telemetry = MagicMock()
        self.gs = MagicMock()
        self.gs.get_state.return_value = "NORMAL"

    def _setup_product_beta_closed(self, pid):
        now = datetime.now(timezone.utc)
        rec = {
            "product_id": pid,
            "state": "Beta",
            "beta_start": now.isoformat(),
            "beta_end": now.isoformat(),
            "beta_closed_at": now.isoformat(),
            "classification": None
        }
        self.engine._state[pid] = rec

    def test_scenario_1_zero_conversions_inativo(self):
        pid = "scen_1_zero"
        self._setup_product_beta_closed(pid)
        self.telemetry.get_latest_snapshot.return_value = {
            "conversions": 0,
            "refund_count": 0,
            "rpm": 0.0,
            "roas": 0.0,
            "margin": 0.0,
            "version_number": 1
        }
        
        result = self.engine.consolidate_post_beta(pid, self.orchestrator, self.telemetry, self.sm, self.gs)
        
        self.assertEqual(result["target_state"], "Inativo")
        self.assertEqual(result["classification"], "nao_elegivel")

    def test_scenario_2_one_conversion_ativo(self):
        pid = "scen_2_one"
        self._setup_product_beta_closed(pid)
        self.telemetry.get_latest_snapshot.return_value = {
            "conversions": 1,
            "refund_count": 0,
            "rpm": 1.0,
            "roas": 2.0,
            "margin": 0.5,
            "version_number": 1
        }
        
        result = self.engine.consolidate_post_beta(pid, self.orchestrator, self.telemetry, self.sm, self.gs)
        
        self.assertEqual(result["target_state"], "Ativo")
        self.assertEqual(result["classification"], "elegivel")

    def test_scenario_3_one_sale_one_refund_inativo(self):
        pid = "scen_3_net_zero"
        self._setup_product_beta_closed(pid)
        self.telemetry.get_latest_snapshot.return_value = {
            "conversions": 1,
            "refund_count": 1,
            "rpm": 0.0,
            "roas": 0.0,
            "margin": 0.0,
            "version_number": 1
        }
        
        result = self.engine.consolidate_post_beta(pid, self.orchestrator, self.telemetry, self.sm, self.gs)
        
        self.assertEqual(result["target_state"], "Inativo")
        self.assertEqual(result["classification"], "nao_elegivel")

    def test_scenario_4_one_sale_low_metrics_ativo(self):
        pid = "scen_4_low_metrics"
        self._setup_product_beta_closed(pid)
        # Even with metrics below thresholds (RPM=0.1 < 0.5, ROAS=0.5 < 1.2, Margin=-0.1 < 0.10)
        # 1 valid net conversion MUST be enough for activation.
        self.telemetry.get_latest_snapshot.return_value = {
            "conversions": 1,
            "refund_count": 0,
            "rpm": 0.1,
            "roas": 0.5,
            "margin": -0.1,
            "version_number": 1
        }
        
        result = self.engine.consolidate_post_beta(pid, self.orchestrator, self.telemetry, self.sm, self.gs)
        
        print(f"\nScenario 4 (Low Metrics): classification={result['classification']}, target_state={result['target_state']}")
        
        self.assertEqual(result["target_state"], "Ativo")
        self.assertEqual(result["classification"], "elegivel")
        
        # Verify event emission
        audit_call = [c for c in self.orchestrator.emit_event.call_args_list if c[1]["event_type"] == "constitutional_c5_life_authority_corrected"]
        self.assertTrue(len(audit_call) > 0)
        payload = audit_call[0][1]["payload"]
        self.assertTrue(payload["economic_threshold_removed"])
        self.assertEqual(payload["net_conversions"], 1)

if __name__ == "__main__":
    unittest.main()
