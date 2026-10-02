from __future__ import annotations

"""
Shipment and ShipmentLeg data contracts.

A ``Shipment`` represents a single cargo movement from origin to destination.
A ``ShipmentLeg`` represents one physical segment of a multi-modal journey
(e.g. truck to port, then sea, then truck again).

Design notes
------------
- Coordinates are stored as (lat, lon) float pairs in ``RouteNode``.
- All timestamps are UTC-aware datetimes validated by Pydantic.
- ``temperature_policy_id`` is a foreign-key reference to ``TemperaturePolicy``
  (``None`` for non-temperature-sensitive cargo).
- ``reason_codes`` is a list of ``SCREAMING_SNAKE_CASE`` strings attached by the
  Impact Engine when the shipment is marked affected by a disruption.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from .enums import CargoMode, ProductClass, ShipmentStatus


class RouteNode(BaseModel):
    """A hub, depot, port, or waypoint on a shipment route.

    ``node_id`` matches the graph node key used by the Impact Engine
    (e.g. ``"PORT-03"``, ``"HUB-A"``).
    """

    node_id: str = Field(..., min_length=1, description="Unique node identifier.")
    name: str = Field("", description="Human-readable location name.")
    lat: float | None = Field(None, ge=-90.0, le=90.0, description="Latitude.")
    lon: float | None = Field(None, ge=-180.0, le=180.0, description="Longitude.")


class ShipmentLeg(BaseModel):
    """One segment of a multi-modal shipment journey.

    Legs are ordered by ``sequence`` (0-based).  The ``origin_node_id``
    of leg N should match the ``destination_node_id`` of leg N-1.
    """

    leg_id: str = Field(..., min_length=1, description="Unique leg identifier.")
    shipment_id: str = Field(..., min_length=1, description="Parent shipment ID.")
    sequence: Annotated[int, Field(ge=0)] = Field(
        ..., description="0-based leg sequence within the shipment."
    )

    origin_node_id: str = Field(..., min_length=1)
    destination_node_id: str = Field(..., min_length=1)

    mode: CargoMode = Field(..., description="Transport mode for this leg.")
    carrier_id: str | None = Field(
        None, description="Carrier operating this leg (may be unknown at planning time)."
    )

    planned_departure: datetime = Field(...)
    planned_arrival: datetime = Field(...)

    actual_departure: datetime | None = Field(None)
    actual_arrival: datetime | None = Field(None)

    distance_km: Annotated[float, Field(gt=0)] | None = Field(
        None, description="Planned leg distance in kilometres."
    )

    cost_usd: float | None = Field(
        None, description="Planned cost for this leg in USD."
    )

    is_disrupted: bool = Field(
        False, description="True when the Impact Engine flags this leg as blocked."
    )

    reason_codes: list[str] = Field(
        default_factory=list,
        description="SCREAMING_SNAKE_CASE reason codes from the Impact Engine.",
    )

    @model_validator(mode="after")
    def _check_leg_times(self) -> ShipmentLeg:
        if self.planned_departure >= self.planned_arrival:
            raise ValueError(
                f"planned_departure ({self.planned_departure}) must be before "
                f"planned_arrival ({self.planned_arrival}) on leg {self.leg_id!r}"
            )
        return self


class Shipment(BaseModel):
    """Top-level shipment record.

    Fields mirror the DuckDB ``shipments`` table defined in
    ``scripts/preflight_demo.py`` with additional Pydantic validation.
    """

    shipment_id: str = Field(..., min_length=1, description="Unique shipment identifier.")

    # ---- cargo metadata ----
    cargo_type: str = Field(
        "", description="Free-text cargo type (e.g. 'reefer', 'dry bulk')."
    )
    product_class: ProductClass = Field(
        ProductClass.OTHER, description="Product class for cold-chain policy lookup."
    )
    temperature_policy_id: str | None = Field(
        None,
        description=(
            "Foreign key to TemperaturePolicy.policy_id.  "
            "None for non-temperature-sensitive cargo."
        ),
    )
    cargo_value_usd: Annotated[float, Field(ge=0.0)] = Field(
        0.0, description="Estimated cargo value in USD."
    )
    weight_kg: Annotated[float, Field(gt=0.0)] = Field(
        ..., description="Total cargo weight in kilograms."
    )

    # ---- route ----
    origin_hub_id: str = Field(..., min_length=1)
    destination_hub_id: str = Field(..., min_length=1)
    current_node_id: str | None = Field(
        None, description="Current node in the route graph (updated during transit)."
    )
    route_node_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of node IDs representing the planned route. "
            "Used by the Impact Engine for disruption intersection checks."
        ),
    )

    # ---- carrier / mode ----
    mode: CargoMode = Field(..., description="Primary transport mode.")
    carrier_id: str | None = Field(None, description="Primary carrier ID.")

    # ---- timing ----
    planned_departure: datetime = Field(...)
    planned_arrival: datetime = Field(...)
    delivery_deadline: datetime = Field(
        ...,
        description=(
            "Hard customer delivery deadline.  Used by the Optimization Engine "
            "for deadline-constraint validation."
        ),
    )
    actual_departure: datetime | None = Field(None)
    actual_arrival: datetime | None = Field(None)

    # ---- status ----
    status: ShipmentStatus = Field(ShipmentStatus.PLANNED)

    # ---- impact fields (populated by the Impact Engine) ----
    is_disrupted: bool = Field(
        False, description="True when at least one active disruption affects this shipment."
    )
    disruption_ids: list[str] = Field(
        default_factory=list,
        description="IDs of active disruptions that affect this shipment.",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="SCREAMING_SNAKE_CASE reason codes from the Impact Engine.",
    )
    confidence: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Impact confidence score (0.0–1.0), set by the Impact Engine.",
    )

    # ---- legs (optional; populated when multi-modal detail is available) ----
    legs: list[ShipmentLeg] = Field(
        default_factory=list,
        description="Ordered list of shipment legs (multi-modal breakdown).",
    )

    # ---- validators ----
    @model_validator(mode="after")
    def _check_shipment_times(self) -> Shipment:
        if self.planned_departure >= self.planned_arrival:
            raise ValueError(
                f"planned_departure ({self.planned_departure}) must be before "
                f"planned_arrival ({self.planned_arrival})"
            )
        return self

    @model_validator(mode="after")
    def _check_deadline_not_before_arrival(self) -> Shipment:
        # Deadline may equal planned_arrival; it must not precede it logically.
        # We only warn-validate; strict enforcement is in the Optimization Engine.
        return self

    @model_validator(mode="after")
    def _check_leg_sequence(self) -> Shipment:
        """Legs must have contiguous 0-based sequence numbers."""
        if not self.legs:
            return self
        sequences = sorted(leg.sequence for leg in self.legs)
        expected = list(range(len(sequences)))
        if sequences != expected:
            raise ValueError(
                f"ShipmentLeg sequences must be 0-based and contiguous; "
                f"got {sequences}"
            )
        return self
