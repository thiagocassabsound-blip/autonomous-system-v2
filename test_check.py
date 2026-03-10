
import json

with open('product_lifecycle_state.json', 'r', encoding='utf-8') as f:
    products = json.load(f)
    for k, v in products.items():
        if v.get('created_at') is None:
            print(f'Product {k} has null created_at')
        if 'created_at' not in v:
            print(f'Product {k} lacks created_at')

with open('radar_evaluations.json', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if not line.strip(): continue
        try:
            eval = json.loads(line)
        except json.JSONDecodeError:
            print(f'Line {i} invalid JSON')
            continue
        if eval.get('timestamp') is None:
            print(f'Eval line {i} has null timestamp')

