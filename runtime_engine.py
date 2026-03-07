import os
import time
import json
import threading
import logging
import datetime
from infrastructure.logger import get_logger
from infrastructure.db import JsonFilePersistence
from worker_manager import WorkerManager

logger = get_logger("RuntimeEngine")

# Setup safe file logging for RuntimeEngine
os.makedirs("logs", exist_ok=True)
fh = logging.FileHandler("logs/runtime_events.log", encoding="utf-8")
fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] [%(message)s]"))
logger.addHandler(fh)

class RuntimeEngine:
    """
    Controls the continuous loop execution of the system pipeline.
    Runs in a background daemon thread to avoid blocking the Flask main thread.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(RuntimeEngine, cls).__new__(cls)
                cls._instance._active = False
                cls._instance._thread = None
                cls._instance._worker = WorkerManager()
                cls._instance._interval_seconds = 60  # Configurable cycle interval
                cls._instance._state_persistence = JsonFilePersistence("data/runtime_state.json")
                cls._instance._load_state()
            return cls._instance

    def _load_state(self):
        self._state = self._state_persistence.load() or {}
        self._state.setdefault("runtime_running", False)
        self._state.setdefault("interval", self._interval_seconds)
        self._state.setdefault("last_cycle_time", None)
        self._state.setdefault("last_successful_cycle", None)
        self._state.setdefault("last_error", None)
        self._state.setdefault("cycle_count", 0)
        self._state.setdefault("last_pain_analysis", None)
        self._state.setdefault("last_pricing_test", None)
        self._state.setdefault("pricing_experiment_active", False)

    def _save_state(self):
        self._state["interval"] = self._interval_seconds
        self._state["runtime_running"] = self._active
        self._state_persistence.save(self._state)

    def set_interval(self, seconds: int):
        self._interval_seconds = seconds
        self._save_state()

    def start(self):
        """Starts the autonomous runtime loop if not already running."""
        with self._lock:
            if self._active:
                logger.warning("Runtime is already active.")
                return False
            
            self._active = True
            self._save_state()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info(f"[RuntimeEngine] Autonomous runtime engine started. Interval={self._interval_seconds}s.")
            return True

    def stop(self):
        """Safely signals the runtime loop to stop."""
        with self._lock:
            if not self._active:
                logger.warning("Runtime is not currently active.")
                return False
            
            self._active = False
            self._save_state()
            logger.info("Autonomous runtime engine stop signal issued.")
            return True

    def _run_loop(self):
        """
        The infinite background execution cycle.
        """
        while self._active:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            logger.info(f"CYCLE START -> Triggering execution cycle #{self._state['cycle_count'] + 1}...")
            
            self._state["last_cycle_time"] = now_iso
            self._save_state()

            results = self._worker.run_pipeline_cycle()
            
            # Evaluate results
            if results.get("status") == "COMPLETED":
                run_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self._state["last_successful_cycle"] = run_time
                self._state["last_pain_analysis"] = run_time
                self._state["last_pricing_test"] = run_time
                # Check specifics from pipeline dict if needed, else assume done
                self._state["cycle_count"] += 1
                self._state["last_error"] = None
                logger.info("CYCLE END -> Pipeline executed successfully.")
            elif results.get("status") == "ERROR":
                err_msg = results.get("details", "Unknown Error")
                self._state["last_error"] = err_msg
                logger.error(f"CYCLE ERROR -> Pipeline failed: {err_msg}")
            
            self._save_state()
            
            # Sleep in small increments to allow for quick interruption upon stop
            slept = 0
            while slept < self._interval_seconds and self._active:
                time.sleep(1)
                slept += 1
                
        logger.info("Runtime thread terminated gracefully.")

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def get_status(self) -> dict:
        self._state["interval"] = self._interval_seconds
        self._state["runtime_running"] = self._active
        return self._state

# Singleton exposed externally
runtime_engine = RuntimeEngine()
