"""
radar/input_layer.py — Bloco 26 V2: Phase 1 Input Layer

Responsibilities:
  • Create RadarQuerySpec from raw parameters (assisted) or from system context (autonomous)
  • Validate all required domain and execution fields
  • Persist versioned query specs (append-only) BEFORE any collection
  • Define execution_mode (autonomous / assisted)

Constitutional constraints:
  - CANNOT collect data
  - CANNOT compute Emotional, Monetization, Growth, or Final scores
  - CANNOT access providers
  - CANNOT access StrategicOpportunityEngine
  - CANNOT modify system state
  - CANNOT alter financial state
  - CANNOT call Orchestrator directly
  - CANNOT bypass governance (Phase 0 runs before Phase 1)

All output is passed downstream to providers and dataset_snapshot.py.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from typing import Optional

from infrastructure.logger import get_logger
from radar.models.radar_query_spec import RadarQuerySpec, VALID_CATEGORIES

logger = get_logger("RadarInputLayer")

# ---------------------------------------------------------------------------
# Autonomous Mode — strategic direction selection
# ---------------------------------------------------------------------------
# The autonomous generator uses a deterministic, scoring-free heuristic to
# select a keyword/segment direction based on:
#   A) Historical cluster saturation (passed in context)
#   B) Growth trend indicators (passed in context)
#   C) Diversification from recent expansions
# It DOES NOT access providers, core, or financial state.
# ---------------------------------------------------------------------------

# Curated seed directions per category for autonomous mode
_AUTONOMOUS_SEED_DIRECTIONS = {
    "saas": [
        {
            "keyword": "client reporting automation",
            "segment": "SaaS agencies and consultancies",
            "publico": "Agency owners managing 5+ clients per month",
            "contexto": "Agencies spend 30% of their time on custom reporting",
            "problema_alvo": "Creating custom reports for each client is extremely time-consuming",
        },
        {
            "keyword": "meeting scheduling friction",
            "segment": "B2B SaaS sales teams",
            "publico": "SDRs and AEs at SMB/mid-market SaaS companies",
            "contexto": "Sales teams lose significant deal velocity to back-and-forth scheduling",
            "problema_alvo": "Manual scheduling loops cost deals and slow pipeline",
        },
        {
            "keyword": "customer churn prediction",
            "segment": "B2B SaaS founders and CS teams",
            "publico": "Customer success managers at SaaS with 100-1000 accounts",
            "contexto": "Reactive churn recovery is costly and often too late",
            "problema_alvo": "Identifying at-risk accounts before they cancel requires manual effort",
        },
    ],
    "info_product": [
        {
            "keyword": "freelancer pricing strategy",
            "segment": "Freelancers and independent consultants",
            "publico": "Freelancers earning under $5k/month wanting to escape hourly billing",
            "contexto": "Most freelancers undercharge and lack a systematic pricing approach",
            "problema_alvo": "No clear method for moving from hourly to value-based pricing",
        },
        {
            "keyword": "course creation bottleneck",
            "segment": "Creators and coaches with expertise to package",
            "publico": "Subject matter experts with 500+ followers wanting to monetize",
            "contexto": "Most creators struggle to move from idea to launched product",
            "problema_alvo": "Overwhelmed by production, technology, and launch complexity",
        },
    ],
    "service": [
        {
            "keyword": "onboarding documentation pain",
            "segment": "B2B service providers and SaaS companies",
            "publico": "Ops and CS leads at companies with 20+ new clients per month",
            "contexto": "Inconsistent onboarding leads to early churn",
            "problema_alvo": "Creating standardized, repeatable onboarding docs is painful",
        },
    ],
    "e_commerce": [
        {
            "keyword": "product returns management",
            "segment": "D2C e-commerce brands",
            "publico": "E-commerce founders with $500k+ annual revenue and scale issues",
            "contexto": "Returns eat margin and damage brand loyalty at scale",
            "problema_alvo": "Manual return workflows create CS overload and customer frustration",
        },
    ],
    "subscription": [
        {
            "keyword": "subscription fatigue cancellation",
            "segment": "Subscription box and SaaS founders",
            "publico": "Founders with monthly churn above 5% looking for retention solutions",
            "contexto": "Consumers are overwhelmed with subscriptions and cancelling more frequently",
            "problema_alvo": "Reducing involuntary and voluntary churn without deep discounting",
        },
    ],
    "marketplace": [
        {
            "keyword": "seller trust verification",
            "segment": "Marketplace operators and platform builders",
            "publico": "Platform founders with fraud or trust problems in their seller base",
            "contexto": "Marketplaces face high fraud and low buyer trust signals",
            "problema_alvo": "Verifying seller legitimacy without creating excessive friction",
        },
    ],
    "api_tool": [
        {
            "keyword": "API integration maintenance cost",
            "segment": "Developer tool companies and API-first startups",
            "publico": "Technical founders and platform teams managing 10+ third-party integrations",
            "contexto": "Third-party API changes break integrations constantly",
            "problema_alvo": "Keeping integrations alive as external APIs change without warning",
        },
    ],
    "course": [
        {
            "keyword": "online course completion rate",
            "segment": "Online educators and course platform operators",
            "publico": "Course creators with completion rates below 20%",
            "contexto": "Students buy courses but never finish them, reducing testimonials and referrals",
            "problema_alvo": "Driving student accountability and completion without constant manual nudging",
        },
    ],
}


def generate_autonomous_query_spec(
    context: dict,
    category: Optional[str] = None,
    sources: Optional[list] = None,
    days_back: int = 90,
    max_per_source: int = 100,
    min_occurrences: int = 50,
    tags: Optional[list] = None,
) -> RadarQuerySpec:
    """
    Phase 1 — Generate a RadarQuerySpec automatically from system context.

    Algorithm:
        A) Identify least-saturated category from recent_cluster_saturations
        B) Select seed direction for that category using growth context
        C) Apply diversification: skip directions used in recent_keywords
        D) Return fully-formed RadarQuerySpec(execution_mode="autonomous")

    Constitutional constraints:
        - DOES NOT access providers
        - DOES NOT access StrategicOpportunityEngine
        - DOES NOT compute Emotional/Monetization/Growth scores
        - Uses only the context dict passed in

    Args:
        context: System context dict. Recognized keys:
            recent_cluster_saturations: dict[str, float]  — category -> saturation 0.0-1.0
            recent_keywords: list[str]                    — keywords used in recent cycles
            growth_trends: dict[str, float]               — category -> growth rate
        category:        Optional override category (skips auto-selection)
        sources:         Data sources (default: 4 major platforms)
        days_back:       Signal lookback window (default 90)
        max_per_source:  Max signals per source (default 100)
        min_occurrences: Min occurrence threshold (default 50)
        tags:            Optional metadata tags

    Returns:
        RadarQuerySpec(execution_mode="autonomous")
    """
    saturations     = context.get("recent_cluster_saturations", {})
    recent_keywords = set(context.get("recent_keywords", []))
    growth_trends   = context.get("growth_trends", {})

    # A) Select category: if not provided, pick the one with lowest saturation
    if category is None:
        scored_cats = []
        for cat in VALID_CATEGORIES:
            sat    = saturations.get(cat, 0.5)
            growth = growth_trends.get(cat, 0.0)
            # Lower saturation + higher growth = better candidate
            score  = (1.0 - sat) + growth
            scored_cats.append((score, cat))
        scored_cats.sort(reverse=True)
        category = scored_cats[0][1]

    # B & C) Select direction for category, avoiding recently used keywords
    directions = _AUTONOMOUS_SEED_DIRECTIONS.get(category, [])
    if not directions:
        # Fallback: generic direction if no seeds for category
        directions = [{
            "keyword":       f"{category} process inefficiency",
            "segment":       f"{category} professionals",
            "publico":       f"Practitioners in the {category} space facing friction",
            "contexto":      f"Growing demand for better {category} tooling",
            "problema_alvo": f"Core {category} workflow lacks automation and consistency",
        }]

    # D) Diversification: prefer unused keywords
    # Use saturation-seeded determinism so repeated calls to same context are reproducible
    seed_str  = f"autonomous:{category}:{sorted(recent_keywords)}"
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:6], 16)

    available = [d for d in directions if d["keyword"] not in recent_keywords]
    if not available:
        available = directions  # all used → allow repeat

    direction = available[seed_hash % len(available)]

    spec = RadarQuerySpec(
        keyword        = direction["keyword"],
        category       = category,
        segment        = direction["segment"],
        publico        = direction["publico"],
        contexto       = direction["contexto"],
        problema_alvo  = direction["problema_alvo"],
        execution_mode = "autonomous",
        sources        = tuple(sources or ["reddit", "twitter", "quora", "hackernews"]),
        days_back      = days_back,
        max_per_source = max_per_source,
        min_occurrences= min_occurrences,
        tags           = tuple(tags or ["autonomous"]),
    )

    logger.info(
        f"[InputLayer:Autonomous] RadarQuerySpec generated. "
        f"event_id={spec.event_id} keyword='{spec.keyword}' "
        f"category='{spec.category}' segment='{spec.segment}'"
    )
    return spec


# ---------------------------------------------------------------------------
# Assisted Mode — human-provided input
# ---------------------------------------------------------------------------

def generate_assisted_query_spec(
    user_input: dict,
    sources: Optional[list] = None,
    days_back: int = 90,
    max_per_source: int = 100,
    min_occurrences: int = 50,
) -> RadarQuerySpec:
    """
    Phase 1 — Create a RadarQuerySpec from human-provided input.

    All domain fields are mandatory. Missing fields raise ValueError.
    operator_id is required (identifies the human operator).

    Args:
        user_input: dict with mandatory keys:
            keyword, category, segment, publico, contexto,
            problema_alvo, operator_id
            Optional: sources, days_back, max_per_source, min_occurrences, tags
        sources, days_back, max_per_source, min_occurrences:
            Override defaults (user_input values take precedence)

    Returns:
        RadarQuerySpec(execution_mode="assisted")

    Raises:
        ValueError if any mandatory field is missing or empty
    """
    MANDATORY_FIELDS = [
        "keyword", "category", "segment", "publico",
        "contexto", "problema_alvo", "operator_id",
    ]
    missing = [f for f in MANDATORY_FIELDS if not user_input.get(f, "").strip()]
    if missing:
        raise ValueError(
            f"[InputLayer:Assisted] Missing or empty required fields: {missing}. "
            f"All domain fields must be provided for assisted mode."
        )

    spec = RadarQuerySpec(
        keyword        = user_input["keyword"].strip(),
        category       = user_input["category"].strip(),
        segment        = user_input["segment"].strip(),
        publico        = user_input["publico"].strip(),
        contexto       = user_input["contexto"].strip(),
        problema_alvo  = user_input["problema_alvo"].strip(),
        execution_mode = "assisted",
        operator_id    = user_input["operator_id"].strip(),
        sources        = tuple(user_input.get("sources", None) or sources or
                               ["reddit", "twitter", "quora", "hackernews"]),
        days_back      = int(user_input.get("days_back", days_back)),
        max_per_source = int(user_input.get("max_per_source", max_per_source)),
        min_occurrences= int(user_input.get("min_occurrences", min_occurrences)),
        tags           = tuple(user_input.get("tags", ["assisted"])),
    )

    logger.info(
        f"[InputLayer:Assisted] RadarQuerySpec created. "
        f"event_id={spec.event_id} keyword='{spec.keyword}' "
        f"operator_id='{spec.operator_id}'"
    )
    return spec


# ---------------------------------------------------------------------------
# Legacy factory (backwards compatibility with callers using keyword+category)
# ---------------------------------------------------------------------------

def create_query_spec(
    keyword: str,
    category: str,
    execution_mode: str = "autonomous",
    sources: Optional[list] = None,
    days_back: int = 90,
    max_per_source: int = 100,
    min_occurrences: int = 50,
    operator_id: Optional[str] = None,
    tags: Optional[list] = None,
    segment: Optional[str] = None,
    publico: Optional[str] = None,
    contexto: Optional[str] = None,
    problema_alvo: Optional[str] = None,
) -> RadarQuerySpec:
    """
    Legacy factory: create a RadarQuerySpec from positional parameters.

    New code should use generate_autonomous_query_spec() or
    generate_assisted_query_spec(). This function fills domain fields
    with safe defaults if not supplied, to maintain backwards compatibility.
    """
    if sources is None:
        sources = ["reddit", "twitter", "quora", "hackernews"]
    if tags is None:
        tags = []

    spec = RadarQuerySpec(
        keyword        = keyword,
        category       = category,
        segment        = segment        or f"{category} professionals",
        publico        = publico        or f"Practitioners experiencing {keyword} pain",
        contexto       = contexto       or f"Radar triggered for '{keyword}' signal analysis",
        problema_alvo  = problema_alvo  or f"Identifying the core pain around '{keyword}'",
        execution_mode = execution_mode,
        sources        = tuple(sources),
        days_back      = days_back,
        max_per_source = max_per_source,
        min_occurrences= min_occurrences,
        operator_id    = operator_id,
        tags           = tuple(tags),
    )

    logger.info(
        f"[InputLayer] RadarQuerySpec created. "
        f"event_id={spec.event_id} keyword='{keyword}' "
        f"category='{category}' mode='{execution_mode}'"
    )
    return spec


# ---------------------------------------------------------------------------
# Persistence (append-only — must be called BEFORE any collection)
# ---------------------------------------------------------------------------

def persist_query_spec(
    spec: RadarQuerySpec,
    persistence_path: str = "radar_query_specs.jsonl",
) -> None:
    """
    Append-only persistence of a RadarQuerySpec.

    MUST be called BEFORE providers are invoked.
    Persists: event_id, timestamp, execution_mode, and full payload.

    Constitutional guarantee: append-only, never overwrites.
    """
    record = {
        "event_id":      spec.event_id,
        "timestamp":     spec.timestamp,
        "execution_mode": spec.execution_mode,
        "payload":       spec.to_dict(),
    }
    line = json.dumps(record, ensure_ascii=False)
    with open(persistence_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    logger.info(
        f"[InputLayer] QuerySpec persisted. "
        f"event_id={spec.event_id} mode={spec.execution_mode} "
        f"path={persistence_path}"
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def list_valid_categories() -> list:
    """Return all valid product categories for query spec construction."""
    return sorted(VALID_CATEGORIES)
