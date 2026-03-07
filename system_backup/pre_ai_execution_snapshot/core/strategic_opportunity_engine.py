"""
core/strategic_opportunity_engine.py — Bloco 26 V2: Strategic Opportunity & Expansion Engine

CONSTITUTIONAL CLASSIFICATION: Strategic Subordinate — ZERO executive authority.
All evaluation is read-only and advisory.

No automatic product creation.
No beta initiation.
No state modification of any kind.
No financial alteration.

All outputs are advisory signals for human decision-making via Dashboard.
Every action requires:
  1. Human click
  2. Formal Orchestrator event
  3. Validation by downstream engines

PIPELINE (6 PHASES):
─────────────────────────────────────────────────────────────────────
  Phase 0 — Governance Pre-Check (B6: blocks before any execution)
  Phase 1 — Radar Input Layer (autonomous or assisted)
  Phase 2 — Data Collection Layer (independent of analysis)
  Phase 2.5 — RadarDatasetSnapshot Persistence (BEFORE scoring)
  Phase 3 — Noise Rejection Layer (Noise_Filter_Score < 60 → reject)
  Phase 4 — Structured Scoring (Emotional / Monetization / Growth)
  Phase 5 — Validation Strategy Layer (ICP + Fake Door)
  Phase 6 — Recommendation Layer (expansion_recommendation_event)
─────────────────────────────────────────────────────────────────────

SCORING (V2 Constitutional):
  Emotional     = (Freq×0.35) + (Intensidade×0.25) + (Recorrência×0.2) + (Persistência×0.2)
  Monetization  = (Intenção×0.4) + (Soluções×0.3) + (CPC×0.2) + (Validação×0.1)
  Score_Final   = (Monetization×0.6) + (Emotional×0.25) + (Growth×0.15)
  Cluster Penalty: cluster_ratio ≥ 30% → Score_Final × 0.6

CONFLUENCE (mandatory before scoring):
  • ≥ 3 distinct sources
  • ≥ 100 total occurrences
  • growth_percent ≥ 15%
  • growth_score ≥ 60
  • noise_filter_score ≥ 60
  • Emotional ≥ 70
  • Monetization ≥ 75

ICE (Expansion Capacity Index):
  Criteria (ALL must pass for MODERADO/ALTO):
    score_global ≥ 78
    roas_avg     ≥ 1.6
    global_state ≠ CONTENÇÃO
    active_betas ≤ 2
    macro_block == False
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("StrategicOpportunityEngine")

# ==============================================================================
# ICE CLASSIFICATIONS
# ==============================================================================
ICE_BLOQUEADO = "BLOQUEADO"
ICE_MODERADO  = "MODERADO"
ICE_ALTO      = "ALTO"

# ==============================================================================
# CONSTITUTIONAL THRESHOLDS (V2 — IMMUTABLE)
# ==============================================================================
EMOTIONAL_CUT           = 70.0
MONETIZATION_CUT        = 75.0
GROWTH_SCORE_CUT        = 60.0
GROWTH_PERCENT_MIN      = 15.0
NOISE_FILTER_CUT        = 60.0
MIN_SOURCES             = 3
MIN_OCCURRENCES         = 100
SCORE_GLOBAL_MIN        = 78.0
ROAS_MIN                = 1.6
MAX_BETAS               = 2
CLUSTER_RATIO_THRESHOLD = 0.30
CLUSTER_PENALTY_FACTOR  = 0.60


# ==============================================================================
# DOMAIN EXCEPTIONS
# ==============================================================================

class AutoExpansionForbiddenError(Exception):
    """Raised if any path attempts automatic product creation or beta launch."""

class DirectOpportunityWriteError(Exception):
    """Raised if engine state is written outside append-only persistence."""

class RadarSnapshotPersistenceError(Exception):
    """Raised if RadarDatasetSnapshot cannot be persisted (execution must abort)."""


# ==============================================================================
# PURE SCORING FUNCTIONS (no side effects)
# ==============================================================================

def _validate_score_input(value: float, label: str) -> float:
    """Validates that a score input is in [0, 100]. No silent fallback."""
    if not (0.0 <= float(value) <= 100.0):
        raise ValueError(
            f"[Bloco 26 V2] Score input '{label}' = {value} is out of range [0, 100]. "
            "All scoring inputs must be explicitly validated before scoring."
        )
    return float(value)


def compute_emotional_score(
    freq: float,
    intensidade: float,
    recorrencia: float,
    persistencia: float,
) -> float:
    """
    Constitutional Emotional Score formula (V2):
      Emotional = (Freq × 0.35) + (Intensidade × 0.25) + (Recorrência × 0.2) + (Persistência × 0.2)

    All 4 factors are mandatory. No silent fallback.
    All inputs must be ∈ [0, 100].
    Returns float 0–100.
    """
    freq        = _validate_score_input(freq,        "freq")
    intensidade = _validate_score_input(intensidade,  "intensidade")
    recorrencia = _validate_score_input(recorrencia,  "recorrencia")
    persistencia = _validate_score_input(persistencia, "persistencia")

    score = (freq * 0.35) + (intensidade * 0.25) + (recorrencia * 0.2) + (persistencia * 0.2)
    return round(score, 4)


def compute_monetization_score(
    intencao_compra: float,
    solucoes_pagas: float,
    cpc_normalizado: float,
    validacao_comercial: float,
) -> float:
    """
    Constitutional Monetization Score formula (V2):
      Monetization = (Intenção×0.4) + (Soluções×0.3) + (CPC×0.2) + (Validação×0.1)

    All inputs must be ∈ [0, 100].
    Returns float 0–100.
    """
    intencao_compra     = _validate_score_input(intencao_compra,     "intencao_compra")
    solucoes_pagas      = _validate_score_input(solucoes_pagas,      "solucoes_pagas")
    cpc_normalizado     = _validate_score_input(cpc_normalizado,      "cpc_normalizado")
    validacao_comercial = _validate_score_input(validacao_comercial,  "validacao_comercial")

    score = (
        (intencao_compra     * 0.4) +
        (solucoes_pagas      * 0.3) +
        (cpc_normalizado     * 0.2) +
        (validacao_comercial * 0.1)
    )
    return round(score, 4)


def compute_final_score(
    monetization: float,
    emotional: float,
    growth_score: float,
    cluster_ratio: float,
) -> tuple[float, bool]:
    """
    Constitutional Score_Final formula (V2):
      Score_Final = (Monetization × 0.6) + (Emotional × 0.25) + (Growth × 0.15)

    Cluster penalty:
      If cluster_ratio ≥ 0.30 → Score_Final × 0.60 (−40%)

    Returns (score_final, penalty_applied).
    """
    raw = (monetization * 0.6) + (emotional * 0.25) + (growth_score * 0.15)
    penalty = cluster_ratio >= CLUSTER_RATIO_THRESHOLD
    final   = raw * CLUSTER_PENALTY_FACTOR if penalty else raw
    return round(final, 4), penalty


def classify_ice(
    score_global: float,
    roas_avg: float,
    global_state: str,
    active_betas: int,
    macro_block: bool,
    positive_trend: bool = False,
) -> tuple[str, list[str]]:
    """
    ICE (Expansion Capacity Index) classification.
    ALL criteria must pass for MODERADO/ALTO.
    Any failure → BLOQUEADO.
    positive_trend=True and all pass → ALTO; else MODERADO.
    """
    reasons: list[str] = []

    if score_global < SCORE_GLOBAL_MIN:
        reasons.append(f"score_global={score_global} < {SCORE_GLOBAL_MIN}")
    if roas_avg < ROAS_MIN:
        reasons.append(f"roas_avg={roas_avg} < {ROAS_MIN}")
    if "CONTEN" in global_state.upper():
        reasons.append(f"global_state={global_state} (CONTENÇÃO)")
    if active_betas > MAX_BETAS:
        reasons.append(f"active_betas={active_betas} > {MAX_BETAS}")
    if macro_block:
        reasons.append("macro_block=True")

    if reasons:
        return ICE_BLOQUEADO, reasons
    return (ICE_ALTO if positive_trend else ICE_MODERADO), []


# ==============================================================================
# RADAR DATASET SNAPSHOT
# ==============================================================================

def _build_integrity_hash(sources: list, occurrence_total: int, growth_percent: float, query_id: str) -> str:
    """
    SHA-256 hash over the raw collection inputs.
    Ensures tamper-evidence for the snapshot before scoring.
    """
    payload = json.dumps(
        {
            "sources":          sorted(sources),
            "occurrence_total": occurrence_total,
            "growth_percent":   growth_percent,
            "query_id":         query_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _create_radar_snapshot(
    event_id: str,
    query_id: str,
    sources: list,
    occurrence_total: int,
    growth_percent: float,
    raw_payload_reference: str,
    now: datetime,
) -> dict:
    """Build the RadarDatasetSnapshot dict (not persisted here — persistence rests on caller)."""
    return {
        "snapshot_id":           str(uuid.uuid4()),
        "event_id":              event_id,
        "query_id":              query_id,
        "timestamp":             now.isoformat(),
        "sources":               list(sources),
        "occurrence_total":      occurrence_total,
        "growth_percent":        round(float(growth_percent), 4),
        "raw_payload_reference": raw_payload_reference,
        "hash_integridade":      _build_integrity_hash(
                                     sources, occurrence_total, growth_percent, query_id
                                 ),
    }


# ==============================================================================
# STRATEGIC OPPORTUNITY ENGINE V2 (CONSTITUTIONAL)
# ==============================================================================

class StrategicOpportunityEngine:
    """
    Bloco 26 V2 — Strategic Opportunity & Expansion Engine

    ZERO executive authority.
    ZERO state modification.
    ZERO financial alteration.
    ZERO automatic product creation.

    All output is advisory. Human action + Orchestrator event required before any execution.
    """

    def __init__(self, orchestrator, persistence, snapshot_persistence=None, now_fn=None):
        """
        Args:
            orchestrator:         Orchestrator instance (emit-only).
            persistence:          Append-only store for scored records.
            snapshot_persistence: Append-only store for raw RadarDatasetSnapshots.
                                  If None, snapshots are embedded in the main record.
            now_fn:               Overridable clock (for testing).
        """
        self.orchestrator          = orchestrator
        self._pers                 = persistence
        self._snapshot_pers        = snapshot_persistence  # can be None
        self._now                  = now_fn or (lambda: datetime.now(timezone.utc))
        self._records: list[dict]  = list(persistence.load_all())
        logger.info(
            f"StrategicOpportunityEngine V2 initialized. "
            f"Stored evaluations: {len(self._records)}"
        )

    # ==========================================================================
    # PHASE 0 — GOVERNANCE PRE-CHECK (B6)
    # Blocks before any computation. No radar runs under containment.
    # ==========================================================================

    def _phase0_governance(self, payload: dict, pid: str, now: datetime) -> tuple[bool, str]:
        """
        Full governance pre-check. Returns (passed, reason).
        Emits radar_execution_blocked if blocked.
        """
        gs              = payload.get("global_state", "NORMAL")
        alert           = payload.get("financial_alert_active", False)
        betas           = int(payload.get("active_betas", 0))
        macro_blocked   = payload.get("macro_exposure_blocked", False)

        reasons: list[str] = []
        if "CONTEN" in gs.upper():
            reasons.append("CONTENÇÃO_FINANCEIRA")
        if alert:
            reasons.append("ALERTA_FINANCEIRO_ATIVO")
        if betas >= MAX_BETAS:
            reasons.append(f"MAX_BETAS_ATINGIDO({betas})")
        if macro_blocked:
            reasons.append("MACRO_EXPOSURE_BLOCKED")

        if reasons:
            reason_str = ", ".join(reasons)
            self.orchestrator.emit_event(
                event_type="radar_execution_blocked",
                product_id=pid,
                payload={
                    "reason":          reason_str,
                    "global_state":    gs,
                    "active_betas":    betas,
                    "financial_alert": alert,
                    "macro_blocked":   macro_blocked,
                    "timestamp":       now.isoformat(),
                },
                source="system",
            )
            logger.warning(f"[Phase 0] BLOCKED '{pid}' — {reason_str}")
            return False, reason_str

        return True, ""

    # ==========================================================================
    # PHASE 1 — RADAR INPUT LAYER
    # ==========================================================================

    @staticmethod
    def _phase1_input(payload: dict, now: datetime) -> tuple[dict, str]:
        """
        Build and validate the RadarQuerySpec.
        Autonomous mode: generated automatically.
        Assisted mode:   requires non-empty query_spec.
        Returns (query_spec, query_id).
        """
        mode       = "assisted" if payload.get("assisted_input") else "autonomous"
        query_spec = payload.get("query_spec", {})

        if mode == "assisted" and not query_spec:
            raise ValueError(
                "[Phase 1] Assisted mode requires a non-empty query_spec. "
                "Nenhuma execução com input vazio."
            )

        query_id = str(uuid.uuid4())
        return {
            "query_id":   query_id,
            "timestamp":  now.isoformat(),
            "mode":       mode,
            "spec":       query_spec,
        }, query_id

    # ==========================================================================
    # PHASE 2 — DATA COLLECTION LAYER (independent of analysis)
    # ==========================================================================

    @staticmethod
    def _phase2_collection(payload: dict) -> tuple[list, int, float]:
        """
        Validates dataset_snapshot contract.
        Returns (sources, occurrence_total, growth_percent).
        Collection is independent of analysis — no scoring occurs here.
        """
        dataset          = payload.get("dataset_snapshot", {})
        sources          = dataset.get("sources", [])
        occurrence_total = int(payload.get("occurrences", 0))
        growth_percent   = float(payload.get("growth_percent", 0.0))

        if len(sources) < MIN_SOURCES:
            raise ValueError(
                f"[Phase 2] Mínimo {MIN_SOURCES} fontes distintas necessárias. "
                f"Recebido: {len(sources)}."
            )

        if occurrence_total < MIN_OCCURRENCES:
            raise ValueError(
                f"[Phase 2] Mínimo {MIN_OCCURRENCES} ocorrências agregadas necessárias. "
                f"Recebido: {occurrence_total}."
            )

        return sources, occurrence_total, growth_percent

    # ==========================================================================
    # PHASE 2.5 — PERSIST RADARDATASETSNAPSHOT (MANDATORY, BEFORE SCORING)
    # ==========================================================================

    def _phase2_5_persist_snapshot(
        self,
        event_id: str,
        query_id: str,
        sources: list,
        occurrence_total: int,
        growth_percent: float,
        raw_payload_reference: str,
        now: datetime,
    ) -> dict:
        """
        Builds and persists the RadarDatasetSnapshot BEFORE any score calculation.
        If persistence fails, execution MUST abort (raises RadarSnapshotPersistenceError).
        """
        snapshot = _create_radar_snapshot(
            event_id=event_id,
            query_id=query_id,
            sources=sources,
            occurrence_total=occurrence_total,
            growth_percent=growth_percent,
            raw_payload_reference=raw_payload_reference,
            now=now,
        )

        try:
            if self._snapshot_pers is not None:
                self._snapshot_pers.append_record(snapshot)
            else:
                # embed snapshot in main record prefix — still persisted before scoring
                self._pers.append_record({"_type": "snapshot", **snapshot})
        except Exception as exc:
            raise RadarSnapshotPersistenceError(
                f"[Phase 2.5] Snapshot persistence failed — execution aborted. Error: {exc}"
            ) from exc

        logger.info(
            f"[Phase 2.5] RadarDatasetSnapshot persisted. "
            f"snapshot_id={snapshot['snapshot_id']} "
            f"hash={snapshot['hash_integridade'][:12]}..."
        )
        return snapshot

    # ==========================================================================
    # PHASE 3 — NOISE REJECTION LAYER
    # ==========================================================================

    @staticmethod
    def _phase3_noise_rejection(payload: dict) -> float:
        """
        Validate Noise_Filter_Score ≥ 60.
        Returns noise_score if passes; raises ValueError if rejected.
        """
        noise_score = float(payload.get("noise_filter_score", 100.0))
        if noise_score < NOISE_FILTER_CUT:
            raise ValueError(
                f"[Phase 3] noise_filter_score={noise_score} < {NOISE_FILTER_CUT}. "
                "Cluster rejeitado pelo filtro de ruído."
            )
        return noise_score

    # ==========================================================================
    # PHASE 4 — STRUCTURED SCORING LAYER
    # ==========================================================================

    def _phase4_scoring(self, payload: dict, sources: list, occurrence_total: int, growth_percent: float) -> dict:
        """
        Compute Emotional, Monetization, Growth, and Score_Final.
        Enforce all confluência mínima requirements.
        """
        # --- Growth validation (explicit, separate from growth_score) ---
        growth_score = float(payload.get("growth_score", 0.0))

        if growth_percent < GROWTH_PERCENT_MIN:
            raise ValueError(
                f"[Phase 4] growth_percent={growth_percent}% < {GROWTH_PERCENT_MIN}% exigido. "
                "Opportunity not qualified."
            )

        if growth_score < GROWTH_SCORE_CUT:
            raise ValueError(
                f"[Phase 4] growth_score={growth_score} < {GROWTH_SCORE_CUT}. "
                "Opportunity not qualified."
            )

        # --- Emotional Score (constitutional 4-factor formula) ---
        emotional = compute_emotional_score(
            freq        = float(payload.get("freq",        0.0)),
            intensidade  = float(payload.get("intensity",   0.0)),
            recorrencia  = float(payload.get("recurrence",  0.0)),
            persistencia = float(payload.get("persistence", 0.0)),
        )

        # --- Monetization Score ---
        monetization = compute_monetization_score(
            intencao_compra     = float(payload.get("intent",     0.0)),
            solucoes_pagas      = float(payload.get("solutions",  0.0)),
            cpc_normalizado     = float(payload.get("cpc",        0.0)),
            validacao_comercial = float(payload.get("validation", 0.0)),
        )

        # --- Confluência Mínima (formal gate) ---
        confluence_failures: list[str] = []
        if len(sources) < MIN_SOURCES:
            confluence_failures.append(f"sources={len(sources)} < {MIN_SOURCES}")
        if occurrence_total < MIN_OCCURRENCES:
            confluence_failures.append(f"occurrences={occurrence_total} < {MIN_OCCURRENCES}")
        if growth_percent < GROWTH_PERCENT_MIN:
            confluence_failures.append(f"growth_percent={growth_percent}% < {GROWTH_PERCENT_MIN}%")
        if growth_score < GROWTH_SCORE_CUT:
            confluence_failures.append(f"growth_score={growth_score} < {GROWTH_SCORE_CUT}")
        if emotional < EMOTIONAL_CUT:
            confluence_failures.append(f"emotional={emotional} < {EMOTIONAL_CUT}")
        if monetization < MONETIZATION_CUT:
            confluence_failures.append(f"monetization={monetization} < {MONETIZATION_CUT}")

        if confluence_failures:
            raise ValueError(
                f"[Phase 4] Confluência mínima not met: {confluence_failures}"
            )

        # --- Cluster ratio & final score ---
        products_in_cluster   = int(payload.get("products_in_cluster",   0))
        total_active_products = max(int(payload.get("total_active_products", 1)), 1)
        cluster_ratio         = round(products_in_cluster / total_active_products, 4)

        score_final, penalty_applied = compute_final_score(
            monetization=monetization,
            emotional=emotional,
            growth_score=growth_score,
            cluster_ratio=cluster_ratio,
        )

        return {
            "emotional":       emotional,
            "monetization":    monetization,
            "growth_score":    growth_score,
            "growth_percent":  growth_percent,
            "cluster_ratio":   cluster_ratio,
            "cluster_penalty": penalty_applied,
            "score_final":     score_final,
        }

    # ==========================================================================
    # PHASE 5 — VALIDATION STRATEGY LAYER
    # ==========================================================================

    @staticmethod
    def _phase5_strategy(product_id: str, scores: dict) -> dict:
        """
        Auto-generate ICP, Fake Door Strategy, minimum validation metric,
        central hypothesis, and justification snapshot.
        Connects Radar → C1 → C1.5 pipeline.
        """
        return {
            "icp":                   f"Usuário com dor recorrente em '{product_id}'",
            "fake_door_strategy":    "Landing com CTA direcionado → medir CTR mínimo 3%",
            "validation_metric":     "CTR ≥ 3% em 72h OR ≥ 50 opt-ins",
            "central_hypothesis":    (
                f"Existe demanda real e recorrente em '{product_id}' "
                f"com Emotional={scores['emotional']} e Monetization={scores['monetization']}."
            ),
            "justification_snapshot": {
                "emotional":      scores["emotional"],
                "monetization":   scores["monetization"],
                "growth_score":   scores["growth_score"],
                "growth_percent": scores["growth_percent"],
                "score_final":    scores["score_final"],
            },
        }

    # ==========================================================================
    # PHASE 6 — RECOMMENDATION LAYER
    # ==========================================================================

    def _phase6_recommendation(
        self,
        event_id: str,
        pid: str,
        scores: dict,
        strategy: dict,
        snapshot: dict,
        ice: str,
        ice_reasons: list,
        payload: dict,
        now: datetime,
    ) -> dict:
        """
        Builds and persists the final scored record.
        Emits expansion_recommendation_event ONLY if all gates pass.
        NEVER executes any action.
        """
        recommended = (
            scores["emotional"]    >= EMOTIONAL_CUT
            and scores["monetization"] >= MONETIZATION_CUT
            and scores["growth_score"] >= GROWTH_SCORE_CUT
            and ice != ICE_BLOQUEADO
        )

        record = {
            "event_id":      event_id,
            "product_id":    pid,
            "timestamp":     now.isoformat(),
            "version":       "2",
            # Scores
            "emotional":       scores["emotional"],
            "monetization":    scores["monetization"],
            "growth_score":    scores["growth_score"],
            "growth_percent":  scores["growth_percent"],
            "score_final":     scores["score_final"],
            "cluster_ratio":   scores["cluster_ratio"],
            "cluster_penalty": scores["cluster_penalty"],
            # ICE
            "ice":                  ice,
            "ice_blocking_reasons": ice_reasons,
            # Eligibility
            "recommended": recommended,
            # Strategy
            "strategy": strategy,
            # Snapshot reference
            "snapshot_id":          snapshot["snapshot_id"],
            "snapshot_hash":        snapshot["hash_integridade"],
            # Context
            "global_state":  payload.get("global_state", "NORMAL"),
            "active_betas":  payload.get("active_betas", 0),
            "score_global":  payload.get("score_global", 0.0),
            "roas_avg":      payload.get("roas", 0.0),
        }

        # Persist (append-only, never update)
        self._pers.append_record(record)
        self._records.append(record)

        if recommended:
            self.orchestrator.emit_event(
                event_type="expansion_recommendation_event",
                product_id=pid,
                payload={
                    "event_id":          event_id,
                    "score_final":       scores["score_final"],
                    "emotional":         scores["emotional"],
                    "monetization":      scores["monetization"],
                    "growth_score":      scores["growth_score"],
                    "growth_percent":    scores["growth_percent"],
                    "cluster_ratio":     scores["cluster_ratio"],
                    "ice":               ice,
                    "strategy":          strategy,
                    "snapshot_id":       snapshot["snapshot_id"],
                    "snapshot_hash":     snapshot["hash_integridade"],
                    "timestamp":         now.isoformat(),
                    "note": (
                        "SIGNAL ONLY — does not create product, "
                        "does not allocate capital, does not start beta."
                    ),
                },
                source="system",
            )
            logger.info(
                f"[Phase 6] expansion_recommendation_event emitted for '{pid}': "
                f"score={scores['score_final']} ICE={ice}"
            )
        else:
            logger.info(
                f"[Phase 6] Recommendation NOT emitted for '{pid}': "
                f"emotional={scores['emotional']} monetization={scores['monetization']} ICE={ice}"
            )

        return record

    # ==========================================================================
    # PRIMARY ENTRY POINT — 6-PHASE PIPELINE
    # ==========================================================================

    def evaluate_opportunity_v2(self, payload: dict) -> dict:
        """
        Full 6-phase constitutional Radar pipeline.

        Payload keys (required for full qualification):
          product_id, global_state, financial_alert_active, active_betas,
          macro_exposure_blocked, assisted_input, query_spec,
          dataset_snapshot (sources list), occurrences, growth_percent,
          noise_filter_score, freq, intensity, recurrence, persistence,
          intent, solutions, cpc, validation, growth_score,
          products_in_cluster, total_active_products,
          score_global, roas, positive_trend

        Returns dict with status=blocked|error|not_qualified|recommended|not_recommended.
        """
        now        = self._now()
        pid        = str(payload.get("product_id", "unknown"))
        event_id   = str(uuid.uuid4())

        # ------------------------------------------------------------------
        # PHASE 0 — GOVERNANCE (B6 PRE-CHECK)
        # ------------------------------------------------------------------
        ok, block_reason = self._phase0_governance(payload, pid, now)
        if not ok:
            return {
                "event_id":  event_id,
                "product_id": pid,
                "timestamp":  now.isoformat(),
                "status":     "blocked",
                "reason":     block_reason,
            }

        # ------------------------------------------------------------------
        # PHASE 1 — RADAR INPUT LAYER
        # ------------------------------------------------------------------
        try:
            query_spec, query_id = self._phase1_input(payload, now)
        except ValueError as exc:
            return {"event_id": event_id, "product_id": pid, "status": "error", "message": str(exc)}

        # ------------------------------------------------------------------
        # PHASE 2 — DATA COLLECTION LAYER
        # ------------------------------------------------------------------
        try:
            sources, occurrence_total, growth_percent = self._phase2_collection(payload)
        except ValueError as exc:
            return {"event_id": event_id, "product_id": pid, "status": "error", "message": str(exc)}

        # ------------------------------------------------------------------
        # PHASE 2.5 — PERSIST RADARDATASETSNAPSHOT (BEFORE SCORING)
        # ------------------------------------------------------------------
        try:
            snapshot = self._phase2_5_persist_snapshot(
                event_id=event_id,
                query_id=query_id,
                sources=sources,
                occurrence_total=occurrence_total,
                growth_percent=growth_percent,
                raw_payload_reference=pid,
                now=now,
            )
        except RadarSnapshotPersistenceError as exc:
            logger.error(str(exc))
            return {"event_id": event_id, "product_id": pid, "status": "error", "message": str(exc)}

        # ------------------------------------------------------------------
        # PHASE 3 — NOISE REJECTION LAYER
        # ------------------------------------------------------------------
        try:
            self._phase3_noise_rejection(payload)
        except ValueError as exc:
            return {"event_id": event_id, "product_id": pid, "status": "rejected", "reason": str(exc)}

        # ------------------------------------------------------------------
        # PHASE 4 — STRUCTURED SCORING LAYER
        # ------------------------------------------------------------------
        try:
            scores = self._phase4_scoring(payload, sources, occurrence_total, growth_percent)
        except ValueError as exc:
            self.orchestrator.emit_event(
                event_type="opportunity_not_qualified",
                product_id=pid,
                payload={"event_id": event_id, "reason": str(exc), "timestamp": now.isoformat()},
                source="system",
            )
            return {"event_id": event_id, "product_id": pid, "status": "not_qualified", "reason": str(exc)}

        # ------------------------------------------------------------------
        # ICE CALCULATION (after scoring, before recommendation)
        # ------------------------------------------------------------------
        ice, ice_reasons = classify_ice(
            score_global = float(payload.get("score_global", 0.0)),
            roas_avg     = float(payload.get("roas", 0.0)),
            global_state = str(payload.get("global_state", "NORMAL")),
            active_betas = int(payload.get("active_betas", 0)),
            macro_block  = bool(payload.get("macro_exposure_blocked", False)),
            positive_trend = bool(payload.get("positive_trend", False)),
        )

        # ------------------------------------------------------------------
        # PHASE 5 — VALIDATION STRATEGY LAYER
        # ------------------------------------------------------------------
        strategy = self._phase5_strategy(pid, scores)

        # ------------------------------------------------------------------
        # PHASE 6 — RECOMMENDATION LAYER
        # ------------------------------------------------------------------
        record = self._phase6_recommendation(
            event_id=event_id,
            pid=pid,
            scores=scores,
            strategy=strategy,
            snapshot=snapshot,
            ice=ice,
            ice_reasons=ice_reasons,
            payload=payload,
            now=now,
        )

        return record

    # ==========================================================================
    # READ-ONLY RANKING
    # ==========================================================================

    def get_ranked_opportunities(self, product_id: str | None = None) -> list[dict]:
        """Return all scored evaluations ordered by score_final descending. Read-only."""
        recs = [r for r in self._records if "_type" not in r]  # exclude snapshot entries
        if product_id is not None:
            recs = [r for r in recs if r.get("product_id") == str(product_id)]
        return sorted(recs, key=lambda r: r.get("score_final", 0.0), reverse=True)

    # ==========================================================================
    # EXECUTION GUARDS — PERMANENTLY FORBIDDEN
    # ==========================================================================

    def create_product_automatically(self, *args, **kwargs) -> None:
        """Always raises. ZERO executive authority."""
        raise AutoExpansionForbiddenError(
            "create_product_automatically() is permanently forbidden. "
            "Bloco 26 V2 has ZERO executive authority. "
            "Product creation requires: human click → Orchestrator event → downstream engine."
        )

    def launch_beta_automatically(self, *args, **kwargs) -> None:
        """Always raises. Beta launch requires explicit human action."""
        raise AutoExpansionForbiddenError(
            "launch_beta_automatically() is permanently forbidden. "
            "Beta launch requires: human click → Orchestrator event → BetaEngine validation."
        )

    def evaluate_opportunity(self, *args, **kwargs) -> dict:
        """Backward-compatible alias for evaluate_opportunity_v2."""
        return self.evaluate_opportunity_v2(dict(kwargs))
