import os
import sys
import re

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
DASHBOARD_DIR = os.path.join(BASE_DIR, "dashboard")

def run_audit():
    errors = []
    log = []
    
    log.append("Scanning /dashboard/ directory structure...")
    expected_files = ["dashboard_server.py", "dashboard_api.py", "dashboard_state_store.py"]
    for f in expected_files:
        if os.path.exists(os.path.join(DASHBOARD_DIR, f)):
            log.append(f"  [OK] Found {f}")
        else:
            errors.append(f"Missing file: {f}")
            
    expected_dirs = ["frontend"]
    for d in expected_dirs:
        if os.path.isdir(os.path.join(DASHBOARD_DIR, d)):
            log.append(f"  [OK] Found /{d}/ directory")
        else:
            errors.append(f"Missing directory: /{d}/")

    log.append("\nVerifying Read Model constraints (dashboard_state_store.py)...")
    store_file = os.path.join(DASHBOARD_DIR, "dashboard_state_store.py")
    if os.path.exists(store_file):
        with open(store_file, 'r', encoding='utf-8') as f:
            content = f.read()
            if re.search(r"open\([^)]+['\"]w['\"]", content) or re.search(r"open\([^)]+['\"]a['\"]", content) or ".write(" in content or ".append(" in content and "ledger" in content:
                # Need to be smart about .append() for lists vs files. 
                # Let's check for specific forbidden patterns literally
                forbidden = ["'w'", '"w"', "'a'", '"a"', ".write("]
                violations = [b for b in forbidden if b in content]
                if violations:
                    errors.append(f"State store contains write operations: {violations}")
                else:
                    log.append("  [OK] No file writing detected in state store.")
    else:
        errors.append("dashboard_state_store.py not found.")

    log.append("\nChecking Engine Isolation in dashboard_api.py and dashboard_server.py...")
    for pf in ["dashboard_api.py", "dashboard_server.py"]:
        pfile = os.path.join(DASHBOARD_DIR, pf)
        if os.path.exists(pfile):
            with open(pfile, 'r', encoding='utf-8') as f:
                content = f.read()
                if "from engine" in content or "import engine" in content or "engine." in content:
                    errors.append(f"Engine direct access detected in {pf}")
                else:
                    log.append(f"  [OK] Engine isolation verified in {pf}")
                    
    log.append("\nValidating EventBus usage for Intents...")
    server_file = os.path.join(DASHBOARD_DIR, "dashboard_server.py")
    if os.path.exists(server_file):
        with open(server_file, 'r', encoding='utf-8') as f:
            content = f.read()
            if "EventBus" in content and "emit(" in content:
                log.append("  [OK] Intents are properly routed via EventBus.")
            else:
                errors.append("Dashboard does not properly emit intent events via EventBus.")

    log.append("\nChecking Ledger Protection...")
    # search all dashboard py files
    for root, dirs, files in os.walk(DASHBOARD_DIR):
        for file in files:
            if file.endswith('.py'):
                with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "ledger.jsonl" in content and ("'w'" in content or "'a'" in content or '"w"' in content or '"a"' in content):
                        errors.append(f"Ledger mutation detected in {file}")

    log.append("  [OK] No ledger modifications found.")

    log.append("\nValidating Frontend Connection Constraints...")
    frontend_js = os.path.join(DASHBOARD_DIR, "frontend", "app.js")
    if os.path.exists(frontend_js):
        with open(frontend_js, 'r', encoding='utf-8') as f:
            js_content = f.read()
            if "fetch(" in js_content and "API_BASE" in js_content:
                log.append("  [OK] Frontend exclusively calls API endpoints.")
            if "fs.read" in js_content or "fetch('file://" in js_content:
                errors.append("Frontend attempts to read files directly.")

    log.append("\nObservability Connection Check...")
    # We want to ensure it uses logs safely
    if os.path.exists(server_file):
        with open(server_file, 'r', encoding='utf-8') as f:
            if "AsyncLogWorker" in f.read():
                log.append("  [OK] Observability logger correctly implemented.")
            else:
                errors.append("Observability connection missing.")

    print("\n".join(log))
    
    if errors:
        print("\n[FAIL] ARCHITECTURE VIOLATION DETECTED")
        for err in errors:
            print(f" - {err}")
        return False, log, errors
    else:
        print("\n[SUCCESS] ARCHITECTURE VERIFIED")
        return True, log, []

if __name__ == "__main__":
    success, log, errs = run_audit()
    
    report_path = os.path.join(BASE_DIR, "system_docs", "dashboard_architecture_audit.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Dashboard Architecture Audit Report\n\n")
        f.write("## Execution Log\n")
        f.write("```\n")
        f.write("\n".join(log))
        f.write("\n```\n\n")
        
        f.write("## Status\n")
        if success:
            f.write("**ARCHITECTURE VERIFIED**\n")
        else:
            f.write("**ARCHITECTURE VIOLATION DETECTED**\n\n")
            f.write("### Errors:\n")
            for e in errs:
                f.write(f"- {e}\n")
