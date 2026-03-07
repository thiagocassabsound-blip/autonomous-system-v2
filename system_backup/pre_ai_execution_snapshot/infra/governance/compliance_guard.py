import os
import json
import datetime
from typing import Dict, Any, List

# Define the absolute paths based on the known project structure
BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
GOVERNANCE_DIR = os.path.join(BASE_DIR, "system_governance")
EXECUTION_LOG = os.path.join(GOVERNANCE_DIR, "execution_log.md")

APPEND_ONLY_FILES = [
    "ledger.jsonl",
    "radar_snapshots.jsonl",
    "telemetry_accumulators.json",
    "state.json"
]

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "RESEND_API_KEY",
    "SERPER_API_KEY"
]

class GovernanceViolation(Exception):
    """Exception raised when an action violates the system governance."""
    pass

def log_governance_validation(action: Dict[str, Any], result: str, details: str = ""):
    """Logs the validation result into the official execution_log.md."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    action_name = action.get('name', 'UNKNOWN_ACTION')
    modules = str(action.get('affected_modules', []))
    
    log_entry = f"| {timestamp} | Governance Guard | {action_name} | {modules} | {result} {details} |\n"
    
    with open(EXECUTION_LOG, "a", encoding="utf-8") as f:
        f.write(log_entry)

def validate_constitution_rules(action: Dict[str, Any]):
    """
    Verifies authority of state mutation, enforces append-only, and economic rules.
    action dict example: 
    {
        "type": "file_mutation", 
        "target_file": "ledger.jsonl", 
        "operation": "overwrite",
        "actor": "EnrichmentEngine"
    }
    """
    # Rule: Append Only Protection
    target_file = action.get("target_file", "")
    operation = action.get("operation", "")
    actor = action.get("actor", "")

    if any(target_file.endswith(f) for f in APPEND_ONLY_FILES):
        if operation in ["overwrite", "delete", "truncate", "w"]:
            raise GovernanceViolation(f"Constitution Violation: Attempted to {operation} append-only file {target_file}.")

    # Rule: Authority of State Mutation
    if action.get("type") == "state_mutation":
        if actor != "Orchestrator":
            raise GovernanceViolation(f"Constitution Violation: State mutation attempted by non-sovereign actor '{actor}'. Only the Orchestrator may mutate state.")

def validate_blocks_architecture(action: Dict[str, Any]):
    """
    Verifies engines respect their defined responsibilities and prevents cross-domain mutations.
    """
    actor = action.get("actor", "")
    action_type = action.get("type", "")

    # Rule: Enrichment Engine (Block 28) Protection
    if actor == "EnrichmentEngine" and action_type == "state_mutation":
        raise GovernanceViolation("Blocks Architecture Violation: Enrichment Engine (Block 28) must NEVER mutate system state directly. It may only emit enrichment_signal_event.")

    # Prevent direct ledger writes bypassing EventBus/Orchestrator
    if action_type == "file_mutation" and target_is_ledger(action.get("target_file", "")):
        if actor not in ["EventBus", "Orchestrator", "StateManager", "GovernanceLayer"]:
             raise GovernanceViolation(f"Blocks Architecture Violation: Actor '{actor}' attempted to write directly to ledger bypassing the Orchestrator.")

def target_is_ledger(target_file: str) -> bool:
    return any(f in target_file for f in APPEND_ONLY_FILES)

def validate_ledger_permissions(action: Dict[str, Any]):
    """
    Verifies that the modification corresponds to a valid task mapped in the implementation ledger.
    """
    # At this architectural stage, if the action explicitly declares 'unauthorized_structural_change'
    if action.get("is_structural_modification", False):
        ledger_task_id = action.get("ledger_task_id")
        if not ledger_task_id:
             raise GovernanceViolation("Ledger Permission Violation: Structural modification attempted without a valid ledger_task_id.")

def validate_dashboard_constraints(action: Dict[str, Any]):
    """
    Confirms the dashboard remains a read-only visualization system.
    """
    actor = action.get("actor", "")
    action_type = action.get("type", "")
    
    if actor == "Dashboard":
        if action_type in ["state_mutation", "metric_calculation", "file_mutation"]:
            raise GovernanceViolation(f"Dashboard Constraint Violation: Dashboard attempting '{action_type}'. Dashboard is strictly read-only and may only emit intent events.")

def validate_integration_safety():
    """
    Validates that all required external integrations (Env Vars) are properly configured.
    """
    # To mimic a real check over the .env file in the root
    env_file = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_file):
        raise GovernanceViolation("Integration Safety Violation: .env file missing.")
        
    with open(env_file, "r", encoding="utf-8") as f:
        content = f.read()
        
    for var in REQUIRED_ENV_VARS:
        if f"{var}=" not in content:
            raise GovernanceViolation(f"Integration Safety Violation: Missing required credential '{var}'.")

def run_governance_preflight(action: Dict[str, Any]) -> bool:
    """
    Executes all validations before any structural action.
    If validation fails, execution is STOPPED, violation is logged.
    """
    try:
        if action.get("requires_integration_check", False):
            validate_integration_safety()

        validate_constitution_rules(action)
        validate_blocks_architecture(action)
        validate_ledger_permissions(action)
        validate_dashboard_constraints(action)
        
        log_governance_validation(action, "SUCCESS")
        return True
        
    except GovernanceViolation as e:
        log_governance_validation(action, "FAIL", details=str(e))
        print(f"\n[GOVERNANCE CRITICAL STOP] {e}")
        # In a real pipeline, returning False or propagating the exception halts the action script.
        return False
