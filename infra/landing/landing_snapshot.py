"""
infra/landing/landing_snapshot.py — Append-only snapshot persistence for Bloco 30.

Constitutional guarantees:
  - Nunca altera state.json
  - Nunca sobrescreve registros existentes
  - Somente append no JSONL
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("infra.landing.snapshot")

_DEFAULT_PATH = Path("infra/landing/landing_snapshots.jsonl")


def _snapshot_path() -> Path:
    custom = os.environ.get("LANDING_SNAPSHOT_PATH")
    return Path(custom) if custom else _DEFAULT_PATH


def append_snapshot(
    *,
    event_id: str,
    product_id: str,
    cluster_id: str,
    prompt_hash: str,
    model_used: str,
    latency_ms: int,
    validation_passed: bool,
    html_hash: str,
    version: int,
    timestamp: Optional[str] = None,
) -> dict:
    """
    Append one snapshot record to landing_snapshots.jsonl.
    Returns the record dict. Never raises (catches and logs exceptions).
    """
    record = {
        "event_id":          event_id,
        "product_id":        product_id,
        "cluster_id":        cluster_id,
        "prompt_hash":       prompt_hash,
        "model_used":        model_used,
        "latency_ms":        int(latency_ms),
        "validation_passed": bool(validation_passed),
        "html_hash":         html_hash,
        "version":           int(version),
        "timestamp":         timestamp or datetime.now(timezone.utc).isoformat(),
    }
    path = _snapshot_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            "[LandingSnapshot] Appended product_id=%s cluster_id=%s version=%d",
            product_id, cluster_id, version,
        )
    except Exception as exc:
        logger.error("[LandingSnapshot] Failed to write snapshot: %s", exc)
    return record


def load_snapshots() -> list[dict]:
    """
    Load all snapshot records from the JSONL file.
    Returns an empty list if the file does not exist or is corrupt.
    """
    path = _snapshot_path()
    records: list[dict] = []
    if not path.exists():
        return records
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "[LandingSnapshot] Skipping corrupt line %d: %s", i, exc
                    )
    except Exception as exc:
        logger.error("[LandingSnapshot] Failed to read snapshots: %s", exc)
    return records


def build_cluster_index(snapshots: list[dict]) -> dict[str, str]:
    """
    Build {cluster_id: product_id} index from snapshot list.
    In case of multiple records for the same cluster_id, the last one wins.
    """
    index: dict[str, str] = {}
    for rec in snapshots:
        cid = rec.get("cluster_id", "")
        pid = rec.get("product_id", "")
        if cid and pid:
            index[cid] = pid
    return index
