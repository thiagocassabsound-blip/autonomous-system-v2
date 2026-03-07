"""
core/telemetry_engine.py — Official Economic Telemetry Engine (A3)

Deterministic, append-only economic accounting system.
Metrics are computed ONLY at cycle close — never retroactively.
All snapshots are immutable once created.

KPIs:
    RPM    = revenue_liquida / visitors
    ROAS   = revenue_liquida / ad_spend
    CAC    = ad_spend / conversions
    Margin = (revenue_liquida - ad_spend) / revenue_liquida
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("TelemetryEngine")


class TelemetryEngine:
    """
    Accumulates economic metrics for open product cycles, then seals
    them into an immutable snapshot when the cycle is closed.

    Persistence:
      - snapshot_persistence     → telemetry_snapshots.json (append-only)
      - accumulator_persistence  → telemetry_accumulators.json (resumable)

    External API (called by Orchestrator service handlers):
        record_visit(product_id)
        record_revenue(product_id, amount)
        record_ad_spend(product_id, amount)
        record_refund(product_id, amount)
        close_cycle_snapshot(product_id, cycle_id, event_bus) → snapshot
    """

    def __init__(self, snapshot_persistence, accumulator_persistence=None):
        self._snap_store = snapshot_persistence
        self._accum_pers = accumulator_persistence

        # Global version = total number of snapshots ever created
        self._version: int = len(self._snap_store.load())

        # In-memory & resumable accumulators: { product_id → counters }
        self._accumulators: dict = {}
        if accumulator_persistence:
            saved = accumulator_persistence.load()
            if isinstance(saved, dict):
                self._accumulators = saved

        logger.info(
            f"TelemetryEngine initialized. "
            f"Snapshots: {self._version}. "
            f"Active accumulators: {len(self._accumulators)}"
        )

    # ==================================================================
    # Accumulation API
    # ==================================================================

    def record_visit(self, product_id: str) -> None:
        product_id = str(product_id)
        acc = self._acc(product_id)
        acc["visitors"] += 1
        self._save_accumulators()

    def record_revenue(self, product_id: str, amount: float) -> None:
        product_id = str(product_id)
        if amount < 0:
            raise ValueError(f"record_revenue: amount must be >= 0, got {amount}.")
        acc = self._acc(product_id)
        acc["revenue_bruta"] += amount
        acc["conversions"]   += 1       # each revenue event = 1 conversion
        self._save_accumulators()

    def record_ad_spend(self, product_id: str, amount: float) -> None:
        product_id = str(product_id)
        if amount < 0:
            raise ValueError(f"record_ad_spend: amount must be >= 0, got {amount}.")
        acc = self._acc(product_id)
        acc["ad_spend"] += amount
        self._save_accumulators()

    def record_refund(self, product_id: str, amount: float) -> None:
        product_id = str(product_id)
        if amount < 0:
            raise ValueError(f"record_refund: amount must be >= 0, got {amount}.")
        acc = self._acc(product_id)
        acc["refunds"] += amount
        acc["refund_count"] = acc.get("refund_count", 0) + 1
        self._save_accumulators()

    # ==================================================================
    # Cycle Close — creates immutable snapshot
    # ==================================================================

    def close_cycle_snapshot(
        self,
        product_id: str,
        cycle_id:   str,
        orchestrator,
        phase_id:   int = None,
    ) -> dict:
        """
        Consolidate accumulated metrics → immutable snapshot.
        Clears the accumulator for this product.
        Emits cycle_snapshot_created to the formal ledger.
        """
        product_id = str(product_id)
        acc = self._accumulators.get(product_id, {})

        visitors        = acc.get("visitors",      0)
        conversions     = acc.get("conversions",   0)
        refund_count    = acc.get("refund_count",  0)
        revenue_bruta   = acc.get("revenue_bruta", 0.0)
        refunds_total   = acc.get("refunds",       0.0)
        ad_spend        = acc.get("ad_spend",      0.0)
        revenue_liquida = revenue_bruta - refunds_total

        rpm    = self._div(revenue_liquida, visitors)
        roas   = self._div(revenue_liquida, ad_spend)
        cac    = self._div(ad_spend,        conversions)
        margin = self._div(revenue_liquida - ad_spend, revenue_liquida)

        self._version += 1

        snapshot: dict = {
            "snapshot_id":     str(uuid.uuid4()),
            "version_number":  self._version,
            "cycle_id":        cycle_id,
            "product_id":      product_id,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "source":          "system",
            "phase_id":        phase_id,
            # Raw counters
            "visitors":        visitors,
            "conversions":     conversions,
            "refund_count":    refund_count,
            "revenue_bruta":   round(revenue_bruta,   2),
            "revenue_liquida": round(revenue_liquida,  2),
            "ad_spend":        round(ad_spend,         2),
            "refunds":         round(refunds_total,    2),
            # Calculated KPIs — computed once, never updated
            "rpm":             rpm,
            "roas":            roas,
            "cac":             cac,
            "margin":          margin,
        }

        # Append-only — immutable from this point
        self._snap_store.append(snapshot)

        # Clear accumulator (cycle is now sealed)
        self._accumulators.pop(product_id, None)
        self._save_accumulators()

        orchestrator.emit_event(
            event_type="cycle_snapshot_created",
            payload={
                "snapshot_id":    snapshot["snapshot_id"],
                "version_number": self._version,
                "cycle_id":       cycle_id,
                "phase_id":       phase_id,
                "rpm":            rpm,
                "roas":           roas,
                "margin":         margin,
            },
            source="TelemetryEngine",
            product_id=product_id
        )

        logger.info(
            f"Snapshot v{self._version} sealed for product '{product_id}' "
            f"(cycle={cycle_id[:8]}...) — "
            f"RPM={rpm:.4f}, ROAS={roas:.4f}, "
            f"CAC={cac:.4f}, Margin={margin:.4f}"
        )
        return snapshot

    # ==================================================================
    # Query API (read-only — safe for Dashboard and Pricing)
    # ==================================================================

    def get_latest_snapshot(self, product_id: str) -> dict | None:
        snaps = self.list_snapshots(product_id)
        return snaps[-1] if snaps else None

    def list_snapshots(self, product_id: str) -> list:
        return [
            s for s in self._snap_store.load()
            if s.get("product_id") == str(product_id)
        ]

    def get_official_cycle_metrics(self, product_id: str, cycle_id: str, phase_id: int) -> dict | None:
        """
        Retrieves the official immutable snapshot for a specific cycle phase.
        """
        for s in reversed(self._snap_store.load()):
            if (s.get("product_id") == str(product_id) and 
                s.get("cycle_id") == cycle_id and 
                s.get("phase_id") == phase_id):
                return s
        return None

    # ==================================================================
    # Internal
    # ==================================================================

    def _acc(self, product_id: str) -> dict:
        """Return (or create) the in-memory accumulator for a product."""
        if product_id not in self._accumulators:
            self._accumulators[product_id] = {
                "visitors":      0,
                "conversions":   0,
                "revenue_bruta": 0.0,
                "refunds":       0.0,
                "refund_count":  0,
                "ad_spend":      0.0,
            }
        
        # Ensure backward compatibility for existing accumulators
        if "refund_count" not in self._accumulators[product_id]:
            self._accumulators[product_id]["refund_count"] = 0

        return self._accumulators[product_id]

    def _save_accumulators(self) -> None:
        if self._accum_pers:
            self._accum_pers.save(self._accumulators)

    @staticmethod
    def _div(numerator: float, denominator: float) -> float:
        """Safe division; returns 0.0 when denominator is zero."""
        return round(numerator / denominator, 6) if denominator else 0.0
