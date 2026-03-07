import os
import threading
import queue
import json

class AsyncLogWorker:
    """
    Singleton background worker for handling disk writes asynchronously.
    Ensures that observability layer never blocks EventBus execution.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AsyncLogWorker, cls).__new__(cls)
                cls._instance._queue = queue.Queue()
                # Run as daemon so it shuts down naturally with the main process
                cls._instance._thread = threading.Thread(target=cls._instance._worker_loop, daemon=True)
                cls._instance._thread.start()
            return cls._instance

    def _worker_loop(self):
        while True:
            try:
                filepath, entry = self._queue.get()
                if filepath is None:
                    break
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception:
                pass  # Passive observability must never crash the thread
            finally:
                self._queue.task_done()

    def push(self, filepath: str, entry: dict):
        """
        Pushes a log entry immediately into the async buffer queue.
        """
        self._queue.put((filepath, entry))
