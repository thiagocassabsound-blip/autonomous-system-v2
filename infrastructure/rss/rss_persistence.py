import os
import json
import logging

logger = logging.getLogger("rss_persistence")

LEDGER_PATH = os.path.join(os.getcwd(), "data", "rss_signal_ledger.jsonl")

class RSSPersistence:
    @staticmethod
    def _ensure_file():
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        if not os.path.exists(LEDGER_PATH):
            with open(LEDGER_PATH, 'w', encoding='utf-8') as f:
                pass
                
    @staticmethod
    def is_duplicate(url, title):
        """Idempotency check: verify if URL or Title already exists in ledger."""
        RSSPersistence._ensure_file()
        try:
            with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        record = json.loads(line)
                        if record.get("url") == url or record.get("title") == title:
                            return True
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error reading RSS ledger: {e}")
        return False

    @staticmethod
    def record_signal(rss_signal):
        """Append-only persistence for RSS signals."""
        RSSPersistence._ensure_file()
        try:
            with open(LEDGER_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rss_signal) + "\n")
        except Exception as e:
            logger.error(f"Failed to record RSS signal: {e}")
