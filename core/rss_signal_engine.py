import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from infrastructure.rss.rss_source_registry import rss_sources
from infrastructure.rss.rss_parser import RSSParser
from infrastructure.rss.rss_event_normalizer import RSSEventNormalizer
from infrastructure.rss.rss_persistence import RSSPersistence

logger = logging.getLogger("rss_signal_engine")

class RSSSignalEngine:
    """
    Acts exclusively as a signal ingestion layer on command.
    No executive authority.
    """
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def run_collection_cycle(self):
        """
        Executes the RSS collection driven by external events, applying safety boundaries.
        """
        # 1. Global State Contencao Check
        global_state = self.orchestrator.get_global_state() if hasattr(self.orchestrator, 'get_global_state') else "NORMAL"
        if global_state == "CONTENCAO":
            logger.warning("[RSS Engine] Execution blocked via global_state == CONTENCAO")
            self.orchestrator.emit_event("rss_execution_blocked", {"reason": "CONTENCAO"}, source="RSSSignalEngine")
            return

        # 2. Financial Safety Check
        # Check central orchestrator memory attributes for critical flags
        credit_critical = getattr(self.orchestrator, 'credit_critical_warning', False)
        financial_alert = getattr(self.orchestrator, 'financial_alert_active', False)
        if credit_critical or financial_alert:
            logger.warning("[RSS Engine] Execution blocked due to financial safety rules")
            self.orchestrator.emit_event("rss_execution_blocked_financial", {"reason": "financial_risk"}, source="RSSSignalEngine")
            return
            
        # 3. Macro Exposure Control Check
        macro_exposure_blocked = getattr(self.orchestrator, 'macro_exposure_blocked', False)
        if macro_exposure_blocked:
            logger.warning("[RSS Engine] Execution blocked due to macro exposure rules")
            return

        logger.info("[RSS Engine] Starting RSS Signal Collection cycle")
        
        valid_signals = []
        for source in rss_sources:
            if not source.get("enabled", False):
                continue
                
            raw_items = RSSParser.fetch_and_extract(source)
            for item in raw_items:
                candidate = RSSEventNormalizer.normalize(item)
                if not candidate:
                    continue 
                    
                # Duplication Check
                url = candidate.get("url")
                title = candidate.get("title")
                if RSSPersistence.is_duplicate(url, title):
                    continue
                    
                # Promotional ad check
                desc_lower = candidate.get("description", "").lower()
                if "buy now" in desc_lower or "discount" in desc_lower or "promo" in desc_lower:
                    continue
                
                # Persist strictly to append-only register
                RSSPersistence.record_signal(candidate)
                valid_signals.append(candidate)
                
                # Emit events via EventBus
                payload = {
                    "signal_id": candidate.get("event_id"),
                    "source": candidate.get("source_name"),
                    "keyword_cluster": candidate.get("keyword_cluster"),
                    "signal_strength": candidate.get("signal_strength"),
                    "timestamp": candidate.get("timestamp")
                }
                
                # 1. Main detected routing
                self.orchestrator.emit_event("rss_signal_detected", payload, source="rss_layer")
                
                # 2. Telemetry tracking event hook logic (orchestrator tracks this automatically or telemetry engine parses it)
                
        return valid_signals
