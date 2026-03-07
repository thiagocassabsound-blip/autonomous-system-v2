import os
import sys
import json
import time

from pathlib import Path

# Ensure V2 root is in path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.logger import get_logger

logger = get_logger("BootstrapVerify")

def verify_bootstrap():
    print(">>> VERIFYING COMMERCIAL ENGINE BOOTSTRAP <<<")
    
    # We import the orchestrator_instance after it's been initialized by the launcher
    try:
        from production_launcher import orchestrator_instance
        
        # 1. Check Service Registration
        ce = orchestrator_instance._services.get("commercial_engine")
        if ce:
            print("[SUCCESS] CommercialEngine registered in Orchestrator.")
        else:
            print("[FAILED] CommercialEngine NOT found in service registry.")
            sys.exit(1)
            
        # 2. Routing Smoke Test
        print("\n--- ROUTING SMOKE TEST ---")
        event_id = f"test_boot_{int(time.time())}"
        
        # Disable strict mode for this test to avoid needing the full orchestrated context in a script
        # Or better, just use receive_event which handles the context internally
        
        orchestrator_instance.receive_event(
            event_type="payment_confirmed",
            payload={
                "user_id": "boot_test@example.com",
                "product_id": "test_v2",
                "payment_id": "pay_boot_123",
                "source": "system",
                "event_id": event_id
            },
            product_id="test_v2",
            source="system"
        )
        
        # 3. Persistence Validation
        # CommercialEngine uses CommercialPersistence which writes to commercial_state.json
        with open("commercial_state.json", "r") as f:
            state = json.load(f)
            
        # CommercialEngine.confirm_payment uses customer_email/user_id as key
        # In my mock I used user_id: boot_test@example.com
        if "boot_test@example.com" in state:
            print("[SUCCESS] Commercial record persisted to commercial_state.json.")
            print(f"Record: {state['boot_test@example.com']}")
        else:
            print("[FAILED] Commercial record NOT found in state file.")
            sys.exit(1)
            
        # 4. Ledger Validation
        events = orchestrator_instance._bus.get_events()
        boot_ev = [e for e in events if e.get("payload", {}).get("event_id") == event_id]
        if boot_ev:
            print("[SUCCESS] Event recorded in Ledger.")
        else:
            print("[FAILED] Event NOT found in Ledger.")
            sys.exit(1)
            
        print("\n>>> ALL BOOTSTRAP CHECKS PASSED <<<")

    except Exception as e:
        print(f"Bootstrap Verification Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    verify_bootstrap()
