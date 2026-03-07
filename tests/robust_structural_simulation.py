import sys
import os
import unittest
import json
import uuid
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

# -- Bootstrap ----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SIM_DATA = ROOT / "tests" / "sim_data_robust"
if SIM_DATA.exists():
    shutil.rmtree(SIM_DATA)
SIM_DATA.mkdir(parents=True, exist_ok=True)

from core.orchestrator import Orchestrator
from core.event_bus import EventBus
from core.state_manager import StateManager
from core.state_machine import StateMachine
from core.global_state import GlobalState, NORMAL, ALERTA_FINANCEIRO, CONTENCAO_FINANCEIRA
from core.telemetry_engine import TelemetryEngine
from core.product_life_engine import ProductLifeEngine
from core.commercial_engine import CommercialEngine
from core.version_manager import VersionManager
from core.finance_engine import FinanceEngine
from core.feedback_incentive_engine import FeedbackIncentiveEngine

# -- Simple Persistence Mock --------------------------------------------------
class SimPersistence:
    def __init__(self, filename):
        self.path = SIM_DATA / filename
    def load(self):
        if not self.path.exists(): return {} if not str(self.path).endswith("jsonl") else []
        with open(self.path, "r", encoding="utf-8") as f:
            if str(self.path).endswith("jsonl"):
                return [json.loads(line) for line in f]
            return json.load(f)
    def save(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    def append(self, record):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

# -- Robust Simulation Suite --------------------------------------------------
class RobustStructuralSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print(f"\n>>> INITIALIZING ROBUST SIMULATION ENVIRONMENT")
        print(f">>> DATA DIR: {SIM_DATA}")

    def setUp(self):
        # 1. Infrastructure
        self.bus_pers = SimPersistence("ledger.jsonl")
        self.bus = EventBus(log_persistence=self.bus_pers)
        
        self.sm_pers = SimPersistence("state.json")
        self.sm = StateManager(persistence=self.sm_pers)
        
        self.mach_pers = SimPersistence("lifecycle.json")
        self.mach = StateMachine(persistence=self.mach_pers)
        
        self.orch = Orchestrator(event_bus=self.bus, state_manager=self.sm)
        
        # 2. Engines
        self.te = TelemetryEngine(
            snapshot_persistence=SimPersistence("snapshots.jsonl"),
            accumulator_persistence=SimPersistence("accumulators.jsonl")
        )
        self.le = ProductLifeEngine(
            persistence=SimPersistence("product_life.json"),
            state_machine=self.mach
        )
        self.ce = CommercialEngine(
            orchestrator=self.orch,
            persistence=SimPersistence("commercial.json")
        )
        self.vm = VersionManager(
            persistence=SimPersistence("versions.json"),
            snapshot_store=self.te
        )
        self.gs = GlobalState(
            orchestrator=self.orch,
            persistence=SimPersistence("global_state.json")
        )
        self.fe = FinanceEngine(
            state_persistence=SimPersistence("finance_state.json"),
            global_state=self.gs
        )
        self.fie = FeedbackIncentiveEngine(
            orchestrator=self.orch,
            persistence=SimPersistence("feedback.jsonl")
        )
        
        # Mock Cycle Manager for snapshot generation
        self.cm = MagicMock()
        self.cm.close_cycle.return_value = {"cycle_id": "sim_cycle"}

        # 3. Registration
        self.orch.register_service("telemetry", self.te)
        self.orch.register_service("product_life", self.le)
        self.orch.register_service("commercial_engine", self.ce)
        self.orch.register_service("version_manager", self.vm)
        self.orch.register_service("global_state", self.gs)
        self.orch.register_service("finance_engine", self.fe)
        self.orch.register_service("feedback_incentive_engine", self.fie)
        self.orch.register_service("state_machine", self.mach)
        self.orch.register_service("cycle_manager", self.cm) # Added
        
        # 4. Final Setup
        self.orch.set_global_state(NORMAL, reason="Simulation Setup")

    def test_end_to_end_scenarios(self):
        events_before = len(self.bus.get_events())
        print(f"\n[STEP 0] Starting Events: {events_before}")

        # Helper to get the last created product ID
        def get_last_pid():
            pids = list(self.le._state.keys())
            return pids[-1] if pids else None

        # ---------------------------------------------------------------------
        # SCENARIO A: 1 VALIDATED SALE (Should Activate)
        # ---------------------------------------------------------------------
        print(f"\n>>> [SCENARIO A] Validated Sale Activation")
        
        self.orch.receive_event("product_creation_requested", {
            "opportunity_id": "opp_a",
            "emotional_score": 0.8,
            "monetization_score": 0.8,
            "growth_percent": 0.5,
            "competitive_gap_flag": False,
            "justification_snapshot": {"opportunity": "test_a"},
            "version_id": "v1.0-alpha"
        })
        pid_a = get_last_pid()
        print(f"  Created Product: {pid_a}")
        
        self.assertEqual(self.mach.get_state(pid_a), "Draft")
        
        # 2. Enter Beta
        self.orch.receive_event("beta_approved_requested", {"product_id": pid_a}, product_id=pid_a)
        self.assertEqual(self.mach.get_state(pid_a), "Beta")
        
        # 3. Purchase Success
        self.orch.receive_event("purchase_success", {
            "product_id": pid_a, "amount_total": 49.90, "stripe_session_id": "sess_a", "customer_email": "user@a.com"
        }, product_id=pid_a)
        
        # 4. Force Beta Expiry
        rec = self.le._state[pid_a]
        rec["beta_end"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.le._save()
        
        # 5. Close Beta (Formal event)
        self.orch.receive_event("beta_close_requested", {"product_id": pid_a}, product_id=pid_a)
        
        # 6. Close Cycle Snapshot
        self.orch.receive_event("cycle_close_requested", {"product_id": pid_a, "cycle_id": "cycle_a_final"}, product_id=pid_a)
        
        # 7. Consolidate
        self.orch.receive_event("post_beta_consolidation_requested", {"product_id": pid_a}, product_id=pid_a)
        
        # VERIFY A
        self.assertEqual(self.mach.get_state(pid_a), "Ativo")
        snap_a = self.te.get_latest_snapshot(pid_a)
        self.assertEqual(snap_a["conversions"], 1)
        self.assertEqual(snap_a["revenue_bruta"], 49.90)
        print("  [OK] Scenario A: Activated Correctly.")

        # ---------------------------------------------------------------------
        # SCENARIO B: 0 SALES (Should Inactivate)
        # ---------------------------------------------------------------------
        print(f"\n>>> [SCENARIO B] Zero Sales Inactivation")
        
        creation_event_b = self.orch.receive_event("product_creation_requested", {
            "opportunity_id": "opp_b",
            "emotional_score": 0.7,
            "monetization_score": 0.7,
            "growth_percent": 0.3,
            "competitive_gap_flag": False,
            "justification_snapshot": {"opportunity": "test_b"},
            "version_id": "v1.0-beta"
        })
        pid_b = get_last_pid()
        
        self.orch.receive_event("beta_approved_requested", {"product_id": pid_b}, product_id=pid_b)
        
        # Force expiry & Consolidate
        rcb = self.le._state[pid_b]
        rcb["beta_end"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.le._save()
        
        self.orch.receive_event("beta_close_requested", {"product_id": pid_b}, product_id=pid_b)
        self.orch.receive_event("cycle_close_requested", {"product_id": pid_b, "cycle_id": "cycle_b_final"}, product_id=pid_b)
        self.orch.receive_event("post_beta_consolidation_requested", {"product_id": pid_b}, product_id=pid_b)
        
        # VERIFY B
        self.assertEqual(self.mach.get_state(pid_b), "Inativo")
        snap_b = self.te.get_latest_snapshot(pid_b)
        self.assertEqual(snap_b["conversions"], 0)
        print("  [OK] Scenario B: Inactivated Correctly.")

        # ---------------------------------------------------------------------
        # SCENARIO C: SALE + REFUND (Should Inactivate & Revoke)
        # ---------------------------------------------------------------------
        print(f"\n>>> [SCENARIO C] Sale + Refund Inactivation")
        
        creation_event_c = self.orch.receive_event("product_creation_requested", {
            "opportunity_id": "opp_c",
            "emotional_score": 0.9,
            "monetization_score": 0.9,
            "growth_percent": 0.1,
            "competitive_gap_flag": True,
            "justification_snapshot": {"opportunity": "test_c"},
            "version_id": "v1.1"
        })
        pid_c = get_last_pid()
        
        self.orch.receive_event("beta_approved_requested", {"product_id": pid_c}, product_id=pid_c)
        
        # 2. Events
        self.orch.receive_event("purchase_success", {
            "product_id": pid_c, "amount_total": 100.0, "stripe_session_id": "sess_c", "customer_email": "user@c.com"
        }, product_id=pid_c)
        
        self.orch.receive_event("refund_completed", {
            "product_id": pid_c, "user_id": "user@c.com", "amount": 100.0, "refund_id": "re_c"
        }, product_id=pid_c)
        
        # 3. Consolidate
        rcc = self.le._state[pid_c]
        rcc["beta_end"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.le._save()
        
        self.orch.receive_event("beta_close_requested", {"product_id": pid_c}, product_id=pid_c)
        self.orch.receive_event("cycle_close_requested", {"product_id": pid_c, "cycle_id": "cycle_c_final"}, product_id=pid_c)
        self.orch.receive_event("post_beta_consolidation_requested", {"product_id": pid_c}, product_id=pid_c)
        
        # VERIFY C
        self.assertEqual(self.mach.get_state(pid_c), "Inativo")
        snap_c = self.te.get_latest_snapshot(pid_c)
        self.assertEqual(snap_c["conversions"], 1)
        self.assertEqual(snap_c["refund_count"], 1)
        self.assertEqual(snap_c["revenue_liquida"], 0.0)
        
        # Verify access revoked in CommercialEngine
        record = self.ce.get_record("user@c.com")
        self.assertEqual(record["status"], "REVOKED")
        print("  [OK] Scenario C: Inactivated and Revoked Correctly.")

        # ---------------------------------------------------------------------
        # GLOBAL INTEGRITY
        # ---------------------------------------------------------------------
        events_after = len(self.bus.get_events())
        print(f"\n[STEP 4] Total Events Produced: {events_after - events_before}")
        self.assertTrue(events_after > events_before)
        
        # Ledger checks
        events = self.bus.get_events()
        ids = [e["event_id"] for e in events]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate Event IDs detected!")
        
        # Persistence Check
        self.assertTrue(Path(SIM_DATA / "ledger.jsonl").exists())
        self.assertTrue(Path(SIM_DATA / "state.json").exists())
        
        print("\n" + "="*40)
        print("SISTEMA APROVADO PARA EXECUÇÃO REAL")
        print("="*40)

if __name__ == "__main__":
    unittest.main()
