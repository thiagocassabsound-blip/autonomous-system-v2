import os
import re
import datetime

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
GOV_DIR = os.path.join(BASE_DIR, "system_governance")
DOCS_DIR = os.path.join(BASE_DIR, "system_docs")

LEDGER_FILE = os.path.join(GOV_DIR, "implementation_ledger.md")
GAP_REPORT_FILE = os.path.join(DOCS_DIR, "implementation_gap_report.md")
PLAN_FILE = os.path.join(DOCS_DIR, "implementation_execution_plan.md")
EXEC_LOG = os.path.join(GOV_DIR, "execution_log.md")

# Governance prep
import sys
sys.path.append(BASE_DIR)
from infra.governance.compliance_guard import run_governance_preflight

def collect_gaps():
    """Reads the ledger to find tasks marked as ⬜ or ⏳"""
    gaps = []
    with open(LEDGER_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            match = re.match(r"^(\d+)\s+([⬜⏳])\s+(.*)$", line.strip())
            if match:
                gaps.append({
                    "id": int(match.group(1)),
                    "status": match.group(2),
                    "desc": match.group(3)
                })
    return gaps

def map_task_to_phase(task_id: int):
    """Maps ledger task IDs to one of the 13 implementation phases."""
    if 98 <= task_id <= 101: return 4 # Radar
    if task_id == 108: return 7 # Telemetry (Feedback limits)
    if 141 <= task_id <= 147: return 12 # Tests (Ignition full test)
    if 168 <= task_id <= 174: return 2 # Infra completion (V1 kill)
    if 175 <= task_id <= 193: return 3 # External Integrations (audit)
    if 202 <= task_id <= 208: return 6 # Landing tests
    if 247 <= task_id <= 290: return 12 # System Validation & Stress Tests
    if 291 <= task_id <= 316: return 11 # Staging Deploy
    if 317 <= task_id <= 349: return 10 # Dashboard
    if 350 <= task_id <= 369: return 12 # UX Flow / Tests
    if 370 <= task_id <= 445: return 12 # Auditoria global
    if 446 <= task_id <= 487: return 13 # Market Activation
    return 1 # Fallback to Foundation

def build_execution_plan(gaps):
    phases = {
        1: {"name": "1️⃣ Foundation Stabilization", "objective": "Finalizing core system foundations.", "tasks": []},
        2: {"name": "2️⃣ Infrastructure Completion", "objective": "Removing legacy code and ensuring V2 is self-sufficient.", "tasks": []},
        3: {"name": "3️⃣ External Integration Infrastructure", "objective": "Auditing API boundaries for Stripe, Resend, and OpenAI.", "tasks": []},
        4: {"name": "4️⃣ Radar System Completion", "objective": "Tuning minimum parameter thresholds and confluence algorithms.", "tasks": []},
        5: {"name": "5️⃣ Product Lifecycle Engines", "objective": "Finalizing lifecycle transition logic.", "tasks": []},
        6: {"name": "6️⃣ Landing Generation System", "objective": "Validating conversions for HTML/LLM output.", "tasks": []},
        7: {"name": "7️⃣ Telemetry & Monitoring", "objective": "Tuning accumulator thresholds (e.g., feedback limits).", "tasks": []},
        8: {"name": "8️⃣ Operational Intelligence Loop", "objective": "Integrating tactical intelligence without mutating state natively.", "tasks": []},
        9: {"name": "9️⃣ Observability Layer", "objective": "Implementing runtime tracking and event traceability.", "tasks": []},
        10: {"name": "🔟 Dashboard System", "objective": "Building the UI command and control tower over the infrastructure.", "tasks": []},
        11: {"name": "11️⃣ Staging Deployment Infrastructure", "objective": "Establishing the container/hosting architecture on Railway.", "tasks": []},
        12: {"name": "12️⃣ System Validation & Stress Tests", "objective": "Auditing and ensuring resilience before market contact.", "tasks": []},
        13: {"name": "13️⃣ Market Activation Readiness", "objective": "Preparing for the first commercial deployment validation.", "tasks": []}
    }
    
    # Custom inserts required by prompt
    phases[8]["tasks"].append({
        "id": "A1",
        "desc": "Create /core/intelligence/operational_intelligence_loop.py (Strategic Signals generator)",
        "impact": "HIGH", "deps": "Telemetry, Radar, Finance", "modules": "/core/intelligence/operational_intelligence_loop.py",
        "complexity": "HIGH", "risk": "Must strictly emit enrichment_signal_event without corrupting state.",
        "outputs": "Active strategic feedback loop."
    })
    
    phases[9]["tasks"].append({
        "id": "A2",
        "desc": "Create Event Trace and Runtime Log adapters",
        "impact": "MEDIUM", "deps": "EventBus", "modules": "/infra/observability/runtime_logger.py, /infra/observability/event_trace.py",
        "complexity": "MEDIUM", "risk": "I/O bound logging might bottleneck EventBus if not asynchronous.",
        "outputs": "/logs/runtime_events.log and /logs/event_trace.log"
    })

    # Distribute Ledger Tasks
    for g in gaps:
        tid = g["id"]
        phase_num = map_task_to_phase(tid)
        
        # Calculate impact heuristically based on ID bucket mapping from previous phase
        impact = "CRITICAL"
        if phase_num in [4, 6]: impact = "HIGH"
        if phase_num in [10]: impact = "MEDIUM"
        if phase_num == 7: impact = "LOW"
        
        complexity = "LOW"
        if phase_num in [11, 12]: complexity = "HIGH"
        if phase_num in [4, 6, 8, 10]: complexity = "MEDIUM"
        
        phases[phase_num]["tasks"].append({
            "id": str(tid),
            "desc": g["desc"],
            "impact": impact,
            "deps": f"Phase {phase_num-1} components",
            "modules": "Various",
            "complexity": complexity,
            "risk": "Requires DRY RUN testing for structural integrity.",
            "outputs": f"Task {tid} implemented and checked."
        })

    md_lines = [
        "# IMPLEMENTATION EXECUTION PLAN",
        "**Phase 7 Architectural Roadmap**\n",
        "> [!IMPORTANT] \n> **GOVERNANCE CONSTRAINT** \n> Ledger files remain append-only. Only the Orchestrator mutates state.\n"
    ]

    for i in range(1, 14):
        p = phases[i]
        md_lines.append(f"## {p['name']}")
        md_lines.append(f"**Objective**: {p['objective']}\n")
        
        if not p["tasks"]:
            md_lines.append("_No pending ledger tasks in this phase._\n")
            continue
            
        for t in p["tasks"]:
            md_lines.append(f"### Task {t['id']}: {t['desc']}")
            md_lines.append(f"- **Impact Level**: {t['impact']}")
            md_lines.append(f"- **Dependencies**: {t['deps']}")
            md_lines.append(f"- **Affected Modules**: {t['modules']}")
            md_lines.append(f"- **Required Integrations**: Internal EventBus")
            md_lines.append(f"- **Estimated Complexity**: {t['complexity']}")
            md_lines.append(f"- **Risk Notes**: {t['risk']}")
            md_lines.append(f"- **Expected Outputs**: {t['outputs']}\n")
            
        md_lines.append("\n---\n")

    return "\n".join(md_lines)

def run_planner():
    gaps = collect_gaps()
    plan_content = build_execution_plan(gaps)
    
    # Governance request
    action = {
        "name": "Generate Execution Plan & Update Ledger Status to IN_PROGRESS",
        "type": "file_mutation",
        "target_file": "implementation_ledger.md",
        "operation": "overwrite",
        "actor": "GovernanceLayer",
        "is_structural_modification": False
    }

    print("Requesting Preflight for phase planner...")
    if not run_governance_preflight(action):
        print("Preflight failed. Stopping.")
        return

    # Write the Plan
    with open(PLAN_FILE, "w", encoding="utf-8") as f:
        f.write(plan_content)
    print(f"Execution plan written to {PLAN_FILE}")

    # Update Ledger: replace ⬜ and ⏳ with 🟡
    with open(LEDGER_FILE, 'r', encoding='utf-8') as f:
        ledger_text = f.read()

    new_ledger_text = re.sub(r"^(\d+)\s+[⬜⏳]", r"\1 🟡", ledger_text, flags=re.MULTILINE)
    
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        f.write(new_ledger_text)
    print("Ledger synced with planner (Tasks moved to IN_PROGRESS).")

    # Write to execution log
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_entry = f"| {timestamp} | P7 | execution_plan_generated | system-wide | SUCCESS | Execution Roadmap created. |\n"
    with open(EXEC_LOG, "a", encoding="utf-8") as f:
        f.write(log_entry)
        
    print("Execution Log updated.")

if __name__ == "__main__":
    run_planner()
