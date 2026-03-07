"""
infra/traffic/traffic_engine_registry.py — Central registry for acquisition engines.

Responsibilities:
  - maintain list of active acquisition engines
  - provide safe iteration for execution
  - prevent duplicate engine registration
"""

import logging

logger = logging.getLogger("infra.traffic.registry")

class TrafficEngineRegistry:
    def __init__(self):
        self._engines = {}

    def register_engine(self, engine_instance) -> None:
        """
        Registers an active acquisition engine.
        Ensures idempotency / deduplication by channel_type.
        """
        if not hasattr(engine_instance, 'channel_type'):
            raise ValueError("Engine instance lacks a 'channel_type' property.")
            
        channel_type = engine_instance.channel_type
        
        expected_channels = ["ia_outreach", "seo", "google_ads"]
        if channel_type not in expected_channels:
            logger.warning("[TrafficEngineRegistry] Registering non-standard channel type: %s", channel_type)
        
        if channel_type in self._engines:
            logger.warning("[TrafficEngineRegistry] Engine for channel '%s' is already registered. Overwriting.", channel_type)
            
        self._engines[channel_type] = engine_instance
        logger.info("[TrafficEngineRegistry] Registered traffic engine: %s", channel_type)

    def get_active_engines(self) -> list:
        """
        Returns a list of all safely registered traffic engines.
        """
        return list(self._engines.values())

    def engine_exists(self, channel_type: str) -> bool:
        """
        Check if an engine is registered for a given channel context.
        """
        return channel_type in self._engines
