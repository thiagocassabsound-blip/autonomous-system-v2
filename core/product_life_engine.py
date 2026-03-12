"""
core/product_life_engine.py — A5 Product Life Engine

Governs the formal lifecycle of products:
  [new] Draft → beta_approved_requested → Beta (7-day fixed window) → Ativo | Inativo

A14 Constitutional additions:
  - create_draft(): formal Draft creation via Orchestrator only
  - active_beta_count(): count of products currently in Beta state
  - start_beta() now enforces:
      1. orchestrated=True  (UnauthorizedLifecycleTransition if missing)
      2. global_state != CONTENÇÃO_FINANCEIRA
      3. active_beta_count < MAX_BETAS
      4. financial_alert_active == False

Rules:
  - Draft consumes no financial allocation.
  - Draft cannot run Ads, cannot start Beta automatically, cannot scale.
  - Draft can only transition to Beta (via beta_approved_requested) or Arquivado.
  - Beta window is FIXED at 7 days — cannot be closed early.
  - Consolidation requires: beta_window_closed + Telemetry snapshot + GlobalState != CONTENÇÃO.
  - All transitions go through StateMachine.
  - No product may remain in limbo.
  - All mutations emit formal events.
"""
import uuid
from datetime import datetime, timezone, timedelta
from infrastructure.logger import get_logger

logger = get_logger("ProductLifeEngine")

BETA_WINDOW_DAYS: int = 7
MAX_BETAS: int = 3

# Default minimum thresholds for post-beta eligibility
DEFAULT_MIN_RPM    = 0.5     # R$ revenue per visitor
DEFAULT_MIN_ROAS   = 1.2     # 120% return on ad spend
DEFAULT_MIN_MARGIN = 0.10    # 10% margin


# ===========================================================================
# Domain Exceptions
# ===========================================================================

class UnauthorizedLifecycleTransition(Exception):
    """
    Raised when a lifecycle mutation (start_beta, create_draft) is invoked
    directly without being routed through the Orchestrator.
    All lifecycle mutations require orchestrated=True.
    """

class BetaStartBlockedError(Exception):
    """
    Raised when start_beta() is blocked by a constitutional governance guard:
      - System is in CONTENÇÃO_FINANCEIRA
      - Active beta count >= MAX_BETAS (2)
      - Financial alert is active
    """

class BetaWindowViolationError(Exception):
    """Raised when trying to close beta before the 7-day window expires."""

class ProductLifecycleIntegrityError(Exception):
    """Raised when a product is detected in an inconsistent lifecycle state."""

class BetaNotStartedError(Exception):
    """Raised when an operation requires a beta record that doesn't exist."""

class ConsolidationPreconditionError(Exception):
    """Raised when post-beta consolidation preconditions are not met."""

class DraftCreationPayloadError(Exception):
    """Raised when required fields are missing from the product_creation_requested payload."""


# ===========================================================================
# Engine
# ===========================================================================

class ProductLifeEngine:
    """
    Formal product lifecycle governor.

    Lifecycle:
        Draft  → (beta_approved_requested) → Beta → Ativo | Inativo → Arquivado
        Draft  → Arquivado

    Persistence:
        product_lifecycle_state.json — one record per product_id

    Configurable thresholds (all passed at construction):
        min_rpm, min_roas, min_margin

    Injectible now_fn for deterministic time in tests:
        now_fn = lambda: datetime.now(timezone.utc)
    """

    def __init__(
        self,
        persistence,
        state_machine=None,
        min_rpm:    float = DEFAULT_MIN_RPM,
        min_roas:   float = DEFAULT_MIN_ROAS,
        min_margin: float = DEFAULT_MIN_MARGIN,
        now_fn=None,
    ):
        self._pers          = persistence
        self._state_machine = state_machine   # injected for active_beta_count()
        self.min_rpm        = min_rpm
        self.min_roas       = min_roas
        self.min_margin     = min_margin
        self._now           = now_fn or (lambda: datetime.now(timezone.utc))

        raw = persistence.load()
        self._state: dict = raw if isinstance(raw, dict) else {}

        logger.info(
            f"ProductLifeEngine initialized. "
            f"Products tracked: {len(self._state)}. "
            f"Thresholds: rpm≥{min_rpm}, roas≥{min_roas}, margin≥{min_margin}"
        )

        # Step 4: 365-day retention policy (auto-cleanup trash on startup)
        self.cleanup_trash()

    # -------------------------------------------------------------------
    # 0. Create Draft  [A14-NEW]
    # -------------------------------------------------------------------

    def create_draft(
        self,
        orchestrator,
        opportunity_id:        str,
        emotional_score:       float,
        monetization_score:    float,
        growth_percent:        float,
        competitive_gap_flag:  bool,
        justification_snapshot: dict,
        version_id:            str,
        orchestrated:          bool = False,
    ) -> dict:
        """
        Formally create a new product in Draft state.

        Constitutional Preconditions:
          1. orchestrated=True  — must be called via Orchestrator.receive_event(
                                  'product_creation_requested', ...)
          2. opportunity_id must be provided
          3. Justification snapshot must be a non-empty dict

        Draft Rules:
          - Consumes no financial allocation
          - Cannot run Ads
          - Cannot start Beta automatically
          - Cannot scale
          - Can be edited structurally
          - Must be persisted in append-only structure

        Emits: product_draft_created
        Raises: UnauthorizedLifecycleTransition, DraftCreationPayloadError
        """
        # --- Guard 0: Orchestrator context ---
        if not orchestrated:
            raise UnauthorizedLifecycleTransition(
                "create_draft() called outside Orchestrator context. "
                "All product creation must flow through "
                "Orchestrator.receive_event('product_creation_requested', ...)."
            )

        # --- Guard 1: Payload completeness ---
        if not opportunity_id:
            raise DraftCreationPayloadError("opportunity_id is required.")
        if not isinstance(justification_snapshot, dict) or not justification_snapshot:
            raise DraftCreationPayloadError(
                "justification_snapshot must be a non-empty dict."
            )

        # --- Generate product_id ---
        product_id = str(uuid.uuid4())
        now        = self._now()

        record: dict = {
            "product_id":             product_id,
            "state":                  "Draft",
            "created_at":             now.isoformat(),
            "opportunity_id":         str(opportunity_id),
            "emotional_score":        round(float(emotional_score), 4),
            "monetization_score":     round(float(monetization_score), 4),
            "growth_percent":         round(float(growth_percent), 4),
            "competitive_gap_flag":   bool(competitive_gap_flag),
            "justification_snapshot": justification_snapshot,
            "version_id":             str(version_id),
            "baseline_version":       "1.0",
            # Beta fields — None until beta starts
            "beta_start":             None,
            "beta_end":               None,
            "beta_closed_at":         None,
            "classification":         None,
            "last_transition":        now.isoformat(),
            # Campaign fields [NEW]
            "campaign_id":            None,
            "campaign_status":        None,
            "traffic_validation_status": None,

            # --- Operational Layer [Step 1, 4, 6] ---
            "product_stage":          "product_created",
            "product_events": [
                {"stage": "radar_detected",      "timestamp": now.isoformat()},
                {"stage": "opportunity_created", "timestamp": now.isoformat()},
                {"stage": "product_created",     "timestamp": now.isoformat()}
            ],
            "ads_enabled":            False,
            "deleted":                False,
            "deleted_at":             None
        }

        self._state[product_id] = record
        self._save()

        orchestrator.emit_event(
            event_type="product_draft_created",
            product_id=product_id,
            payload={
                "product_id":             product_id,
                "opportunity_id":         str(opportunity_id),
                "state":                  "Draft",
                "baseline_version":       "1.0",
                "emotional_score":        record["emotional_score"],
                "monetization_score":     record["monetization_score"],
                "growth_percent":         record["growth_percent"],
                "competitive_gap_flag":   record["competitive_gap_flag"],
                "version_id":             str(version_id),
                "created_at":             now.isoformat(),
                "campaign_id":            None,
                "campaign_status":        None,
                "traffic_validation_status": None,
                "note": (
                    "Draft state: no financial allocation, no Ads, "
                    "no automatic Beta. Awaiting beta_approved_requested."
                ),
            }
        )

        logger.info(
            f"[A14] Draft created: product_id='{product_id}' "
            f"from opportunity_id='{opportunity_id}' at {now.isoformat()}"
        )
        return record

    def update_metadata(self, product_id: str, updates: dict) -> dict:
        """
        Update specific metadata fields for a product.
        Used for campaign_id, campaign_status, etc.
        """
        p   = str(product_id)
        rec = self._require_record(p)
        
        allowed_fields = {
            "campaign_id", "campaign_status", "traffic_validation_status",
            "landing_url", "ad_group_id", "ads_enabled"
        }
        
        for k, v in updates.items():
            if k in allowed_fields:
                rec[k] = v
                # Auto-transition stage if landing_url is provided
                if k == "landing_url" and v:
                    self._record_event(p, "landing_generated")
        
        rec["last_transition"] = self._now().isoformat()
        self._save()
        logger.info(f"Updated metadata for {p}: {updates.keys()}")
        return rec

    def _record_event(self, product_id: str, stage: str):
        """Internal helper to record a lifecycle stage transition."""
        rec = self._state.get(str(product_id))
        if not rec: return
        
        now = self._now().isoformat()
        rec["product_stage"] = stage
        if "product_events" not in rec or not isinstance(rec["product_events"], list):
            rec["product_events"] = []
            
        # Avoid duplicate consecutive stages
        if not rec["product_events"] or rec["product_events"][-1]["stage"] != stage:
            rec["product_events"].append({"stage": stage, "timestamp": now})
            logger.info(f"Event recorded for {product_id}: {stage}")


    # -------------------------------------------------------------------
    # 1. Start Beta
    # -------------------------------------------------------------------

    def start_beta(
        self,
        product_id: str,
        orchestrator,
        orchestrated:           bool  = False,
        global_state            = None,
        financial_alert_active: bool  = False,
    ) -> dict:
        """
        Register the start of beta for a product.
        Sets beta_start and fixed beta_end (start + 7 days).

        Constitutional Preconditions [A14]:
          1. orchestrated=True   — UnauthorizedLifecycleTransition if missing
          2. global_state != CONTENÇÃO_FINANCEIRA
          3. active_beta_count()  < MAX_BETAS (2)
          4. financial_alert_active == False

        Emits: beta_started | beta_start_blocked
        Raises: UnauthorizedLifecycleTransition, BetaStartBlockedError
        """
        from core.global_state import CONTENCAO_FINANCEIRA

        p = str(product_id)

        # --- Guard 0: Orchestrator context [A14] ---
        if not orchestrated:
            raise UnauthorizedLifecycleTransition(
                f"Product '{p}': start_beta() called outside Orchestrator context. "
                f"Beta launch must flow through "
                f"Orchestrator.receive_event('beta_approved_requested', ...)."
            )

        now = self._now()

        # --- Guard 1: CONTENÇÃO_FINANCEIRA ---
        if global_state and global_state.get_state() == CONTENCAO_FINANCEIRA:
            reason = f"global_state=CONTENÇÃO_FINANCEIRA"
            orchestrator.emit_event(
                event_type="beta_start_blocked",
                product_id=p,
                payload={
                    "product_id":       p,
                    "blocking_reason":  reason,
                    "timestamp":        now.isoformat(),
                }
            )
            logger.warning(
                f"[A14] Beta blocked for '{p}': {reason}"
            )
            raise BetaStartBlockedError(
                f"Product '{p}': beta start blocked — {reason}"
            )

        # --- Guard 2: Active beta count ---
        current_betas = self.active_beta_count()
        if current_betas >= MAX_BETAS:
            reason = f"active_beta_count={current_betas} >= MAX_BETAS={MAX_BETAS}"
            orchestrator.emit_event(
                event_type="beta_start_blocked",
                product_id=p,
                payload={
                    "product_id":       p,
                    "blocking_reason":  reason,
                    "active_betas":     current_betas,
                    "max_betas":        MAX_BETAS,
                    "timestamp":        now.isoformat(),
                }
            )
            logger.warning(
                f"[A14] Beta blocked for '{p}': {reason}"
            )
            raise BetaStartBlockedError(
                f"Product '{p}': beta start blocked — {reason}"
            )

        # --- Guard 3: Financial alert ---
        if financial_alert_active:
            reason = "financial_alert_active=True"
            orchestrator.emit_event(
                event_type="beta_start_blocked",
                product_id=p,
                payload={
                    "product_id":      p,
                    "blocking_reason": reason,
                    "timestamp":       now.isoformat(),
                }
            )
            logger.warning(
                f"[A14] Beta blocked for '{p}': {reason}"
            )
            raise BetaStartBlockedError(
                f"Product '{p}': beta start blocked — {reason}"
            )

        # --- All guards passed: start beta ---
        end = now + timedelta(days=BETA_WINDOW_DAYS)

        if self._state_machine:
            try:
                self._state_machine.transition(
                    product_id=p,
                    new_state="Beta",
                    reason="Beta phase formally started via ProductLifeEngine.",
                    metric=None,
                    orchestrator=orchestrator
                )
            except Exception as e:
                logger.error(f"State transition to Beta failed for '{p}': {e}")
                # We continue to ensure engine record is updated, 
                # though inconsistency will be caught by Orchestrator/Guardian.

        # Update existing record (from Draft) or create minimal record
        if p in self._state:
            rec = self._state[p]
            rec["state"]           = self._state_machine.get_state(p) if self._state_machine else "Beta"
            rec["beta_start"]      = now.isoformat()
            rec["beta_end"]        = end.isoformat()
            rec["beta_closed_at"]  = None
            rec["last_transition"] = now.isoformat()
        else:
            rec = {
                "product_id":      p,
                "state":           self._state_machine.get_state(p) if self._state_machine else "Beta",
                "beta_start":      now.isoformat(),
                "beta_end":        end.isoformat(),
                "classification":  None,
                "last_transition": now.isoformat(),
                "beta_closed_at":  None,
            }
            self._state[p] = rec

        self._record_event(p, "beta_started")
        self._save()

        orchestrator.emit_event(
            event_type="beta_started",
            product_id=p,
            payload={
                "beta_start":         rec["beta_start"],
                "beta_end":           rec["beta_end"],
                "beta_duration_days": BETA_WINDOW_DAYS,
            }
        )
        logger.info(
            f"Beta started for '{p}'. "
            f"Window: {rec['beta_start']} → {rec['beta_end']}"
        )
        return rec

    # -------------------------------------------------------------------
    # 2. Active Beta Count  [A14-NEW]
    # -------------------------------------------------------------------

    def active_beta_count(self) -> int:
        """
        Count products where state == 'Beta'.

        Uses state_machine if injected (authoritative); otherwise falls back
        to records in the lifecycle persistence store.
        """
        if self._state_machine is not None:
            # Authoritative: query the state machine directly
            try:
                sm_states = self._state_machine._product_states
                return sum(1 for s in sm_states.values() if s == "Beta")
            except Exception:
                pass

        # Fallback: count from own lifecycle records
        count = 0
        for rec in self._state.values():
            # Beta: beta_start set, beta_closed_at not set
            if rec.get("beta_start") and not rec.get("beta_closed_at"):
                count += 1
        return count

    # -------------------------------------------------------------------
    # 3. Check Expiration (passive — emits beta_window_closed if expired)
    # -------------------------------------------------------------------

    def check_beta_expiration(self, product_id: str, orchestrator) -> bool:
        """
        Check if the beta window has expired.
        If yes and not yet closed, emit beta_window_closed automatically.
        Returns True if the window is now closed.
        """
        p   = str(product_id)
        rec = self._require_record(p)

        if rec["beta_closed_at"]:
            return True     # already closed

        now, end = self._now(), self._parse_dt(rec["beta_end"])
        if now >= end:
            self._seal_beta(p, now, orchestrator)
            return True
        return False

    # -------------------------------------------------------------------
    # 4. Close Beta (explicit — raises if before window)
    # -------------------------------------------------------------------

    def close_beta(self, product_id: str, orchestrator) -> dict:
        """
        Formally close beta for a product.
        Raises BetaWindowViolationError if the 7-day window has not elapsed.
        Emits: beta_window_closed
        """
        p   = str(product_id)
        rec = self._require_record(p)

        if rec["beta_closed_at"]:
            return rec      # idempotent

        now, end = self._now(), self._parse_dt(rec["beta_end"])
        if now < end:
            raise BetaWindowViolationError(
                f"Product '{p}': beta window ends at {rec['beta_end']}. "
                f"Cannot close {(end - now).days}d {(end - now).seconds // 3600}h early."
            )

        return self._seal_beta(p, now, orchestrator)

    # -------------------------------------------------------------------
    # 5. Post-Beta Consolidation
    # -------------------------------------------------------------------

    def consolidate_post_beta(
        self,
        product_id:      str,
        orchestrator,
        telemetry_engine,
        state_machine,
        global_state=None,
    ) -> dict:
        """
        Consolidate metrics after beta and transition the product state.

        Preconditions:
            1. beta_window_closed must be recorded.
            2. GlobalState must NOT be CONTENÇÃO_FINANCEIRA.
            3. A Telemetry snapshot must exist.

        Classification:
            elegivel     → StateMachine.transition(→ Ativo)
            nao_elegivel → StateMachine.transition(→ Inativo)

        Emits: post_beta_consolidated
        """
        from core.global_state import CONTENCAO_FINANCEIRA

        p   = str(product_id)
        rec = self._require_record(p)

        # --- Precondition 1: beta must be closed ---
        if not rec.get("beta_closed_at"):
            raise ConsolidationPreconditionError(
                f"Product '{p}': beta_window_closed not recorded. "
                f"Run close_beta() or check_beta_expiration() first."
            )

        # --- Precondition 2: financial clearance ---
        if global_state and global_state.get_state() == CONTENCAO_FINANCEIRA:
            raise ConsolidationPreconditionError(
                f"Product '{p}': consolidation blocked — "
                f"system is in CONTENÇÃO_FINANCEIRA."
            )

        # --- Precondition 3: telemetry snapshot ---
        snapshot = telemetry_engine.get_latest_snapshot(p)
        if not snapshot:
            raise ConsolidationPreconditionError(
                f"Product '{p}': no Telemetry snapshot available. "
                f"Close a cycle via TelemetryEngine first."
            )

        rpm    = snapshot.get("rpm",    0.0)
        roas   = snapshot.get("roas",   0.0)
        margin = snapshot.get("margin", 0.0)
        
        # --- CONSTITUTIONAL CORRECTION (C5) ---
        # "Vida governada exclusivamente pela presença de pelo menos uma venda validada"
        conversions  = snapshot.get("conversions", 0)
        refund_count = snapshot.get("refund_count", 0)
        net_conversions = conversions - refund_count

        eligible       = net_conversions >= 1
        classification = "elegivel" if eligible else "nao_elegivel"
        target_state   = "Ativo"   if eligible else "Inativo"

        now = self._now()

        # Emit audit trail for constitutional correction
        orchestrator.emit_event(
            event_type="constitutional_c5_life_authority_corrected",
            product_id=p,
            payload={
                "previous_logic_detected": True,
                "economic_threshold_removed": True,
                "constitution_reference": "Camada 2 — Vida governada por venda validada",
                "net_conversions": net_conversions,
                "thresholds_ignored": {
                    "rpm": self.min_rpm,
                    "roas": self.min_roas,
                    "margin": self.min_margin
                },
                "timestamp": now.isoformat()
            }
        )

        # --- Formal State Machine Transition ---
        transition_result = None
        if state_machine:
            try:
                transition_result = state_machine.transition(
                    product_id=p,
                    new_state=target_state,
                    reason=f"Post-beta consolidation: {classification}.",
                    metric=f"net_conv={net_conversions},roas={roas:.3f},rpm={rpm:.3f}",
                    orchestrator=orchestrator
                )
            except Exception as e:
                logger.error(f"Post-beta transition failed for '{p}': {e}")

        # Update stage
        if eligible:
            self._record_event(p, "test_running")
        
        # --- Persist classification ---
        rec["classification"]  = classification
        rec["state"]           = state_machine.get_state(p) if state_machine else target_state
        rec["last_transition"] = now.isoformat()
        self._save()

        # --- Formal event ---
        orchestrator.emit_event(
            event_type="post_beta_consolidated",
            product_id=p,
            payload={
                "product_id":       p,
                "classification":   classification,
                "net_conversions":  net_conversions,
                "rpm":              rpm,
                "roas":             roas,
                "margin":           margin,
                "snapshot_version": snapshot.get("version_number"),
            }
        )

        logger.info(
            f"Post-beta consolidation for '{p}': {classification} → {target_state}. "
            f"RPM={rpm:.4f}, ROAS={roas:.4f}, Margin={margin:.4f}"
        )

        # --- Limbo guard (always after consolidation) ---
        self.ensure_no_product_in_limbo()

        return {
            "classification": classification,
            "target_state":   target_state,
            "snapshot":       snapshot,
            "transition":     transition_result,
        }

    # -------------------------------------------------------------------
    # 7. Soft Delete (Trash) [Step 4]
    # -------------------------------------------------------------------

    def move_to_trash(self, product_id: str) -> dict:
        """Sets deleted=True and records deleted_at timestamp."""
        p = str(product_id)
        rec = self._require_record(p)
        now = self._now().isoformat()
        
        rec["deleted"] = True
        rec["deleted_at"] = now
        rec["last_transition"] = now
        self._save()
        
        logger.info(f"Product moved to trash: {p}")
        return rec

    def restore_from_trash(self, product_id: str) -> dict:
        """Restores a product from trash."""
        p = str(product_id)
        rec = self._require_record(p)
        now = self._now().isoformat()
        
        rec["deleted"] = False
        rec["deleted_at"] = None
        rec["last_transition"] = now
        self._save()
        
        logger.info(f"Product restored from trash: {p}")
        return rec

    def delete_permanently(self, product_id: str) -> bool:
        """Permanently removes a product from persistence."""
        p = str(product_id)
        if p in self._state:
            del self._state[p]
            self._save()
            logger.info(f"Product permanently deleted: {p}")
            return True
        return False

    def cleanup_trash(self, retention_days: int = 365):
        """Removes products from trash that are older than retention_days."""
        now = self._now()
        to_delete = []
        
        for pid, rec in self._state.items():
            if rec.get("deleted") and rec.get("deleted_at"):
                try:
                    del_at = datetime.fromisoformat(rec["deleted_at"])
                    if (now - del_at).days >= retention_days:
                        to_delete.append(pid)
                except Exception as e:
                    logger.warning(f"Failed to parse deleted_at for {pid}: {e}")
        
        if to_delete:
            for pid in to_delete:
                del self._state[pid]
            self._save()
            logger.info(f"Trash cleanup: permanently deleted {len(to_delete)} products.")

    # -------------------------------------------------------------------
    # 6. Limbo Detection
    # -------------------------------------------------------------------

    def ensure_no_product_in_limbo(self) -> None:
        """
        Scan all tracked products for lifecycle integrity violations.
        Raises ProductLifecycleIntegrityError on first violation.

        Limbo conditions:
          - Beta window expired but beta_window_closed NOT recorded.
        """
        now = self._now()
        for pid, rec in self._state.items():
            if not rec.get("beta_end"):
                continue   # Draft products have no beta window — skip
            end = self._parse_dt(rec["beta_end"])
            # Expired beta with no formal closure = LIMBO
            if now >= end and not rec.get("beta_closed_at"):
                raise ProductLifecycleIntegrityError(
                    f"LIMBO: Product '{pid}' beta expired ({rec['beta_end']}) "
                    f"but beta_window_closed was never recorded."
                )

    # ===========================================================================
    # Internal
    # ===========================================================================

    def _require_record(self, p: str) -> dict:
        rec = self._state.get(p)
        if not rec:
            raise BetaNotStartedError(
                f"No lifecycle record for product '{p}'. "
                f"Call create_draft() or start_beta() first."
            )
        return rec

    def _seal_beta(self, p: str, now: datetime, orchestrator) -> dict:
        """Mark beta as closed, persist, and emit beta_window_closed."""
        rec = self._state[p]
        rec["beta_closed_at"]  = now.isoformat()
        rec["last_transition"] = now.isoformat()
        self._save()

        orchestrator.emit_event(
            event_type="beta_window_closed",
            product_id=p,
            payload={
                "product_id":         p,
                "beta_duration_days": BETA_WINDOW_DAYS,
                "closed_at":          now.isoformat(),
            }
        )
        logger.info(f"Beta window closed for '{p}' at {now.isoformat()}.")
        return rec

    def _parse_dt(self, ts: str) -> datetime:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _save(self) -> None:
        self._pers.save(self._state)
