import os
import sys

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

class BootSafetyCheck:
    @staticmethod
    def validate_environment():
        print("Starting Boot Environment Validation...")
        env_dict = {}
        env_file = os.path.join(BASE_DIR, '.env')
        if os.path.exists(env_file):
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            env_dict[parts[0].strip()] = parts[1].strip()
        else:
            print("[FAIL] Missing .env file")
            return False

        critical_keys = ["OPENAI_API_KEY", "STRIPE_SECRET_KEY", "SERPER_API_KEY"]
        missing = [k for k in critical_keys if k not in env_dict or not env_dict[k]]
        if missing:
            print(f"[FAIL] Missing environmental keys: {missing}")
            return False
            
        print("  [OK] Environment variables valid.")
        return True

    @staticmethod
    def validate_filesystem():
        print("Validating Filesystem Structure...")
        required_dirs = ["logs", "data", "system_docs", "system_governance", "dashboard", "core", "infra"]
        for d in required_dirs:
            path = os.path.join(BASE_DIR, d)
            if not os.path.exists(path):
                os.makedirs(path)
                print(f"  [-] Created missing directory: /{d}")
                
        required_files = ["state.json", "ledger.jsonl", "radar_snapshots.jsonl", "telemetry_accumulators.json"]
        data_dir = os.path.join(BASE_DIR, "data")
        for f in required_files:
            path = os.path.join(data_dir, f)
            if not os.path.exists(path):
                # Write empty initial state gracefully
                with open(path, 'w', encoding='utf-8') as file_obj:
                    if f.endswith('.json'):
                        file_obj.write('{}')
                        
                print(f"  [-] Created missing data file: {f}")
        
        print("  [OK] Filesystem structure intact.")
        return True

    @staticmethod
    def validate_workers():
        print("Validating System Runtime Workers...")
        # Check EventBus, Logging, Telemetry, Strategy Memory
        workers = [
            os.path.join(BASE_DIR, "core", "event_bus.py"),
            os.path.join(BASE_DIR, "infra", "observability", "async_worker.py"),
            os.path.join(BASE_DIR, "core", "intelligence", "strategy_memory.py")
        ]
        
        for w in workers:
            if not os.path.exists(w):
                print(f"[FAIL] Missing critical runtime dependency: {w}")
                return False
                
        print("  [OK] Core worker modules are present.")
        return True

    @staticmethod
    def run_all_checks():
        print("=== BOOT SAFETY CHECK ===")
        if not BootSafetyCheck.validate_environment():
            return False
        if not BootSafetyCheck.validate_filesystem():
            return False
        if not BootSafetyCheck.validate_workers():
            return False
            
        # Hard check for DRY_RUN_MODE
        env_file = os.path.join(BASE_DIR, '.env')
        dry_run_active = False
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                if 'DRY_RUN_MODE' in line and 'true' in line.lower():
                    dry_run_active = True
                    break
                    
        if not dry_run_active:
            print("[FAIL] DRY_RUN_MODE is not set to true. Deployment halted.")
            return False
            
        print("=== BOOT SAFE ===")
        return True

if __name__ == "__main__":
    if not BootSafetyCheck.run_all_checks():
        print("SYSTEM DEPLOYMENT HALTED DUE TO SAFETY FAILURES.")
        sys.exit(1)
    else:
        print("SYSTEM READY FOR STAGING.")
