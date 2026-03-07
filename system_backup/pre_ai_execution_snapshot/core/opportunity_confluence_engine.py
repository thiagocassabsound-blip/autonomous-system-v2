"""
core/opportunity_confluence_engine.py — B2: Confluência Mínima

Classification: Structural Validation Filter — ZERO executive authority.

B2 is a binary pre-filter that MUST be passed before Bloco 26 computes
any Score_Final or ICE. If B2 rejects an opportunity, Bloco 26 must
stop processing immediately — no score, no ranking, no ICE evaluation.

Three hard gates (ALL must pass):
  1. categories_confirmed ≥ 3  (distinct, independent signal categories)
  2. growth_percent       ≥ 15  (relative growth in last 30 days)
  3. intensity_score      ≥ 60  (scale 0–100)

On any gate failure:
  • eligible = False
  • event: opportunity_rejected_confluence  (append-only persisted)
  • Bloco 26 must not proceed with scoring

This engine:
  ✗ Does not create products
  ✗ Does not alter state
  ✗ Does not alter capital
  ✗ Does not compute Score_Final
  ✗ Does not compute ICE
  ✓ Validates structural market reality only
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("OpportunityConfluenceEngine")

# Hard thresholds (immutable)
MIN_CATEGORIES = 3
MIN_GROWTH_PCT  = 15.0
MIN_INTENSITY   = 65.0  # V2: Intensidade média ≥ 65

# Valid signal categories
VALID_CATEGORIES = {
    "busca_ativa",
    "discussao_organica",
    "intencao_comercial",
    "tendencia_crescimento",
    "volume_consolidado",
    "frequencia_recorrente",
    "intensidade_linguistica",
}


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class ConfluenceValidationError(Exception):
    """Raised when confluence criteria are not met (standard flow)."""

class ConfluenceExecutionForbiddenError(Exception):
    """Raised if B2 is used to attempt any executive action."""


# ---------------------------------------------------------------------------
# Confluence result data class
# ---------------------------------------------------------------------------

class ConfluenceResult:
    """
    Immutable result of a confluence validation.
    Passed to Bloco 26 so it can decide whether to proceed.
    """
    __slots__ = (
        "approved",
        "event_id",
        "categories_confirmed",
        "growth_percent",
        "intensity_score",
        "blocking_reasons",
        "timestamp",
    )

    def __init__(
        self,
        approved: bool,
        event_id: str,
        categories_confirmed: list[str],
        growth_percent: float,
        intensity_score: float,
        blocking_reasons: list[str],
        timestamp: str,
    ):
        self.approved             = approved
        self.event_id             = event_id
        self.categories_confirmed = categories_confirmed
        self.growth_percent       = growth_percent
        self.intensity_score      = intensity_score
        self.blocking_reasons     = blocking_reasons
        self.timestamp            = timestamp

    def as_dict(self) -> dict:
        return {
            "approved":             self.approved,
            "event_id":             self.event_id,
            "categories_confirmed": self.categories_confirmed,
            "growth_percent":       self.growth_percent,
            "intensity_score":      self.intensity_score,
            "blocking_reasons":     self.blocking_reasons,
            "timestamp":            self.timestamp,
        }


# ---------------------------------------------------------------------------
# Confluence Engine
# ---------------------------------------------------------------------------

class OpportunityConfluenceEngine:
    """
    B2 — Structural Validation Filter.

    Must be called by Bloco 26 before any score computation.
    Never executes, never creates, never modifies state.
    """

    def __init__(self, orchestrator, persistence, now_fn=None):
        self.orchestrator = orchestrator
        self._pers       = persistence
        self._now        = now_fn or (lambda: datetime.now(timezone.utc))
        self._records: list[dict] = list(persistence.load_all())
        logger.info(
            f"OpportunityConfluenceEngine initialized. "
            f"Stored validations: {len(self._records)}"
        )

    # ==================================================================
    # PRIMARY ENTRY POINT
    # ==================================================================

    def validate(
        self,
        *,
        product_id:           str,
        categories_confirmed: list[str],
        growth_percent:       float,
        intensity_score:      float,
    ) -> ConfluenceResult:
        """
        Validate confluence for a single opportunity.

        Parameters:
          product_id           — product or opportunity identifier
          categories_confirmed — list of distinct signal category names
          growth_percent       — relative % growth over last 30 days
          intensity_score      — 0–100 intensity measure

        Returns:
          ConfluenceResult with approved=True/False and full audit trail.

        Side effects:
          • Persists audit record (append-only)
          • Emits opportunity_confluence_validated or opportunity_rejected_confluence
        """
        pid = str(product_id)
        now = self._now()

        # Deduplicate and filter only known categories
        confirmed = list({c for c in categories_confirmed if c in VALID_CATEGORIES})

        # --- Evaluate three gates ---
        blocking_reasons: list[str] = []

        if len(confirmed) < MIN_CATEGORIES:
            blocking_reasons.append(
                f"categories_confirmed={len(confirmed)} < {MIN_CATEGORIES} required. "
                f"Provided: {categories_confirmed}"
            )
        if growth_percent < MIN_GROWTH_PCT:
            blocking_reasons.append(
                f"growth_percent={growth_percent}% < {MIN_GROWTH_PCT}% required"
            )
        if intensity_score < MIN_INTENSITY:
            blocking_reasons.append(
                f"intensity_score={intensity_score} < {MIN_INTENSITY} required"
            )

        approved = len(blocking_reasons) == 0
        status   = "aprovado" if approved else "rejeitado"
        event_id = str(uuid.uuid4())

        # --- Build audit record ---
        record = {
            "event_id":             event_id,
            "product_id":           pid,
            "timestamp":            now.isoformat(),
            "categories_confirmed": confirmed,
            "growth_percent":       round(float(growth_percent), 4),
            "intensity_score":      round(float(intensity_score), 4),
            "status":               status,
            "motivo_bloqueio":      blocking_reasons if not approved else [],
        }

        # --- Persist (append-only) ---
        self._pers.append_record(record)
        self._records.append(record)

        # --- Emit event ---
        if approved:
            self.orchestrator.emit_event(
                event_type="opportunity_confluence_validated",
                product_id=pid,
                payload={
                    "event_id":             event_id,
                    "categories_confirmed": confirmed,
                    "growth_percent":       round(float(growth_percent), 4),
                    "intensity_score":      round(float(intensity_score), 4),
                    "timestamp":            now.isoformat(),
                },
                source="system",
            )
            logger.info(
                f"[B2] Confluence APPROVED for '{pid}': "
                f"categories={confirmed} growth={growth_percent}% intensity={intensity_score}"
            )
        else:
            self.orchestrator.emit_event(
                event_type="opportunity_rejected_confluence",
                product_id=pid,
                payload={
                    "event_id":        event_id,
                    "blocking_reasons": blocking_reasons,
                    "categories_confirmed": confirmed,
                    "growth_percent":  round(float(growth_percent), 4),
                    "intensity_score": round(float(intensity_score), 4),
                    "timestamp":       now.isoformat(),
                },
                source="system",
            )
            logger.warning(
                f"[B2] Confluence REJECTED for '{pid}': {blocking_reasons}"
            )

        return ConfluenceResult(
            approved=approved,
            event_id=event_id,
            categories_confirmed=confirmed,
            growth_percent=round(float(growth_percent), 4),
            intensity_score=round(float(intensity_score), 4),
            blocking_reasons=blocking_reasons,
            timestamp=now.isoformat(),
        )

    # ==================================================================
    # Read-only history
    # ==================================================================

    def get_all_validations(self, product_id: str | None = None) -> list[dict]:
        """Return all validation records, optionally filtered by product_id."""
        recs = list(self._records)
        if product_id is not None:
            recs = [r for r in recs if r["product_id"] == str(product_id)]
        return recs

    # ==================================================================
    # Execution guards
    # ==================================================================

    def create_product_automatically(self, *args, **kwargs) -> None:
        """Always raises. B2 has zero executive authority."""
        raise ConfluenceExecutionForbiddenError(
            "create_product_automatically() is permanently forbidden in B2. "
            "B2 is a binary validation filter with zero executive authority."
        )

    def approve_and_launch(self, *args, **kwargs) -> None:
        """Always raises. Approval never triggers launch."""
        raise ConfluenceExecutionForbiddenError(
            "approve_and_launch() is permanently forbidden. "
            "B2 approval does not trigger any execution. "
            "All actions require: human click → Orchestrator event → downstream engine."
        )
