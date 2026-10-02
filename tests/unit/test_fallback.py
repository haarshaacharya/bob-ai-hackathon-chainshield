from __future__ import annotations

"""
Unit tests for src/chainshield/explanation/fallback.py

Seven focused scenarios:
  1. Deterministic identical output   – two calls with the same input produce
                                        byte-identical dicts.
  2. Reason codes preserved           – all input reason_codes appear in
                                        evidence and why_affected.
  3. Evidence preserved               – explicit evidence list is carried
                                        verbatim into the output.
  4. Recommended action preserved     – a caller-supplied recommended_action
                                        is never rewritten.
  5. Uncertainties preserved          – cold-chain and no-route paths generate
                                        the expected uncertainty notices.
  6. No fabricated facts              – the output contains no strings that
                                        were not derived from the input.
  7. WATSONX_ENABLED=false fallback   – generated_by is always the template
                                        sentinel, model_used is always None.
"""

import copy

import pytest

from src.chainshield.explanation.fallback import (
    KIND_COLD_CHAIN,
    KIND_IMPACT,
    KIND_ROUTING,
    generate_fallback_explanation,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FULL_IMPACT_DECISION: dict = {
    "kind": KIND_IMPACT,
    "shipment_id": "SHP-0042",
    "disruption": "PORT_STRIKE_01",
    "reason_codes": ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
    "recommended_route": {
        "carrier": "Carrier B",
        "eta_delta_hours": 5.4,
        "additional_cost_usd": 1800,
    },
    "cold_chain": {
        "status": "EXCURSION_REVIEW",
        "max_celsius": 10.4,
        "policy_max_celsius": 8.0,
        "duration_minutes": 18,
    },
}

ROUTING_DECISION: dict = {
    "kind": KIND_ROUTING,
    "shipment_id": "SHP-0099",
    "disruption": "RAIL_CLOSURE_07",
    "reason_codes": ["ROUTE_CAPACITY_EXCEEDED"],
    "recommended_route": {
        "carrier": "Carrier C",
        "eta_delta_hours": 2.0,
        "additional_cost_usd": 450,
    },
    "cold_chain": {},
}

COLD_CHAIN_DECISION: dict = {
    "kind": KIND_COLD_CHAIN,
    "shipment_id": "SHP-0042",
    "disruption": "AMBIENT_TEMP_SPIKE",
    "reason_codes": ["TEMPERATURE_EXPOSURE_INCREASED"],
    "recommended_route": {},
    "cold_chain": {
        "status": "EXCURSION_REVIEW",
        "max_celsius": 10.4,
        "policy_max_celsius": 8.0,
        "duration_minutes": 18,
    },
}

NO_ROUTE_DECISION: dict = {
    "kind": KIND_IMPACT,
    "shipment_id": "SHP-0077",
    "disruption": "TYPHOON_CLOSURE",
    "reason_codes": ["PORT_NODE_BLOCKED"],
    "recommended_route": {},
    "cold_chain": {},
}


# ---------------------------------------------------------------------------
# 1. Deterministic identical output
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_input_produces_same_output(self) -> None:
        """Two independent calls with an identical input dict must return
        byte-identical results — no timestamps, no random values."""
        decision_a = copy.deepcopy(FULL_IMPACT_DECISION)
        decision_b = copy.deepcopy(FULL_IMPACT_DECISION)

        result_a = generate_fallback_explanation(decision_a)
        result_b = generate_fallback_explanation(decision_b)

        assert result_a == result_b, (
            "generate_fallback_explanation is not deterministic: "
            f"first call returned {result_a!r}, second returned {result_b!r}"
        )

    def test_different_inputs_produce_different_output(self) -> None:
        """Sanity check: two structurally different decisions must not collide."""
        result_impact = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        result_routing = generate_fallback_explanation(copy.deepcopy(ROUTING_DECISION))

        assert result_impact != result_routing

    def test_determinism_cold_chain(self) -> None:
        d = copy.deepcopy(COLD_CHAIN_DECISION)
        assert generate_fallback_explanation(d) == generate_fallback_explanation(d)

    def test_determinism_no_route(self) -> None:
        d = copy.deepcopy(NO_ROUTE_DECISION)
        assert generate_fallback_explanation(d) == generate_fallback_explanation(d)


# ---------------------------------------------------------------------------
# 2. Reason codes preserved
# ---------------------------------------------------------------------------

class TestReasonCodesPreserved:
    def test_all_reason_codes_in_evidence(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        for code in FULL_IMPACT_DECISION["reason_codes"]:
            assert code in result["evidence"], (
                f"reason code {code!r} is missing from evidence"
            )

    def test_reason_codes_reflected_in_why_affected(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        for code in FULL_IMPACT_DECISION["reason_codes"]:
            assert any(code in line for line in result["why_affected"]), (
                f"reason code {code!r} not found in any why_affected entry"
            )

    def test_empty_reason_codes_produces_safe_default(self) -> None:
        decision = {**copy.deepcopy(NO_ROUTE_DECISION), "reason_codes": []}
        result = generate_fallback_explanation(decision)
        assert result["why_affected"], "why_affected must not be empty"
        # No fabricated codes should appear
        assert result["evidence"] == []

    def test_routing_reason_codes_preserved(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(ROUTING_DECISION))
        assert "ROUTE_CAPACITY_EXCEEDED" in result["evidence"]


# ---------------------------------------------------------------------------
# 3. Evidence preserved
# ---------------------------------------------------------------------------

class TestEvidencePreserved:
    def test_explicit_evidence_list_carried_verbatim(self) -> None:
        """Caller-supplied evidence refs must appear in the output evidence."""
        decision = copy.deepcopy(FULL_IMPACT_DECISION)
        decision["evidence"] = ["CHK-2/affected_shipments", "SENSOR-9/ts=2026-09-14T08:12"]
        result = generate_fallback_explanation(decision)
        for ref in decision["evidence"]:
            assert ref in result["evidence"], (
                f"evidence ref {ref!r} was dropped"
            )

    def test_evidence_never_empty_when_reason_codes_present(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert len(result["evidence"]) >= len(FULL_IMPACT_DECISION["reason_codes"])

    def test_evidence_is_list_of_strings(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert isinstance(result["evidence"], list)
        for item in result["evidence"]:
            assert isinstance(item, str), f"evidence item {item!r} is not a str"


# ---------------------------------------------------------------------------
# 4. Recommended action preserved
# ---------------------------------------------------------------------------

class TestRecommendedActionPreserved:
    def test_caller_supplied_action_is_used_verbatim(self) -> None:
        decision = copy.deepcopy(FULL_IMPACT_DECISION)
        decision["recommended_action"] = "Override action: divert to HUB-X immediately."
        result = generate_fallback_explanation(decision)
        assert result["recommended_action"] == "Override action: divert to HUB-X immediately.", (
            "Caller-supplied recommended_action was rewritten by the fallback"
        )

    def test_route_dict_produces_action_with_carrier(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert "Carrier B" in result["recommended_action"]

    def test_route_dict_action_contains_eta_delta(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert "5.4" in result["recommended_action"]

    def test_route_dict_action_contains_cost_delta(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert "1800" in result["recommended_action"]

    def test_no_route_produces_constraint_notice(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(NO_ROUTE_DECISION))
        assert "hard constraints" in result["recommended_action"].lower()

    def test_cold_chain_only_produces_manual_review_action(self) -> None:
        decision = copy.deepcopy(COLD_CHAIN_DECISION)
        # strip route so only cold-chain path is tested
        decision["recommended_route"] = {}
        result = generate_fallback_explanation(decision)
        assert "EXCURSION_REVIEW" in result["recommended_action"]


# ---------------------------------------------------------------------------
# 5. Uncertainties preserved
# ---------------------------------------------------------------------------

class TestUncertaintiesPreserved:
    def test_excursion_review_adds_manual_review_uncertainty(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert any("EXCURSION_REVIEW" in u for u in result["uncertainties"]), (
            "Expected EXCURSION_REVIEW notice in uncertainties"
        )

    def test_urgent_escalation_adds_uncertainty(self) -> None:
        decision = copy.deepcopy(COLD_CHAIN_DECISION)
        decision["cold_chain"]["status"] = "URGENT_ESCALATION"
        decision["recommended_route"] = {}
        result = generate_fallback_explanation(decision)
        assert any("URGENT_ESCALATION" in u for u in result["uncertainties"])

    def test_policy_required_adds_uncertainty(self) -> None:
        decision = copy.deepcopy(COLD_CHAIN_DECISION)
        decision["cold_chain"]["status"] = "POLICY_REQUIRED"
        decision["recommended_route"] = {}
        result = generate_fallback_explanation(decision)
        assert any("POLICY_REQUIRED" in u for u in result["uncertainties"])

    def test_no_route_impact_adds_operator_judgment_uncertainty(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(NO_ROUTE_DECISION))
        assert any("operator judgment" in u.lower() for u in result["uncertainties"])

    def test_safe_cold_chain_no_extra_uncertainty(self) -> None:
        decision = {
            "kind": KIND_COLD_CHAIN,
            "shipment_id": "SHP-1000",
            "disruption": "NONE",
            "reason_codes": [],
            "recommended_route": {},
            "cold_chain": {"status": "SAFE"},
        }
        result = generate_fallback_explanation(decision)
        # SAFE status must not inject a manual-review uncertainty
        assert not any("manual review" in u.lower() for u in result["uncertainties"])

    def test_uncertainties_is_list(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert isinstance(result["uncertainties"], list)

    def test_unknown_kind_adds_uncertainty(self) -> None:
        decision = {**copy.deepcopy(NO_ROUTE_DECISION), "kind": "future_engine"}
        result = generate_fallback_explanation(decision)
        assert any("future_engine" in u for u in result["uncertainties"])


# ---------------------------------------------------------------------------
# 6. No fabricated facts
# ---------------------------------------------------------------------------

class TestNoFabricatedFacts:
    """Verifies that no string present in the output was invented by the
    fallback.  Every substantive token must be traceable to the input dict."""

    def test_shipment_id_in_summary(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert "SHP-0042" in result["summary"]

    def test_disruption_in_summary(self) -> None:
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        assert "PORT_STRIKE_01" in result["summary"]

    def test_no_hardcoded_temperature(self) -> None:
        """The fallback must never emit a temperature number that was not in
        the input (i.e. no hardcoded 10.4 / 8.0 / 2.0 literals)."""
        # Decision with completely different cold-chain numbers
        decision = copy.deepcopy(COLD_CHAIN_DECISION)
        decision["cold_chain"]["max_celsius"] = 55.5
        decision["cold_chain"]["policy_max_celsius"] = 40.0
        result = generate_fallback_explanation(decision)
        full_text = str(result)
        assert "10.4" not in full_text, "Hardcoded temperature 10.4 found in output"
        assert "8.0" not in full_text, "Hardcoded temperature 8.0 found in output"

    def test_no_hardcoded_dates(self) -> None:
        """No date literals should appear in the output."""
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        full_text = str(result)
        assert "2026" not in full_text, "Hardcoded year '2026' found in output"
        assert "2025" not in full_text, "Hardcoded year '2025' found in output"

    def test_no_hardcoded_assets(self) -> None:
        """The fallback must not inject asset IDs not present in the input."""
        result = generate_fallback_explanation(copy.deepcopy(FULL_IMPACT_DECISION))
        full_text = str(result)
        # Assets from the demo data that the fallback must never fabricate
        for fabricated in ("TRUCK-17", "SENSOR-9", "HUB-A", "HUB-B", "HUB-D"):
            assert fabricated not in full_text, (
                f"Fabricated asset reference {fabricated!r} found in output"
            )

    def test_no_hardcoded_route_nodes(self) -> None:
        """Routing output must only reference carrier from the input dict."""
        result = generate_fallback_explanation(copy.deepcopy(ROUTING_DECISION))
        # The carrier in the input is "Carrier C"
        assert "Carrier C" in result["recommended_action"]
        # Must not invent PORT-03 or any other route node
        assert "PORT-03" not in str(result)

    def test_empty_decision_produces_safe_defaults_not_invented_facts(self) -> None:
        result = generate_fallback_explanation({})
        # Should say UNKNOWN for shipment_id and 'an unspecified disruption'
        assert "UNKNOWN" in result["summary"]
        assert result["model_used"] is None
        assert result["generated_by"] == "deterministic_fallback_template"


# ---------------------------------------------------------------------------
# 7. WATSONX_ENABLED=false / fallback identity
# ---------------------------------------------------------------------------

class TestWatsonxDisabledFallbackBehavior:
    """The fallback must always self-identify as the deterministic template
    regardless of any environment variable state, and must never pretend
    to be a model-generated response."""

    def test_generated_by_is_always_template_sentinel(self) -> None:
        for decision in [
            FULL_IMPACT_DECISION,
            ROUTING_DECISION,
            COLD_CHAIN_DECISION,
            NO_ROUTE_DECISION,
        ]:
            result = generate_fallback_explanation(copy.deepcopy(decision))
            assert result["generated_by"] == "deterministic_fallback_template", (
                f"generated_by was {result['generated_by']!r} for {decision['kind']!r} decision"
            )

    def test_model_used_is_always_none(self) -> None:
        for decision in [
            FULL_IMPACT_DECISION,
            ROUTING_DECISION,
            COLD_CHAIN_DECISION,
        ]:
            result = generate_fallback_explanation(copy.deepcopy(decision))
            assert result["model_used"] is None, (
                f"model_used should be None but got {result['model_used']!r}"
            )

    def test_output_schema_complete(self) -> None:
        """All five required keys from the preflight CHK-5 contract must
        be present in every output."""
        required = {"summary", "why_affected", "recommended_action", "evidence", "uncertainties"}
        for decision in [
            FULL_IMPACT_DECISION,
            ROUTING_DECISION,
            COLD_CHAIN_DECISION,
            NO_ROUTE_DECISION,
            {},  # empty / degenerate
        ]:
            result = generate_fallback_explanation(copy.deepcopy(decision))
            missing = required - result.keys()
            assert not missing, (
                f"Output is missing required keys {missing!r} for decision {decision!r}"
            )

    def test_no_external_calls_possible(self) -> None:
        """The module must not import requests, urllib, httpx, or boto3
        at module level — verifiable by inspecting the module's globals."""
        import src.chainshield.explanation.fallback as mod

        forbidden = {"requests", "urllib", "httpx", "boto3", "aiohttp"}
        module_globals = set(vars(mod).keys())
        collisions = forbidden & module_globals
        assert not collisions, (
            f"Forbidden network dependency imported at module level: {collisions}"
        )

    def test_watsonx_env_var_has_no_effect(self) -> None:
        """Setting WATSONX_ENABLED to any value must not change the output —
        the fallback never reads environment variables."""
        import os
        decision = copy.deepcopy(FULL_IMPACT_DECISION)

        # Result with env unset
        os.environ.pop("WATSONX_ENABLED", None)
        result_off = generate_fallback_explanation(copy.deepcopy(decision))

        # Result with env set to true
        os.environ["WATSONX_ENABLED"] = "true"
        result_on = generate_fallback_explanation(copy.deepcopy(decision))

        # Restore
        os.environ.pop("WATSONX_ENABLED", None)

        assert result_off == result_on, (
            "Output changed based on WATSONX_ENABLED env var — "
            "fallback must be env-agnostic"
        )
        assert result_on["generated_by"] == "deterministic_fallback_template"
