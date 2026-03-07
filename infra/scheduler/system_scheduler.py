import time
import threading
import sys
import os

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from core.event_bus import EventBus
from infra.observability.async_worker import AsyncLogWorker

class SystemScheduler:
    """
    Centralized event-driven scheduler.
    Emits lifecycle ticks over the EventBus natively.
    Never mutates state directly.
    """
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.running = False
        self.threads = []
        
        # Schedule configuration (in seconds)
        self.intervals = {
            "radar_scan": 3600,         # 1 hour
            "telemetry_agg": 300,       # 5 minutes
            "intelligence_loop": 600,   # 10 minutes
            "strategy_memory": 900,     # 15 minutes
            "infra_health": 3600,       # 1 hour
            "rss_trigger": 7200         # 2 hours
        }

    def _loop(self, task_name, interval, event_name, payload):
        while self.running:
            time.sleep(interval)
            if not self.running:
                break
            self.event_bus.emit(event_name, payload)
            
    def start(self):
        self.running = True
        
        # 1. Radar Scans
        t1 = threading.Thread(
            target=self._loop, 
            args=("Radar", self.intervals["radar_scan"], "scheduler_radar_scan_tick", {"source": "scheduler"}),
            daemon=True
        )
        # 2. Telemetry
        t2 = threading.Thread(
            target=self._loop, 
            args=("Telemetry", self.intervals["telemetry_agg"], "scheduler_telemetry_tick", {"source": "scheduler"}),
            daemon=True
        )
        # 3. Operational Intelligence
        t3 = threading.Thread(
            target=self._loop, 
            args=("Intelligence", self.intervals["intelligence_loop"], "scheduler_intelligence_tick", {"source": "scheduler"}),
            daemon=True
        )
        # 4. Strategy Memory Persistence
        t4 = threading.Thread(
            target=self._loop, 
            args=("Strategy", self.intervals["strategy_memory"], "scheduler_strategy_tick", {"source": "scheduler"}),
            daemon=True
        )
        # 5. Infrastructure Health Monitor
        t5 = threading.Thread(
            target=self._loop, 
            args=("InfraHealth", self.intervals["infra_health"], "scheduler_infra_health_tick", {"source": "scheduler"}),
            daemon=True
        )
        # 6. RSS Trigger
        t6 = threading.Thread(
            target=self._loop, 
            args=("RSSTrigger", self.intervals["rss_trigger"], "rss_signal_collection_requested", {"source": "scheduler"}),
            daemon=True
        )
        
        self.threads = [t1, t2, t3, t4, t5, t6]
        for t in self.threads:
            t.start()
            
        self.event_bus.emit("scheduler_started", {"intervals": self.intervals})

    def stop(self):
        self.running = False
        self.event_bus.emit("scheduler_stopped", {})

if __name__ == "__main__":
    print("Initializing Autonomous System Scheduler (Simulation Mode)...")
    bus = EventBus()
    logger = AsyncLogWorker()
    logger.start()
    
    # Mount logging
    bus.subscribe("scheduler_started", lambda payload: print(f"[SCHEDULER] Started intervals -> {payload}"))
    bus.subscribe("scheduler_radar_scan_tick", lambda payload: print("[SCHEDULER] Emitted Radar Scan Tick"))
    bus.subscribe("scheduler_telemetry_tick", lambda payload: print("[SCHEDULER] Emitted Telemetry Tick"))
    
    scheduler = SystemScheduler(bus)
    scheduler.start()
    
    try:
        time.sleep(2)
        print("[OK] Scheduler daemon loops active. Shutting down test run.")
    finally:
        scheduler.stop()
        logger.stop()
