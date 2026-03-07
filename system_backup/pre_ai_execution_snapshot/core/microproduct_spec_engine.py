"""
core/microproduct_spec_engine.py

Deterministic engine to transform normalized radar cluster payloads
into exactly ONE microproduct specification optimized for $5 base pricing.
"""

class MicroProductSpecificationError(Exception):
    """Raised when microproduct specification generation fails guards or logic."""
    pass


class MicroProductSpecificationEngine:
    """
    Deterministic engine for generating microproduct specifications.
    
    Processes normalized clusters through a 7-step pipeline to extract 
    a single high-probability microproduct.
    """

    def generate_spec(self, normalized_cluster: dict, price_base: float = 5.0) -> dict:
        """
        Generates a microproduct specification from normalized radar data.
        
        Args:
            normalized_cluster (dict): Output from RadarNormalizationEngine.
            price_base (float): Base price for the microproduct (default $5.0).
            
        Returns:
            dict: The generated microproduct specification.
            
        Raises:
            MicroProductSpecificationError: If guards or validation steps fail.
        """
        
        # --- STEP 1: MicroPain Selection (Deterministic) ---
        tasks = normalized_cluster.get("detected_tasks", [])
        if not tasks:
            raise MicroProductSpecificationError("Cannot generate spec: No detected_tasks in cluster.")

        scored_tasks = []
        intensity_factor = (normalized_cluster.get("intensity_score", 0.0) / 100.0) * 0.3
        
        for task in tasks:
            micro_score = (
                (task.get("frequency", 0.0) * 0.4) +
                (task.get("execution_simplicity", 0.0) * 0.3) +
                intensity_factor
            )
            scored_tasks.append((micro_score, task))

        # Select highest score (deterministic fallback to first if equal)
        scored_tasks.sort(key=lambda x: x[0], reverse=True)
        micro_score, selected_task = scored_tasks[0]
        task_label = selected_task.get("task_label", "unknown task")

        # --- STEP 2: Complexity Guard ---
        # score = (1 - simplicity)*0.6 + (1 - freq)*0.4
        simplicity = selected_task.get("execution_simplicity", 0.0)
        frequency = selected_task.get("frequency", 0.0)
        
        complexity_score = ((1.0 - simplicity) * 0.6) + ((1.0 - frequency) * 0.4)
        
        if complexity_score > 0.75:
            raise MicroProductSpecificationError(
                f"Task too complex for ${price_base} microproduct (Complexity: {complexity_score:.2f} > 0.75)"
            )

        # --- STEP 3: Transformation Synthesis (Template-Based) ---
        transformation_statement = f"Automate {task_label} in under 20 minutes using a ready-to-use system."
        measurable_outcome = f"Reduce manual execution time of {task_label}"

        # --- STEP 4: Deliverable Definition (Deterministic) ---
        delivery_format = "Template + Execution Guide"
        asset_structure = [
            "ready_to_use_template",
            "step_by_step_execution_guide",
            "quick_start_instructions"
        ]
        setup_time_minutes = 20
        consumption_time_minutes = 45

        # --- STEP 5: Scope Limiter (Deterministic) ---
        scope_included = [
            "template system",
            "execution instructions",
            "example use case"
        ]
        scope_excluded = [
            "customization service",
            "1:1 support",
            "external software integration",
            "advanced automation setup"
        ]

        # --- STEP 6: Value Perception Check ---
        perceived_value_score = (
            (normalized_cluster.get("monetization_score", 0.0) * 0.6) +
            (normalized_cluster.get("emotional_score", 0.0) * 0.4)
        )
        
        value_to_price_ratio = perceived_value_score / price_base
        
        if value_to_price_ratio < 8:
            raise MicroProductSpecificationError(
                f"Insufficient value-to-price ratio: {value_to_price_ratio:.2f} < 8"
            )

        # --- STEP 7: Return Product Specification ---
        return {
            "cluster_id": str(normalized_cluster["cluster_id"]),
            "micro_pain_id": str(selected_task["task_id"]),
            "micro_pain_description": task_label,
            "micro_pain_score": round(micro_score, 4),
            "transformation_statement": transformation_statement,
            "measurable_outcome": measurable_outcome,
            "delivery_format": delivery_format,
            "asset_structure": asset_structure,
            "scope_included": scope_included,
            "scope_excluded": scope_excluded,
            "setup_time_minutes": setup_time_minutes,
            "consumption_time_minutes": consumption_time_minutes,
            "perceived_value_score": round(perceived_value_score, 4),
            "value_to_price_ratio": round(value_to_price_ratio, 4),
            "baseline_version": "1.0"
        }


# ==============================================================================
# INTERNAL VERIFICATION TESTS
# ==============================================================================

def run_internal_verification():
    """Validates the MPSE engine logic."""
    print(">>> Starting MicroProductSpecificationEngine Verification...")
    engine = MicroProductSpecificationEngine()

    # Shared Normalized Input Mock
    mock_cluster = {
        "cluster_id": "c-test-01",
        "cluster_label": "Excel Automation Pain",
        "intensity_score": 80.0,
        "emotional_score": 70.0,
        "monetization_score": 90.0,
        "detected_tasks": [
            {
                "task_id": "t-01",
                "task_label": "Copying data between rows",
                "frequency": 0.9,
                "execution_simplicity": 0.8
            },
            {
                "task_id": "t-02",
                "task_label": "Cleaning broken formulas",
                "frequency": 0.4,
                "execution_simplicity": 0.2
            }
        ]
    }

    # Case 1: Success Scenario
    try:
        spec = engine.generate_spec(mock_cluster, price_base=5.0)
        assert spec["micro_pain_id"] == "t-01"  # Should win due to high simplicity/freq
        assert "Automate Copying data between rows" in spec["transformation_statement"]
        assert spec["value_to_price_ratio"] > 10
        print("[PASS] Success scenario generation verified.")
    except Exception as e:
        print(f"[FAIL] Success scenario failed: {e}")
        return False

    # Case 2: Complexity Guard Trigger
    complex_mock = mock_cluster.copy()
    # Task 2 is already quite complex, but let's make it more so
    complex_mock["detected_tasks"] = [
        {"task_id": "t-03", "task_label": "Deep Neural Net Debugging", "frequency": 0.1, "execution_simplicity": 0.05}
    ]
    try:
        engine.generate_spec(complex_mock)
        print("[FAIL] Complexity guard failed (should have raised error).")
        return False
    except MicroProductSpecificationError as e:
        print(f"[PASS] Complexity guard detected heavy task: {e}")

    # Case 3: Value Ratio Guard Trigger
    low_value_mock = mock_cluster.copy()
    low_value_mock["monetization_score"] = 20.0
    low_value_mock["emotional_score"] = 10.0
    try:
        engine.generate_spec(low_value_mock, price_base=10.0) # High price, low score
        print("[FAIL] Value ratio guard failed (should have raised error).")
        return False
    except MicroProductSpecificationError as e:
        print(f"[PASS] Value ratio guard detected low value: {e}")

    # Case 4: Missing Tasks
    empty_mock = mock_cluster.copy()
    empty_mock["detected_tasks"] = []
    try:
        engine.generate_spec(empty_mock)
        print("[FAIL] Empty tasks check failed.")
        return False
    except MicroProductSpecificationError as e:
        print(f"[PASS] Empty tasks handled: {e}")

    print(">>> All Internal Verifications Passed.")
    return True


if __name__ == "__main__":
    if run_internal_verification():
        exit(0)
    else:
        exit(1)
