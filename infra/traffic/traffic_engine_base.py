"""
infra/traffic/traffic_engine_base.py — Base class for Acquisition Engines (Block 30 -> Traffic -> Block 9/17)

Responsibilities:
  - define standard interface for acquisition engines
  - enforce event-based communication
  - enforce telemetry emission
  - prevent direct state mutation

Constitutional constraints:
  - never mutate product state
  - never mutate price
  - never allocate capital
  - never bypass Orchestrator
"""

import abc
import logging

class TrafficEngineBase(abc.ABC):
    def __init__(self, orchestrator):
        self._orchestrator = orchestrator
        self.logger = logging.getLogger(f"infra.traffic.engine.{self.channel_type}")

    @property
    @abc.abstractmethod
    def channel_type(self) -> str:
        """
        Must return string like 'ia_outreach', 'seo', or 'google_ads'.
        """
        pass

    @abc.abstractmethod
    def initialize(self):
        """
        Initialize the engine, load credentials, setup API clients.
        Must not execute traffic operations yet.
        """
        pass

    @abc.abstractmethod
    def handle_landing_ready_event(self, payload: dict):
        """
        Consume the landing_ready_event payload.
        This triggers the engine's execution strategy.
        """
        pass

    def emit_traffic_event(self, event_type: str, data: dict):
        """
        Standard interface to emit traffic events.
        Enforces telemetry emission structure constraints.
        Forwards events safely to the EventBus via Orchestrator.
        """
        payload = data.copy()
        payload["traffic_source"] = self.channel_type
        
        # Events such as traffic_event_detected, conversion_detected, campaign_performance_event
        # are safely pushed to the bus using Orchestrator.
        self._orchestrator.receive_event(
            event_type=event_type,
            payload=payload
        )
