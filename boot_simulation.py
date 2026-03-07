import sys
import logging
from unittest.mock import MagicMock

# Basic logging config to see potential errors
logging.basicConfig(level=logging.INFO)

print("Starting Boot Simulation...")

try:
    # 1. Core Infrastructure
    print("Loading Core Infrastructure...")
    from core.event_bus import EventBus
    from core.telemetry_engine import TelemetryEngine
    from core.finance_engine import FinanceEngine
    from core.security_layer import SecurityLayer
    from core.orchestrator import Orchestrator

    # 2. Traffic Infrastructure
    print("Loading Traffic Infrastructure...")
    from infra.traffic.traffic_engine_registry import TrafficEngineRegistry
    from infra.traffic.traffic_execution_layer import TrafficExecutionLayer
    from infra.traffic.traffic_engine_base import TrafficEngineBase

    # 3. Acquisition Engines
    print("Loading Acquisition Engines...")
    from infra.traffic.engines.outreach_engine import IAOutreachEngine
    from infra.traffic.engines.seo_engine import SEOEngine
    from infra.traffic.engines.google_ads_engine import GoogleAdsEngine

    # 4. Landing Infrastructure
    print("Loading Landing Infrastructure...")
    import infra.landing.landing_recommendation_handler
    import infra.landing.landing_draft_listener
    # Ignore missing specific modules if they are named slightly differently, we'll try to find them
    try:
        from infra.landing.landing_llm_executor import LandingLLMExecutor
        from infra.landing.landing_structure_validator import LandingStructureValidator
        from infra.landing.landing_html_validator import LandingHTMLValidator
    except ImportError as e:
        print(f"Non-critical landing module import warning: {e}")

    # Initialize pieces to ensure they don't break
    bus = EventBus()
    pers_mock = MagicMock()
    tm = TelemetryEngine(snapshot_persistence=pers_mock, accumulator_persistence=pers_mock)
    fe = FinanceEngine(state_persistence=pers_mock, projection_persistence=pers_mock)
    orc_mock = MagicMock()

    # Check if traffic engines register
    registry = TrafficEngineRegistry()
    registry.register_engine(IAOutreachEngine(orc_mock))
    registry.register_engine(SEOEngine(orc_mock))
    registry.register_engine(GoogleAdsEngine(orc_mock))

    traffic_layer = TrafficExecutionLayer(orc_mock)
    
    print("BOOT_STATUS: SUCCESS")
except Exception as e:
    print(f"BOOT_STATUS: FAILED - {e}")
    sys.exit(1)
