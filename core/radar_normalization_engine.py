"""
core/radar_normalization_engine.py

Deterministic engine to normalize raw radar cluster data (V1 style)
into a V2-consistent schema for governance and further processing.
"""

class RadarNormalizationError(Exception):
    """Raised when radar cluster data fails validation or normalization."""
    pass


class RadarNormalizationEngine:
    """
    Deterministic engine for normalizing radar clusters.
    
    This engine performs field renaming, type enforcement, and value-based guards
    without any LLM dependency or probabilistic scoring.
    """

    REQUIRED_FIELDS = [
        "cluster_id", "cluster_label", "mentions", "growth_30d", "growth_90d",
        "intensity_score", "emotional_score", "monetization_score",
        "gap_strength_score", "complaints", "tasks"
    ]

    def normalize_cluster(self, raw_cluster: dict) -> dict:
        """
        Validates and transforms a raw V1-style cluster into a V2-normalized schema.
        
        Args:
            raw_cluster (dict): The raw input cluster dictionary.

        Returns:
            dict: The normalized cluster according to V2 schema.

        Raises:
            RadarNormalizationError: If validation fails or critical constraints are violated.
        """
        # 1. Validate required fields
        missing = [f for f in self.REQUIRED_FIELDS if f not in raw_cluster]
        if missing:
            raise RadarNormalizationError(f"Missing required fields: {missing}")

        # 2. Extract and Validate Multipliers/Constraints
        mentions = int(raw_cluster["mentions"])
        if mentions <= 0:
            raise RadarNormalizationError(f"Invalid mentions count: {mentions} (must be > 0)")

        growth_30d = float(raw_cluster["growth_30d"])
        if growth_30d < -100:
            raise RadarNormalizationError(f"Invalid 30d growth: {growth_30d}% (below -100% floor)")

        intensity = float(raw_cluster["intensity_score"])
        if intensity < 0:
            raise RadarNormalizationError(f"Invalid intensity score: {intensity} (must be >= 0)")

        monetization = float(raw_cluster["monetization_score"])
        if monetization < 0:
            raise RadarNormalizationError(f"Invalid monetization score: {monetization} (must be >= 0)")

        # 3. Transform Complaint Corpus
        complaint_corpus = []
        for c in raw_cluster["complaints"]:
            complaint_corpus.append({
                "text": str(c.get("text", "")),
                "source": str(c.get("source", "unknown")),
                "timestamp": str(c.get("timestamp", "unknown")),
                "urgency_weight": 0.5,           # Deterministic default
                "solution_intent_weight": 0.5    # Deterministic default
            })

        # 4. Normalize Detected Tasks
        detected_tasks = []
        for t in raw_cluster["tasks"]:
            freq = float(t.get("frequency", 0.0))
            # Bound frequency between 0 and 1
            freq = max(0.0, min(1.0, freq))
            
            simplicity = float(t.get("execution_simplicity", 0.0))
            simplicity = max(0.0, min(1.0, simplicity))

            detected_tasks.append({
                "task_id": str(t.get("task_id", "")),
                "task_label": str(t.get("task_label", "")),
                "frequency": freq,
                "execution_simplicity": simplicity
            })

        # 5. Build Final Schema
        return {
            "cluster_id": str(raw_cluster["cluster_id"]),
            "cluster_label": str(raw_cluster["cluster_label"]),
            "total_mentions": mentions,
            "growth_percent_30d": growth_30d,
            "growth_percent_90d": float(raw_cluster["growth_90d"]),
            "intensity_score": intensity,
            "emotional_score": float(raw_cluster["emotional_score"]),
            "monetization_score": monetization,
            "gap_strength_score": float(raw_cluster["gap_strength_score"]),
            "complaint_corpus": complaint_corpus,
            "detected_tasks": detected_tasks
        }


# ==============================================================================
# INTERNAL UNIT TESTS
# ==============================================================================

def run_internal_verification():
    """Validates the normalization engine logic."""
    print(">>> Starting RadarNormalizationEngine Verification...")
    engine = RadarNormalizationEngine()

    # Case 1: Success Scenario
    valid_raw = {
        "cluster_id": "c-001",
        "cluster_label": "Slow API Response Pain",
        "mentions": 150,
        "growth_30d": 25.5,
        "growth_90d": 10.0,
        "intensity_score": 75.0,
        "emotional_score": 80.0,
        "monetization_score": 65.0,
        "gap_strength_score": 0.8,
        "complaints": [
            {"text": "The API is too slow", "source": "reddit", "timestamp": "2024-01-01"}
        ],
        "tasks": [
            {"task_id": "t-001", "task_label": "Optimize endpoint", "frequency": 0.9, "execution_simplicity": 0.4}
        ]
    }

    try:
        normalized = engine.normalize_cluster(valid_raw)
        assert normalized["total_mentions"] == 150
        assert normalized["growth_percent_30d"] == 25.5
        assert normalized["complaint_corpus"][0]["urgency_weight"] == 0.5
        assert normalized["detected_tasks"][0]["frequency"] == 0.9
        print("[PASS] Valid normalization successful.")
    except Exception as e:
        print(f"[FAIL] Valid normalization failed: {e}")
        return False

    # Case 2: Missing Fields
    invalid_raw = {"cluster_id": "c-002"}
    try:
        engine.normalize_cluster(invalid_raw)
        print("[FAIL] Missing fields check failed (should have raised error).")
        return False
    except RadarNormalizationError as e:
        print(f"[PASS] Missing fields detected: {e}")

    # Case 3: Invalid Mentions
    invalid_mentions = valid_raw.copy()
    invalid_mentions["mentions"] = 0
    try:
        engine.normalize_cluster(invalid_mentions)
        print("[FAIL] Invalid mentions check failed (should have raised error).")
        return False
    except RadarNormalizationError as e:
        print(f"[PASS] Invalid mentions detected: {e}")

    # Case 4: Frequency Clipping
    clipping_raw = valid_raw.copy()
    clipping_raw["tasks"] = [
        {"task_id": "t-002", "task_label": "Extreme freq", "frequency": 1.5, "execution_simplicity": -0.5}
    ]
    try:
        normalized = engine.normalize_cluster(clipping_raw)
        assert normalized["detected_tasks"][0]["frequency"] == 1.0
        assert normalized["detected_tasks"][0]["execution_simplicity"] == 0.0
        print("[PASS] Frequency clipping verified.")
    except Exception as e:
        print(f"[FAIL] Frequency clipping failed: {e}")
        return False

    print(">>> All Internal Verifications Passed.")
    return True


if __name__ == "__main__":
    if run_internal_verification():
        exit(0)
    else:
        exit(1)
