import os
import threading
import logging
from infrastructure.logger import get_logger
from orchestrator import start_system

logger = get_logger("WorkerManager")

# Setup safe file logging for WorkerManager
os.makedirs("logs", exist_ok=True)
fh = logging.FileHandler("logs/runtime_events.log", encoding="utf-8")
fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] [%(message)s]"))
logger.addHandler(fh)

class WorkerManager:
    """
    Manages task execution and prevents overlapping pipeline runs.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(WorkerManager, cls).__new__(cls)
                cls._instance._is_running = False
                cls._instance._mutex = threading.Lock()
            return cls._instance

    def run_pipeline_cycle(self) -> dict:
        """
        Attempts to run a full pipeline cycle.
        Returns early if a cycle is already running.
        """
        if not self._mutex.acquire(blocking=False):
            logger.warning("[WorkerManager] A cycle is already running. Skipping overlapping execution.")
            return {"status": "SKIPPED_OVERLAP", "details": "Pipeline is already in progress."}

        self._is_running = True
        logger.info("[WorkerManager] Acquired lock. Starting pipeline cycle.")
        try:
            # Delegate to the orchestrator we built earlier
            results = start_system()
            return results
        except Exception as e:
            logger.error(f"[WorkerManager] Exception during pipeline cycle: {e}")
            return {"status": "ERROR", "details": str(e)}
        finally:
            self._is_running = False
            self._mutex.release()
            logger.info("[WorkerManager] Released lock. Pipeline cycle finished.")

    def is_currently_running(self) -> bool:
        return self._is_running

