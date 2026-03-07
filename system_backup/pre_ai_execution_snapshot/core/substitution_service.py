"""
core/substitution_service.py — Market Loop Substitution Engine
Deterministic evaluation of version candidates against baselines.
"""
from infrastructure.logger import get_logger

logger = get_logger("SubstitutionService")

class SubstitutionService:
    @staticmethod
    def evaluate(candidate: dict, baseline: dict, 
                 min_rpm_gain: float = 0.0, 
                 min_roas_gain: float = 0.0,
                 max_margin_deg: float = 0.05) -> dict:
        """
        Evaluate if a candidate version should replace the baseline.
        
        Rules:
        1. (RPM gain > min_rpm_gain OR ROAS gain > min_roas_gain)
        2. Margin drop <= max_margin_deg
        """
        if not candidate or not baseline:
            return {"approved": False, "reason": "Missing snapshot data"}

        c_rpm = candidate.get("rpm", 0.0)
        c_roas = candidate.get("roas", 0.0)
        c_mrg = candidate.get("margin", 0.0)

        b_rpm = baseline.get("rpm", 0.0)
        b_roas = baseline.get("roas", 0.0)
        b_mrg = baseline.get("margin", 0.0)

        margin_drop = b_mrg - c_mrg
        rpm_gain = c_rpm - b_rpm
        roas_gain = c_roas - b_roas

        if margin_drop > max_margin_deg:
            return {
                "approved": False, 
                "reason": f"Margin degraded: {margin_drop:.4f} > {max_margin_deg}"
            }

        if rpm_gain > min_rpm_gain or roas_gain > min_roas_gain:
            return {
                "approved": True,
                "reason": f"Improvement detected: RPM gain={rpm_gain:.4f}, ROAS gain={roas_gain:.4f}"
            }

        return {
            "approved": False,
            "reason": "No significant improvement detected"
        }
