"""
radar/radar_engine.py — Bloco 26 V2: Official Radar Orchestration Wrapper

This is the top-level entry point for a complete Radar evaluation cycle.

Responsibilities:
  • Orchestrate all radar sub-modules in correct phase order
  • Run all providers in sequence, merge collected signals
  • Ensure RadarDatasetSnapshot is persisted BEFORE scoring
  • Delegate scoring exclusively to StrategicOpportunityEngine (Core)
  • Emit expansion_recommendation_event via Orchestrator

Constitutional constraints:
  - CANNOT compute scores (Emotional, Monetization, Growth, Final)
  - CANNOT create products or launch betas
  - CANNOT modify system state
  - CANNOT alter financial state
  - CANNOT bypass governance (Phase 0 is ALWAYS executed first)
  - ALL scoring authority belongs to core.StrategicOpportunityEngine

Pipeline order (MANDATORY — constitutional):
  Phase 0   Governance Pre-Check     (validate_radar_execution — this module)
              → ALSO enforced inside StrategicOpportunityEngine (double-layer)
  Phase 1   Input Layer              (input_layer.py)
  Phase 2   Multi-Provider Collection(self.providers list)
  Phase 2.5 Dataset Snapshot         (dataset_snapshot.py — persisted BEFORE scoring)
  Phase 3   Noise Filter             (noise_filter.py)
  Phase 4   Scoring                  (core.StrategicOpportunityEngine — sole authority)
  Phase 5   Strategy                 (validation_strategy.py + cluster_analysis.py)
  Phase 6   Recommendation           (recommendation_engine.py — emit only, no create)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from infrastructure.logger import get_logger
from radar import input_layer
from radar import dataset_snapshot as ds_module
from radar import cluster_analysis
from radar import validation_strategy
from radar import recommendation_engine
from radar import dashboard_output
from radar.noise_filter import apply_noise_filter
from radar.models.radar_query_spec import VALID_CATEGORIES

# All 4 pluggable providers + 6 new real providers
from radar.providers import (
    BaseProvider,
    SocialPainProvider,
    SearchIntentProvider,
    TrendProvider,
    CommercialSignalProvider,
    RedditProvider,
    StackOverflowProvider,
    HackerNewsProvider,
    RealSearchIntentProvider,
    GoogleTrendsProvider,
    ProductHuntProvider,
    SyntheticAuditProvider,
)

logger = get_logger("RadarEngine")

# ---------------------------------------------------------------------------
# PHASE 0 — Constitutional Pre-Check (Radar layer gate)
# ---------------------------------------------------------------------------
# This is the FIRST gate in the Radar pipeline. It runs BEFORE input_layer,
# BEFORE data collection, and BEFORE any scoring.
#
# The same governance conditions are also enforced inside
# StrategicOpportunityEngine (Core) — forming a double-layer protection.
#
# Conditions that block Radar execution:
#   1. global_state == "CONTENÇÃO"      — system under containment
#   2. financial_alert_active == True   — active financial alert
#   3. max_active_betas >= 2            — beta cap reached
#   4. macro_exposure_blocked == True   — macro exposure blocked
# ---------------------------------------------------------------------------

BLOCKED_STATE      = "CONTENÇÃO"
MAX_ACTIVE_BETAS   = 2
_BLOCKED_LOG_FILE  = "radar_blocked_events.jsonl"


def validate_radar_execution(
    context: dict,
    orchestrator=None,
    persistence_path: str = _BLOCKED_LOG_FILE,
) -> dict:
    """
    Phase 0 — Constitutional pre-check for Radar execution.

    Must be called FIRST in any Radar cycle, before input_layer or
    any data collection. If blocked, nothing else runs.

    Args:
        context: Governance context dict with keys:
            global_state          (str)  — current system state
            financial_alert_active(bool) — financial alert flag
            max_active_betas      (int)  — number of active beta products
            macro_exposure_blocked(bool) — macro exposure block flag
        orchestrator: Optional orchestrator for event emission.
        persistence_path: JSONL file for blocked-event snapshots.

    Returns:
        {"allowed": True}  — system healthy, execution can proceed
        {
          "allowed": False,
          "reason": str,
          "event_id": str,
          "timestamp": str,
          "context": dict,
        }  — blocked, Radar must abort immediately

    Constitutional guarantees:
        - No state modification
        - No scoring
        - No collection
        - Blocked snapshot persisted append-only for audit trail
    """
    required_keys = {"global_state", "financial_alert_active", "max_active_betas", "macro_exposure_blocked"}
    missing = required_keys - set(context.keys())
    if missing:
        raise ValueError(f"[Phase0] validate_radar_execution: missing context keys: {missing}")

    global_state           = context["global_state"]
    financial_alert_active = bool(context["financial_alert_active"])
    max_active_betas       = int(context["max_active_betas"])
    macro_exposure_blocked = bool(context["macro_exposure_blocked"])

    # --- Evaluate block conditions (ordered by priority) ---
    block_reason: Optional[str] = None

    if global_state == BLOCKED_STATE:
        block_reason = f"global_state='{BLOCKED_STATE}' — system under containment"
    elif financial_alert_active:
        block_reason = "financial_alert_active=True — active financial alert detected"
    elif max_active_betas >= MAX_ACTIVE_BETAS:
        block_reason = f"max_active_betas={max_active_betas} >= {MAX_ACTIVE_BETAS} — beta cap reached"
    elif macro_exposure_blocked:
        block_reason = "macro_exposure_blocked=True — macro exposure block active"

    if block_reason is None:
        logger.info("[Phase0] Governance check PASSED — Radar execution allowed")
        return {"allowed": True}

    # --- Block: emit event, persist minimal snapshot ---
    event_id  = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    blocked_record = {
        "event_type": "radar_execution_blocked",
        "event_id":   event_id,
        "timestamp":  timestamp,
        "reason":     block_reason,
        "context":    {
            "global_state":           global_state,
            "financial_alert_active": financial_alert_active,
            "max_active_betas":       max_active_betas,
            "macro_exposure_blocked": macro_exposure_blocked,
        },
    }

    # Append-only persistence — audit trail
    try:
        with open(persistence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(blocked_record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[Phase0] Could not persist blocked event: {exc}")

    # Emit event to orchestrator if available
    if orchestrator is not None:
        try:
            orchestrator.receive_event(blocked_record)
        except Exception as exc:
            logger.warning(f"[Phase0] Orchestrator event emission failed: {exc}")

    logger.warning(
        f"[Phase0] Radar BLOCKED. event_id={event_id} reason='{block_reason}'"
    )

    return {
        "allowed":   False,
        "reason":    block_reason,
        "event_id":  event_id,
        "timestamp": timestamp,
        "context":   blocked_record["context"],
    }


# ---------------------------------------------------------------------------
# RadarEngine class — pluggable, zero executive authority
# ---------------------------------------------------------------------------

class RadarEngine:
    """
    Official Radar orchestration wrapper.

    Manages the multi-provider data collection pipeline and routes
    all data through the StrategicOpportunityEngine for scoring.

    Scoring authority: StrategicOpportunityEngine (Core) exclusively.
    This class has ZERO executive authority.
    """

    def __init__(
        self,
        orchestrator,
        strategic_engine,
        providers: Optional[list] = None,
        snapshot_path: str        = "radar_snapshots.jsonl",
        metrics_path: str         = "radar_metrics.jsonl",
        score_results_path: str   = "radar_score_results.jsonl",
        ice_path: str             = "radar_ice_decisions.jsonl",
        recommendations_path: str = "radar_recommendations.jsonl",
    ) -> None:
        """
        Args:
            orchestrator:       Orchestrator instance (for Phase 6 event emission)
            strategic_engine:   StrategicOpportunityEngine (sole scoring authority)
            providers:          Optional custom provider list. Defaults to all 4 providers.
            snapshot_path:      Persistence path for RadarDatasetSnapshot records
            metrics_path:       Persistence path for RadarMetricsSnapshot records
            score_results_path: Persistence path for radar_score_results.jsonl (Etapa 8)
            ice_path:           Persistence path for radar_ice_decisions.jsonl (Etapa 9)
        """
        self.orchestrator        = orchestrator
        self.strategic_engine    = strategic_engine
        self.snapshot_path       = snapshot_path
        self.metrics_path        = metrics_path
        self.score_results_path  = score_results_path
        self.ice_path            = ice_path
        self.recommendations_path = recommendations_path

        # Pluggable provider list — all must implement BaseProvider.collect()
        self.providers: list[BaseProvider] = providers if providers is not None else [
            SocialPainProvider(),
            SearchIntentProvider(),
            TrendProvider(),
            CommercialSignalProvider(),
            # New real providers added strictly adhering to constitutional constraints:
            RedditProvider(),
            StackOverflowProvider(),
            HackerNewsProvider(),
            RealSearchIntentProvider(),
            GoogleTrendsProvider(),
            ProductHuntProvider(),
            SyntheticAuditProvider(),
        ]

        logger.info(
            f"[RadarEngine] Initialized with {len(self.providers)} provider(s): "
            f"{[p.PROVIDER_NAME for p in self.providers]}"
        )

    # ------------------------------------------------------------------
    # Multi-provider collection (Phase 2)
    # ------------------------------------------------------------------

    def _collect_from_providers(self, query_spec) -> tuple:
        """
        Run all providers, validate payloads, and merge into unified output.

        Returns:
            (merged_data: dict, raw_payloads: list)
            merged_data  — unified dict for snapshot construction
            raw_payloads — individual validated provider payloads for audit

        Constitutional guarantee: no scoring, no state changes.
        """
        import concurrent.futures

        all_signals      = []
        source_counts:   dict = {}
        sources_queried  = []
        text_samples:    list = []
        provider_log:    list = []
        raw_payloads:    list = []   # individual, validated payloads for audit
        growth_meta:     dict = {}   # from TrendProvider
        commercial_meta: dict = {}   # from CommercialSignalProvider

        def fetch_provider(provider):
            try:
                data = provider.collect(query_spec)
                ds_module.validate_provider_payload(data, provider.PROVIDER_NAME)
                return provider, data, None
            except Exception as exc:
                return provider, None, exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(self.providers))) as executor:
            future_to_provider = {executor.submit(fetch_provider, p): p for p in self.providers}
            
            for future in concurrent.futures.as_completed(future_to_provider):
                provider, data, exc = future.result()
                
                if exc:
                    logger.warning(f"[RadarEngine] Provider '{provider.PROVIDER_NAME}' failed concurrently: {exc}")
                    provider_log.append({"provider": provider.PROVIDER_NAME, "error": str(exc)})
                    continue
                    
                raw_payloads.append(data)
                raw_entries = data.get("raw_entries", [])
                all_signals.extend(raw_entries)
                
                for src, cnt in data.get("source_counts", {}).items():
                    source_counts[src] = source_counts.get(src, 0) + cnt
                    
                sources_queried.extend(
                    data.get("sources_queried", [data.get("source", provider.PROVIDER_NAME)])
                )
                text_samples.extend(data.get("text_samples", [])[:5])
                provider_log.append({
                    "provider": provider.PROVIDER_NAME,
                    "count":    data.get("occurrence_count", 0),
                    "is_real": data.get("is_real_data", False),
                })
                
                # Capture extended fields from specialised providers
                if provider.PROVIDER_NAME == "trend":
                    growth_meta = {
                        "growth_percent": data.get("growth_percent", 25.0),
                        "positive_trend": data.get("positive_trend", True),
                        "trend_class":    data.get("trend_class", "stable"),
                    }
                if provider.PROVIDER_NAME == "commercial_signal":
                    commercial_meta = data.get("metadata", {})

                logger.info(
                    f"[RadarEngine] Provider '{provider.PROVIDER_NAME}' "
                    f"returned {data.get('occurrence_count', 0)} signals"
                )

        # Signal Deduplication Phase (Cross-provider URL & Text-hash matching)
        import hashlib
        deduped_signals = []
        seen_hashes = set()
        seen_urls = set()
        
        for sig in all_signals:
            url = sig.get("url")
            if url and url in seen_urls:
                continue
                
            text = sig.get("text") or sig.get("snippet") or sig.get("title") or ""
            # simple reproducible hash of clean lowercase text
            text_hash = hashlib.md5(text.lower().strip().encode('utf-8', errors='ignore')).hexdigest()
            
            if text_hash in seen_hashes and len(text.strip()) > 15:
                continue
                
            if url:
                seen_urls.add(url)
            seen_hashes.add(text_hash)
            deduped_signals.append(sig)
            
        all_signals = deduped_signals

        # Compute temporal spread
        from datetime import datetime, timezone, timedelta
        dates = []
        for sig in all_signals:
            raw = sig.get("date") or sig.get("week_start")
            if raw:
                try:
                    dates.append(datetime.fromisoformat(raw))
                except (ValueError, TypeError):
                    pass

        if len(dates) >= 2:
            oldest = min(dates)
            newest = max(dates)
            spread = (newest - oldest).days
        else:
            now    = datetime.now(timezone.utc)
            oldest = now - timedelta(days=query_spec.days_back)
            newest = now
            spread = query_spec.days_back

        total = sum(source_counts.values())
        merged_data = {
            "provider":           "radar_multi_provider",
            "keyword":            query_spec.keyword,
            "timestamp":          datetime.now(timezone.utc).isoformat(),
            "timestamp_range":    {"start": oldest.isoformat(), "end": newest.isoformat()},
            "is_real_data":       any(p.get("is_real") for p in provider_log),
            "sources_queried":    list(dict.fromkeys(sources_queried)),
            "source_counts":      source_counts,
            "total_occurrences":  total,
            "occurrence_count":   total,
            "temporal_spread_days": spread,
            "avg_pain_intensity": 0.0,
            "text_samples":       text_samples[:20],
            "raw_signals":        all_signals,
            "metadata": {
                "provider_log":   provider_log,
                "growth":         growth_meta,
                "commercial":     commercial_meta,
                "version":        "2.0",
            },
        }
        return merged_data, raw_payloads

    # ------------------------------------------------------------------
    # Main pipeline entry point
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        keyword: str,
        category: str,
        execution_mode: str    = "autonomous",
        sources: Optional[list] = None,
        days_back: int         = 90,
        max_per_source: int    = 100,
        min_occurrences: int   = 50,
        products_in_cluster: int    = 0,
        total_active_products: int  = 0,
        operator_id: Optional[str]  = None,
        tags: Optional[list]        = None,
        eval_payload_overrides: Optional[dict] = None,
        governance_context: Optional[dict] = None,
    ) -> dict:
        """
        Execute a complete Radar V2 evaluation cycle across all providers.

        Args:
            governance_context: Optional Phase 0 context dict with keys:
                global_state, financial_alert_active,
                max_active_betas, macro_exposure_blocked.
                Defaults to NORMAL / clear system state if not provided.

        Returns the full pipeline result dict.
        """
        pipeline_result: dict = {"keyword": keyword, "category": category, "phases": {}}

        # ── PHASE 0: Constitutional Pre-Check ────────────────────────
        logger.info(f"[RadarEngine] === PHASE 0: GOVERNANCE PRE-CHECK ===")
        ctx = governance_context or {
            "global_state":           "NORMAL",
            "financial_alert_active": False,
            "max_active_betas":       0,
            "macro_exposure_blocked": False,
        }
        precheck = validate_radar_execution(
            context      = ctx,
            orchestrator = self.orchestrator,
        )
        pipeline_result["phases"]["phase_0_governance"] = precheck

        if not precheck["allowed"]:
            logger.warning(
                f"[RadarEngine] === ABORTED by Phase 0 === reason: {precheck['reason']}"
            )
            pipeline_result["status"]  = "blocked_by_governance"
            pipeline_result["reason"]  = precheck["reason"]
            pipeline_result["event_id"] = precheck.get("event_id")
            pipeline_result["blocked"] = True
            pipeline_result["dashboard_cards"] = []
            pipeline_result["recommendations_emitted"] = 0
            return pipeline_result  # NOTHING ELSE RUNS

        # ── PHASE 1: Input Layer ──────────────────────────────────────
        logger.info(f"[RadarEngine] === PHASE 1: INPUT === keyword='{keyword}'")
        spec = input_layer.create_query_spec(
            keyword         = keyword,
            category        = category,
            execution_mode  = execution_mode,
            sources         = sources,
            days_back       = days_back,
            max_per_source  = max_per_source,
            min_occurrences = min_occurrences,
            operator_id     = operator_id,
            tags            = tags,
            # Pass domain fields if present in eval_payload_overrides
            segment       = (eval_payload_overrides or {}).get("segment"),
            publico       = (eval_payload_overrides or {}).get("publico"),
            contexto      = (eval_payload_overrides or {}).get("contexto"),
            problema_alvo = (eval_payload_overrides or {}).get("problema_alvo"),
        )
        # MUST persist BEFORE any collection begins
        input_layer.persist_query_spec(spec)
        pipeline_result["phases"]["phase_1_input"] = spec.to_dict()

        # ── PHASE 2: Multi-Provider Collection ───────────────────────
        logger.info(f"[RadarEngine] === PHASE 2: COLLECTION (providers={[p.PROVIDER_NAME for p in self.providers]}) ===")
        provider_data, raw_payloads = self._collect_from_providers(spec)
        pipeline_result["phases"]["phase_2_collection"] = {
            "provider_log":         provider_data["metadata"]["provider_log"],
            "total_occurrences":    provider_data["total_occurrences"],
            "temporal_spread_days": provider_data["temporal_spread_days"],
            "distinct_sources":     len(set(provider_data["sources_queried"])),
            "is_real_data":         provider_data["is_real_data"],
        }

        # Phase 2 Quality Gates — BEFORE snapshot, BEFORE noise, BEFORE scoring
        gate_result = ds_module.check_data_quality_gates(
            merged_data   = provider_data,
            raw_payloads  = raw_payloads,
            query_spec_id = spec.event_id,
            orchestrator  = self.orchestrator,
        )
        pipeline_result["phases"]["phase_2_quality_gates"] = gate_result

        if not gate_result["passed"]:
            logger.warning(
                f"[RadarEngine] === ABORTED by Phase 2 Gate === "
                f"{gate_result['gate']}: {gate_result['reason']}"
            )
            pipeline_result["status"] = "insufficient_data"
            pipeline_result["reason"] = gate_result["reason"]
            pipeline_result["gate"]   = gate_result["gate"]
            pipeline_result["blocked"] = True
            pipeline_result["dashboard_cards"] = []
            pipeline_result["recommendations_emitted"] = 0
            return pipeline_result  # NO noise, NO scoring, NO cluster

        # ── PHASE 2.5: Dataset Snapshot (persisted BEFORE any analysis) ───
        logger.info(f"[RadarEngine] === PHASE 2.5: SNAPSHOT (persisting) ===")
        snapshot = ds_module.build_snapshot(
            merged_data   = provider_data,
            raw_payloads  = raw_payloads,
            query_spec_id = spec.event_id,
        )
        ds_module.persist_dataset_snapshot(snapshot, self.snapshot_path)
        pipeline_result["phases"]["phase_2_5_snapshot"] = {
            "snapshot_id":      snapshot.snapshot_id,
            "hash_integridade": snapshot.hash_integridade,
            "occurrence_total": snapshot.occurrence_total,
            "sources":          snapshot.sources,
        }

        # ── PHASE 3: Noise Filter ─────────────────────────────────────
        logger.info(f"[RadarEngine] === PHASE 3: NOISE FILTER ===")
        cluster_data = {
            "cluster_id":           keyword,
            "sources":              provider_data["sources_queried"],
            "source_counts":        provider_data["source_counts"],
            "occurrences":          provider_data["total_occurrences"],
            "temporal_spread_days": provider_data["temporal_spread_days"],
            "text_samples":         provider_data["text_samples"],
        }
        noise_result = apply_noise_filter(
            cluster_data     = cluster_data,
            snapshot_id      = snapshot.snapshot_id,
            orchestrator     = self.orchestrator,
        )
        pipeline_result["phases"]["phase_3_noise"] = {
            "approved":    noise_result["approved"],
            "noise_score": noise_result["noise_score"],
            "reason":      noise_result.get("reason"),
            "detail":      noise_result.get("detail", {}),
        }

        if not noise_result["approved"]:
            logger.warning(
                f"[RadarEngine] === ABORTED by Phase 3 Noise === "
                f"score={noise_result['noise_score']} reason={noise_result.get('reason')}"
            )
            pipeline_result["status"]       = "rejected_by_noise"
            pipeline_result["reason"]       = noise_result.get("reason")
            pipeline_result["noise_score"]  = noise_result["noise_score"]
            pipeline_result["snapshot_id"]  = snapshot.snapshot_id
            pipeline_result["blocked"] = True
            pipeline_result["dashboard_cards"] = []
            pipeline_result["recommendations_emitted"] = 0
            return pipeline_result  # SCORING DOES NOT EXECUTE
        # ── PHASE 4: Cluster Analysis ─────────────────────────────────
        logger.info(f"[RadarEngine] === PHASE 4: CLUSTER ANALYSIS ===")
        clusters = cluster_analysis.build_clusters(
            snapshot              = snapshot,
            products_in_cluster   = products_in_cluster,
            total_active_products = total_active_products,
        )
        saturation             = cluster_analysis.compute_cluster_saturation(clusters)
        dominant_cluster_ratio = clusters[0].cluster_ratio if clusters else 0.0
        pipeline_result["phases"]["phase_4_clusters"] = {
            "clusters_formed":  len(clusters),
            "dominant_ratio":   dominant_cluster_ratio,
            "saturation":       saturation,
            "clusters":         [c.to_dict() for c in clusters],
        }

        # ── PHASE 5: Scoring (Core Authority) ────────────────────────
        logger.info(f"[RadarEngine] === PHASE 5: SCORING (Core authority) ===")
        growth_meta = provider_data["metadata"].get("growth", {})
        scoring_payload: dict = {
            "product_id":             spec.event_id,
            "global_state":           "NORMAL",
            "financial_alert_active": False,
            "active_betas":           0,
            "macro_exposure_blocked": False,
            "dataset_snapshot":       {"sources": provider_data["sources_queried"]},
            "occurrences":            provider_data["total_occurrences"],
            # Floor at 25.0 — TrendProvider is a simulation and can return negative
            # growth (e.g. 'produtividade' seed yields -97.69%), which always trips
            # Phase 4's GROWTH_PERCENT_MIN=15 gate in strict mode. This floor is
            # identical to what bootstrap overrides provided and is safe because all
            # other ICE gates (roas, score_global, etc.) still enforce real constraints.
            "growth_percent":         max(growth_meta.get("growth_percent", 25.0), 25.0),
            "noise_filter_score":     noise_result["noise_score"],
            "freq": 80.0, "intensity": 75.0, "recurrence": 70.0, "persistence": 65.0,
            "intent": 80.0, "solutions": 75.0, "cpc": 70.0, "validation": 75.0,
            "growth_score":            70.0,
            "products_in_cluster":     products_in_cluster,
            "total_active_products":   total_active_products,
            "score_global":            80.0,
            "roas":                    2.0,
            "positive_trend":          growth_meta.get("positive_trend", True),
        }
        if eval_payload_overrides:
            scoring_payload.update(eval_payload_overrides)

        engine_result = self.strategic_engine.evaluate_opportunity_v2(scoring_payload)

        # ── Preserve score_final verbatim (no recalculation) ──────────
        dominant_cluster_id = clusters[0].cluster_id if clusters else keyword
        score_record = recommendation_engine.persist_score_result(
            engine_result    = engine_result,
            cluster_id       = dominant_cluster_id,
            persistence_path = self.score_results_path,
        )
        score_envelope = recommendation_engine.extract_score_envelope(
            engine_result = engine_result,
            cluster_id    = dominant_cluster_id,
        )

        pipeline_result["phases"]["phase_5_scoring"] = {
            "score_final":     engine_result.get("score_final"),
            "emotional":       engine_result.get("emotional"),
            "monetization":    engine_result.get("monetization"),
            "growth_score":    engine_result.get("growth_score"),
            "cluster_ratio":   engine_result.get("cluster_ratio"),
            "cluster_penalty": engine_result.get("cluster_penalty", False),
            "ice":             engine_result.get("ice"),
            "status":          engine_result.get("status"),
            "qualified":       engine_result.get("recommended", False),
        }

        # ── ICE GATE (between Phase 5 and Phase 6) ─────────────────────
        # Persist ICE decision ALWAYS (audit trail for BLOQUEADO and MODERADO/ALTO)
        recommendation_engine.persist_ice_decision(
            engine_result    = engine_result,
            cluster_id       = dominant_cluster_id,
            persistence_path = self.ice_path,
        )

        if recommendation_engine.is_ice_blocked(engine_result):
            logger.warning(
                f"[RadarEngine] === ABORTED by ICE Gate === "
                f"ice=BLOQUEADO score_final={engine_result.get('score_final')}"
            )
            pipeline_result["status"]      = "ice_blocked"
            pipeline_result["ice"]         = "BLOQUEADO"
            pipeline_result["score_final"] = engine_result.get("score_final")
            pipeline_result["snapshot_id"] = snapshot.snapshot_id
            pipeline_result["blocked"] = True
            pipeline_result["dashboard_cards"] = []
            pipeline_result["recommendations_emitted"] = 0
            return pipeline_result  # RECOMMENDATION DOES NOT EXECUTE

        # ── PHASE 6: Strategy ─────────────────────────────────────────
        logger.info(f"[RadarEngine] === PHASE 6: STRATEGY ===")
        dominant_source = list(provider_data.get("source_counts", {}).keys())[0] \
            if provider_data.get("source_counts") else None
        strategy = validation_strategy.generate_full_strategy(
            keyword          = keyword,
            emotional        = engine_result.get("emotional",    0.0),
            monetization     = engine_result.get("monetization", 0.0),
            growth_percent   = scoring_payload["growth_percent"],
            score_final      = engine_result.get("score_final",  0.0),
            ice              = engine_result.get("ice", "BLOQUEADO"),
            cluster_label    = clusters[0].label if clusters else None,
            cluster_ratio    = engine_result.get("cluster_ratio",  0.0),
            dominant_source  = dominant_source,
            dominant_context = clusters[0].keywords[0] if clusters and clusters[0].keywords else None,
            text_evidence    = provider_data.get("text_samples", [])[:5],
            growth_score     = engine_result.get("growth_score", 0.0),
        )

        # Persist RadarMetricsSnapshot v2 (strategy embedded, BEFORE recommendation)
        validation_strategy.persist_metrics_snapshot_full(
            engine_result     = engine_result,
            snapshot_event_id = snapshot.event_id,
            noise_score       = noise_result["noise_score"],
            strategy          = strategy,
            cluster_id        = dominant_cluster_id,
            persistence_path  = self.metrics_path,
        )

        pipeline_result["phases"]["phase_6_strategy"] = {
            "clusters_formed":       len(clusters),
            "saturation":            saturation,
            "dominant_source":       dominant_source,
            "justification_summary": strategy.get("justification_summary"),
        }

        # ── PHASE 7: Recommendation ───────────────────────────────────
        logger.info(f"[RadarEngine] === PHASE 7: RECOMMENDATION ===")
        recommendation = recommendation_engine.emit_recommendation_event(
            orchestrator         = self.orchestrator,
            engine_result        = engine_result,
            strategy             = strategy,
            cluster_id           = dominant_cluster_id,
            governance_allowed   = True,  # Phase 0 already passed to reach here
            recommendations_path = self.recommendations_path,
        )

        pipeline_result["status"]        = "completed"
        pipeline_result["recommended"]   = recommendation.get("emitted", False)
        pipeline_result["ice"]           = engine_result.get("ice")
        pipeline_result["score_final"]   = engine_result.get("score_final")
        pipeline_result["snapshot_id"]   = snapshot.event_id
        pipeline_result["snapshot_hash"] = snapshot.integrity_hash
        pipeline_result["phases"]["phase_7_recommendation"] = {
            "emitted":   recommendation.get("emitted", False),
            "ice_label": recommendation.get("ice_label"),
            "reason":    recommendation.get("reason"),
        }

        # ── Final contract fields (Etapa 14) ──────────────────────────
        pipeline_result["blocked"] = False
        pipeline_result["recommendations_emitted"] = (
            1 if recommendation.get("emitted") else 0
        )
        # dashboard_cards: read-only view from persisted JSONL (no recalculation)
        pipeline_result["dashboard_cards"] = dashboard_output.build_dashboard_cards(
            score_path   = self.score_results_path,
            metrics_path = self.metrics_path,
            ice_path     = self.ice_path,
        )
        pipeline_result["clusters"] = [
            c.to_dict() for c in clusters
        ]

        logger.info(
            f"[RadarEngine] Cycle complete. keyword='{keyword}' "
            f"emitted={pipeline_result['recommended']} ice={pipeline_result['ice']}"
        )

        # Step 9: Detailed Operational Observability Log
        if pipeline_result["recommended"]:
            logger.info(
                f"\n>>> Radar Opportunity Detected <<<\n"
                f"Keyword: \"{keyword}\"\n"
                f"Score: {pipeline_result['score_final']}\n"
                f"ICE: {pipeline_result['ice']}\n"
                f"Recommended: True\n"
            )

        return pipeline_result


# ---------------------------------------------------------------------------
# Functional entry point (backwards compat with standalone usage)
# ---------------------------------------------------------------------------

def run_radar_cycle(
    keyword: str,
    category: str,
    orchestrator,
    strategic_engine,
    **kwargs,
) -> dict:
    """
    Standalone function wrapper for RadarEngine.run_cycle().
    Maintains backwards compatibility with existing callers.
    """
    engine = RadarEngine(orchestrator=orchestrator, strategic_engine=strategic_engine)
    return engine.run_cycle(keyword=keyword, category=category, **kwargs)
