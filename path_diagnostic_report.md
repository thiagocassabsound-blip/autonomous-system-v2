# Diagnostic Report — FASE C6.3: State Engine Path Diagnostic

## 1. Issue Description
The dashboard consistently reports "State Engine unavailable — Persistence read failed" despite `global_state.json` being present in the project root.

## 2. Path Investigation
The `DashboardStateManager` (specifically `_load_real_data` in `core/dashboard_state_manager.py`) uses literal relative paths to access persistence files:

- `open("global_state.json", ...)`
- `open("radar_evaluations.json", ...)`
- `open("product_lifecycle_state.json", ...)`

### Observed Behavior (Trace Results):
- **When run from ROOT:** Successfully resolves to `.../autonomous-system-v2/global_state.json`.
- **When run from SUBDIRECTORY (e.g., api/):** Incorrectly resolves to `.../autonomous-system-v2/api/global_state.json`.

## 3. Findings & Failure Analysis
- **Expected File Path:** `C:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\global_state.json`
- **Actual Runtime Path (Detected):** `C:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\api\global_state.json` (assuming server started from `api/`)
- **Root Cause:** The dashboard runtime is not anchored to the project root. Any variation in the `CWD` (Current Working Directory) of the executing process breaks the persistence link because the paths are not absolute or dynamic relative to the module location.

## 4. Recommended Repair Action
Normalize all paths in `core/dashboard_state_manager.py` using `os.path.join(PROJECT_ROOT, ...)` or by anchoring them to the absolute directory of the script file itself to ensure runtime environmental independence.

---
**Diagnostic Status:** COMPLETE ✅
**Issue Identified:** Runtime CWD Mismatch (Relative Path Sensitivity)
