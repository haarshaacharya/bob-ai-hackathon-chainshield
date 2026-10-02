from __future__ import annotations

"""
Unit tests for the ChainShield Evidence/Audit Layer.

Coverage requirements (from task spec)
---------------------------------------
1.  Evidence record creation — all four concrete types.
2.  Required fields — every record carries record_id, decision_type,
    shipment_id, reason_codes, source_refs, timestamp.
3.  JSON serialisation — to_dict() and to_json() round-trip cleanly.
4.  Deterministic repeated records — same inputs → same record_id.
5.  Evidence links to the correct shipment/result.
6.  Rejection reason codes are preserved in OptimizationRejectionEvidence.

Additional coverage
-------------------
- EvidenceStore.add() idempotency.
- EvidenceStore query helpers (for_shipment, for_disruption, for_decision_type,
  get).
- EvidenceStore.to_json() produces valid JSON.
- ColdChainEvidence and ImpactAnalysisEvidence type-specific fields.
"""

import json
from datetime import datetime, timezone

import pytest

from chainshield.evidence import (
    ColdChainEvidence,
    DecisionType,
    EvidenceRecord,
    EvidenceStore,
    ImpactAnalysisEvidence,
    OptimizationRejectionEvidence,
    RouteRecommendationEvidence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SHIPMENT_ID = "SHP-001"
DISRUPTION_ID = "DIS-TYPHOON-01"
ASSET_ID = "ASSET-REEFER-07"


def _make_route_evidence(**kwargs) -> RouteRecommendationEvidence:
    defaults = dict(
        decision_type=DecisionType.ROUTE_RECOMMENDATION,
        shipment_id=SHIPMENT_ID,
        reason_codes=["PORT_NODE_BLOCKED", "ALT_ROUTE_AVAILABLE"],
        source_refs={"graph_version": "v1.2", "disruption_ids": [DISRUPTION_ID]},
        disruption_ids=[DISRUPTION_ID],
        recommended_route_node_ids=["HUB-A", "HUB-C", "HUB-D"],
        original_route_node_ids=["HUB-A", "PORT-03", "HUB-D"],
        estimated_delay_hours=4.0,
    )
    defaults.update(kwargs)
    return RouteRecommendationEvidence(**defaults)


def _make_impact_evidence(**kwargs) -> ImpactAnalysisEvidence:
    defaults = dict(
        decision_type=DecisionType.IMPACT_ANALYSIS,
        shipment_id=SHIPMENT_ID,
        reason_codes=["DISRUPTION_INTERSECTION", "ETA_SLA_BREACH"],
        source_refs={"algorithm": "networkx_shortest_path", "node_radius_km": 50},
        disruption_ids=[DISRUPTION_ID],
        affected_node_ids=["PORT-03"],
        affected_leg_ids=["LEG-002"],
        impact_score=0.85,
    )
    defaults.update(kwargs)
    return ImpactAnalysisEvidence(**defaults)


def _make_cold_chain_evidence(**kwargs) -> ColdChainEvidence:
    defaults = dict(
        decision_type=DecisionType.COLD_CHAIN_CLASSIFICATION,
        shipment_id=SHIPMENT_ID,
        reason_codes=["EXCURSION_REVIEW"],
        source_refs={"policy_id": "cdc_refrigerated_vaccine_demo"},
        policy_id="cdc_refrigerated_vaccine_demo",
        severity="EXCURSION_REVIEW",
        out_of_range_readings=3,
        duration_minutes=18.0,
        max_celsius=10.4,
        min_celsius=6.4,
    )
    defaults.update(kwargs)
    return ColdChainEvidence(**defaults)


def _make_rejection_evidence(**kwargs) -> OptimizationRejectionEvidence:
    defaults = dict(
        decision_type=DecisionType.OPTIMIZATION_REJECTION,
        shipment_id=SHIPMENT_ID,
        reason_codes=["CAPACITY_EXCEEDED", "DEADLINE_INFEASIBLE"],
        source_refs={"solver": "ortools_cp_sat", "solver_status": "INFEASIBLE"},
        asset_ids=[ASSET_ID],
        candidate_route_node_ids=["HUB-A", "PORT-03", "HUB-D"],
        rejected_asset_ids=[ASSET_ID],
        constraint_violations=["WEIGHT_LIMIT", "ARRIVAL_DEADLINE"],
    )
    defaults.update(kwargs)
    return OptimizationRejectionEvidence(**defaults)


# ===========================================================================
# 1. Evidence record creation
# ===========================================================================

class TestEvidenceRecordCreation:
    def test_route_recommendation_creates_successfully(self):
        rec = _make_route_evidence()
        assert isinstance(rec, RouteRecommendationEvidence)
        assert isinstance(rec, EvidenceRecord)

    def test_impact_analysis_creates_successfully(self):
        rec = _make_impact_evidence()
        assert isinstance(rec, ImpactAnalysisEvidence)
        assert isinstance(rec, EvidenceRecord)

    def test_cold_chain_creates_successfully(self):
        rec = _make_cold_chain_evidence()
        assert isinstance(rec, ColdChainEvidence)
        assert isinstance(rec, EvidenceRecord)

    def test_optimization_rejection_creates_successfully(self):
        rec = _make_rejection_evidence()
        assert isinstance(rec, OptimizationRejectionEvidence)
        assert isinstance(rec, EvidenceRecord)


# ===========================================================================
# 2. Required fields
# ===========================================================================

class TestRequiredFields:
    """Every record must carry record_id, decision_type, shipment_id,
    reason_codes, source_refs, and timestamp."""

    @pytest.mark.parametrize(
        "make_fn",
        [
            _make_route_evidence,
            _make_impact_evidence,
            _make_cold_chain_evidence,
            _make_rejection_evidence,
        ],
        ids=["route", "impact", "cold_chain", "rejection"],
    )
    def test_record_id_present_and_non_empty(self, make_fn):
        rec = make_fn()
        assert rec.record_id
        assert isinstance(rec.record_id, str)

    @pytest.mark.parametrize(
        "make_fn",
        [
            _make_route_evidence,
            _make_impact_evidence,
            _make_cold_chain_evidence,
            _make_rejection_evidence,
        ],
        ids=["route", "impact", "cold_chain", "rejection"],
    )
    def test_decision_type_present(self, make_fn):
        rec = make_fn()
        assert isinstance(rec.decision_type, DecisionType)

    @pytest.mark.parametrize(
        "make_fn",
        [
            _make_route_evidence,
            _make_impact_evidence,
            _make_cold_chain_evidence,
            _make_rejection_evidence,
        ],
        ids=["route", "impact", "cold_chain", "rejection"],
    )
    def test_shipment_id_present(self, make_fn):
        rec = make_fn()
        assert rec.shipment_id == SHIPMENT_ID

    @pytest.mark.parametrize(
        "make_fn",
        [
            _make_route_evidence,
            _make_impact_evidence,
            _make_cold_chain_evidence,
            _make_rejection_evidence,
        ],
        ids=["route", "impact", "cold_chain", "rejection"],
    )
    def test_reason_codes_present_and_non_empty(self, make_fn):
        rec = make_fn()
        assert isinstance(rec.reason_codes, list)
        assert len(rec.reason_codes) > 0

    @pytest.mark.parametrize(
        "make_fn",
        [
            _make_route_evidence,
            _make_impact_evidence,
            _make_cold_chain_evidence,
            _make_rejection_evidence,
        ],
        ids=["route", "impact", "cold_chain", "rejection"],
    )
    def test_source_refs_present(self, make_fn):
        rec = make_fn()
        assert isinstance(rec.source_refs, dict)

    @pytest.mark.parametrize(
        "make_fn",
        [
            _make_route_evidence,
            _make_impact_evidence,
            _make_cold_chain_evidence,
            _make_rejection_evidence,
        ],
        ids=["route", "impact", "cold_chain", "rejection"],
    )
    def test_timestamp_is_iso8601_utc(self, make_fn):
        rec = make_fn()
        assert rec.timestamp
        # must parse as a valid ISO-8601 datetime
        parsed = datetime.fromisoformat(rec.timestamp)
        assert parsed.tzinfo is not None


# ===========================================================================
# 3. JSON serialisation
# ===========================================================================

class TestJSONSerialisation:
    def test_to_dict_returns_plain_dict(self):
        rec = _make_route_evidence()
        d = rec.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_contains_required_keys(self):
        rec = _make_impact_evidence()
        d = rec.to_dict()
        for key in ("record_id", "decision_type", "shipment_id",
                    "reason_codes", "source_refs", "timestamp",
                    "disruption_ids", "asset_ids", "extra"):
            assert key in d, f"Missing key: {key}"

    def test_to_json_is_valid_json(self):
        rec = _make_cold_chain_evidence()
        raw = rec.to_json()
        parsed = json.loads(raw)
        assert parsed["shipment_id"] == SHIPMENT_ID

    def test_to_dict_round_trips_through_json(self):
        rec = _make_rejection_evidence()
        d = rec.to_dict()
        raw = json.dumps(d)  # must not raise
        back = json.loads(raw)
        assert back["record_id"] == rec.record_id

    def test_route_evidence_extra_fields_in_dict(self):
        rec = _make_route_evidence()
        d = rec.to_dict()
        assert "recommended_route_node_ids" in d
        assert "original_route_node_ids" in d
        assert "estimated_delay_hours" in d

    def test_cold_chain_extra_fields_in_dict(self):
        rec = _make_cold_chain_evidence()
        d = rec.to_dict()
        assert "policy_id" in d
        assert "severity" in d
        assert "max_celsius" in d
        assert "min_celsius" in d

    def test_impact_extra_fields_in_dict(self):
        rec = _make_impact_evidence()
        d = rec.to_dict()
        assert "affected_node_ids" in d
        assert "affected_leg_ids" in d
        assert "impact_score" in d

    def test_rejection_extra_fields_in_dict(self):
        rec = _make_rejection_evidence()
        d = rec.to_dict()
        assert "candidate_route_node_ids" in d
        assert "rejected_asset_ids" in d
        assert "constraint_violations" in d


# ===========================================================================
# 4. Deterministic repeated records
# ===========================================================================

class TestDeterministicIds:
    """The same logical inputs must always produce the same record_id."""

    def test_same_inputs_same_route_record_id(self):
        r1 = _make_route_evidence()
        r2 = _make_route_evidence()
        assert r1.record_id == r2.record_id

    def test_same_inputs_same_impact_record_id(self):
        r1 = _make_impact_evidence()
        r2 = _make_impact_evidence()
        assert r1.record_id == r2.record_id

    def test_same_inputs_same_cold_chain_record_id(self):
        r1 = _make_cold_chain_evidence()
        r2 = _make_cold_chain_evidence()
        assert r1.record_id == r2.record_id

    def test_same_inputs_same_rejection_record_id(self):
        r1 = _make_rejection_evidence()
        r2 = _make_rejection_evidence()
        assert r1.record_id == r2.record_id

    def test_different_shipment_id_produces_different_record_id(self):
        r1 = _make_route_evidence(shipment_id="SHP-001")
        r2 = _make_route_evidence(shipment_id="SHP-002")
        assert r1.record_id != r2.record_id

    def test_different_reason_codes_produce_different_record_id(self):
        r1 = _make_impact_evidence(reason_codes=["DISRUPTION_INTERSECTION"])
        r2 = _make_impact_evidence(reason_codes=["ETA_SLA_BREACH"])
        assert r1.record_id != r2.record_id


# ===========================================================================
# 5. Evidence links to the correct shipment/result
# ===========================================================================

class TestEvidenceLinking:
    def test_route_evidence_shipment_id_matches(self):
        rec = _make_route_evidence(shipment_id="SHP-XYZ")
        assert rec.shipment_id == "SHP-XYZ"

    def test_impact_evidence_disruption_id_present(self):
        rec = _make_impact_evidence(disruption_ids=[DISRUPTION_ID])
        assert DISRUPTION_ID in rec.disruption_ids

    def test_cold_chain_evidence_policy_id_preserved(self):
        rec = _make_cold_chain_evidence(policy_id="my_custom_policy")
        assert rec.policy_id == "my_custom_policy"

    def test_rejection_evidence_asset_id_linked(self):
        rec = _make_rejection_evidence(asset_ids=[ASSET_ID])
        assert ASSET_ID in rec.asset_ids

    def test_route_evidence_original_and_new_routes_differ(self):
        rec = _make_route_evidence()
        assert rec.recommended_route_node_ids != rec.original_route_node_ids

    def test_impact_evidence_affected_nodes_linked(self):
        rec = _make_impact_evidence(affected_node_ids=["PORT-03", "PORT-04"])
        assert "PORT-03" in rec.affected_node_ids

    def test_store_for_shipment_returns_only_matching(self):
        store = EvidenceStore()
        r1 = _make_route_evidence(shipment_id="SHP-001")
        r2 = _make_impact_evidence(shipment_id="SHP-002")
        store.add(r1)
        store.add(r2)
        results = store.for_shipment("SHP-001")
        assert len(results) == 1
        assert results[0].shipment_id == "SHP-001"

    def test_store_for_disruption_returns_matching(self):
        store = EvidenceStore()
        r1 = _make_route_evidence(disruption_ids=[DISRUPTION_ID])
        r2 = _make_cold_chain_evidence(disruption_ids=[])
        store.add(r1)
        store.add(r2)
        results = store.for_disruption(DISRUPTION_ID)
        assert len(results) == 1
        assert DISRUPTION_ID in results[0].disruption_ids


# ===========================================================================
# 6. Rejection reason codes are preserved
# ===========================================================================

class TestRejectionReasonCodes:
    def test_rejection_codes_present_in_record(self):
        codes = ["CAPACITY_EXCEEDED", "DEADLINE_INFEASIBLE"]
        rec = _make_rejection_evidence(reason_codes=codes)
        assert rec.reason_codes == codes

    def test_rejection_codes_preserved_in_to_dict(self):
        codes = ["CAPACITY_EXCEEDED", "DEADLINE_INFEASIBLE"]
        rec = _make_rejection_evidence(reason_codes=codes)
        d = rec.to_dict()
        assert d["reason_codes"] == codes

    def test_rejection_codes_preserved_in_to_json(self):
        codes = ["WEIGHT_LIMIT", "REEFER_UNIT_UNAVAILABLE"]
        rec = _make_rejection_evidence(reason_codes=codes)
        parsed = json.loads(rec.to_json())
        assert parsed["reason_codes"] == codes

    def test_constraint_violations_preserved(self):
        violations = ["WEIGHT_LIMIT", "ARRIVAL_DEADLINE"]
        rec = _make_rejection_evidence(constraint_violations=violations)
        assert rec.constraint_violations == violations
        assert rec.to_dict()["constraint_violations"] == violations

    def test_rejection_record_id_stable_across_calls(self):
        codes = ["CAPACITY_EXCEEDED", "DEADLINE_INFEASIBLE"]
        rec1 = _make_rejection_evidence(reason_codes=codes)
        rec2 = _make_rejection_evidence(reason_codes=codes)
        assert rec1.record_id == rec2.record_id


# ===========================================================================
# EvidenceStore tests
# ===========================================================================

class TestEvidenceStore:
    def test_empty_store_has_zero_length(self):
        store = EvidenceStore()
        assert len(store) == 0

    def test_add_increments_length(self):
        store = EvidenceStore()
        store.add(_make_route_evidence())
        assert len(store) == 1

    def test_add_is_idempotent(self):
        store = EvidenceStore()
        rec = _make_route_evidence()
        store.add(rec)
        store.add(rec)  # same record_id → ignored
        assert len(store) == 1

    def test_all_returns_all_records(self):
        store = EvidenceStore()
        store.add(_make_route_evidence())
        store.add(_make_impact_evidence())
        assert len(store.all()) == 2

    def test_for_decision_type_filters_correctly(self):
        store = EvidenceStore()
        store.add(_make_route_evidence())
        store.add(_make_rejection_evidence())
        routes = store.for_decision_type(DecisionType.ROUTE_RECOMMENDATION)
        assert len(routes) == 1
        assert routes[0].decision_type == DecisionType.ROUTE_RECOMMENDATION

    def test_get_returns_record_by_id(self):
        store = EvidenceStore()
        rec = _make_cold_chain_evidence()
        store.add(rec)
        found = store.get(rec.record_id)
        assert found is rec

    def test_get_returns_none_for_unknown_id(self):
        store = EvidenceStore()
        assert store.get("nonexistent-id") is None

    def test_to_json_valid_array(self):
        store = EvidenceStore()
        store.add(_make_route_evidence())
        store.add(_make_cold_chain_evidence())
        parsed = json.loads(store.to_json())
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_to_dicts_returns_list_of_dicts(self):
        store = EvidenceStore()
        store.add(_make_rejection_evidence())
        result = store.to_dicts()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_all_returns_copy_not_reference(self):
        store = EvidenceStore()
        store.add(_make_route_evidence())
        copy = store.all()
        copy.clear()
        assert len(store) == 1  # internal list unchanged
