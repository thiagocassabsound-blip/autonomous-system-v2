"""
infra/system/product_gc.py — Product garbage collector for Etapa 2.6.

Identifies landing snapshots older than ARCHIVE_RETENTION_DAYS and emits
product_purge_event for each. Never deletes ledger records.

Preserved permanently per product:
  - product_id
  - cluster_id
  - historical scores (snapshot header)

Constitutional guarantees:
  - No state.json access
  - No StateMachine calls
  - Events via orchestrator.receive_event()
  - Never deletes ledger records
  - Never raises
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("infra.system.product_gc")

# ── Configuration ─────────────────────────────────────────────────────────────
ARCHIVE_RETENTION_DAYS = int(os.getenv("ARCHIVE_RETENTION_DAYS", "365"))

# ── Snapshot path resolution (mirrors landing_snapshot.py) ────────────────────
_DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data"

def _resolve_snapshot_path(override: Optional[Path] = None) -> Path:
    if override:
        return override
    env = os.getenv("LANDING_SNAPSHOT_PATH")
    if env:
        return Path(env)
    return _DEFAULT_SNAPSHOT_DIR / "landing_snapshots.jsonl"


# ── Public API ────────────────────────────────────────────────────────────────

def run_product_gc(
    orchestrator,
    snapshot_path: Optional[Path] = None,
    dry_run: bool = False,
) -> dict:
    """
    Scan landing_snapshots.jsonl and emit product_purge_event for each
    record whose creation timestamp exceeds ARCHIVE_RETENTION_DAYS.

    Args:
        orchestrator:   Orchestrator instance (for receive_event)
        snapshot_path:  Override path to JSONL (for testing)
        dry_run:        If True, log but do not emit events

    Returns:
        {
          "checked":  int,       # total records scanned
          "purged":   int,       # records marked for purge
          "skipped":  int,       # too young or malformed
          "errors":   int,       # parse errors
        }
    Never raises.
    """
    path    = _resolve_snapshot_path(snapshot_path)
    cutoff  = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_RETENTION_DAYS)
    stats   = {"checked": 0, "purged": 0, "skipped": 0, "errors": 0}
    seen_product_ids: set[str] = set()

    if not path.exists():
        logger.info("[ProductGC] Snapshot file not found at %s — nothing to collect.", path)
        return stats

    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except Exception as exc:
        logger.error("[ProductGC] Failed to read snapshot file: %s", exc)
        return stats

    logger.info("[ProductGC] Starting GC scan. path=%s retention_days=%d",
                path, ARCHIVE_RETENTION_DAYS)

    for raw in lines:
        if not raw.strip():
            continue
        stats["checked"] += 1

        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            stats["errors"] += 1
            continue

        product_id = rec.get("product_id", "")
        cluster_id = rec.get("cluster_id", "")
        created_at = rec.get("created_at") or rec.get("timestamp", "")

        if not product_id or not created_at:
            stats["skipped"] += 1
            continue

        # Parse creation timestamp
        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            stats["skipped"] += 1
            continue

        # Check age
        if ts >= cutoff:
            stats["skipped"] += 1
            continue

        age_days = (datetime.now(timezone.utc) - ts).days

        # Deduplicate — only purge each product_id once
        if product_id in seen_product_ids:
            stats["skipped"] += 1
            continue
        seen_product_ids.add(product_id)

        stats["purged"] += 1
        logger.info(
            "[ProductGC] %s product_id=%s cluster_id=%s age_days=%d",
            "DRY_RUN" if dry_run else "PURGE",
            product_id, cluster_id, age_days,
        )

        if dry_run:
            continue

        # Emit purge event — history stays in ledger, never deleted
        try:
            orchestrator.receive_event(
                event_type="product_purge_event",
                payload={
                    "product_id":     product_id,
                    "cluster_id":     cluster_id,
                    "age_days":       age_days,
                    "retention_days": ARCHIVE_RETENTION_DAYS,
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.error("[ProductGC] Failed to emit purge event for %s: %s",
                         product_id, exc)

    logger.info("[ProductGC] Scan complete. checked=%d purged=%d skipped=%d errors=%d",
                stats["checked"], stats["purged"], stats["skipped"], stats["errors"])
    return stats
