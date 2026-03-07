import os
import json
import threading
from datetime import datetime, timezone
from infra.observability.async_worker import AsyncLogWorker

DATA_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\data"
MEMORY_FILE = os.path.join(DATA_DIR, "strategy_memory.json")
LOG_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\logs"
RUNTIME_LOG_FILE = os.path.join(LOG_DIR, "runtime_events.log")

class StrategyMemory:
    """
    Passive intelligence memory repository.
    Subscribes to EventBus, extracts strategic patterns, and persists them without mutating GlobalState or acting as an engine.
    """
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.memory_cache = self._load_memory()
        self._dirty = False
        self._subscribe_events()
        threading.Thread(target=self._persistence_worker, daemon=True).start()

    def _load_memory(self):
        try:
            if os.path.exists(MEMORY_FILE):
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "winning_copy_patterns": [],
            "buyer_segments": [],
            "pricing_patterns": [],
            "seo_keyword_patterns": [],
            "upsell_patterns": [],
            "product_success_signals": [],
            "product_failure_signals": []
        }

    def _persist_memory(self):
        # We instead flag the state as dirty to be written by the daemon thread.
        self._dirty = True

    def _persistence_worker(self):
        import time
        while True:
            time.sleep(0.5) # Wake up twice per second
            if self._dirty:
                try:
                    json_str = json.dumps(self.memory_cache, indent=2)
                    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                        f.write(json_str)
                    self._dirty = False
                except Exception:
                    pass

    def _log_activity(self, event_type: str, details: dict):
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "product_id": "SYSTEM_MEMORY",
                "payload": details
            }
            AsyncLogWorker().push(RUNTIME_LOG_FILE, entry)
        except Exception:
            pass

    def _subscribe_events(self):
        bus = self.orchestrator._bus
        events = [
            "product_created",
            "product_state_transition",
            "radar_opportunity_detected",
            "landing_generated",
            "traffic_started",
            "conversion_detected",
            "upsell_opportunity_detected",
            "copy_adjustment_event",
            "seo_adjustment_event",
            "targeting_adjustment_event",
            "pricing_signal_event",
            "buyer_segment_discovery_event",
            "human_patch_event"
        ]
        for ev in events:
            bus.subscribe(ev, lambda payload, event_type=ev: self._process_signal(event_type, payload))

    def _process_signal(self, event_type: str, payload: dict):
        # Extract patterns depending on event type
        pattern_detected = False
        
        if event_type == "copy_adjustment_event":
            self.memory_cache["winning_copy_patterns"].append({
                "type": "copy_pattern",
                "source_event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": payload.get("adjustment")
            })
            pattern_detected = True
            
        elif event_type == "seo_adjustment_event":
            self.memory_cache["seo_keyword_patterns"].append({
                "type": "seo_cluster",
                "source_event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": payload.get("adjustment")
            })
            pattern_detected = True
            
        elif event_type == "buyer_segment_discovery_event":
            self.memory_cache["buyer_segments"].append({
                "type": "buyer_segment",
                "segment": payload.get("segment", "unknown"),
                "source_event": event_type,
                "confidence": payload.get("confidence", 0.5),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            pattern_detected = True
            
        elif event_type == "pricing_signal_event":
            self.memory_cache["pricing_patterns"].append({
                "type": "pricing_conversion",
                "source_event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": payload.get("signal")
            })
            pattern_detected = True
            
        elif event_type == "upsell_opportunity_detected":
            self.memory_cache["upsell_patterns"].append({
                "type": "upsell_relationship",
                "source_event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": payload.get("opportunity")
            })
            pattern_detected = True
            
        elif event_type in ["conversion_detected", "product_success_signal"]:
            self.memory_cache["product_success_signals"].append({
                "type": "success_signal",
                "source_event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": payload
            })
            pattern_detected = True
            
        elif event_type == "product_state_transition" and payload.get("new_state") == "archive":
            self.memory_cache["product_failure_signals"].append({
                "type": "failure_signal",
                "source_event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": payload
            })
            pattern_detected = True
            
        elif event_type == "human_patch_event":
            if "generation_errors" not in self.memory_cache:
                self.memory_cache["generation_errors"] = []
                
            self.memory_cache["generation_errors"].append({
                "type": "generation_error",
                "origin": "human_patch",
                "confidence": "high",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context": payload.get("context", ""),
                "patch_type": payload.get("patch_type", ""),
                "target": payload.get("target", "")
            })
            pattern_detected = True
        
        # If any patterns were added, persist and log
        if pattern_detected:
            self._persist_memory()
            self._log_activity("strategy_memory_pattern_detected", {"source": event_type, "product_id": payload.get("product_id")})
        
        # Always log an update
        self._log_activity("strategy_memory_update", {"source": event_type, "product_id": payload.get("product_id")})

    def get_strategy_context(self):
        """
        Exposes summarized insights to the intelligence loop without mutating state.
        """
        self._log_activity("strategy_memory_context_loaded", {})
        
        # In a real scenario, this would apply summarization logic over the arrays.
        # For now, it returns a contextual snapshot.
        return {
            "top_converting_buyer_segments": self.memory_cache.get("buyer_segments", [])[-5:],
            "recurring_copy_styles": self.memory_cache.get("winning_copy_patterns", [])[-5:],
            "successful_pricing_ranges": self.memory_cache.get("pricing_patterns", [])[-5:],
            "seo_keyword_clusters": self.memory_cache.get("seo_keyword_patterns", [])[-5:],
            "upsell_product_relationships": self.memory_cache.get("upsell_patterns", [])[-5:]
        }
