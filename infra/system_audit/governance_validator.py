import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOV_DIR = os.path.join(BASE_DIR, "system_governance")

class GovernanceValidator:
    """
    Validates the constitutional foundation exist and respects
    single-authority and economic bounding principles.
    """
    REQUIRED_FILES = [
        "constitution.md",
        "blocks.md",
        "implementation_ledger.md",
        "dashboard_implementation_plan.md",
        "economic_governance_model.md"
    ]
    
    @staticmethod
    def validate():
        results = {
            "status": "OK",
            "missing_files": [],
            "violations": []
        }
        
        for file in GovernanceValidator.REQUIRED_FILES:
            file_path = os.path.join(GOV_DIR, file)
            if not os.path.exists(file_path):
                results["missing_files"].append(file)
                results["status"] = "ERROR"
                results["violations"].append(f"Missing mandatory governance file: {file}")
                
        # Basic content checks to ensure foundational terminology exists
        # indicating Single Authority Principle presence
        if os.path.exists(os.path.join(GOV_DIR, "constitution.md")):
            with open(os.path.join(GOV_DIR, "constitution.md"), 'r', encoding='utf-8') as f:
                content = f.read().lower()
                if "orchestrator" not in content and "eventbus" not in content:
                    results["status"] = "ERROR"
                    results["violations"].append("constitution.md lacks Orchestrator/Eventbus structural definitions")
        
        return results
