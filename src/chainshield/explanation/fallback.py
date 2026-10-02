from __future__ import annotations

"""
ChainShield Deterministic Explanation Fallback
===============================================

Generates human-readable explanations from already-computed, already-authorised
structured decision/evidence data.  No LLM, no network, no external API.

Used when:
  - WATSONX_ENABLED=false (default offline/demo mode), OR
  - The watsonx.ai call exceeds its 2.5 s timeout budget.

Design rules (from AGENTS.md / preflight_demo.py):
  - The deterministic operational result is always the source of truth.
  - Never invent routes, assets, temperatures, dates, or facts.
  - Output is deterministic for identical inputs (no randomness, no timestamps
    in the body, no UUIDs).
  - reason_codes, evidence, affected shipment, recommended action, and
    uncertainty/limitations are all preserved verbatim from the input decision.
  - ``generated_by`` is always ``"deterministic_fallback_template"`` so
    consumers can distinguish this path from a real Granite/watsonx.ai call.
  - Supports three decision kinds: ``impact``, ``routing``, ``cold_chain``.
    Unknown kinds still produce a valid schema-complete output with a clear
    limitation notice.
"""

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Decision kind constants  (extend as new engines are added)
# ---------------------------------------------------------------------------

KIND_IMPACT: str = "impact"
KIND_ROUTING: str = "routing"
KIND_COLD_CHAIN: str = "cold_chain"

_KNOWN_KINDS: frozenset[str] = frozenset({KIND_IMPACT, KIND_ROUTING, KIND_COLD_CHAIN})

# Cold-chain statuses that require a manual-review uncertainty note
_COLD_CHAIN_REVIEW_STATUSES: frozenset[str] = frozenset(
    {"EXCURSION_REVIEW", "URGENT_ESCALATION", "POLICY_REQUIRED"}
)

# ---------------------------------------------------------------------------
# Public output type
# ---------------------------------------------------------------------------


@dataclass
class FallbackExplanation:
    """Schema-complete explanation produced by the deterministic fallback.

    All fields map 1-to-1 with the ``{summary, why_affected,
    recommended_action, evidence, uncertainties}`` contract required by
    preflight check CHK-5 and the Evidence Drawer in the frontend.
    """

    summary: str
    why_affected: list[str]
    recommended_action: str
    evidence: list[str]
    uncertainties: list[str]
    generated_by: str = "deterministic_fallback_template"
    model_used: None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict (JSON-serialisable, no dataclass overhead)."""
        return {
            "summary": self.summary,
            "why_affected": self.why_affected,
            "recommended_action": self.recommended_action,
            "evidence": self.evidence,
            "uncertainties": self.uncertainties,
            "generated_by": self.generated_by,
            "model_used": self.model_used,
        }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------


def generate_fallback_explanation(decision: dict[str, Any]) -> dict[str, Any]:
    """Generate a deterministic explanation dict from a structured decision.

    Parameters
    ----------
    decision:
        Structured result from a ChainShield deterministic engine.  Expected
        keys (all optional — missing keys produce safe default text):

        ``shipment_id``   str   – affected shipment identifier
        ``disruption``    str   – disruption event identifier or label
        ``kind``          str   – one of ``"impact"``, ``"routing"``,
                                  ``"cold_chain"``; defaults to ``"impact"``
        ``reason_codes``  list[str] – SCREAMING_SNAKE_CASE codes from the engine
        ``evidence``      list[str] | list[dict] – source references / audit
                          links; if omitted, reason_codes are used as evidence
        ``recommended_action`` str – pre-computed action text; if present it is
                          preserved verbatim (the fallback never rewrites it)
        ``recommended_route``  dict – routing engine output
            ``carrier``              str
            ``eta_delta_hours``      float
            ``additional_cost_usd``  float
        ``cold_chain``    dict – cold-chain engine output
            ``status``           str
            ``max_celsius``      float
            ``policy_max_celsius`` float
            ``duration_minutes`` int

    Returns
    -------
    dict with keys: summary, why_affected, recommended_action, evidence,
    uncertainties, generated_by, model_used.
    """
    kind: str = decision.get("kind", KIND_IMPACT)
    shipment_id: str = decision.get("shipment_id", "UNKNOWN")
    disruption: str = decision.get("disruption", "an unspecified disruption")
    reason_codes: list[str] = list(decision.get("reason_codes", []))

    # evidence: caller may pass explicit evidence refs; fall back to reason codes
    raw_evidence = decision.get("evidence", reason_codes)
    if isinstance(raw_evidence, list):
        evidence: list[str] = [str(e) for e in raw_evidence] if raw_evidence else list(reason_codes)
    else:
        evidence = list(reason_codes)

    # Always include reason codes in evidence so they are never lost
    for code in reason_codes:
        if code not in evidence:
            evidence.append(code)

    # --- why_affected -------------------------------------------------------
    why_affected: list[str] = [f"Flagged due to {code}" for code in reason_codes]
    if not why_affected:
        why_affected = ["No reason codes provided by the deterministic engine."]

    # --- recommended_action --------------------------------------------------
    # If the caller already encoded a recommended action, preserve it verbatim.
    recommended_action: str = _build_recommended_action(decision)

    # --- uncertainties -------------------------------------------------------
    uncertainties: list[str] = _build_uncertainties(decision, kind)

    # --- summary -------------------------------------------------------------
    summary: str = _build_summary(decision, shipment_id, disruption, kind)

    explanation = FallbackExplanation(
        summary=summary,
        why_affected=why_affected,
        recommended_action=recommended_action,
        evidence=evidence,
        uncertainties=uncertainties,
    )
    return explanation.to_dict()


# ---------------------------------------------------------------------------
# Private helpers  (no external state, fully deterministic)
# ---------------------------------------------------------------------------


def _build_summary(
    decision: dict[str, Any],
    shipment_id: str,
    disruption: str,
    kind: str,
) -> str:
    if kind == KIND_COLD_CHAIN:
        cold_chain = decision.get("cold_chain", {})
        status = cold_chain.get("status", "UNKNOWN")
        return (
            f"{shipment_id} has a cold-chain status of {status} "
            f"during {disruption}."
        )
    if kind == KIND_ROUTING:
        route = decision.get("recommended_route", {})
        carrier = route.get("carrier", "no carrier identified")
        return (
            f"{shipment_id} requires rerouting due to {disruption}; "
            f"best available carrier: {carrier}."
        )
    # default / impact
    return f"{shipment_id} is affected by {disruption}."


def _build_recommended_action(decision: dict[str, Any]) -> str:
    # Verbatim caller-supplied action takes absolute precedence
    if "recommended_action" in decision and decision["recommended_action"]:
        return str(decision["recommended_action"])

    route = decision.get("recommended_route", {})
    cold_chain = decision.get("cold_chain", {})

    if route:
        carrier = route.get("carrier", "unknown carrier")
        eta_delta = route.get("eta_delta_hours", "?")
        cost_delta = route.get("additional_cost_usd", "?")
        return (
            f"Reroute via {carrier}: "
            f"+{eta_delta}h, "
            f"+${cost_delta} vs. current plan."
        )

    if cold_chain:
        status = cold_chain.get("status", "")
        if status in _COLD_CHAIN_REVIEW_STATUSES:
            return (
                f"Cold-chain status is {status}. "
                "Initiate manual temperature excursion review before disposition."
            )

    return "No feasible route alternative was found within hard constraints."


def _build_uncertainties(decision: dict[str, Any], kind: str) -> list[str]:
    uncertainties: list[str] = []

    cold_chain = decision.get("cold_chain", {})
    route = decision.get("recommended_route", {})

    if cold_chain.get("status") in _COLD_CHAIN_REVIEW_STATUSES:
        uncertainties.append(
            f"Cold-chain status is {cold_chain['status']}; "
            "requires manual review before disposition."
        )

    if not route and kind in {KIND_IMPACT, KIND_ROUTING}:
        uncertainties.append(
            "Route recommendation unavailable; operator judgment required."
        )

    if kind not in _KNOWN_KINDS:
        uncertainties.append(
            f"Decision kind '{kind}' is not recognised; "
            "explanation may be incomplete."
        )

    return uncertainties
