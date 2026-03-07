"""
infra/observability/event_trace.py
Passive observability layer tracing the entire EventBus flow.
"""
import os
import json
from datetime import datetime, timezone

from infra.observability.async_worker import AsyncLogWorker

LOG_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\logs"
TRACE_LOG_FILE = os.path.join(LOG_DIR, "event_trace.log")

class EventTrace:
    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        
    def hook_event_bus(self, orchestrator):
        # We patch the event bus to capture ALL formal append_events passively
        original_append = orchestrator._bus.append_event
        
        def tracing_append(event: dict):
            # Let the primary bus do its job securely
            formal = original_append(event)
            
            # Record it structurally strictly for tracing
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": formal.get("event_type"),
                "origin_engine": formal.get("source"),
                "payload": formal.get("payload"),
                "routing_result": "APPended_TO_LEDGER"
            }
            try:
                AsyncLogWorker().push(TRACE_LOG_FILE, entry)
            except Exception:
                pass # Passive observability, never block execution
            
            return formal
            
        orchestrator._bus.append_event = tracing_append
