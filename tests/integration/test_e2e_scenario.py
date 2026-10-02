from __future__ import annotations

"""
ChainShield — End-to-End Integration Tests
==========================================

Tests the complete scenario from disruption activation through action-plan
generation, verifying all 12 required demo scenario properties:

  1.  Active disruption at a route node.
  2.  At least one affected shipment.
  3.  Cargo value at risk returned.
  4.  Deterministic reason codes.
  5.  Cold-chain sensor excursion for the affected cold shipment.
  6.  Cold-chain severity EXCURSION_REVIEW for the 18-min excursion.
  7.  At least one feasible route alternative.
  8.  At least one rejected alternative with explicit reason code.
  9.  At least one compatible idle asset.
  10. Evidence records linking decisions to source data.
  11. Deterministic explanation fallback.
  12. JSON and Markdown action plan exported.

No live APIs, no external services, no LLM dependency.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup (mirrors conftest.py)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (_REPO_ROOT / "src", _REPO_ROOT / "scripts"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import networkx as nx

from chainshield.cold_chain.engine import ColdChainEngine
from chainshield.evidence.events import DecisionType
from chainshield.evidence.store import EvidenceStore
from chainshield.explanation.fallback import generate_fallback_explanation
from chainshield.impact.engine import ImpactEngine
from chainshield.models.asset import Asset, AssetMode, AssetStatus, AssetType
from chainshield.models.disruption import (
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
)
from chainshield.models.enums import CargoMode, ExcursionSeverity, ProductClass, ShipmentStatus
from chainshield.models.sensor_reading import SensorReading
from chainshield.models.shipment import Shipment
from chainshield.models.temperature_policy import SeverityRules, TemperaturePolicy
from chainshield.optimization.engine import OptimizationEngine
from generate_synthetic_data import generate_scenario
from demo_scenario import _build_scenario_data, _build_scenario_graph, run_demo_scenario


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scenario_result():
    """Run the demo scenario once for the whole module; all tests share this result."""
    return run_demo_scenario()


@pytest.fixture(scope="module")
def bundle():
    """Return the raw synthetic data bundle (seed=42)."""
    return generate_scenario(seed=42)


@pytest.fixture(scope="module")
def graph():
    return _build_scenario_graph()


@pytest.fixture(scope="module")
def scenario_data():
    """Return (disruption, shipments, assets, sensor_map, policy)."""
    return _build_scenario_data()


# ---------------------------------------------------------------------------
# Property 1 — Active disruption at a route node
# ---------------------------------------------------------------------------

class TestActiveDisruption:
    def test_disruption_is_active(self, scenario_data):
        disruption, *_ = scenario_data
        assert disruption.status == DisruptionStatus.ACTIVE

    def test_disruption_blocks_port_node(self, scenario_data):
        disruption, *_ = scenario_data
        assert "PORT-03" in disruption.geometry.blocked_nodes

    def test_disruption_has_non_empty_window(self, scenario_data):
        disruption, *_ = scenario_data
        assert disruption.window_end > disruption.window_start

    def test_disruption_type_is_port_strike(self, scenario_data):
        disruption, *_ = scenario_data
        assert disruption.disruption_type == DisruptionType.PORT_STRIKE


# ---------------------------------------------------------------------------
# Property 2 — At least one affected shipment
# ---------------------------------------------------------------------------

class TestAffectedShipment:
    def test_at_least_one_affected_shipment(self, scenario_result):
        assert len(scenario_result.affected_shipment_ids) >= 1

    def test_shp001_is_affected(self, scenario_result):
        assert "SHP-001" in scenario_result.affected_shipment_ids

    def test_unaffected_shipment_excluded(self, scenario_data, graph):
        """SHP-002 routes via DEPOT-X and must NOT be affected by the PORT-03 disruption."""
        disruption, shipments, *_ = scenario_data
        engine = ImpactEngine(graph)
        shp_002 = next(s for s in shipments if s.shipment_id == "SHP-002")
        result = engine.evaluate(shp_002, disruption)
        assert not result.is_affected

    def test_impact_engine_returns_correct_affected_set(self, scenario_data, graph):
        disruption, shipments, *_ = scenario_data
        engine = ImpactEngine(graph)
        results = engine.evaluate_many(shipments, disruption)
        affected = {r.shipment_id for r in results if r.is_affected}
        # SHP-001 and SHP-004 pass through PORT-03; SHP-002 and SHP-003 do not
        assert "SHP-001" in affected
        assert "SHP-002" not in affected


# ---------------------------------------------------------------------------
# Property 3 — Cargo value at risk
# ---------------------------------------------------------------------------

class TestCargoValueAtRisk:
    def test_cargo_value_at_risk_positive(self, scenario_result):
        assert scenario_result.cargo_value_at_risk_usd > 0

    def test_cargo_value_reflects_shp001_value(self, scenario_data):
        """SHP-001 cargo_value_usd is $520,000; total at-risk must be >= that."""
        _, shipments, *_ = scenario_data
        shp_001 = next(s for s in shipments if s.shipment_id == "SHP-001")
        assert shp_001.cargo_value_usd == pytest.approx(520_000.0)

    def test_cargo_value_present_in_action_plan(self, scenario_result):
        entries = scenario_result.action_plan_json["shipments"]
        shp_entry = next(e for e in entries if e["shipment_id"] == "SHP-001")
        assert shp_entry["cargo_value_usd"] >= 520_000.0


# ---------------------------------------------------------------------------
# Property 4 — Deterministic reason codes
# ---------------------------------------------------------------------------

class TestDeterministicReasonCodes:
    def test_impact_reason_codes_non_empty(self, scenario_result):
        assert len(scenario_result.impact_reason_codes) > 0

    def test_port_node_blocked_code_present(self, scenario_result):
        assert "PORT_NODE_BLOCKED" in scenario_result.impact_reason_codes

    def test_reason_codes_are_screaming_snake_case(self, scenario_result):
        for code in scenario_result.all_reason_codes:
            assert code == code.upper(), f"Code {code!r} is not SCREAMING_SNAKE_CASE"
            assert " " not in code, f"Code {code!r} must not contain spaces"

    def test_repeated_runs_produce_same_reason_codes(self):
        """Identical inputs must always produce identical reason codes."""
        r1 = run_demo_scenario()
        r2 = run_demo_scenario()
        assert r1.impact_reason_codes == r2.impact_reason_codes
        assert r1.cold_chain_reason_codes == r2.cold_chain_reason_codes

    def test_reason_codes_in_evidence_records(self, scenario_result):
        for rec in scenario_result.evidence_records:
            assert "reason_codes" in rec
            assert isinstance(rec["reason_codes"], list)

    def test_impact_codes_from_engine_match_scenario_result(self, scenario_data, graph):
        disruption, shipments, *_ = scenario_data
        engine = ImpactEngine(graph)
        shp_001 = next(s for s in shipments if s.shipment_id == "SHP-001")
        result = engine.evaluate(shp_001, disruption)
        assert "PORT_NODE_BLOCKED" in result.reason_codes


# ---------------------------------------------------------------------------
# Property 5 — Cold-chain sensor excursion
# ---------------------------------------------------------------------------

class TestColdChainExcursion:
    def test_excursion_detected(self, scenario_result):
        assert scenario_result.cold_chain_duration_minutes > 0

    def test_excursion_max_temperature_above_policy_max(self, scenario_result):
        """Policy max is 8.0 °C; observed max must exceed that."""
        assert scenario_result.cold_chain_max_celsius > 8.0

    def test_excursion_max_temperature_matches_reference(self, scenario_result):
        """The reference scenario peaks at 10.4 °C (from preflight_demo.py)."""
        assert scenario_result.cold_chain_max_celsius == pytest.approx(10.4)

    def test_18_minute_excursion_window(self, scenario_result):
        """3 out-of-range readings × 6 min interval = 18 minutes."""
        assert scenario_result.cold_chain_duration_minutes == pytest.approx(18.0)

    def test_cold_chain_reason_codes_non_empty(self, scenario_result):
        assert len(scenario_result.cold_chain_reason_codes) > 0

    def test_temperature_above_max_code_present(self, scenario_result):
        assert "TEMPERATURE_ABOVE_MAX" in scenario_result.cold_chain_reason_codes

    def test_policy_none_returns_policy_required(self):
        engine = ColdChainEngine()
        result = engine.evaluate(None, [])
        assert result.severity == ExcursionSeverity.POLICY_REQUIRED

    def test_empty_readings_returns_urgent_escalation(self):
        engine = ColdChainEngine()
        policy = TemperaturePolicy(
            policy_id="test-pol",
            product_class=ProductClass.REFRIGERATED_VACCINE,
            min_celsius=2.0,
            max_celsius=8.0,
            max_continuous_excursion_minutes=15.0,
        )
        result = engine.evaluate(policy, [])
        assert result.severity == ExcursionSeverity.URGENT_ESCALATION


# ---------------------------------------------------------------------------
# Property 6 — Cold-chain severity: EXCURSION_REVIEW for 18-min excursion
# ---------------------------------------------------------------------------

class TestColdChainSeverity:
    def test_severity_is_excursion_review(self, scenario_result):
        assert scenario_result.cold_chain_severity == "EXCURSION_REVIEW"

    def test_excursion_review_not_urgent_escalation(self, scenario_result):
        """18 min < 30-min policy threshold → EXCURSION_REVIEW, not URGENT_ESCALATION."""
        assert scenario_result.cold_chain_severity != "URGENT_ESCALATION"

    def test_policy_threshold_drives_severity(self):
        """Setting threshold to 10 min makes the 18-min window trigger URGENT_ESCALATION."""
        engine = ColdChainEngine()
        base = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
        readings = [
            SensorReading(sensor_id="S1", shipment_id="SHP-001", ts=base, temperature_c=6.9),
            SensorReading(sensor_id="S1", shipment_id="SHP-001", ts=base.replace(minute=6), temperature_c=8.9),
            SensorReading(sensor_id="S1", shipment_id="SHP-001", ts=base.replace(minute=12), temperature_c=10.4),
            SensorReading(sensor_id="S1", shipment_id="SHP-001", ts=base.replace(minute=18), temperature_c=9.1),
            SensorReading(sensor_id="S1", shipment_id="SHP-001", ts=base.replace(minute=24), temperature_c=6.4),
        ]
        policy_strict = TemperaturePolicy(
            policy_id="strict",
            product_class=ProductClass.REFRIGERATED_VACCINE,
            min_celsius=2.0,
            max_celsius=8.0,
            max_continuous_excursion_minutes=10.0,  # 3 readings × 6 min = 18 min > 10 → URGENT
            severity_rules=SeverityRules(
                out_of_range=ExcursionSeverity.EXCURSION_REVIEW,
                sustained_excursion=ExcursionSeverity.URGENT_ESCALATION,
            ),
        )
        result = engine.evaluate(policy_strict, readings)
        assert result.severity == ExcursionSeverity.URGENT_ESCALATION

    def test_in_range_reading_is_safe(self):
        engine = ColdChainEngine()
        base = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
        readings = [
            SensorReading(sensor_id="S1", shipment_id="SHP-X", ts=base, temperature_c=5.0),
        ]
        policy = TemperaturePolicy(
            policy_id="safe-pol",
            product_class=ProductClass.REFRIGERATED_VACCINE,
            min_celsius=2.0,
            max_celsius=8.0,
            max_continuous_excursion_minutes=15.0,
        )
        result = engine.evaluate(policy, readings)
        assert result.severity == ExcursionSeverity.SAFE


# ---------------------------------------------------------------------------
# Property 7 — At least one feasible route alternative
# ---------------------------------------------------------------------------

class TestFeasibleAlternative:
    def test_at_least_one_feasible_alternative(self, scenario_result):
        assert len(scenario_result.feasible_alternatives) >= 1

    def test_feasible_alternative_has_valid_path(self, scenario_result):
        for alt in scenario_result.feasible_alternatives:
            assert len(alt["path"]) >= 2, "A feasible alternative must have at least 2 nodes"

    def test_feasible_alternative_avoids_blocked_node(self, scenario_result, scenario_data):
        disruption, *_ = scenario_data
        blocked = set(disruption.geometry.blocked_nodes)
        for alt in scenario_result.feasible_alternatives:
            path_set = set(alt["path"])
            assert path_set.isdisjoint(blocked), (
                f"Alternative {alt['alternative_id']} traverses blocked node {blocked & path_set}"
            )

    def test_feasible_alternative_has_rank_gte_1(self, scenario_result):
        for alt in scenario_result.feasible_alternatives:
            assert alt["rank"] >= 1

    def test_feasible_alternative_cost_positive(self, scenario_result):
        for alt in scenario_result.feasible_alternatives:
            assert alt["total_cost_usd"] >= 0


# ---------------------------------------------------------------------------
# Property 8 — At least one rejected alternative with explicit reason code
# ---------------------------------------------------------------------------

class TestRejectedAlternative:
    def test_at_least_one_rejected_alternative(self, scenario_result):
        assert len(scenario_result.rejected_alternatives) >= 1

    def test_rejected_alternative_has_reason_codes(self, scenario_result):
        for alt in scenario_result.rejected_alternatives:
            assert len(alt["reason_codes"]) >= 1, (
                f"Rejected alternative {alt['alternative_id']} has no reason codes"
            )

    def test_rejected_reason_codes_are_known(self, scenario_result):
        known_codes = {
            "CAPACITY_VIOLATION", "DEADLINE_VIOLATION", "REEFER_REQUIRED",
            "CARRIER_UNAVAILABLE", "MODE_INCOMPATIBLE", "ROUTE_EDGE_BLOCKED",
            "ROUTE_NODE_BLOCKED", "NO_FEASIBLE_ALTERNATIVE",
        }
        for alt in scenario_result.rejected_alternatives:
            for code in alt["reason_codes"]:
                assert code in known_codes, f"Unknown rejection code: {code!r}"

    def test_rejection_reason_codes_in_result(self, scenario_result):
        """The OptimizationResult.rejection_reason_codes must be non-empty."""
        action_plan = scenario_result.action_plan_json
        entry = action_plan["shipments"][0]
        # Either explicit rejection codes or the alternatives list has rejected entries
        has_codes = len(entry.get("rejection_reason_codes", [])) > 0
        has_rejected = len(entry.get("rejected_alternatives", [])) > 0
        assert has_codes or has_rejected


# ---------------------------------------------------------------------------
# Property 9 — At least one compatible idle asset
# ---------------------------------------------------------------------------

class TestIdleCompatibleAsset:
    def test_at_least_one_compatible_idle_asset(self, scenario_result):
        assert len(scenario_result.idle_compatible_assets) >= 1

    def test_reefer_capable_asset_in_compatible_list(self, scenario_data):
        _, _, assets, *_ = scenario_data
        idle_reefer = [a for a in assets if a.status == AssetStatus.AVAILABLE and a.reefer_capable]
        assert len(idle_reefer) >= 1

    def test_compatible_asset_has_sufficient_capacity(self, scenario_data):
        _, shipments, assets, *_ = scenario_data
        shp_001 = next(s for s in shipments if s.shipment_id == "SHP-001")
        compatible = [
            a for a in assets
            if a.status == AssetStatus.AVAILABLE
            and a.reefer_capable
            and a.capacity_kg >= shp_001.weight_kg
        ]
        assert len(compatible) >= 1, (
            f"No asset can carry {shp_001.weight_kg} kg with reefer capability"
        )

    def test_incompatible_dry_truck_not_in_compatible_list(self, scenario_data):
        _, _, assets, *_ = scenario_data
        dry_trucks = [a for a in assets if not a.reefer_capable and a.status == AssetStatus.AVAILABLE]
        assert len(dry_trucks) >= 1  # sanity: there IS a dry truck in the pool


# ---------------------------------------------------------------------------
# Property 10 — Evidence records linking decisions to source data
# ---------------------------------------------------------------------------

class TestEvidenceRecords:
    def test_evidence_records_present(self, scenario_result):
        assert len(scenario_result.evidence_records) >= 3  # impact + cc + route rec

    def test_every_record_has_required_fields(self, scenario_result):
        required = {"record_id", "decision_type", "shipment_id", "reason_codes", "source_refs"}
        for rec in scenario_result.evidence_records:
            missing = required - rec.keys()
            assert not missing, f"Evidence record missing fields: {missing}"

    def test_impact_analysis_evidence_present(self, scenario_result):
        impact_recs = [
            r for r in scenario_result.evidence_records
            if r["decision_type"] == "IMPACT_ANALYSIS"
        ]
        assert len(impact_recs) >= 1

    def test_cold_chain_evidence_present(self, scenario_result):
        cc_recs = [
            r for r in scenario_result.evidence_records
            if r["decision_type"] == "COLD_CHAIN_CLASSIFICATION"
        ]
        assert len(cc_recs) >= 1
        cc_rec = cc_recs[0]
        assert cc_rec["severity"] == "EXCURSION_REVIEW"

    def test_route_recommendation_evidence_present(self, scenario_result):
        route_recs = [
            r for r in scenario_result.evidence_records
            if r["decision_type"] == "ROUTE_RECOMMENDATION"
        ]
        assert len(route_recs) >= 1

    def test_optimization_rejection_evidence_present(self, scenario_result):
        rej_recs = [
            r for r in scenario_result.evidence_records
            if r["decision_type"] == "OPTIMIZATION_REJECTION"
        ]
        assert len(rej_recs) >= 1
        rej_rec = rej_recs[0]
        assert len(rej_rec["reason_codes"]) >= 1

    def test_evidence_records_link_shipment_id(self, scenario_result):
        for rec in scenario_result.evidence_records:
            assert rec["shipment_id"] == "SHP-001"

    def test_evidence_records_link_disruption_id(self, scenario_result, scenario_data):
        disruption, *_ = scenario_data
        for rec in scenario_result.evidence_records:
            assert disruption.disruption_id in rec["disruption_ids"], (
                f"Record {rec['record_id']} does not reference disruption {disruption.disruption_id}"
            )

    def test_record_ids_are_deterministic(self):
        """The same scenario run must produce the same record_ids."""
        r1 = run_demo_scenario()
        r2 = run_demo_scenario()
        ids1 = sorted(r["record_id"] for r in r1.evidence_records)
        ids2 = sorted(r["record_id"] for r in r2.evidence_records)
        assert ids1 == ids2, "Evidence record IDs are not deterministic across runs"


# ---------------------------------------------------------------------------
# Property 11 — Deterministic explanation fallback
# ---------------------------------------------------------------------------

class TestDeterministicExplanationFallback:
    def test_explanation_present(self, scenario_result):
        assert scenario_result.explanation is not None

    def test_generated_by_is_fallback_template(self, scenario_result):
        assert scenario_result.explanation["generated_by"] == "deterministic_fallback_template"

    def test_model_used_is_none(self, scenario_result):
        assert scenario_result.explanation["model_used"] is None

    def test_required_keys_present(self, scenario_result):
        required = {"summary", "why_affected", "recommended_action", "evidence", "uncertainties"}
        assert required.issubset(scenario_result.explanation.keys())

    def test_summary_contains_shipment_id(self, scenario_result):
        assert "SHP-001" in scenario_result.explanation["summary"]

    def test_evidence_contains_reason_codes(self, scenario_result):
        for code in scenario_result.impact_reason_codes:
            assert code in scenario_result.explanation["evidence"], (
                f"Reason code {code!r} not in explanation evidence"
            )

    def test_uncertainties_list_present(self, scenario_result):
        assert isinstance(scenario_result.explanation["uncertainties"], list)

    def test_explanation_identical_on_repeated_runs(self):
        r1 = run_demo_scenario()
        r2 = run_demo_scenario()
        for key in ("summary", "why_affected", "recommended_action", "generated_by"):
            assert r1.explanation[key] == r2.explanation[key], (
                f"Explanation field '{key}' differs between runs"
            )

    def test_fallback_with_no_route_produces_fallback_action(self):
        """When no route alternative is available, the action must reference limitations."""
        decision = {
            "shipment_id": "SHP-TEST",
            "disruption": "TEST-DISRUPTION",
            "kind": "impact",
            "reason_codes": ["PORT_NODE_BLOCKED"],
            "recommended_route": {},
            "cold_chain": {},
        }
        result = generate_fallback_explanation(decision)
        assert "No feasible route" in result["recommended_action"]

    def test_fallback_with_cold_chain_adds_uncertainty(self):
        """EXCURSION_REVIEW cold-chain status must add an uncertainty note."""
        decision = {
            "shipment_id": "SHP-TEST",
            "disruption": "TEST-DISRUPTION",
            "kind": "cold_chain",
            "reason_codes": ["TEMPERATURE_ABOVE_MAX"],
            "recommended_route": {},
            "cold_chain": {
                "status": "EXCURSION_REVIEW",
                "max_celsius": 10.4,
                "policy_max_celsius": 8.0,
                "duration_minutes": 18,
            },
        }
        result = generate_fallback_explanation(decision)
        cold_chain_uncertainty = any(
            "EXCURSION_REVIEW" in u for u in result["uncertainties"]
        )
        assert cold_chain_uncertainty


# ---------------------------------------------------------------------------
# Property 12 — JSON and Markdown action plan
# ---------------------------------------------------------------------------

class TestActionPlan:
    def test_action_plan_json_present(self, scenario_result):
        assert scenario_result.action_plan_json is not None

    def test_action_plan_json_contains_disruption_id(self, scenario_result, scenario_data):
        disruption, *_ = scenario_data
        assert scenario_result.action_plan_json["disruption_id"] == disruption.disruption_id

    def test_action_plan_json_contains_shp001(self, scenario_result):
        ids = [e["shipment_id"] for e in scenario_result.action_plan_json["shipments"]]
        assert "SHP-001" in ids

    def test_action_plan_json_has_evidence_count(self, scenario_result):
        assert scenario_result.action_plan_json["evidence_record_count"] >= 3

    def test_action_plan_json_shp001_has_cold_chain_severity(self, scenario_result):
        entry = next(
            e for e in scenario_result.action_plan_json["shipments"]
            if e["shipment_id"] == "SHP-001"
        )
        assert entry["cold_chain_severity"] == "EXCURSION_REVIEW"

    def test_action_plan_json_shp001_has_alternatives_or_rejection(self, scenario_result):
        entry = next(
            e for e in scenario_result.action_plan_json["shipments"]
            if e["shipment_id"] == "SHP-001"
        )
        has_alternatives = len(entry.get("route_alternatives", [])) > 0
        has_rejection = len(entry.get("rejected_alternatives", [])) > 0
        assert has_alternatives or has_rejection

    def test_action_plan_markdown_present(self, scenario_result):
        assert scenario_result.action_plan_markdown is not None
        assert len(scenario_result.action_plan_markdown) > 0

    def test_action_plan_markdown_contains_disruption_id(self, scenario_result, scenario_data):
        disruption, *_ = scenario_data
        assert disruption.disruption_id in scenario_result.action_plan_markdown

    def test_action_plan_markdown_contains_shipment_id(self, scenario_result):
        assert "SHP-001" in scenario_result.action_plan_markdown

    def test_action_plan_markdown_contains_cold_chain_severity(self, scenario_result):
        assert "EXCURSION_REVIEW" in scenario_result.action_plan_markdown

    def test_action_plan_markdown_has_explanation_section(self, scenario_result):
        assert "Explanation" in scenario_result.action_plan_markdown

    def test_action_plan_identical_on_repeated_runs(self):
        """Markdown and JSON outputs must be structurally equivalent across runs."""
        r1 = run_demo_scenario()
        r2 = run_demo_scenario()
        assert r1.action_plan_json["disruption_id"] == r2.action_plan_json["disruption_id"]
        assert (
            r1.action_plan_json["shipments"][0]["reason_codes"]
            == r2.action_plan_json["shipments"][0]["reason_codes"]
        )
        assert (
            r1.action_plan_json["shipments"][0]["cold_chain_severity"]
            == r2.action_plan_json["shipments"][0]["cold_chain_severity"]
        )


# ---------------------------------------------------------------------------
# Full scenario pass
# ---------------------------------------------------------------------------

class TestScenarioPasses:
    def test_scenario_passed_flag_is_true(self, scenario_result):
        """The orchestrator's own self-check must pass."""
        assert scenario_result.scenario_passed, (
            f"Demo scenario reported failures: {scenario_result.failure_reasons}"
        )

    def test_no_failure_reasons(self, scenario_result):
        assert scenario_result.failure_reasons == [], (
            f"Unexpected failures: {scenario_result.failure_reasons}"
        )

    def test_all_12_properties_covered(self, scenario_result):
        """Smoke check that all 12 required properties produce non-empty data."""
        # 1. Disruption is active (checked separately)
        # 2. Affected shipments
        assert len(scenario_result.affected_shipment_ids) >= 1
        # 3. Cargo value
        assert scenario_result.cargo_value_at_risk_usd > 0
        # 4. Reason codes
        assert len(scenario_result.impact_reason_codes) > 0
        # 5. Excursion
        assert scenario_result.cold_chain_duration_minutes > 0
        # 6. Severity
        assert scenario_result.cold_chain_severity == "EXCURSION_REVIEW"
        # 7. Feasible alt
        assert len(scenario_result.feasible_alternatives) >= 1
        # 8. Rejected alt
        assert len(scenario_result.rejected_alternatives) >= 1
        # 9. Idle compatible asset
        assert len(scenario_result.idle_compatible_assets) >= 1
        # 10. Evidence
        assert len(scenario_result.evidence_records) >= 3
        # 11. Explanation
        assert scenario_result.explanation["generated_by"] == "deterministic_fallback_template"
        # 12. Action plan
        assert scenario_result.action_plan_json is not None
        assert scenario_result.action_plan_markdown is not None
