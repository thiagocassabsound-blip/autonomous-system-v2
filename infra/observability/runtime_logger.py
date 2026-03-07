"""
infra/observability/runtime_logger.py
Passive observability layer logging business occurrences.
"""
import os
import json
from datetime import datetime, timezone

from infra.observability.async_worker import AsyncLogWorker

LOG_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\logs"
RUNTIME_LOG_FILE = os.path.join(LOG_DIR, "runtime_events.log")

class RuntimeLogger:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        os.makedirs(LOG_DIR, exist_ok=True)
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        bus = self.orchestrator._bus
        events_to_track = [
             "product_created",
             "product_state_transition",
             "radar_opportunity_detected",
             "landing_generated",
             "traffic_started",
             "pricing_adjustment",
             "upsell_opportunity_event",
             "targeting_adjustment_event",
             "seo_adjustment_event",
             "copy_adjustment_event",
             "pricing_signal_event",
             "product_evolution_event",
             "buyer_segment_discovery_event",
             "system_warning",
             "system_error",
             "traffic_event_detected",
             "conversion_detected",
             "campaign_performance_event",
             "outreach_message_generated",
             "seo_opportunity_detected",
             "campaign_prepared",
             "ads_cost_reported",
             "ads_budget_limit_reached",
             "infrastructure_check_started",
             "infrastructure_check_completed",
             "domain_expiration_warning",
             "domain_expiration_critical",
             "dns_resolution_failure",
             "ssl_expiration_warning",
             "ssl_expiration_critical",
             "hosting_unreachable",
             "hosting_latency_warning",
             "billing_payment_warning",
             "billing_failure"
        ]
        for ev in events_to_track:
            bus.subscribe(ev, lambda payload, event_type=ev: self._log_event(event_type, payload))

    def _log_event(self, event_type: str, payload: dict):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "product_id": payload.get("product_id", "N/A"),
            "payload": payload
        }
        try:
            AsyncLogWorker().push(RUNTIME_LOG_FILE, entry)
        except Exception:
            pass # Passive observability, never break execution
