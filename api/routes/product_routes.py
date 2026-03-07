"""
api/routes/product_routes.py — Product inspection endpoints.

Read-only. No engine modifications. No state writes.
Reads from infra/landing/landing_snapshots.jsonl.
"""
from flask import Blueprint, jsonify
from infra.landing.landing_snapshot import load_snapshots

product_bp = Blueprint("product_routes", __name__)


@product_bp.route("/products", methods=["GET"])
def list_products():
    """Return deduplicated list of all known products (latest snapshot per product)."""
    snapshots = load_snapshots()

    products: dict = {}
    for snap in snapshots:
        pid = snap.get("product_id")
        if not pid:
            continue
        # Last write wins — latest snapshot is authoritative
        products[pid] = {
            "product_id": pid,
            "cluster_id": snap.get("cluster_id"),
            "score":      snap.get("score"),
            "version":    snap.get("version"),
            "created_at": snap.get("created_at") or snap.get("timestamp"),
        }

    return jsonify(list(products.values()))


@product_bp.route("/products/<product_id>", methods=["GET"])
def get_product(product_id: str):
    """Return the latest snapshot metadata for a given product_id."""
    snapshots = load_snapshots()

    for snap in reversed(snapshots):
        if snap.get("product_id") == product_id:
            return jsonify({
                "product_id": product_id,
                "cluster_id": snap.get("cluster_id"),
                "score":      snap.get("score"),
                "version":    snap.get("version"),
                "created_at": snap.get("created_at") or snap.get("timestamp"),
            })

    return jsonify({
        "error":      "product_not_found",
        "product_id": product_id,
    }), 404
