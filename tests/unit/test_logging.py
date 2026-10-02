from __future__ import annotations

"""
ChainShield Task 14 — Deterministic Application Logging and Observability Test Suite.

Covers
------
1. Logging configuration (idempotency, level filtering, JSON & text formatters)
2. Required structured fields on key operational events
3. Strict secret redaction (no API keys, tokens, or passwords in log output)
4. API error logging (HTTP 404, exceptions, structured path & status)
5. Deterministic operational event logging across the scenario flow
"""

import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chainshield.api.dependencies import (
    _build_demo_assets,
    _build_demo_policies,
    _build_demo_sensor_readings,
    _build_demo_shipments,
    get_active_disruptions,
    get_app_config,
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
from chainshield.config import ChainShieldConfig
from chainshield.evidence.events import (
    ColdChainEvidence,
    DecisionType,
    ImpactAnalysisEvidence,
)
from chainshield.evidence.store import EvidenceStore
from chainshield.explanation import generate_explanation_with_fallback
from chainshield.impact.engine import ImpactEngine
from chainshield.logging import (
    ALL_EVENTS,
    EVENT_ACTION_PLAN_EXPORT,
    EVENT_API_ERROR,
    EVENT_APP_STARTUP,
    EVENT_COLD_CHAIN_EVALUATION,
    EVENT_DISRUPTION_ACTIVATION,
    EVENT_EVIDENCE_CREATION,
    EVENT_EXPLANATION_GENERATION,
    EVENT_IMPACT_EVALUATION,
    EVENT_OPTIMIZATION_EXECUTION,
    StructuredLogFormatter,
    get_logger,
    log_event,
    redact_secrets,
    setup_logging,
)
from chainshield.models.disruption import (
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
)
from chainshield.optimization.engine import OptimizationEngine


class LogCaptureHandler(logging.Handler):
    """Memory handler that captures LogRecord objects and formatted strings."""

    def __init__(self, json_format: bool = True) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.lines: list[str] = []
        self.setFormatter(StructuredLogFormatter(json_format=json_format))

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.lines.append(self.format(record))


# ===========================================================================
# 1. Logging Configuration Tests
# ===========================================================================

class TestLoggingConfiguration:
    """Verify logging setup, idempotency, and formatting modes."""

    def test_setup_logging_idempotent(self) -> None:
        """Repeated calls to setup_logging must not add duplicate handlers."""
        logger = logging.getLogger("chainshield")
        initial_count = len([
            h for h in logger.handlers
            if isinstance(getattr(h, "formatter", None), StructuredLogFormatter)
        ])

        setup_logging(level=logging.INFO)
        setup_logging(level=logging.INFO)
        setup_logging(level=logging.INFO)

        chainshield_handlers = [
            h for h in logger.handlers
            if isinstance(getattr(h, "formatter", None), StructuredLogFormatter)
        ]
        assert len(chainshield_handlers) == 1

    def test_json_formatter_produces_valid_json(self) -> None:
        """StructuredLogFormatter in JSON mode emits parseable JSON lines."""
        handler = LogCaptureHandler(json_format=True)
        test_logger = get_logger("test_json")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        log_event(
            test_logger,
            logging.INFO,
            EVENT_DISRUPTION_ACTIVATION,
            "Disruption activated",
            disruption_id="DISR-01",
            reason_codes=["PORT_NODE_BLOCKED"],
        )

        assert len(handler.lines) == 1
        payload = json.loads(handler.lines[0])
        assert payload["event"] == EVENT_DISRUPTION_ACTIVATION
        assert payload["disruption_id"] == "DISR-01"
        assert payload["reason_codes"] == ["PORT_NODE_BLOCKED"]
        assert payload["level"] == "INFO"
        assert "timestamp" in payload

    def test_text_formatter_produces_structured_line(self) -> None:
        """StructuredLogFormatter in text mode emits readable key-value line."""
        handler = LogCaptureHandler(json_format=False)
        test_logger = get_logger("test_text")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        log_event(
            test_logger,
            logging.INFO,
            EVENT_IMPACT_EVALUATION,
            "Impact check complete",
            shipment_id="SHP-0042",
            decision_type="impact_analysis",
            reason_codes=["PORT_NODE_BLOCKED"],
        )

        assert len(handler.lines) == 1
        line = handler.lines[0]
        assert "event=IMPACT_EVALUATION" in line
        assert "shipment_id=SHP-0042" in line
        assert "decision_type=impact_analysis" in line
        assert "PORT_NODE_BLOCKED" in line

    def test_log_level_filtering(self) -> None:
        """Messages below the configured log level are not emitted."""
        handler = LogCaptureHandler(json_format=True)
        test_logger = get_logger("test_level")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.WARNING)

        log_event(test_logger, logging.INFO, "IGNORE_ME", "Info level message")
        assert len(handler.lines) == 0

        log_event(test_logger, logging.WARNING, "WARN_ME", "Warning level message")
        assert len(handler.lines) == 1


# ===========================================================================
# 2. Required Fields on Key Events
# ===========================================================================

class TestRequiredFieldsOnKeyEvents:
    """Verify that all standard operational events provide required context fields."""

    @pytest.mark.parametrize("event_name", list(ALL_EVENTS))
    def test_all_operational_events_support_standard_fields(self, event_name: str) -> None:
        """Every event formatted through StructuredLogFormatter contains standard keys."""
        handler = LogCaptureHandler(json_format=True)
        test_logger = get_logger(f"test_fields_{event_name}")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        log_event(
            test_logger,
            logging.INFO,
            event_name,
            f"Testing {event_name}",
            shipment_id="SHP-TEST",
            disruption_id="DISR-TEST",
            asset_id="ASSET-TEST",
            decision_type="test_decision",
            reason_codes=["CODE_A", "CODE_B"],
        )

        assert len(handler.lines) == 1
        data = json.loads(handler.lines[0])

        required_keys = [
            "timestamp",
            "level",
            "event",
            "shipment_id",
            "disruption_id",
            "asset_id",
            "decision_type",
            "reason_codes",
            "message",
        ]
        for key in required_keys:
            assert key in data, f"Key '{key}' missing from event {event_name}"

        assert data["event"] == event_name
        assert data["shipment_id"] == "SHP-TEST"
        assert data["disruption_id"] == "DISR-TEST"
        assert data["asset_id"] == "ASSET-TEST"
        assert data["decision_type"] == "test_decision"
        assert data["reason_codes"] == ["CODE_A", "CODE_B"]


# ===========================================================================
# 3. No Secrets in Log Output
# ===========================================================================

class TestNoSecretsInLogOutput:
    """Verify that credentials, tokens, and API keys are strictly redacted."""

    def test_redact_secrets_in_dict_and_strings(self) -> None:
        sensitive = {
            "watsonx_apikey": "secret-api-key-9999999",
            "token": "token-xyz-1234567890",
            "nested": {
                "auth_password": "super-password-456",
                "normal": "safe_value",
            },
            "msg": "Authorization: bearer a1b2c3d4e5f6g7h8i9j0k1l2m3",
        }
        clean = redact_secrets(sensitive)
        assert clean["watsonx_apikey"] == "***REDACTED***"
        assert clean["token"] == "***REDACTED***"
        assert clean["nested"]["auth_password"] == "***REDACTED***"
        assert clean["nested"]["normal"] == "safe_value"
        assert "bearer ***REDACTED***" in clean["msg"]

    def test_log_formatter_masks_secrets_automatically(self) -> None:
        """StructuredLogFormatter must mask secrets in message and extra kwargs."""
        handler = LogCaptureHandler(json_format=True)
        test_logger = get_logger("test_secrets")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        log_event(
            test_logger,
            logging.INFO,
            EVENT_APP_STARTUP,
            "Connecting with bearer secret_token_value_123456",
            watsonx_apikey="private-key-abcdef-123456789",
            secret="shh-secret",
        )

        assert len(handler.lines) == 1
        output = handler.lines[0]
        assert "private-key-abcdef-123456789" not in output
        assert "secret_token_value_123456" not in output
        assert "shh-secret" not in output
        assert "***REDACTED***" in output


# ===========================================================================
# 4. API Error Logging
# ===========================================================================

class TestApiErrorLogging:
    """Verify HTTP and runtime API errors are logged with structured context."""

    @pytest.fixture()
    def client_with_log_capture(self) -> tuple[TestClient, LogCaptureHandler]:
        handler = LogCaptureHandler(json_format=True)
        api_logger = get_logger("api")
        api_logger.addHandler(handler)
        api_logger.setLevel(logging.INFO)

        store = EvidenceStore()
        active_disruptions: list[Disruption] = []
        offline_cfg = ChainShieldConfig(demo_mode=True, watsonx_enabled=False, network_required=False)

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
        app.dependency_overrides[get_app_config] = lambda: offline_cfg

        client = TestClient(app)
        yield client, handler

        app.dependency_overrides.clear()
        api_logger.removeHandler(handler)

    def test_http_404_logs_api_error(
        self, client_with_log_capture: tuple[TestClient, LogCaptureHandler]
    ) -> None:
        client, handler = client_with_log_capture
        resp = client.get("/api/v1/shipments/SHP-NONEXISTENT")
        assert resp.status_code == 404

        error_logs = [
            json.loads(line) for line in handler.lines
            if "API_ERROR" in line
        ]
        assert len(error_logs) >= 1
        err = error_logs[0]
        assert err["event"] == EVENT_API_ERROR
        assert err["status_code"] == 404
        assert "/api/v1/shipments/SHP-NONEXISTENT" in err["path"]
        assert err["method"] == "GET"


# ===========================================================================
# 5. Deterministic Operational Event Logging
# ===========================================================================

class TestDeterministicOperationalEventLogging:
    """Verify logging across engines during scenario execution."""

    def test_scenario_execution_logs_operational_events(self) -> None:
        """Exercising the scenario flow produces structured events in order."""
        handler = LogCaptureHandler(json_format=True)
        root_cs_logger = logging.getLogger("chainshield")
        root_cs_logger.addHandler(handler)
        root_cs_logger.setLevel(logging.INFO)

        graph = get_graph()
        impact_engine = ImpactEngine(graph)
        cold_chain_engine = ColdChainEngine()
        opt_engine = OptimizationEngine(graph)
        store = EvidenceStore()

        shipments = _build_demo_shipments()
        assets = _build_demo_assets()
        policies = _build_demo_policies()
        readings = _build_demo_sensor_readings()

        disruption = Disruption(
            disruption_id="DISR-LOG-TEST",
            disruption_type=DisruptionType.PORT_STRIKE,
            severity=DisruptionSeverity.HIGH,
            status=DisruptionStatus.ACTIVE,
            title="Logging Test Disruption",
            description="Testing logging",
            window_start=datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc),
            geometry=DisruptionGeometry(blocked_nodes=["PORT-03"]),
        )

        # 1. Impact evaluation
        impact_results = impact_engine.evaluate_many(list(shipments.values()), disruption)
        assert len(impact_results) == 2

        # 2. Cold-chain evaluation
        cc_result = cold_chain_engine.evaluate(policies["POL-CDC-01"], readings["SHP-0042"])
        assert cc_result.severity.value == "EXCURSION_REVIEW"

        # 3. Optimization execution
        opt_result = opt_engine.find_alternatives(shipments["SHP-0042"], assets)
        assert opt_result.shipment_id == "SHP-0042"

        # 4. Evidence creation
        record = ImpactAnalysisEvidence(
            decision_type=DecisionType.IMPACT_ANALYSIS,
            shipment_id="SHP-0042",
            reason_codes=["PORT_NODE_BLOCKED"],
            source_refs={"disruption_id": "DISR-LOG-TEST"},
        )
        store.add(record)

        # 5. Explanation generation
        explanation = generate_explanation_with_fallback(
            {
                "kind": "impact",
                "shipment_id": "SHP-0042",
                "disruption": "DISR-LOG-TEST",
                "reason_codes": ["PORT_NODE_BLOCKED"],
            },
            config=ChainShieldConfig(watsonx_enabled=False, network_required=False),
        )
        assert explanation["generated_by"] == "deterministic_fallback_template"

        # Inspect captured events
        captured_events = [json.loads(line)["event"] for line in handler.lines]

        assert EVENT_IMPACT_EVALUATION in captured_events
        assert EVENT_COLD_CHAIN_EVALUATION in captured_events
        assert EVENT_OPTIMIZATION_EXECUTION in captured_events
        assert EVENT_EVIDENCE_CREATION in captured_events
        assert EVENT_EXPLANATION_GENERATION in captured_events

        root_cs_logger.removeHandler(handler)
