import threading
import time
from infrastructure.logger import get_logger

logger = get_logger("Scheduler")


class Scheduler:
    """
    Controlled execution loop. Emits 'cycle_tick' every 2 seconds.
    Supports start() and stop().
    """

    def __init__(self, event_bus, interval: float = 2.0):
        self.bus = event_bus
        self.interval = interval
        self._running = False
        self._thread: threading.Thread = None
        self._tick_count = 0

    def start(self):
        if self._running:
            logger.warning("Scheduler is already running.")
            return

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"Scheduler started (interval={self.interval}s).")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
        logger.info("Scheduler stopped.")

    def _loop(self):
        while self._running:
            time.sleep(self.interval)
            if not self._running:
                break

            self._tick_count += 1
            self.bus.emit("cycle_tick", {"tick": self._tick_count})
            logger.info(f"Cycle tick #{self._tick_count}")
