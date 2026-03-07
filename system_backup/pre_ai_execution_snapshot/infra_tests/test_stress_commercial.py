import os
import json
import uuid
import threading
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from core.commercial_engine import CommercialEngine

# ------------------------------------------------------------
# Setup temp files
# ------------------------------------------------------------

STATE_FILE = "state_stress_test.json"
LEDGER_FILE = "ledger_stress_test.jsonl"

# Clean previous runs
for f in [STATE_FILE, LEDGER_FILE]:
    if os.path.exists(f):
        os.remove(f)

# ------------------------------------------------------------
# Persistence Adapters
# ------------------------------------------------------------

class FilePersistence:
    """Matches StateManager expectations."""
    def __init__(self, path):
        self.path = path
    def load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    def save(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

class LedgerPersistence:
    """Matches EventBus expectations (JSONL)."""
    def __init__(self, path):
        self.path = path
    def load(self):
        events = []
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        return events
    def append(self, entry):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

class MockPersistence:
    """In-memory mock for CommercialEngine."""
    def __init__(self, initial_data=None):
        self.data = initial_data if initial_data is not None else {}
    def load(self): return self.data
    def save(self, data): self.data = data

# ------------------------------------------------------------
# Boot isolated system
# ------------------------------------------------------------

state_pers = FilePersistence(STATE_FILE)
ledger_pers = LedgerPersistence(LEDGER_FILE)

bus = EventBus(log_persistence=ledger_pers)
state = StateManager(persistence=state_pers)
orch = Orchestrator(event_bus=bus, state_manager=state)

comm_pers = MockPersistence({})
commercial = CommercialEngine(orchestrator=orch, persistence=comm_pers)
orch.register_service("commercial_engine", commercial)

# ------------------------------------------------------------
# Helper: simulate purchase event
# ------------------------------------------------------------

def simulate_purchase(i):
    # The payload expected by Orchestrator._sh_purchase_success:
    # amount_total, customer_email, stripe_session_id
    product_id = f"stress_product_{i}"
    payload = {
        "event_type": "purchase_success",
        "product_id": product_id,
        "customer_email": f"user{i}@test.com",
        "amount_total": 100.0,
        "stripe_session_id": f"sess_{uuid.uuid4()}"
    }
    orch.receive_event("purchase_success", payload)

# ------------------------------------------------------------
# PHASE 1 — 50 Sequential Events
# ------------------------------------------------------------

sequential_ok = True

try:
    for i in range(50):
        simulate_purchase(i)
except Exception as e:
    sequential_ok = False
    print(f"Sequential Error: {e}")

# ------------------------------------------------------------
# PHASE 2 — 20 Concurrent Events
# ------------------------------------------------------------

threads = []
concurrent_ok = True

try:
    for i in range(50, 70):
        t = threading.Thread(target=simulate_purchase, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
except Exception as e:
    concurrent_ok = False
    print(f"Concurrent Error: {e}")

# ------------------------------------------------------------
# PHASE 3 — Ledger Integrity Check
# ------------------------------------------------------------

ledger_integrity = True
duplicate_event_ids = False
corrupt_lines = False

event_ids = set()

try:
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    record = json.loads(line)
                    eid = record.get("event_id")
                    if not eid:
                        ledger_integrity = False
                    if eid in event_ids:
                        duplicate_event_ids = True
                    event_ids.add(eid)
                except Exception:
                    corrupt_lines = True
    else:
        ledger_integrity = False
except Exception:
    ledger_integrity = False

if duplicate_event_ids or corrupt_lines:
    ledger_integrity = False

# ------------------------------------------------------------
# PHASE 4 — State Consistency
# ------------------------------------------------------------

state_consistent = True

try:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state_data = json.load(f)

        if not isinstance(state_data, dict):
            state_consistent = False
    else:
        state_consistent = False

except Exception:
    state_consistent = False

# ------------------------------------------------------------
# FINAL RESULT
# ------------------------------------------------------------

result = {
    "sequential_events_stable": sequential_ok,
    "concurrent_events_stable": concurrent_ok,
    "ledger_integrity_valid": ledger_integrity,
    "state_consistent": state_consistent,
    "duplicate_event_ids_detected": duplicate_event_ids,
    "corrupt_ledger_lines_detected": corrupt_lines,
    "total_events_recorded": len(event_ids),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}

print(json.dumps(result, indent=2))

# Cleanup
for f in [STATE_FILE, LEDGER_FILE]:
    if os.path.exists(f):
        os.remove(f)

if not all([
    sequential_ok,
    concurrent_ok,
    ledger_integrity,
    state_consistent,
]):
    sys.exit(1)
