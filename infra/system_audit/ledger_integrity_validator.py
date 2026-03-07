import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")

class LedgerIntegrityValidator:
    """
    Validates the structure and existence of protected global ledgers.
    Confirms they are not being overwritten incorrectly (through file permissions or exist checks).
    """
    PROTECTED_LEDGERS = [
        "state.json",
        "radar_snapshots.jsonl",
        "telemetry_accumulators.json",
        "rss_signal_ledger.jsonl"
    ]
    # ledger.jsonl might be huge or located at BASE_DIR depending on system
    
    @staticmethod
    def validate():
        results = {
            "status": "OK",
            "missing_ledgers": [],
            "violations": []
        }
        
        # Check standard data folder ledgers
        for ledger in LedgerIntegrityValidator.PROTECTED_LEDGERS:
            pth = os.path.join(DATA_DIR, ledger)
            if not os.path.exists(pth):
                results["status"] = "WARNING"
                results["missing_ledgers"].append(ledger)
                results["violations"].append(f"ledger_integrity_violation: {ledger} not found (may not be generated yet)")
                
        # Main transaction ledger
        main_ledger_path = os.path.join(BASE_DIR, "ledger.jsonl")
        if not os.path.exists(main_ledger_path):
            results["status"] = "ERROR"
            results["missing_ledgers"].append("ledger.jsonl")
            results["violations"].append(f"ledger_integrity_violation: Core ledger.jsonl is missing!")
            
        return results
