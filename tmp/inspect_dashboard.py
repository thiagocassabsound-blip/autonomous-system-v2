import json

def load_jsonl(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

evals = load_jsonl("radar_evaluations.json")
prods_dict = load_json("product_lifecycle_state.json")
global_state = load_json("global_state.json")

print(f"Cycles/Evals: {len(evals)}")
print(f"Products dict keys: {len(prods_dict)}")
print(f"Global State: {global_state}")

print("\nLast 2 Eval keys:", evals[-2:] if len(evals) > 1 else evals)
if prods_dict:
    print("\nSample Product:", json.dumps(prods_dict[list(prods_dict.keys())[-1]], indent=2))
