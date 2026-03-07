"""
infra/landing/landing_prompt_builder.py — Deterministic prompt constructor for Bloco 30.

Characteristics:
  - No LLM calls
  - No external I/O
  - Fully deterministic — same input always produces same output
  - Structured prompt that drives landing page generation
"""
from __future__ import annotations


def build_prompt(
    *,
    icp: str,
    strategy: str,
    justification_summary: str,
    emotional_score: float,
    monetization_score: float,
) -> str:
    """
    Build a structured, deterministic LLM prompt for landing page generation.

    Returns a plain-text prompt string.
    Does not call any LLM. Does not mutate state.
    """
    emotional_label = (
        "muito alta" if emotional_score >= 85 else
        "alta" if emotional_score >= 70 else
        "moderada"
    )
    monetization_label = (
        "muito alta" if monetization_score >= 85 else
        "alta" if monetization_score >= 70 else
        "moderada"
    )

    prompt = f"""You are an expert direct-response copywriter and HTML developer.

Create a complete, high-converting landing page in valid HTML for the following product opportunity.

TARGET AUDIENCE (ICP):
{icp.strip()}

POSITIONING STRATEGY:
{strategy.strip()}

JUSTIFICATION SUMMARY:
{justification_summary.strip()}

SIGNAL CONTEXT:
- Emotional resonance: {emotional_label} ({emotional_score:.1f}/100)
- Monetization potential: {monetization_label} ({monetization_score:.1f}/100)

MANDATORY REQUIREMENTS:
1. Return ONLY the complete HTML document — no markdown, no explanations, no code fences.
2. Include a single <h1> headline that communicates the core transformation in one sentence.
3. Include a <h2> subheadline that expands on the promise.
4. Include exactly one call-to-action button with id="checkout-btn".
5. Include at least 3 benefit bullet points that are specific, not generic.
6. Include a clear price section (use placeholder $97 if no price is specified).
7. No placeholder text like [INSERT], [YOUR NAME], [PRODUCT NAME].
8. The page must be self-contained, with inline CSS styling.
9. No external scripts, no tracking pixels, no iframe.
10. The offer must be clear within 5 seconds of reading.

OUTPUT: Valid HTML only. Start with <!DOCTYPE html>.
"""
    return prompt.strip()
