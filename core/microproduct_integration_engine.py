"""
core/microproduct_integration_engine.py

Constitutional module that integrates MicroProductSpecificationEngine (MPSE)
output into the VersionManager pipeline by creating a version candidate 
with a linked structural snapshot.
"""

import sys
from pathlib import Path

# -- path bootstrap -----------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uuid
from datetime import datetime, timezone
from core.microproduct_spec_engine import MicroProductSpecificationEngine

class MicroProductIntegrationError(Exception):
    """Raised when microproduct integration into version pipeline fails."""
    pass


class MicroProductIntegrationEngine:
    """
    Integrates microproduct specifications into the versioning system.
    
    Validated product state, generates spec, creates structural snapshot,
    and registers a version candidate via the Orchestrator.
    """

    def generate_and_register_candidate(
        self, 
        product_id: str, 
        normalized_cluster: dict, 
        orchestrator, 
        version_manager, 
        telemetry_engine
    ) -> dict:
        """
        Main integration entry point. Validates state, generates spec, and registers candidate.
        
        Args:
            product_id (str): The product ID (must be in Draft state).
            normalized_cluster (dict): The normalized radar data.
            orchestrator: The system Orchestrator (A4).
            version_manager: The Version Manager (A8).
            telemetry_engine: The Telemetry Engine (A4.1).
            
        Returns:
            dict: Integration result summary.
            
        Raises:
            MicroProductIntegrationError: If any step fails.
        """
        
        # --- STEP 1: Validate Product State ---
        # Note: In V2, we check state via StateMachine or Orchestrator's state access.
        # Assuming product_life_engine or state_machine is registered as a service or accessible.
        # We'll use product_id to lookup state in state_machine (available via orchestrator.state).
        
        state_info = orchestrator.state.get_product_state(product_id)
        current_state = state_info.get("state") if state_info else None
        
        if current_state != "Draft":
            raise MicroProductIntegrationError(
                f"Product '{product_id}' must be in 'Draft' state. Current state: '{current_state}'"
            )

        # --- STEP 2: Generate MicroProduct Spec ---
        mpse = MicroProductSpecificationEngine()
        try:
            spec = mpse.generate_spec(normalized_cluster)
        except Exception as e:
            raise MicroProductIntegrationError(f"MPSE spec generation failed: {e}")

        # --- STEP 3: Create Structural Snapshot ---
        snapshot_id = str(uuid.uuid4())
        snapshot = {
            "snapshot_id": snapshot_id,
            "product_id": product_id,
            "baseline_version": "1.0",
            "structure": spec,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "origin": "C2_MPSE"
        }
        
        try:
            telemetry_engine.store_snapshot(snapshot)
        except Exception as e:
            raise MicroProductIntegrationError(f"Failed to persist structural snapshot: {e}")

        # --- STEP 4: Register Version Candidate via Orchestrator ---
        try:
            orchestrator.receive_event(
                "version_candidate_created",
                {
                    "product_id": product_id,
                    "version_label": "1.0",
                    "snapshot_id": snapshot_id
                },
                source="C2_Integration"
            )
        except Exception as e:
            raise MicroProductIntegrationError(f"Failed to register version candidate: {e}")

        # --- STEP 5: Return Integration Result ---
        return {
            "status": "candidate_registered",
            "product_id": product_id,
            "snapshot_id": snapshot_id,
            "version_label": "1.0",
            "micro_pain_id": spec["micro_pain_id"],
            "transformation_statement": spec["transformation_statement"]
        }


# ==============================================================================
# INTERNAL VERIFICATION TESTS
# ==============================================================================

def run_internal_verification():
    """Validates the integration engine logic using mocks."""
    print(">>> Starting MicroProductIntegrationEngine Verification...")
    
    # --- Mocks ---
    class MockState:
        def get_product_state(self, pid):
            if pid == "valid-draft":
                return {"state": "Draft"}
            return {"state": "Active"}

    class MockOrchestrator:
        def __init__(self):
            self.state = MockState()
            self.events = []
        def receive_event(self, event_type, payload, source=None):
            self.events.append({"type": event_type, "payload": payload, "source": source})

    class MockTelemetry:
        def __init__(self):
            self.snapshots = {}
        def store_snapshot(self, snapshot):
            sid = snapshot.get("snapshot_id")
            if not sid: raise ValueError("missing id")
            self.snapshots[sid] = snapshot

    class MockVersionManager:
        pass

    engine = MicroProductIntegrationEngine()
    orch = MockOrchestrator()
    telemetry = MockTelemetry()
    vm = MockVersionManager()

    mock_cluster = {
        "cluster_id": "c-001",
        "cluster_label": "Test Pain",
        "total_mentions": 100,
        "growth_percent_30d": 20.0,
        "growth_percent_90d": 10.0,
        "intensity_score": 80.0,
        "emotional_score": 80.0,
        "monetization_score": 80.0,
        "gap_strength_score": 0.8,
        "detected_tasks": [
            {"task_id": "t-01", "task_label": "Slow work", "frequency": 0.9, "execution_simplicity": 0.9}
        ]
    }

    # Case 1: Successful Integration
    try:
        res = engine.generate_and_register_candidate(
            "valid-draft", mock_cluster, orch, vm, telemetry
        )
        assert res["status"] == "candidate_registered"
        assert len(orch.events) == 1
        assert orch.events[0]["type"] == "version_candidate_created"
        assert len(telemetry.snapshots) == 1
        print("[PASS] Successful integration verified.")
    except Exception as e:
        print(f"[FAIL] Success scenario failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Case 2: Wrong State Guard
    try:
        engine.generate_and_register_candidate(
            "active-prod", mock_cluster, orch, vm, telemetry
        )
        print("[FAIL] State guard failed (should have raised error).")
        return False
    except MicroProductIntegrationError as e:
        print(f"[PASS] State guard correctly rejected non-Draft product: {e}")

    # Case 3: Proper Snapshot Linking
    try:
        sid = orch.events[0]["payload"]["snapshot_id"]
        assert sid in telemetry.snapshots
        assert telemetry.snapshots[sid]["product_id"] == "valid-draft"
        assert "structure" in telemetry.snapshots[sid]
        print("[PASS] Snapshot linking verified.")
    except Exception as e:
        print(f"[FAIL] Snapshot linking failed: {e}")
        return False

    print(">>> All Internal Verifications Passed.")
    return True


if __name__ == "__main__":
    if run_internal_verification():
        exit(0)
    else:
        exit(1)
