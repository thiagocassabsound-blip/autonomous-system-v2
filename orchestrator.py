import os
import sys
import subprocess
from infrastructure.logger import get_logger

logger = get_logger("ProjectOrchestrator")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run_script(script_name: str) -> bool:
    script_path = os.path.join(BASE_DIR, script_name)
    if not os.path.exists(script_path):
        logger.error(f"[FAIL] Script not found: {script_name}")
        return False
        
    logger.info(f"==> Starting execution: {script_name}")
    try:
        # Avoid hanging if scripts are interactive or infinite looping unless they are meant to
        # But per the prompt, we coordinate their execution as a pipeline sequentially
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info(f"[OK] Successfully executed {script_name}")
            return True
        else:
            logger.error(f"[ERROR] Failed to execute {script_name}. Return code: {result.returncode}")
            logger.error(f"STDOUT:\n{result.stdout}")
            logger.error(f"STDERR:\n{result.stderr}")
            return False
    except Exception as e:
        logger.error(f"[EXCEPTION] Could not run {script_name}: {e}")
        return False

def run_boot_simulation() -> bool:
    return run_script("boot_simulation.py")

def run_audit_phase8() -> bool:
    return run_script("audit_phase8.py")

def run_audit_phase8_dynamic() -> bool:
    return run_script("audit_phase8_dynamic.py")

def run_llm_pain_analyzer_adapter() -> bool:
    return run_script(os.path.join("migrations", "llm_pain_analyzer_adapter.py"))

def run_pricing_ab_test_adapter() -> bool:
    return run_script(os.path.join("migrations", "pricing_ab_test_adapter.py"))

def run_generate_logs() -> bool:
    return run_script("generate_logs.py")

def run_audit_phase9_dashboard() -> bool:
    return run_script("audit_phase9_dashboard.py")

def start_system() -> dict:
    """
    Executes the full pipeline sequentially as requested.
    Returns a status dict.
    """
    logger.info(">>> BEGINNING FULL PIPELINE ORCHESTRATION <<<")
    results = {}
    
    results["boot_simulation"] = run_boot_simulation()
    if not results["boot_simulation"]:
        logger.warning("Pipeline halted at boot_simulation.")
        return {"status": "HALTED", "details": results}

    results["audit_phase8"] = run_audit_phase8()
    results["audit_phase8_dynamic"] = run_audit_phase8_dynamic()
    results["llm_pain_analyzer"] = run_llm_pain_analyzer_adapter()
    results["pricing_ab_test"] = run_pricing_ab_test_adapter()
    results["generate_logs"] = run_generate_logs()
    results["audit_phase9_dashboard"] = run_audit_phase9_dashboard()
    
    logger.info(">>> PIPELINE ORCHESTRATION COMPLETED <<<")
    return {"status": "COMPLETED", "details": results}

if __name__ == "__main__":
    start_system()
