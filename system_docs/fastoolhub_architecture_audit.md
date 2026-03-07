# FastoolHub Architecture Evolution Audit (V1 ➔ V2)
**Date:** 2026-03-06
**Status:** READ-ONLY Forensic Inspection Complete
**Risk Score:** LOW (No structural violations found during the scan)

---

## 1. V1 Legacy Architecture Summary
The V1 system (`__V1_TEMP_DISABLED`) was organized as a collection of independent scripts with procedural execution loops and direct state mutations. 

**Core V1 Modules:**
- `radar/`: `fetcher.py`, `parser.py`, `pain_analyzer.py` (LLM scoring), `competitor_scan.py`, `rss_reader.py`, `search_engine.py`
- `paginas/`: `builder.py`, `copywriter.py` (Landing page generation)
- `pricing/`: `engine.py` (A/B testing, dynamic pricing rollbacks), `stripe_manager.py`
- `email/` & `deploy/`: Basic API wrappers for SendGrid/Vercel.
- `execucao/`: `main.py`, `webhook_server.py`, `utils.py` (Synchronous loops)
- `guardian/`: `monitor.py` (Basic error catching)
- `upgrade/`: `loop.py`

**Characteristics:** High coupling, direct dependency on LLMs for core logic, scattershot persistence without a centralized event ledger.

---

## 2. V2 Current Architecture Summary
The V2 system (`autonomous-system-v2`) operates on a strict Event-Driven Constitutional Architecture.

**Core V2 Principles:**
- **Single Authority:** `Orchestrator` & `EventBus` manage all state mutations.
- **Append-Only Ledgers:** `EventLogPersistence` and `SnapshotPersistence` record immutable history.
- **Deterministic Independence:** Engines (`EconomicEngine`, `StrategicOpportunityEngine`, `FinanceEngine`) use deterministic rules rather than relying blindly on LLMs.
- **Continuous Runtime:** `runtime_engine.py` and `worker_manager.py` handle safe background intervals with mutex locks, managed via Flask API (`main.py`).

**V1 to V2 Mapped Components (Already Migrated & Upgraded):**
- `paginas/` ➔ `infra/landing/` (Landing Engine, Copywriter Prompt Builder)
- `deploy/` & `email/` ➔ Handled natively by V2 gateway adapters (Vercel/Resend).
- `execucao/` ➔ Replaced by `Orchestrator`, `runtime_engine.py`, and EventBus architecture.
- `guardian/` ➔ Subsumed into `TelemetryEngine` and `SecurityLayer`.

---

## 3. Unfinished Migrations & Reusable V1 Logic
During the scan, we identified two powerful pieces of logic in V1 that are fundamentally missing from V2's strict rule-based engines.

### A. Dynamic Pricing A/B Testing (`pricing/engine.py`)
V2 uses a static formula (`score_final * 0.8`) in `EconomicEngine`. 
V1 contains a robust capability to test 3 price variants (-20%, Base, +20%) and automatically select the winner based on `conversion_rate * avg_revenue`, including rollback safety nets.

### B. LLM Pain Clustering (`radar/pain_analyzer.py`)
V2 uses rigid formulas (Freq + Intensity) for scoring under `StrategicOpportunityEngine`.
V1 uses `gpt-3.5-turbo` to cluster raw inputs by tool, workflow, and outcome semantic similarity. This is extremely valuable for data pre-processing before it hits the deterministic V2 constitutional scoring.

---

## 4. Migration Plan
To safely port these capabilities without violating V2's "deterministic engines" rule, we must encapsulate them as **Adapters** that feed standard events into the Orchestrator.

We have generated safe migration stubs in `autonomous-system-v2/migrations/`:
- `migrations/pricing_ab_test_adapter.py`
- `migrations/llm_pain_analyzer_adapter.py`

These scripts are **passive**, do not contain execution loops, and rely cleanly on `Orchestrator.receive_event()` for state mutations.

---

## 5. Security & Dead Code Observations
- **Dead Code:** All code in `__V1_TEMP_DISABLED/execucao/` is obsolete and safely disjointed from V2.
- **Risk:** V1 scripts had hardcoded `.env` reads that could clash if run accidentally. Moving them to a disabled state was correct.
- **Recommendation:** `__V1_TEMP_DISABLED` can be zipped and securely archived offline. It poses negligible risks as it is disconnected from the Railway deployment context.
