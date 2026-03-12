"""
infra/traffic/traffic_execution_layer.py — Orchestrated Traffic Execution Layer

Responsibilities:
  - subscribe to landing_ready_event from EventBus
  - fetch all registered engines
  - dispatch event to engines
  - route telemetry signals via EventBus

Constitutional constraints:
  - never mutate product state
  - never mutate price
  - never allocate capital
  - never bypass Orchestrator
"""

import logging
from core.event_bus import EventBus
from infra.traffic.traffic_engine_registry import TrafficEngineRegistry

logger = logging.getLogger("infra.traffic.execution_layer")

class TrafficExecutionLayer:
    def __init__(self, orchestrator):
        """
        Initializes the traffic layer safely attached to the central Orchestrator.
        Takes advantage of the registry for deterministic initialization.
        """
        self._orchestrator = orchestrator
        self.registry = TrafficEngineRegistry()

    def initialize(self):
        """
        Instantiate registry, register event listeners, and register specific engines.
        Called on system startup.
        """
        logger.info("[TrafficExecutionLayer] Initializing...")
        
        # Subscribe to landing ready signals
        self._orchestrator._bus.subscribe("landing_ready_event", self.handle_landing_ready)
        
        # Register engines
        try:
            from infra.traffic.engines.outreach_engine import IAOutreachEngine
            from infra.traffic.engines.seo_engine import SEOEngine
            from infra.traffic.engines.google_ads_engine import GoogleAdsEngine
            
            self.registry.register_engine(IAOutreachEngine(self._orchestrator))
            self.registry.register_engine(SEOEngine(self._orchestrator))
            self.registry.register_engine(GoogleAdsEngine(self._orchestrator))
            
            logger.info("[TrafficExecutionLayer] Engines successfully registered.")
        except Exception as e:
            logger.error("[TrafficExecutionLayer] Failed to register engines: %s", str(e))
        
        logger.info("[TrafficExecutionLayer] Initialization complete. Subscribed to landing_ready_event.")

    def handle_landing_ready(self, event: dict) -> None:
        """
        Triggered when a landing page is successfully compiled by Block 30.
        Dispatches payload to each active acquisition engine.
        Engines will then emit their telemetry / campaign signals through EventBus.
        """
        payload = event.get("payload", event)
        product_id = payload.get("product_id")
        
        if not product_id:
            logger.warning("[TrafficExecutionLayer] Ignored landing_ready_event, missing product_id.")
            return
            
        logger.info("[TrafficExecutionLayer] Received landing_ready for product_id=%s. Dispatching to traffic layer...", product_id)
        
        engines = self.registry.get_active_engines()
        if not engines:
            logger.info("[TrafficExecutionLayer] No traffic engines currently registered. Landing event acknowledged and finalized.")
            return
            
        # Dispatch to registered engines without direct cross-communication
        for engine in engines:
            logger.info("[TrafficExecutionLayer] Dispatching to engine: %s", engine.channel_type)
            try:
                engine.handle_landing_ready_event(payload)
            except Exception as e:
                logger.error(
                    "[TrafficExecutionLayer] Engine %s failed to handle event: %s", 
                    engine.channel_type, str(e), exc_info=True
                )
