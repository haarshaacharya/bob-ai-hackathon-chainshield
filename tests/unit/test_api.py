from __future__ import annotations

"""
Unit tests for src/chainshield/api/main.py

Covers all eight required scenarios:
  1. Successful disruption activation
  2. Shipment lookup (valid ID)
  3. Idle asset lookup
  4. Cold-chain timeline
  5. Explanation fallback (deterministic, watsonx disabled)
  6. Action-plan export (JSON and Markdown)
  7. Invalid shipment ID → 404
  8. Deterministic repeated response behaviour

Uses FastAPI TestClient; no live network, no external credentials.
Dependency overrides swap in isolated, deterministic demo data for each test.
"""

import copy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from chainshield.api.dependencies import (
    _build_demo_assets,
    _build_demo_policies,
    _build_demo_sensor_readings,
    _build_demo_shipments,
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
from chainshield.evidence.store import EvidenceStore
from chainshield.impact.engine import ImpactEngine
from chainshield.optimization.engine import OptimizationEngine


# ---------------------------------------------------------------------------
# Fixtures — fresh isolated state for every test
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Return a TestClient with all dependency overrides applied.

    Each call produces a brand-new EvidenceStore so tests do not bleed
    state into each other.
    """
    graph = get_graph()
    shipments = _build_demo_shipments()
    assets = _build_demo_assets()
    readings = _build_demo_sensor_readings()
    policies = _build_demo_policies()
    store = EvidenceStore()
    impact_engine = ImpactEngine(graph)
    cold_chain_engine = ColdChainEngine()
    opt_engine = OptimizationEngine(graph)
    disruptions: list = []

    app.dependency_overrides[get_shipments] = lambda: shipments
    app.dependency_overrides[get_assets] = lambda: assets
    app.dependency_overrides[get_sensor_readings] = lambda: readings
    app.dependency_overrides[get_policies] = lambda: policies
    app.dependency_overrides[get_evidence_store] = lambda: store
    app.dependency_overrides[get_impact_engine] = lambda: impact_engine
    app.dependency_overrides[get_cold_chain_engine] = lambda: cold_chain_engine
    app.dependency_overrides[get_optimization_engine] = lambda: opt_engine
    app.dependency_overrides[get_active_disruptions] = lambda: disruptions

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# Shared disruption payload (mirrors the preflight_demo.py scenario)
DISRUPTION_PAYLOAD = {
    "disruption_id": "PORT_STRIKE_01",
    "disruption_type": "port_strike",
    "severity": "HIGH",
    "title": "Port of Aden strike action",
    "description": "Test disruption",
    "window_start": "2026-09-14T00:00:00Z",
    "window_end": "2026-09-17T00:00:00Z",
    "blocked_nodes": ["PORT-03"],
    "blocked_edges": [],
}


# ---------------------------------------------------------------------------
# 1. Successful disruption activation
# ---------------------------------------------------------------------------

class TestDisruptionActivation:
    def test_activation_returns_200(self, client: TestClient) -> None:
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        assert resp.status_code == 200

    def test_affected_shipment_identified(self, client: TestClient) -> None:
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        data = resp.json()
        assert "SHP-0042" in data["affected_shipment_ids"]

    def test_unaffected_shipment_excluded(self, client: TestClient) -> None:
        """SHP-0099 takes the bypass route (HUB-A → HUB-D) and must not be affected."""
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        data = resp.json()
        assert "SHP-0099" not in data["affected_shipment_ids"]

    def test_reason_codes_returned(self, client: TestClient) -> None:
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        data = resp.json()
        assert "PORT_NODE_BLOCKED" in data["reason_codes"]

    def test_cargo_value_at_risk_positive(self, client: TestClient) -> None:
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        data = resp.json()
        assert data["cargo_value_at_risk_usd"] > 0

    def test_evidence_records_returned(self, client: TestClient) -> None:
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        data = resp.json()
        assert isinstance(data["evidence"], list)
        assert len(data["evidence"]) > 0
        # Each evidence record must have a record_id and reason_codes
        for rec in data["evidence"]:
            assert "record_id" in rec
            assert "reason_codes" in rec

    def test_disruption_id_echoed(self, client: TestClient) -> None:
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        assert resp.json()["disruption_id"] == "PORT_STRIKE_01"

    def test_affected_count_matches_list(self, client: TestClient) -> None:
        resp = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)
        data = resp.json()
        assert data["affected_shipment_count"] == len(data["affected_shipment_ids"])


# ---------------------------------------------------------------------------
# 2. Shipment lookup
# ---------------------------------------------------------------------------

class TestShipmentLookup:
    def test_known_shipment_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/shipments/SHP-0042")
        assert resp.status_code == 200

    def test_shipment_fields_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/shipments/SHP-0042")
        data = resp.json()
        assert data["shipment_id"] == "SHP-0042"
        assert "status" in data
        assert "is_disrupted" in data
        assert "reason_codes" in data
        assert "cargo_value_usd" in data

    def test_shipment_mode_returned(self, client: TestClient) -> None:
        resp = client.get("/api/v1/shipments/SHP-0042")
        assert resp.json()["mode"] == "sea"

    def test_temperature_policy_id_returned(self, client: TestClient) -> None:
        resp = client.get("/api/v1/shipments/SHP-0042")
        assert resp.json()["temperature_policy_id"] == "POL-CDC-01"

    def test_second_shipment_accessible(self, client: TestClient) -> None:
        resp = client.get("/api/v1/shipments/SHP-0099")
        assert resp.status_code == 200
        assert resp.json()["shipment_id"] == "SHP-0099"


# ---------------------------------------------------------------------------
# 3. Idle asset lookup
# ---------------------------------------------------------------------------

class TestIdleAssets:
    def test_idle_assets_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/assets/idle")
        assert resp.status_code == 200

    def test_all_available_assets_returned(self, client: TestClient) -> None:
        resp = client.get("/api/v1/assets/idle")
        data = resp.json()
        assert data["count"] == 2  # both demo assets are AVAILABLE
        assert len(data["assets"]) == 2

    def test_asset_fields_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/assets/idle")
        for asset in resp.json()["assets"]:
            assert "asset_id" in asset
            assert "status" in asset
            assert asset["status"] == "available"
            assert "reefer_capable" in asset
            assert "capacity_kg" in asset

    def test_reefer_capable_asset_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/assets/idle")
        reefer_assets = [a for a in resp.json()["assets"] if a["reefer_capable"]]
        assert len(reefer_assets) >= 1

    def test_count_matches_list_length(self, client: TestClient) -> None:
        resp = client.get("/api/v1/assets/idle")
        data = resp.json()
        assert data["count"] == len(data["assets"])


# ---------------------------------------------------------------------------
# 4. Cold-chain timeline
# ---------------------------------------------------------------------------

class TestColdChainTimeline:
    def test_timeline_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        assert resp.status_code == 200

    def test_severity_is_excursion_review(self, client: TestClient) -> None:
        """The demo readings (max 10.4 °C, ~18 min OOR) must classify as EXCURSION_REVIEW."""
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        assert resp.json()["severity"] == "EXCURSION_REVIEW"

    def test_reason_codes_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        data = resp.json()
        assert isinstance(data["reason_codes"], list)
        assert len(data["reason_codes"]) > 0

    def test_temperature_bounds_returned(self, client: TestClient) -> None:
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        data = resp.json()
        assert data["max_temp_c"] == pytest.approx(10.4)
        assert data["min_temp_c"] == pytest.approx(6.4)

    def test_readings_returned(self, client: TestClient) -> None:
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        data = resp.json()
        assert data["reading_count"] == 5
        assert len(data["readings"]) == 5

    def test_evidence_returned(self, client: TestClient) -> None:
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        evidence = resp.json()["evidence"]
        assert "record_id" in evidence
        assert evidence["severity"] == "EXCURSION_REVIEW"

    def test_policy_id_returned(self, client: TestClient) -> None:
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        assert resp.json()["policy_id"] == "POL-CDC-01"

    def test_dry_goods_shipment_no_policy(self, client: TestClient) -> None:
        """SHP-0099 has no temperature policy; severity must be POLICY_REQUIRED."""
        resp = client.get("/api/v1/cold-chain/SHP-0099/timeline")
        assert resp.status_code == 200
        assert resp.json()["severity"] == "POLICY_REQUIRED"


# ---------------------------------------------------------------------------
# 5. Explanation fallback
# ---------------------------------------------------------------------------

class TestExplanationFallback:
    def _payload(self) -> dict:
        return {
            "shipment_id": "SHP-0042",
            "disruption": "PORT_STRIKE_01",
            "kind": "impact",
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
            "evidence": [],
        }

    def test_explanation_returns_200(self, client: TestClient) -> None:
        resp = client.post("/api/v1/explanations/generate", json=self._payload())
        assert resp.status_code == 200

    def test_generated_by_is_deterministic_fallback(self, client: TestClient) -> None:
        resp = client.post("/api/v1/explanations/generate", json=self._payload())
        assert resp.json()["generated_by"] == "deterministic_fallback_template"

    def test_model_used_is_none(self, client: TestClient) -> None:
        resp = client.post("/api/v1/explanations/generate", json=self._payload())
        assert resp.json()["model_used"] is None

    def test_summary_contains_shipment_id(self, client: TestClient) -> None:
        resp = client.post("/api/v1/explanations/generate", json=self._payload())
        assert "SHP-0042" in resp.json()["summary"]

    def test_reason_codes_in_evidence(self, client: TestClient) -> None:
        resp = client.post("/api/v1/explanations/generate", json=self._payload())
        data = resp.json()
        for code in ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"]:
            assert code in data["evidence"]

    def test_required_keys_present(self, client: TestClient) -> None:
        resp = client.post("/api/v1/explanations/generate", json=self._payload())
        required = {"summary", "why_affected", "recommended_action", "evidence", "uncertainties"}
        assert required.issubset(resp.json().keys())

    def test_watsonx_enabled_field_present(self, client: TestClient) -> None:
        resp = client.post("/api/v1/explanations/generate", json=self._payload())
        assert "watsonx_enabled" in resp.json()

    def test_watsonx_never_determines_operational_result(self, client: TestClient) -> None:
        """Regardless of WATSONX_ENABLED env var, the result must always be the
        deterministic fallback and model_used must be None."""
        import os
        os.environ["WATSONX_ENABLED"] = "true"
        try:
            resp = client.post("/api/v1/explanations/generate", json=self._payload())
        finally:
            os.environ.pop("WATSONX_ENABLED", None)
        assert resp.json()["generated_by"] == "deterministic_fallback_template"
        assert resp.json()["model_used"] is None


# ---------------------------------------------------------------------------
# 6. Action-plan export
# ---------------------------------------------------------------------------

class TestActionPlanExport:
    def _activate(self, client: TestClient) -> None:
        """Activate the demo disruption to populate the evidence store first."""
        client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD)

    def test_export_json_returns_200(self, client: TestClient) -> None:
        self._activate(client)
        resp = client.post(
            "/api/v1/action-plan/export",
            json={"disruption_id": "PORT_STRIKE_01", "format": "json"},
        )
        assert resp.status_code == 200

    def test_export_contains_affected_shipment(self, client: TestClient) -> None:
        self._activate(client)
        resp = client.post(
            "/api/v1/action-plan/export",
            json={"disruption_id": "PORT_STRIKE_01", "format": "json"},
        )
        data = resp.json()
        shipment_ids = [s["shipment_id"] for s in data["shipments"]]
        assert "SHP-0042" in shipment_ids

    def test_export_cold_chain_severity_present(self, client: TestClient) -> None:
        self._activate(client)
        resp = client.post(
            "/api/v1/action-plan/export",
            json={"disruption_id": "PORT_STRIKE_01", "format": "json"},
        )
        data = resp.json()
        shp_entry = next(s for s in data["shipments"] if s["shipment_id"] == "SHP-0042")
        assert shp_entry["cold_chain_severity"] == "EXCURSION_REVIEW"

    def test_export_markdown_format(self, client: TestClient) -> None:
        self._activate(client)
        resp = client.post(
            "/api/v1/action-plan/export",
            json={"disruption_id": "PORT_STRIKE_01", "format": "markdown"},
        )
        data = resp.json()
        assert data["format"] == "markdown"
        assert data["markdown"] is not None
        assert "PORT_STRIKE_01" in data["markdown"]
        assert "SHP-0042" in data["markdown"]

    def test_export_route_alternatives_or_rejection_codes(self, client: TestClient) -> None:
        """Each shipment entry must have either feasible alternatives or rejection codes."""
        self._activate(client)
        resp = client.post(
            "/api/v1/action-plan/export",
            json={"disruption_id": "PORT_STRIKE_01", "format": "json"},
        )
        for entry in resp.json()["shipments"]:
            has_alternatives = len(entry["route_alternatives"]) > 0
            has_rejection = len(entry["rejection_reason_codes"]) > 0
            assert has_alternatives or has_rejection, (
                f"Shipment {entry['shipment_id']} has neither alternatives nor rejection codes"
            )

    def test_export_generated_at_is_utc(self, client: TestClient) -> None:
        self._activate(client)
        resp = client.post(
            "/api/v1/action-plan/export",
            json={"disruption_id": "PORT_STRIKE_01", "format": "json"},
        )
        generated_at = resp.json()["generated_at"]
        assert generated_at is not None
        # Must be parseable as an ISO timestamp
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# 7. Invalid shipment ID → 404
# ---------------------------------------------------------------------------

class TestInvalidIds:
    def test_unknown_shipment_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/v1/shipments/SHP-DOES-NOT-EXIST")
        assert resp.status_code == 404

    def test_unknown_shipment_cold_chain_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/v1/cold-chain/SHP-DOES-NOT-EXIST/timeline")
        assert resp.status_code == 404

    def test_unknown_shipment_explanation_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/explanations/generate",
            json={
                "shipment_id": "SHP-DOES-NOT-EXIST",
                "disruption": "X",
                "kind": "impact",
                "reason_codes": [],
            },
        )
        assert resp.status_code == 404

    def test_404_detail_mentions_shipment_id(self, client: TestClient) -> None:
        resp = client.get("/api/v1/shipments/SHP-PHANTOM")
        assert "SHP-PHANTOM" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8. Deterministic repeated response behaviour
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_disruption_activation_is_deterministic(self, client: TestClient) -> None:
        """Two identical activations must produce identical affected_shipment_ids
        and reason_codes (evidence record_ids are deterministic too)."""
        r1 = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD).json()
        # Fresh client is NOT used here — same store, second call is idempotent
        r2 = client.post("/api/v1/disruptions/activate", json=DISRUPTION_PAYLOAD).json()
        assert r1["affected_shipment_ids"] == r2["affected_shipment_ids"]
        assert r1["reason_codes"] == r2["reason_codes"]
        assert r1["cargo_value_at_risk_usd"] == r2["cargo_value_at_risk_usd"]

    def test_shipment_lookup_is_deterministic(self, client: TestClient) -> None:
        r1 = client.get("/api/v1/shipments/SHP-0042").json()
        r2 = client.get("/api/v1/shipments/SHP-0042").json()
        assert r1 == r2

    def test_cold_chain_timeline_is_deterministic(self, client: TestClient) -> None:
        r1 = client.get("/api/v1/cold-chain/SHP-0042/timeline").json()
        r2 = client.get("/api/v1/cold-chain/SHP-0042/timeline").json()
        # Remove evidence record_id and timestamp fields since they are content-stable
        # but include timestamps; compare the classification fields that matter
        assert r1["severity"] == r2["severity"]
        assert r1["reason_codes"] == r2["reason_codes"]
        assert r1["max_temp_c"] == r2["max_temp_c"]
        assert r1["min_temp_c"] == r2["min_temp_c"]

    def test_explanation_is_deterministic(self, client: TestClient) -> None:
        payload = {
            "shipment_id": "SHP-0042",
            "disruption": "PORT_STRIKE_01",
            "kind": "impact",
            "reason_codes": ["PORT_NODE_BLOCKED"],
            "recommended_route": {},
            "cold_chain": {},
            "evidence": [],
        }
        r1 = client.post("/api/v1/explanations/generate", json=payload).json()
        r2 = client.post("/api/v1/explanations/generate", json=payload).json()
        # summary, why_affected, recommended_action must be identical
        for key in ("summary", "why_affected", "recommended_action", "generated_by"):
            assert r1[key] == r2[key], f"Field '{key}' is not deterministic"

    def test_idle_assets_is_deterministic(self, client: TestClient) -> None:
        r1 = client.get("/api/v1/assets/idle").json()
        r2 = client.get("/api/v1/assets/idle").json()
        assert r1 == r2
