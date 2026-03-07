"""
api/routes/landing_routes.py — Serve generated landing pages.

Read-only. No engine modifications. No state writes.
Reads from infra/landing/landing_snapshots.jsonl.
"""
from flask import Blueprint, Response, jsonify
from infra.landing.landing_snapshot import load_snapshots

landing_bp = Blueprint("landing_routes", __name__)


@landing_bp.route("/landing/<product_id>", methods=["GET"])
def get_landing(product_id: str):
    """
    Serve the latest generated HTML landing for a given product_id.
    Returns 404 if no landing exists yet.
    """
    snapshots = load_snapshots()

    for snap in reversed(snapshots):
        if snap.get("product_id") == product_id:
            html = snap.get("html")
            if html:
                return Response(html, mimetype="text/html")

    return jsonify({
        "error":      "landing_not_found",
        "product_id": product_id,
    }), 404
