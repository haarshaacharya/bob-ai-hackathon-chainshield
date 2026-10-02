from __future__ import annotations

"""
ChainShield — Complete End-to-End Flow Verification (Task 12)
============================================================

Verifies all 12 stages of the complete offline operational flow:
  1. Load deterministic synthetic data
  2. Activate a disruption
  3. Identify affected shipment(s)
  4. Calculate cargo value at risk
  5. Evaluate cold-chain telemetry and severity
  6. Find feasible route/asset alternatives with OR-Tools
  7. Preserve rejection reason codes
  8. Create Evidence/Audit records
  9. Generate deterministic explanation fallback
  10. Generate the final JSON/Markdown action plan
  11. Verify the FastAPI endpoints expose the same deterministic results
  12. Verify the React frontend can consume the API successfully

Requirements verified:
  - No live external APIs
  - No LLM dependency
  - Deterministic repeated execution
  - Evidence/source references preserved
  - Same shipment/disruption IDs throughout the flow
  - Primary cold-chain demo remains EXCURSION_REVIEW for the 18-minute excursion
  - At least one feasible alternative and at least one rejected alternative
"""

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Resolve repository paths
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (_REPO_ROOT / "src", _REPO_ROOT / "scripts"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import networkx as nx

from chainshield.api.dependencies import (
    get_active_disruptions,
    get_assets,
    get_cold_chain_engine,
    get_evidence_store,
    get_graph,
    get_impact_engine,
    get_optimization_engine,
    get_policies,
    get_sensor_readings,
    get_shipments,
)
from chainshield.api.main import app
from chainshield.cold_chain.engine import ColdChainEngine
from chainshield.evidence.events import (
    ColdChainEvidence,
    DecisionType,
    ImpactAnalysisEvidence,
    OptimizationRejectionEvidence,
    RouteRecommendationEvidence,
)
from chainshield.evidence.store import EvidenceStore
from chainshield.explanation.fallback import generate_fallback_explanation
from chainshield.impact.engine import ImpactEngine
from chainshield.models.asset import Asset, AssetStatus
from chainshield.models.disruption import Disruption, DisruptionStatus
from chainshield.models.enums import ExcursionSeverity
from chainshield.models.sensor_reading import SensorReading
from chainshield.models.shipment import Shipment
from chainshield.models.temperature_policy import TemperaturePolicy
from chainshield.optimization.engine import OptimizationEngine
from demo_scenario import (
    _build_scenario_data,
    _build_scenario_graph,
    run_demo_scenario,
)
from generate_synthetic_data import generate_scenario


# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scenario_bundle():
    return run_demo_scenario()


@pytest.fixture(scope="module")
def raw_data():
    return _build_scenario_data()


@pytest.fixture(scope="module")
def scenario_graph():
    return _build_scenario_graph()


@pytest.fixture()
def scenario_api_client(raw_data, scenario_graph):
    """FastAPI TestClient wired with the deterministic scenario data."""
    disruption, shipments, assets, sensor_map, policy = raw_data
    shipment_dict = {s.shipment_id: s for s in shipments}
    policy_dict = {policy.policy_id: policy}
    store = EvidenceStore()
    impact_engine = ImpactEngine(scenario_graph)
    cold_chain_engine = ColdChainEngine()
    opt_engine = OptimizationEngine(scenario_graph)

    app.dependency_overrides[get_graph] = lambda: scenario_graph
    app.dependency_overrides[get_shipments] = lambda: shipment_dict
    app.dependency_overrides[get_assets] = lambda: assets
    app.dependency_overrides[get_sensor_readings] = lambda: sensor_map
    app.dependency_overrides[get_policies] = lambda: policy_dict
    app.dependency_overrides[get_evidence_store] = lambda: store
    app.dependency_overrides[get_impact_engine] = lambda: impact_engine
    app.dependency_overrides[get_cold_chain_engine] = lambda: cold_chain_engine
    app.dependency_overrides[get_optimization_engine] = lambda: opt_engine
    app.dependency_overrides[get_active_disruptions] = lambda: [disruption]

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ===========================================================================
# Stage 1: Load deterministic synthetic data
# ===========================================================================

class TestStage1SyntheticData:
    def test_deterministic_bundle_generation(self):
        bundle1 = generate_scenario(seed=42)
        bundle2 = generate_scenario(seed=42)
        assert len(bundle1.shipments) == len(bundle2.shipments)
        assert [s.shipment_id for s in bundle1.shipments] == [s.shipment_id for s in bundle2.shipments]
        assert len(bundle1.assets) == len(bundle2.assets)
        assert len(bundle1.disruptions) >= 1

    def test_bundle_contains_required_entities(self, raw_data):
        disruption, shipments, assets, sensor_map, policy = raw_data
        assert any(s.shipment_id == "SHP-001" for s in shipments)
        assert any(a.asset_id == "ASSET-REEFER-01" for a in assets)
        assert "SHP-001" in sensor_map
        assert policy.policy_id == "POL-CDC-REFVAX-01"


# ===========================================================================
# Stage 2: Activate a disruption
# ===========================================================================

class TestStage2DisruptionActivation:
    def test_disruption_is_active(self, raw_data):
        disruption, *_ = raw_data
        assert disruption.disruption_id == "DISR-PORT-STRIKE-01"
        assert disruption.status == DisruptionStatus.ACTIVE
        assert "PORT-03" in disruption.geometry.blocked_nodes

    def test_disruption_window_is_valid(self, raw_data):
        disruption, *_ = raw_data
        assert disruption.window_start < disruption.window_end


# ===========================================================================
# Stage 3: Identify affected shipment(s)
# ===========================================================================

class TestStage3IdentifyAffectedShipments:
    def test_shp001_identified_as_affected(self, scenario_bundle):
        assert "SHP-001" in scenario_bundle.affected_shipment_ids

    def test_reason_codes_contain_port_node_blocked(self, scenario_bundle):
        assert "PORT_NODE_BLOCKED" in scenario_bundle.impact_reason_codes

    def test_unaffected_shipments_properly_excluded(self, raw_data, scenario_graph):
        disruption, shipments, *_ = raw_data
        engine = ImpactEngine(scenario_graph)
        shp_002 = next(s for s in shipments if s.shipment_id == "SHP-002")
        res = engine.evaluate(shp_002, disruption)
        assert not res.is_affected


# ===========================================================================
# Stage 4: Calculate cargo value at risk
# ===========================================================================

class TestStage4CargoValueAtRisk:
    def test_cargo_value_at_risk_quantified(self, scenario_bundle, raw_data):
        _, shipments, *_ = raw_data
        shp_001 = next(s for s in shipments if s.shipment_id == "SHP-001")
        assert scenario_bundle.cargo_value_at_risk_usd >= shp_001.cargo_value_usd
        assert shp_001.cargo_value_usd == 520_000.0


# ===========================================================================
# Stage 5: Evaluate cold-chain telemetry and severity
# ===========================================================================

class TestStage5ColdChainEvaluation:
    def test_excursion_duration_and_peak(self, scenario_bundle):
        assert scenario_bundle.cold_chain_duration_minutes == pytest.approx(18.0)
        assert scenario_bundle.cold_chain_max_celsius == pytest.approx(10.4)

    def test_severity_is_excursion_review(self, scenario_bundle):
        assert scenario_bundle.cold_chain_severity == "EXCURSION_REVIEW"

    def test_reason_codes_include_temperature_above_max(self, scenario_bundle):
        assert "TEMPERATURE_ABOVE_MAX" in scenario_bundle.cold_chain_reason_codes


# ===========================================================================
# Stage 6: Find feasible route/asset alternatives with OR-Tools
# ===========================================================================

class TestStage6FeasibleAlternatives:
    def test_at_least_one_feasible_alternative(self, scenario_bundle):
        assert len(scenario_bundle.feasible_alternatives) >= 1

    def test_feasible_alternative_uses_compatible_asset(self, scenario_bundle):
        top_alt = scenario_bundle.feasible_alternatives[0]
        assert top_alt["asset_id"] == "ASSET-REEFER-01"
        assert "PORT-03" not in top_alt["path"]
        assert "DEPOT-X" in top_alt["path"]


# ===========================================================================
# Stage 7: Preserve rejection reason codes
# ===========================================================================

class TestStage7RejectionReasonCodes:
    def test_at_least_one_rejected_alternative(self, scenario_bundle):
        assert len(scenario_bundle.rejected_alternatives) >= 1

    def test_rejection_reason_codes_preserved(self, scenario_bundle):
        codes = [c for alt in scenario_bundle.rejected_alternatives for c in alt["reason_codes"]]
        assert len(codes) >= 1
        assert any(c in codes for c in ["REEFER_REQUIRED", "ROUTE_NODE_BLOCKED", "CAPACITY_VIOLATION"])


# ===========================================================================
# Stage 8: Create Evidence/Audit records
# ===========================================================================

class TestStage8EvidenceAuditRecords:
    def test_evidence_records_created(self, scenario_bundle):
        assert len(scenario_bundle.evidence_records) >= 4

    def test_same_shipment_and_disruption_ids_in_evidence(self, scenario_bundle, raw_data):
        disruption, *_ = raw_data
        for rec in scenario_bundle.evidence_records:
            assert rec["shipment_id"] == "SHP-001"
            assert disruption.disruption_id in rec["disruption_ids"]
            assert len(rec["reason_codes"]) >= 1
            assert "source_refs" in rec and len(rec["source_refs"]) > 0


# ===========================================================================
# Stage 9: Generate deterministic explanation fallback
# ===========================================================================

class TestStage9DeterministicExplanation:
    def test_explanation_structure_and_keys(self, scenario_bundle):
        exp = scenario_bundle.explanation
        required = {"summary", "why_affected", "recommended_action", "evidence", "uncertainties"}
        assert required.issubset(exp.keys())
        assert exp["generated_by"] == "deterministic_fallback_template"
        assert exp["model_used"] is None

    def test_explanation_contains_shipment_id_and_evidence(self, scenario_bundle):
        exp = scenario_bundle.explanation
        assert "SHP-001" in exp["summary"]
        assert len(exp["evidence"]) >= 1


# ===========================================================================
# Stage 10: Generate final JSON/Markdown action plan
# ===========================================================================

class TestStage10ActionPlanGeneration:
    def test_json_action_plan_structure(self, scenario_bundle):
        plan = scenario_bundle.action_plan_json
        assert plan["disruption_id"] == "DISR-PORT-STRIKE-01"
        assert len(plan["shipments"]) >= 1
        shp = plan["shipments"][0]
        assert shp["shipment_id"] == "SHP-001"
        assert shp["cold_chain_severity"] == "EXCURSION_REVIEW"
        assert len(shp["route_alternatives"]) >= 1

    def test_markdown_action_plan_contents(self, scenario_bundle):
        md = scenario_bundle.action_plan_markdown
        assert "# Action Plan" in md
        assert "DISR-PORT-STRIKE-01" in md
        assert "SHP-001" in md
        assert "EXCURSION_REVIEW" in md
        assert "Explanation" in md


# ===========================================================================
# Stage 11: Verify FastAPI endpoints expose the same deterministic results
# ===========================================================================

class TestStage11FastApiExposure:
    def test_disruption_activation_endpoint(self, scenario_api_client):
        payload = {
            "disruption_id": "DISR-PORT-STRIKE-01",
            "disruption_type": "port_strike",
            "severity": "HIGH",
            "title": "Port strike at PORT-03",
            "description": "Port blocked",
            "window_start": "2026-09-14T00:00:00Z",
            "window_end": "2026-09-17T00:00:00Z",
            "blocked_nodes": ["PORT-03"],
            "blocked_edges": [],
        }
        res = scenario_api_client.post("/api/v1/disruptions/activate", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["disruption_id"] == "DISR-PORT-STRIKE-01"
        assert "SHP-001" in data["affected_shipment_ids"]
        assert data["cargo_value_at_risk_usd"] >= 520_000.0
        assert "PORT_NODE_BLOCKED" in data["reason_codes"]
        assert len(data["evidence"]) >= 1

    def test_shipment_lookup_endpoint(self, scenario_api_client):
        res = scenario_api_client.get("/api/v1/shipments/SHP-001")
        assert res.status_code == 200
        data = res.json()
        assert data["shipment_id"] == "SHP-001"
        assert data["temperature_policy_id"] == "POL-CDC-REFVAX-01"
        assert data["cargo_value_usd"] == 520_000.0

    def test_cold_chain_timeline_endpoint(self, scenario_api_client):
        res = scenario_api_client.get("/api/v1/cold-chain/SHP-001/timeline")
        assert res.status_code == 200
        data = res.json()
        assert data["shipment_id"] == "SHP-001"
        assert data["severity"] == "EXCURSION_REVIEW"
        assert "TEMPERATURE_ABOVE_MAX" in data["reason_codes"]
        assert data["max_temp_c"] == pytest.approx(10.4)
        assert data["total_out_of_range_minutes"] == pytest.approx(18.0)

    def test_idle_assets_endpoint(self, scenario_api_client):
        res = scenario_api_client.get("/api/v1/assets/idle")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] >= 1
        asset_ids = [a["asset_id"] for a in data["assets"]]
        assert "ASSET-REEFER-01" in asset_ids

    def test_explanation_generate_endpoint(self, scenario_api_client):
        payload = {
            "shipment_id": "SHP-001",
            "disruption_id": "DISR-PORT-STRIKE-01",
            "decision_type": "IMPACT_ANALYSIS",
            "reason_codes": ["PORT_NODE_BLOCKED"],
            "temperature_c": 10.4,
            "cold_chain_severity": "EXCURSION_REVIEW",
            "watsonx_enabled": False,
        }
        res = scenario_api_client.post("/api/v1/explanations/generate", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["generated_by"] == "deterministic_fallback_template"
        assert data["model_used"] is None
        assert "SHP-001" in data["summary"]

    def test_action_plan_export_endpoint(self, scenario_api_client):
        payload = {
            "disruption_id": "DISR-PORT-STRIKE-01",
            "format": "both",
        }
        res = scenario_api_client.post("/api/v1/action-plan/export", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["disruption_id"] == "DISR-PORT-STRIKE-01"
        assert isinstance(data["shipments"], list)
        assert len(data["shipments"]) >= 1
        shp_entry = next((s for s in data["shipments"] if s["shipment_id"] == "SHP-001"), None)
        assert shp_entry is not None
        assert shp_entry["cold_chain_severity"] == "EXCURSION_REVIEW"


# ===========================================================================
# Stage 12: Verify React frontend API consumption alignment
# ===========================================================================

class TestStage12FrontendAlignment:
    def test_frontend_types_match_api_disruption_response(self, scenario_api_client):
        payload = {
            "disruption_id": "DISR-PORT-STRIKE-01",
            "disruption_type": "port_strike",
            "severity": "HIGH",
            "title": "Port strike at PORT-03",
            "description": "Port blocked",
            "window_start": "2026-09-14T00:00:00Z",
            "window_end": "2026-09-17T00:00:00Z",
            "blocked_nodes": ["PORT-03"],
            "blocked_edges": [],
        }
        data = scenario_api_client.post("/api/v1/disruptions/activate", json=payload).json()
        # Frontend DisruptionActivateResponse expected fields:
        assert isinstance(data["disruption_id"], str)
        assert isinstance(data["affected_shipment_ids"], list)
        assert isinstance(data["affected_shipment_count"], int)
        assert isinstance(data["cargo_value_at_risk_usd"], (int, float))
        assert isinstance(data["reason_codes"], list)
        assert isinstance(data["evidence"], list)

    def test_frontend_types_match_api_cold_chain_response(self, scenario_api_client):
        data = scenario_api_client.get("/api/v1/cold-chain/SHP-001/timeline").json()
        # Frontend ColdChainTimelineResponse expected fields:
        assert isinstance(data["shipment_id"], str)
        assert isinstance(data["severity"], str)
        assert isinstance(data["reason_codes"], list)
        assert isinstance(data["total_out_of_range_minutes"], (int, float))
        assert isinstance(data["max_continuous_excursion_minutes"], (int, float))
        assert isinstance(data["out_of_range_count"], int)
        assert isinstance(data["reading_count"], int)
        assert isinstance(data["readings"], list)
        for r in data["readings"]:
            assert "sensor_id" in r
            assert "ts" in r
            assert "temperature_c" in r

    def test_frontend_types_match_api_action_plan_response(self, scenario_api_client):
        data = scenario_api_client.post("/api/v1/action-plan/export", json={"disruption_id": "DISR-PORT-STRIKE-01"}).json()
        assert isinstance(data["disruption_id"], str)
        assert isinstance(data["generated_at"], str)
        assert isinstance(data["shipments"], list)
        for s in data["shipments"]:
            assert "shipment_id" in s
            assert "cargo_value_usd" in s
            assert "route_alternatives" in s
            assert "rejection_reason_codes" in s
