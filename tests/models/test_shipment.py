from __future__ import annotations

"""
Unit tests for Shipment, ShipmentLeg, and RouteNode data contracts.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from chainshield.models.enums import CargoMode, ProductClass, ShipmentStatus
from chainshield.models.shipment import RouteNode, Shipment, ShipmentLeg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)


def make_leg(sequence: int = 0) -> dict:
    return dict(
        leg_id=f"LEG-{sequence:02d}",
        shipment_id="SHP-0042",
        sequence=sequence,
        origin_node_id="HUB-A",
        destination_node_id="PORT-03",
        mode=CargoMode.SEA,
        planned_departure=T0,
        planned_arrival=T1,
    )


def make_shipment(**overrides) -> dict:
    base = dict(
        shipment_id="SHP-0042",
        product_class=ProductClass.REFRIGERATED_VACCINE,
        temperature_policy_id="POL-CDC-01",
        cargo_value_usd=520_000.0,
        weight_kg=8200.0,
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-D",
        mode=CargoMode.SEA,
        carrier_id="CARRIER-A",
        planned_departure=T0,
        planned_arrival=T1,
        delivery_deadline=T2,
        status=ShipmentStatus.IN_TRANSIT,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# RouteNode
# ---------------------------------------------------------------------------


class TestRouteNode:
    def test_minimal(self):
        node = RouteNode(node_id="PORT-03")
        assert node.node_id == "PORT-03"
        assert node.lat is None

    def test_with_coordinates(self):
        node = RouteNode(node_id="HUB-A", lat=12.5, lon=55.3)
        assert node.lat == 12.5

    def test_lat_out_of_range(self):
        with pytest.raises(ValidationError):
            RouteNode(node_id="X", lat=91.0)

    def test_lon_out_of_range(self):
        with pytest.raises(ValidationError):
            RouteNode(node_id="X", lon=-181.0)


# ---------------------------------------------------------------------------
# ShipmentLeg
# ---------------------------------------------------------------------------


class TestShipmentLeg:
    def test_valid_leg(self):
        leg = ShipmentLeg(**make_leg(0))
        assert leg.sequence == 0
        assert leg.mode == CargoMode.SEA
        assert leg.is_disrupted is False

    def test_departure_after_arrival_rejected(self):
        data = make_leg(0)
        data["planned_departure"], data["planned_arrival"] = T1, T0
        with pytest.raises(ValidationError, match="planned_departure"):
            ShipmentLeg(**data)

    def test_departure_equal_arrival_rejected(self):
        data = {**make_leg(0), "planned_departure": T0, "planned_arrival": T0}
        with pytest.raises(ValidationError, match="planned_departure"):
            ShipmentLeg(**data)

    def test_reason_codes_default_empty(self):
        leg = ShipmentLeg(**make_leg(0))
        assert leg.reason_codes == []

    def test_reason_codes_populated(self):
        leg = ShipmentLeg(**{**make_leg(0), "reason_codes": ["PORT_NODE_BLOCKED"]})
        assert "PORT_NODE_BLOCKED" in leg.reason_codes


# ---------------------------------------------------------------------------
# Shipment
# ---------------------------------------------------------------------------


class TestShipment:
    def test_valid_shipment(self):
        shp = Shipment(**make_shipment())
        assert shp.shipment_id == "SHP-0042"
        assert shp.status == ShipmentStatus.IN_TRANSIT
        assert shp.is_disrupted is False
        assert shp.legs == []
        assert shp.reason_codes == []

    def test_departure_after_arrival_rejected(self):
        with pytest.raises(ValidationError):
            Shipment(**make_shipment(planned_departure=T1, planned_arrival=T0))

    def test_departure_equals_arrival_rejected(self):
        with pytest.raises(ValidationError):
            Shipment(**make_shipment(planned_departure=T0, planned_arrival=T0))

    def test_weight_must_be_positive(self):
        with pytest.raises(ValidationError):
            Shipment(**make_shipment(weight_kg=0.0))

    def test_cargo_value_zero_allowed(self):
        shp = Shipment(**make_shipment(cargo_value_usd=0.0))
        assert shp.cargo_value_usd == 0.0

    def test_non_cold_chain_shipment_no_policy(self):
        shp = Shipment(**make_shipment(temperature_policy_id=None, product_class=ProductClass.DRY_GOODS))
        assert shp.temperature_policy_id is None

    def test_route_node_ids_stored(self):
        shp = Shipment(**make_shipment(route_node_ids=["HUB-A", "PORT-03", "HUB-D"]))
        assert shp.route_node_ids == ["HUB-A", "PORT-03", "HUB-D"]

    def test_disruption_fields_populated(self):
        shp = Shipment(
            **make_shipment(
                is_disrupted=True,
                disruption_ids=["PORT_STRIKE_01"],
                reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
                confidence=0.94,
            )
        )
        assert shp.is_disrupted is True
        assert "PORT_NODE_BLOCKED" in shp.reason_codes
        assert shp.confidence == 0.94

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            Shipment(**make_shipment(confidence=1.5))

    def test_valid_legs_attached(self):
        leg0 = ShipmentLeg(**make_leg(0))
        shp = Shipment(**make_shipment(legs=[leg0]))
        assert len(shp.legs) == 1

    def test_non_contiguous_leg_sequences_rejected(self):
        leg0 = ShipmentLeg(**make_leg(0))
        leg2 = ShipmentLeg(**make_leg(2))  # gap: missing sequence 1
        with pytest.raises(ValidationError, match="contiguous"):
            Shipment(**make_shipment(legs=[leg0, leg2]))

    def test_duplicate_leg_sequences_rejected(self):
        leg0a = ShipmentLeg(**make_leg(0))
        leg0b = ShipmentLeg(**make_leg(0))
        with pytest.raises(ValidationError, match="contiguous"):
            Shipment(**make_shipment(legs=[leg0a, leg0b]))

    def test_json_round_trip(self):
        shp = Shipment(**make_shipment())
        reloaded = Shipment.model_validate_json(shp.model_dump_json())
        assert reloaded == shp
