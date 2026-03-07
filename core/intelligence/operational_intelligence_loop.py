"""
core/intelligence/operational_intelligence_loop.py — Wave 3
Operational Intelligence Loop:
Consumes signals from cross-system engines and aggregates intelligence to 
emit strategic adjustment events via the formal Orchestrator pipeline.
NEVER mutates state directly.
"""
from infrastructure.logger import get_logger
import uuid
from datetime import datetime, timezone

logger = get_logger("OperationalIntelligenceLoop")

class OperationalIntelligenceLoop:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        from core.intelligence.strategy_memory import StrategyMemory
        self.strategy_memory = StrategyMemory(orchestrator)
        self._subscribe_to_signals()
        logger.info("OperationalIntelligenceLoop initialized.")

    def _subscribe_to_signals(self):
        """Subscribe to raw signals from various system engines."""
        bus = self.orchestrator._bus
        # Consume signals (simulated integration points based on EventBus)
        bus.subscribe("radar_opportunity_detected", self._handle_radar_signal)
        bus.subscribe("audience_signal", self._handle_enrichment_signal)
        bus.subscribe("pain_signal", self._handle_enrichment_signal)
        bus.subscribe("keyword_signal", self._handle_enrichment_signal)
        bus.subscribe("telemetry_anomaly_detected", self._handle_telemetry_signal)
        bus.subscribe("financial_alert_raised", self._handle_finance_signal)
        bus.subscribe("product_structural_decline_detected", self._handle_lifecycle_signal)

    def _emit_strategic_event(self, event_type: str, payload: dict, product_id: str = None):
        """
        Routes the strategic intelligence signal back into the system formally 
        via the Orchestrator without mutating any state directly.
        """
        try:
            context = self.strategy_memory.get_strategy_context()
            payload["strategy_context"] = context
        except Exception as e:
            logger.error(f"[IntelligenceLoop] Failed to attach strategy context: {e}")

        # We wrap in a formal event payload
        event_payload = {
            "intelligence_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis_origin": "OperationalIntelligenceLoop",
            "body": payload
        }
        
        try:
            # Emit publicly so pub/sub (RuntimeLogger) hears it
            self.orchestrator._bus.emit(event_type, event_payload)
            # Route to formal execution pipeline
            self.orchestrator.receive_event(
                event_type=event_type,
                payload=event_payload,
                source="OperationalIntelligenceLoop",
                product_id=product_id
            )
            logger.info(f"[IntelligenceLoop] Emitted strategic event: {event_type} (product: {product_id})")
        except Exception as e:
            logger.error(f"[IntelligenceLoop] Failed to emit {event_type}: {e}")

    # ==========================================
    # Signal Handlers
    # ==========================================

    def _handle_radar_signal(self, payload: dict):
        """Process Radar Engine outputs mapping them to SEO and targeting adjustments."""
        product_id = payload.get("product_id")
        if not product_id: return
        
        # Example Logic: convert trending query to SEO adjustment signal
        query = payload.get("opportunity_query")
        if query:
            self._emit_strategic_event(
                "seo_adjustment_event", 
                {"reason": "Trending query matched existing product", "target_keyword": query}, 
                product_id=product_id
            )
            
    def _handle_enrichment_signal(self, payload: dict):
        """Process Enrichment Engine signals (e.g. pain_signal) mapping to Copy / Product Evolution."""
        product_id = payload.get("product_id")
        signal_type = payload.get("signal_type", "unknown")
        
        if signal_type == "pain_signal":
            self._emit_strategic_event(
                "copy_adjustment_event",
                {"trigger": "New pain point discovered", "focus_area": payload.get("pain_point")},
                product_id=product_id
            )
            self._emit_strategic_event(
                "product_evolution_event",
                {"trigger": "Feature gap identified based on pain points", "suggestion": payload.get("pain_point")},
                product_id=product_id
            )
        elif signal_type == "audience_signal":
            self._emit_strategic_event(
                "buyer_segment_discovery_event",
                {"new_segment": payload.get("audience_demographic")},
                product_id=product_id
            )
            self._emit_strategic_event(
                "targeting_adjustment_event",
                {"action": "Add discovered segment to ad campaigns", "segment": payload.get("audience_demographic")},
                product_id=product_id
            )

    def _handle_telemetry_signal(self, payload: dict):
        """Process Telemetry patterns mapping them to Upsells or Pricing shifts."""
        product_id = payload.get("product_id")
        
        high_engagement = payload.get("metric_type") == "session_duration" and payload.get("value", 0) > 300
        if high_engagement:
             self._emit_strategic_event(
                "upsell_opportunity_event",
                {"reason": "High session duration implies strong qualification.", "metric_value": payload.get("value")},
                product_id=product_id
             )

    def _handle_finance_signal(self, payload: dict):
        """Process Financial alarms mapping them to conservative Pricing signals."""
        # Generic financial signal does not strictly need product_id
        product_id = payload.get("product_id", "GLOBAL")
        self._emit_strategic_event(
            "pricing_signal_event",
            {"direction": "defensive", "reason": "Financial alert triggered."},
            product_id=product_id
        )

    def _handle_lifecycle_signal(self, payload: dict):
        """Process Product Lifecycle shifts (e.g. decline) mapping to aggressive Evolution or Copy rewrite."""
        product_id = payload.get("product_id")
        
        self._emit_strategic_event(
            "copy_adjustment_event",
            {"direction": "aggressive_rewrite", "reason": "Product entered structural decline."},
            product_id=product_id
        )
        self._emit_strategic_event(
            "pricing_signal_event",
            {"direction": "offensive_discount", "reason": "Attempting to reverse structural decline curve."},
            product_id=product_id
        )
