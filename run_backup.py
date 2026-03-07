import os
import shutil

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
BACKUP_DIR = os.path.join(BASE_DIR, "system_backup", "pre_ai_execution_snapshot")

IGNORE_DIRS = {".git", ".venv", "__pycache__", "system_backup", "__V1_TEMP_DISABLED", ".pytest_cache"}

def safe_copy_env(src, dest):
    """Copies .env file but redacts secret values to maintain structure."""
    with open(src, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    safe_lines = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key, val = line.split("=", 1)
            safe_lines.append(f"{key}=[REDACTED_BY_BACKUP]\n")
        else:
            safe_lines.append(line)
            
    with open(dest, 'w', encoding='utf-8') as f:
        f.writelines(safe_lines)

def create_snapshot():
    print(f"Beggining safe backup to: {BACKUP_DIR}")
    if os.path.exists(BACKUP_DIR):
        print("Backup directory already exists. Overwriting...")
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)
        
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    total_files = 0
    total_size = 0
            
    for item in os.listdir(BASE_DIR):
        item_path = os.path.join(BASE_DIR, item)
        dest_path = os.path.join(BACKUP_DIR, item)
        
        if os.path.isdir(item_path):
            if item in IGNORE_DIRS:
                continue
            shutil.copytree(item_path, dest_path, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            # Calculate size
            for root, _, files in os.walk(dest_path):
                for f in files:
                    total_files += 1
                    total_size += os.path.getsize(os.path.join(root, f))
        elif os.path.isfile(item_path):
            if item == ".env":
                safe_copy_env(item_path, dest_path)
            else:
                shutil.copy2(item_path, dest_path)
            total_files += 1
            total_size += os.path.getsize(dest_path)

    print(f"Snapshot created successfully.")
    print(f"Files Copied: {total_files}")
    print(f"Total Size: {total_size / (1024*1024):.2f} MB")
    
    # Audit Checklist
    print("\n--- Mandatory Files Audit ---")
    mandatory = ["ledger.jsonl", "radar_snapshots.jsonl", "telemetry_accumulators.json", "state.json"]
    for m in mandatory:
        path = os.path.join(BACKUP_DIR, m)
        if os.path.exists(path):
            print(f"[OK] {m} preserved.")
        else:
            print(f"[ERROR] {m} missing from backup!")

if __name__ == "__main__":
    create_snapshot()
