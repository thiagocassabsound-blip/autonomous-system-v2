"""
infra/landing/landing_versioning.py — Version computation for Bloco 30.

Version rule:
    version = count of existing records in JSONL for cluster_id + 1

Version starts at 1 for the first landing.
Subsequent regenerations increment the version.
Previous HTML is never overwritten.
"""
from __future__ import annotations

from infra.landing.landing_snapshot import load_snapshots


def compute_version(cluster_id: str) -> int:
    """
    Compute the next version number for a given cluster_id.
    Counts existing snapshot records for the cluster and adds 1.

    Returns 1 if no prior records exist.
    """
    snapshots = load_snapshots()
    count = sum(1 for s in snapshots if s.get("cluster_id") == cluster_id)
    return count + 1
