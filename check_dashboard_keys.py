import os
import sys

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.append(PROJECT_ROOT)

from core.dashboard_state_manager import dashboard_state

def test_dashboard_keys():
    print("Iniciando verificação de alinhamento de chaves...")
    
    # Force refresh to ensure data is loaded
    data = dashboard_state.get_data()
    
    # 1. Global State Key Check
    global_s = data.get("global_state", {})
    state = global_s.get("state") # dashboard_routes.py line 63
    print(f"Global State Key 'state': {state}")
    assert state is not None, "ERRO: Chave 'state' não encontrada no global_state!"

    # 2. Budget Keys Check (Used in MOCK mode often)
    budget = data.get("budget", {})
    # Check if budget exists (might be empty dictionary if file cost_today is 0 and max is 100)
    # Actually dashboard_routes uses budget.get("calls_today", 0) etc.
    print(f"Budget Keys: {list(budget.keys())}")
    
    # 3. History snapshot check
    # We check if history appends use the correct key
    # (By looking at the latest entry in the file)
    history_file = dashboard_state.paths["history_log"]
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            lines = f.readlines()
            if lines:
                last_entry = eval(lines[-1])
                state_in_history = last_entry.get("summary", {}).get("state")
                print(f"última entrada no histórico (chave 'state'): {state_in_history}")
                assert state_in_history is not None, "ERRO: Chave 'state' não encontrada no histórico!"

    print("\nSUCESSO: Todas as chaves críticas estão alinhadas com o Dashboard!")

if __name__ == "__main__":
    try:
        test_dashboard_keys()
    except Exception as e:
        print(f"\nFALHA na verificação: {e}")
        sys.exit(1)
