from __future__ import annotations

"""
ChainShield Task 13 — Offline Hardening Test Suite.

Covers
------
1. Offline configuration (defaults, env parsing, timeouts, redaction)
2. Missing external credentials (no crash, safe degradation)
3. Network-disabled mode (socket blocking: deterministic core makes zero network calls)
4. Deterministic fallback behavior (timeout degradation, error handling, schema compliance)
5. Offline API startup (health endpoints, full endpoint suite functioning offline)
6. No unexpected external network dependency & no hardcoded secrets
"""

import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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
from chainshield.config import (
    ChainShieldConfig,
    _parse_bool,
    _parse_float,
    get_config,
    load_config,
)
from chainshield.database import connect as db_connect
from chainshield.evidence.store import EvidenceStore
from chainshield.explanation import (
    generate_explanation_with_fallback,
    generate_fallback_explanation,
)
from chainshield.impact.engine import ImpactEngine
from chainshield.models.disruption import (
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
)
from chainshield.optimization.engine import OptimizationEngine


# ===========================================================================
# 1. Offline Configuration Tests
# ===========================================================================

class TestOfflineConfiguration:
    """Verify configuration loading and offline default behavior."""

    def test_default_config_is_offline(self) -> None:
        """With an empty environment, the config must default to offline/demo."""
        cfg = load_config(env={})
        assert cfg.demo_mode is True
        assert cfg.watsonx_enabled is False
        assert cfg.network_required is False
        assert cfg.is_offline is True
        assert cfg.can_call_watsonx is False
        assert cfg.watsonx_apikey is None
        assert cfg.watsonx_timeout_seconds == 2.5
        assert cfg.external_call_timeout_seconds == 2.5

    def test_config_from_explicit_offline_env(self) -> None:
        """Config respects DEMO_MODE=true, WATSONX_ENABLED=false, NETWORK_REQUIRED=false."""
        env = {
            "DEMO_MODE": "true",
            "WATSONX_ENABLED": "false",
            "NETWORK_REQUIRED": "false",
        }
        cfg = load_config(env=env)
        assert cfg.demo_mode is True
        assert cfg.watsonx_enabled is False
        assert cfg.network_required is False
        assert cfg.is_offline is True
        assert cfg.can_call_watsonx is False

    @pytest.mark.parametrize(
        "val,expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("enabled", True),
            ("on", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("disabled", False),
            ("off", False),
            ("", False),
            (None, False),
        ],
    )
    def test_parse_bool_robustness(self, val: Any, expected: bool) -> None:
        assert _parse_bool(val, default=False) == expected

    def test_timeout_fallback_on_invalid_value(self) -> None:
        """Invalid timeout values must safely fall back to 2.5s default."""
        cfg = load_config(env={"WATSONX_TIMEOUT_SECONDS": "invalid_number"})
        assert cfg.watsonx_timeout_seconds == 2.5

        cfg_neg = load_config(env={"WATSONX_TIMEOUT_SECONDS": "-5.0"})
        assert cfg_neg.watsonx_timeout_seconds == 2.5

    def test_to_dict_redacts_credentials(self) -> None:
        """to_dict() must redact watsonx API key if present."""
        cfg = load_config(
            env={
                "WATSONX_APIKEY": "super_secret_test_key_12345",
                "WATSONX_PROJECT_ID": "proj-999",
            }
        )
        d = cfg.to_dict(redact_secrets=True)
        assert d["watsonx_apikey"] == "***REDACTED***"
        assert d["watsonx_project_id"] == "proj-999"


# ===========================================================================
# 2. Missing External Credentials Tests
# ===========================================================================

class TestMissingExternalCredentials:
    """Verify application behavior when external credentials are absent."""

    def test_can_call_watsonx_false_when_apikey_missing(self) -> None:
        """Even if WATSONX_ENABLED=true and NETWORK_REQUIRED=true, missing key disables call."""
        cfg = load_config(
            env={
                "WATSONX_ENABLED": "true",
                "NETWORK_REQUIRED": "true",
                "WATSONX_PROJECT_ID": "proj-123",
                # WATSONX_APIKEY is omitted
            }
        )
        assert cfg.can_call_watsonx is False

    def test_can_call_watsonx_false_when_project_id_missing(self) -> None:
        """Missing project_id disables call even if key is present."""
        cfg = load_config(
            env={
                "WATSONX_ENABLED": "true",
                "NETWORK_REQUIRED": "true",
                "WATSONX_APIKEY": "some-key",
            }
        )
        assert cfg.can_call_watsonx is False

    def test_generate_explanation_never_crashes_with_missing_credentials(self) -> None:
        """Calling explanation generator with missing credentials must produce fallback smoothly."""
        cfg = load_config(
            env={
                "WATSONX_ENABLED": "true",
                "NETWORK_REQUIRED": "true",
                # no credentials
            }
        )
        decision = {
            "kind": "impact",
            "shipment_id": "SHP-0042",
            "reason_codes": ["PORT_NODE_BLOCKED"],
            "recommended_route": {},
            "cold_chain": {},
            "evidence": ["Node PORT-03 is blocked"],
        }
        result = generate_explanation_with_fallback(decision, config=cfg)
        assert result["generated_by"] == "deterministic_fallback_template"
        assert "SHP-0042" in result["summary"]


# ===========================================================================
# 3. Network-Disabled Mode (Zero Socket Calls)
# ===========================================================================

class TestNetworkDisabledMode:
    """Verify that deterministic core operations make ZERO network socket calls."""

    @pytest.fixture()
    def guard_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Block all socket connection attempts."""
        def forbidden_connect(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("NETWORK_ACCESS_FORBIDDEN: Unexpected external socket call in offline mode!")

        monkeypatch.setattr(socket, "create_connection", forbidden_connect)
        monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    def test_deterministic_core_runs_with_blocked_sockets(self, guard_network: None) -> None:
        """Impact, cold chain, optimization, and fallback engines must not touch sockets."""
        graph = get_graph()
        impact_engine = ImpactEngine(graph)
        cold_chain_engine = ColdChainEngine()
        opt_engine = OptimizationEngine(graph)

        shipments = _build_demo_shipments()
        assets = _build_demo_assets()
        sensor_readings = _build_demo_sensor_readings()
        policies = _build_demo_policies()

        disruption = Disruption(
            disruption_id="DISRUPT-TEST",
            disruption_type=DisruptionType.PORT_STRIKE,
            severity=DisruptionSeverity.HIGH,
            status=DisruptionStatus.ACTIVE,
            title="Test Port Strike",
            description="Testing network-free execution",
            window_start=datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc),
            geometry=DisruptionGeometry(blocked_nodes=["PORT-03"]),
        )

        # 1. Impact Engine
        impact_results = impact_engine.evaluate_many(list(shipments.values()), disruption)
        assert len(impact_results) == 2

        # 2. Cold Chain Engine
        cc_result = cold_chain_engine.evaluate(
            policies["POL-CDC-01"],
            sensor_readings["SHP-0042"],
        )
        assert cc_result.severity.value == "EXCURSION_REVIEW"

        # 3. Optimization Engine
        opt_result = opt_engine.find_alternatives(shipments["SHP-0042"], assets)
        assert opt_result.shipment_id == "SHP-0042"

        # 4. Fallback Explanation
        exp = generate_explanation_with_fallback(
            {"kind": "impact", "shipment_id": "SHP-0042", "reason_codes": ["PORT_NODE_BLOCKED"]},
            config=ChainShieldConfig(watsonx_enabled=False, network_required=False),
        )
        assert exp["generated_by"] == "deterministic_fallback_template"

        # 5. Local DuckDB Store
        from chainshield.database import create_tables, insert_shipments
        con = db_connect(database=":memory:")
        create_tables(con)
        insert_shipments(con, list(shipments.values()))
        count = con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        assert count >= 1
        con.close()


# ===========================================================================
# 4. Deterministic Fallback Behavior
# ===========================================================================

class TestDeterministicFallbackBehavior:
    """Verify fallback explanation generation and timeout handling."""

    def test_fallback_schema_completeness(self) -> None:
        """Deterministic fallback output must provide all contract keys."""
        decision = {
            "kind": "routing",
            "shipment_id": "SHP-0042",
            "reason_codes": ["PORT_NODE_BLOCKED"],
            "recommended_route": {
                "alternative_id": "ALT-1",
                "carrier_id": "CARRIER-B",
                "path": ["HUB-B", "HUB-D"],
                "total_cost_usd": 1200.0,
                "eta_delta_hours": 2.5,
            },
            "cold_chain": {"severity": "EXCURSION_REVIEW"},
            "evidence": ["Primary port route blocked"],
        }
        res = generate_fallback_explanation(decision)
        required_keys = {
            "summary",
            "why_affected",
            "recommended_action",
            "evidence",
            "uncertainties",
            "generated_by",
            "model_used",
        }
        assert required_keys.issubset(res.keys())
        assert res["generated_by"] == "deterministic_fallback_template"
        assert res["model_used"] is None

    def test_simulated_watsonx_timeout_falls_back_gracefully(self) -> None:
        """When watsonx call exceeds the timeout budget, fallback is returned immediately."""
        import time

        def slow_watsonx_call(*args: Any, **kwargs: Any) -> Any:
            time.sleep(0.2)  # simulate slow network call
            return {"summary": "from watsonx"}

        cfg = ChainShieldConfig(
            watsonx_enabled=True,
            network_required=True,
            watsonx_apikey="fake-key",
            watsonx_project_id="fake-proj",
            watsonx_timeout_seconds=0.05,  # short 50ms budget
        )

        with patch("chainshield.explanation.watsonx._call_watsonx_with_timeout", side_effect=TimeoutError("Timed out")):
            res = generate_explanation_with_fallback(
                {"kind": "impact", "shipment_id": "SHP-0042"},
                config=cfg,
            )
            assert res["generated_by"] == "deterministic_fallback_template"

    def test_simulated_watsonx_exception_falls_back_gracefully(self) -> None:
        """When watsonx call raises any network/HTTP error, fallback is returned."""
        cfg = ChainShieldConfig(
            watsonx_enabled=True,
            network_required=True,
            watsonx_apikey="fake-key",
            watsonx_project_id="fake-proj",
            watsonx_timeout_seconds=2.5,
        )

        with patch("chainshield.explanation.watsonx._call_watsonx_with_timeout", side_effect=ConnectionError("Connection refused")):
            res = generate_explanation_with_fallback(
                {"kind": "impact", "shipment_id": "SHP-0042"},
                config=cfg,
            )
            assert res["generated_by"] == "deterministic_fallback_template"


# ===========================================================================
# 5. Offline API Startup & Endpoints
# ===========================================================================

class TestOfflineApiStartup:
    """Verify FastAPI application starts and serves all endpoints offline."""

    @pytest.fixture()
    def offline_client(self) -> TestClient:
        offline_cfg = ChainShieldConfig(
            demo_mode=True,
            watsonx_enabled=False,
            network_required=False,
        )
        store = EvidenceStore()
        active_disruptions: list[Disruption] = []

        app.dependency_overrides[get_evidence_store] = lambda: store
        app.dependency_overrides[get_active_disruptions] = lambda: active_disruptions
        app.dependency_overrides[get_graph] = lambda: get_graph()
        app.dependency_overrides[get_shipments] = lambda: _build_demo_shipments()
        app.dependency_overrides[get_assets] = lambda: _build_demo_assets()
        app.dependency_overrides[get_sensor_readings] = lambda: _build_demo_sensor_readings()
        app.dependency_overrides[get_policies] = lambda: _build_demo_policies()
        app.dependency_overrides[get_impact_engine] = lambda: ImpactEngine(get_graph())
        app.dependency_overrides[get_cold_chain_engine] = lambda: ColdChainEngine()
        app.dependency_overrides[get_optimization_engine] = lambda: OptimizationEngine(get_graph())
        from chainshield.api.dependencies import get_app_config
        app.dependency_overrides[get_app_config] = lambda: offline_cfg

        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_health_check_offline(self, offline_client: TestClient) -> None:
        """GET /health and /api/v1/health return 200 with offline status."""
        for path in ("/health", "/api/v1/health"):
            resp = offline_client.get(path)
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["demo_mode"] is True
            assert data["watsonx_enabled"] is False
            assert data["network_required"] is False
            assert data["offline"] is True

    def test_all_api_endpoints_work_offline(self, offline_client: TestClient) -> None:
        """All six required API endpoints respond with 200 without network."""
        # 1. Activate disruption
        act_resp = offline_client.post(
            "/api/v1/disruptions/activate",
            json={
                "disruption_id": "PORT_STRIKE_01",
                "disruption_type": "port_strike",
                "severity": "HIGH",
                "window_start": "2026-09-14T00:00:00Z",
                "window_end": "2026-09-17T00:00:00Z",
                "blocked_nodes": ["PORT-03"],
            },
        )
        assert act_resp.status_code == 200
        assert "SHP-0042" in act_resp.json()["affected_shipment_ids"]

        # 2. Get shipment
        shp_resp = offline_client.get("/api/v1/shipments/SHP-0042")
        assert shp_resp.status_code == 200
        assert shp_resp.json()["shipment_id"] == "SHP-0042"

        # 3. Idle assets
        asset_resp = offline_client.get("/api/v1/assets/idle")
        assert asset_resp.status_code == 200
        assert asset_resp.json()["count"] >= 1

        # 4. Cold chain timeline
        cc_resp = offline_client.get("/api/v1/cold-chain/SHP-0042/timeline")
        assert cc_resp.status_code == 200
        assert cc_resp.json()["severity"] == "EXCURSION_REVIEW"

        # 5. Explanation generation (deterministic fallback)
        exp_resp = offline_client.post(
            "/api/v1/explanations/generate",
            json={
                "shipment_id": "SHP-0042",
                "kind": "impact",
                "reason_codes": ["PORT_NODE_BLOCKED"],
            },
        )
        assert exp_resp.status_code == 200
        assert exp_resp.json()["generated_by"] == "deterministic_fallback_template"
        assert exp_resp.json()["watsonx_enabled"] is False

        # 6. Action plan export
        plan_resp = offline_client.post(
            "/api/v1/action-plan/export",
            json={"disruption_id": "PORT_STRIKE_01", "format": "json"},
        )
        assert plan_resp.status_code == 200
        assert len(plan_resp.json()["shipments"]) >= 1


# ===========================================================================
# 6. No Unexpected External Network Dependency & No Hardcoded Secrets
# ===========================================================================

class TestNoUnexpectedNetworkDependency:
    """Verify absence of hardcoded secrets or accidental external network calls."""

    def test_no_hardcoded_secrets_in_source(self) -> None:
        """Scan source files to verify no API keys, tokens, or passwords are hardcoded."""
        root = Path(__file__).parent.parent.parent / "src" / "chainshield"
        py_files = list(root.glob("**/*.py"))
        assert len(py_files) > 0

        secret_patterns = [
            re.compile(r"""(?:api[_-]?key|secret|password|token)\s*=\s*['"][a-zA-Z0-9_\-]{16,}['"]""", re.I),
            re.compile(r"""(?:bearer\s+[a-zA-Z0-9_\-\.]{20,})""", re.I),
        ]

        for py_file in py_files:
            content = py_file.read_text(encoding="utf-8")
            for pattern in secret_patterns:
                matches = pattern.findall(content)
                assert not matches, f"Possible hardcoded secret in {py_file.name}: {matches}"

    def test_preflight_demo_runs_offline_cleanly(self) -> None:
        """Preflight demo script checks must pass in strict mode."""
        import scripts.preflight_demo as pfd

        r1 = pfd.check_duckdb_schema()
        assert r1[0] == pfd.PASS

        r2 = pfd.check_networkx_impact_engine()
        assert r2[0] == pfd.PASS

        r3 = pfd.check_ortools_feasibility()
        assert r3[0] in (pfd.PASS, pfd.SKIP)

        r4 = pfd.check_cold_chain_policy_engine()
        assert r4[0] == pfd.PASS

        r5 = pfd.check_deterministic_fallback()
        assert r5[0] == pfd.PASS
