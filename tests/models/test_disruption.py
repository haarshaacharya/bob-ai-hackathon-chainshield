from __future__ import annotations

"""
Unit tests for Disruption, DisruptionGeometry data contracts.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from chainshield.models.disruption import (
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
)


T_START = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
T_END = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)

VALID_DISRUPTION = dict(
    disruption_id="PORT_STRIKE_01",
    disruption_type=DisruptionType.PORT_STRIKE,
    severity=DisruptionSeverity.HIGH,
    status=DisruptionStatus.ACTIVE,
    title="Port of Aden strike action",
    window_start=T_START,
    window_end=T_END,
    geometry=DisruptionGeometry(blocked_nodes=["PORT-03"]),
)


# ---------------------------------------------------------------------------
# DisruptionGeometry
# ---------------------------------------------------------------------------


class TestDisruptionGeometry:
    def test_empty_geometry(self):
        geo = DisruptionGeometry()
        assert geo.blocked_nodes == []
        assert geo.blocked_edges == []
        assert geo.geometry_wkt is None

    def test_with_blocked_nodes(self):
        geo = DisruptionGeometry(blocked_nodes=["PORT-03", "HUB-X"])
        assert "PORT-03" in geo.blocked_nodes

    def test_with_radius(self):
        geo = DisruptionGeometry(center_lat=12.0, center_lon=45.0, radius_km=50.0)
        assert geo.radius_km == 50.0

    def test_radius_must_be_positive(self):
        with pytest.raises(ValidationError):
            DisruptionGeometry(radius_km=0.0)

    def test_lat_lon_bounds(self):
        with pytest.raises(ValidationError):
            DisruptionGeometry(center_lat=91.0)
        with pytest.raises(ValidationError):
            DisruptionGeometry(center_lon=-181.0)


# ---------------------------------------------------------------------------
# Disruption
# ---------------------------------------------------------------------------


class TestDisruption:
    def test_valid_disruption(self):
        d = Disruption(**VALID_DISRUPTION)
        assert d.disruption_id == "PORT_STRIKE_01"
        assert d.status == DisruptionStatus.ACTIVE
        assert "PORT-03" in d.geometry.blocked_nodes

    def test_window_inverted_rejected(self):
        with pytest.raises(ValidationError, match="window_start"):
            Disruption(**{**VALID_DISRUPTION, "window_start": T_END, "window_end": T_START})

    def test_window_equal_rejected(self):
        with pytest.raises(ValidationError, match="window_start"):
            Disruption(**{**VALID_DISRUPTION, "window_start": T_START, "window_end": T_START})

    def test_default_geometry_empty(self):
        d = Disruption(**{k: v for k, v in VALID_DISRUPTION.items() if k != "geometry"})
        assert d.geometry.blocked_nodes == []

    def test_affected_shipment_ids_default_empty(self):
        d = Disruption(**VALID_DISRUPTION)
        assert d.affected_shipment_ids == []

    def test_affected_shipment_ids_populated(self):
        d = Disruption(
            **{
                **VALID_DISRUPTION,
                "affected_shipment_ids": ["SHP-0042"],
                "affected_shipment_count": 1,
                "cargo_value_at_risk_usd": 520_000.0,
                "reason_codes": ["PORT_NODE_BLOCKED"],
            }
        )
        assert d.affected_shipment_count == 1
        assert d.cargo_value_at_risk_usd == 520_000.0
        assert "PORT_NODE_BLOCKED" in d.reason_codes

    def test_cargo_value_negative_rejected(self):
        with pytest.raises(ValidationError):
            Disruption(**{**VALID_DISRUPTION, "cargo_value_at_risk_usd": -1.0})

    def test_affected_count_negative_rejected(self):
        with pytest.raises(ValidationError):
            Disruption(**{**VALID_DISRUPTION, "affected_shipment_count": -1})

    def test_all_disruption_types_accepted(self):
        for dtype in DisruptionType:
            d = Disruption(**{**VALID_DISRUPTION, "disruption_type": dtype})
            assert d.disruption_type == dtype

    def test_all_severity_levels_accepted(self):
        for sev in DisruptionSeverity:
            d = Disruption(**{**VALID_DISRUPTION, "severity": sev})
            assert d.severity == sev

    def test_resolved_status_with_timestamp(self):
        resolved_at = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        d = Disruption(
            **{**VALID_DISRUPTION, "status": DisruptionStatus.RESOLVED, "resolved_at": resolved_at}
        )
        assert d.status == DisruptionStatus.RESOLVED
        assert d.resolved_at == resolved_at

    def test_json_round_trip(self):
        d = Disruption(**VALID_DISRUPTION)
        reloaded = Disruption.model_validate_json(d.model_dump_json())
        assert reloaded == d
