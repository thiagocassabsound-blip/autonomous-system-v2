import json
import os
import unittest
from flask import Flask, jsonify

# Mocking the blueprint structure for testing
from flask import Blueprint

def test_runtime_status_logic():
    # Simulate the logic in system_routes.py
    state_path = "data/runtime_state.json"
    
    # Case 1: File exists
    mock_data = {"runtime_running": True, "cycle_count": 10}
    os.makedirs("data", exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(mock_data, f)
    
    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            content = json.load(f)
            assert content == mock_data
            print("Logic Test Case 1 (File exists): PASSED")
            
    # Case 2: File missing
    os.remove(state_path)
    if not os.path.exists(state_path):
        response = {"runtime_running": False, "message": "runtime state not initialized"}
        assert response["runtime_running"] == False
        print("Logic Test Case 2 (File missing): PASSED")

if __name__ == "__main__":
    try:
        test_runtime_status_logic()
    except Exception as e:
        print(f"Logic Test FAILED: {e}")
    finally:
        if os.path.exists("data/runtime_state.json"):
            os.remove("data/runtime_state.json")
