from __future__ import annotations

"""
Disruption data contracts.

A ``Disruption`` represents an active supply-chain disruption event
(port closure, weather event, strike, geopolitical restriction).

``DisruptionGeometry`` captures the affected geographic zone and the set of
blocked route-graph nodes/edges.  The Impact Engine uses this to determine
which shipments are affected via graph overlap and time-window matching.

Design notes
------------
- ``blocked_nodes`` is the primary contract between the disruption record and
  the Impact Engine: any shipment whose ``route_node_ids`` intersects this
  set, AND whose transit window overlaps the disruption window, is affected.
- ``geometry_wkt`` is optional human-readable/GIS-friendly polygon string.
- All timestamps are UTC datetimes.
- ``reason_codes`` emitted by a disruption are ``SCREAMING_SNAKE_CASE`` per
  the project contract (e.g. ``PORT_NODE_BLOCKED``, ``WEATHER_ZONE_OVERLAP``).
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class DisruptionType(str, Enum):
    """Category of disruption event."""

    PORT_CLOSURE = "port_closure"
    PORT_STRIKE = "port_strike"
    SEVERE_WEATHER = "severe_weather"
    GEOPOLITICAL_RESTRICTION = "geopolitical_restriction"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    CARRIER_STRIKE = "carrier_strike"
    CUSTOMS_DELAY = "customs_delay"
    OTHER = "other"


class DisruptionSeverity(str, Enum):
    """Operator-assigned or system-computed severity of the disruption."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DisruptionStatus(str, Enum):
    """Lifecycle status of the disruption."""

    ACTIVE = "ACTIVE"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class DisruptionGeometry(BaseModel):
    """Geographic and graph-topological footprint of a disruption.

    ``blocked_nodes`` is the authoritative set used by the Impact Engine.
    ``blocked_edges`` is optional additional context (node pairs as strings
    ``"NODE-A:NODE-B"``).
    ``geometry_wkt`` is an optional WKT polygon for map visualisation.
    """

    blocked_nodes: list[str] = Field(
        default_factory=list,
        description=(
            "Route-graph node IDs blocked by this disruption.  "
            "Used by the Impact Engine for intersection detection."
        ),
    )
    blocked_edges: list[str] = Field(
        default_factory=list,
        description=(
            "Optional blocked edge descriptors in 'ORIGIN_ID:DEST_ID' format.  "
            "Used when an edge is blocked but neither endpoint alone is affected."
        ),
    )
    geometry_wkt: str | None = Field(
        None,
        description="WKT polygon of the affected geographic zone (for map overlay).",
    )
    center_lat: float | None = Field(
        None, ge=-90.0, le=90.0, description="Approximate centre latitude."
    )
    center_lon: float | None = Field(
        None, ge=-180.0, le=180.0, description="Approximate centre longitude."
    )
    radius_km: Annotated[float, Field(gt=0.0)] | None = Field(
        None,
        description="Radius in km (used for circular approximations instead of WKT).",
    )


class Disruption(BaseModel):
    """An active or historical supply-chain disruption event.

    Consumed by the Impact Engine to compute affected shipments.

    Quick-start example (matches the preflight_demo.py scenario)::

        Disruption(
            disruption_id="PORT_STRIKE_01",
            disruption_type=DisruptionType.PORT_STRIKE,
            severity=DisruptionSeverity.HIGH,
            status=DisruptionStatus.ACTIVE,
            title="Port of Aden strike action",
            window_start=datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc),
            geometry=DisruptionGeometry(blocked_nodes=["PORT-03"]),
        )
    """

    disruption_id: str = Field(
        ..., min_length=1, description="Unique disruption identifier."
    )

    disruption_type: DisruptionType = Field(...)

    severity: DisruptionSeverity = Field(DisruptionSeverity.HIGH)

    status: DisruptionStatus = Field(DisruptionStatus.ACTIVE)

    title: str = Field("", description="Short human-readable title for the disruption.")

    description: str = Field("", description="Longer operator-facing description.")

    # ---- time window ----
    window_start: datetime = Field(
        ...,
        description="UTC datetime when the disruption begins (or is expected to begin).",
    )
    window_end: datetime = Field(
        ...,
        description="UTC datetime when the disruption is expected to end.",
    )

    # ---- affected geography / graph topology ----
    geometry: DisruptionGeometry = Field(
        default_factory=DisruptionGeometry,
        description="Geographic and graph-topological footprint.",
    )

    # ---- impact metadata (populated by the Impact Engine) ----
    affected_shipment_ids: list[str] = Field(
        default_factory=list,
        description="Shipment IDs determined to be affected by the Impact Engine.",
    )
    affected_shipment_count: int = Field(
        0, ge=0, description="Count of affected shipments (denormalised for quick read)."
    )
    cargo_value_at_risk_usd: float = Field(
        0.0, ge=0.0, description="Total estimated cargo value at risk (USD)."
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="SCREAMING_SNAKE_CASE codes describing why shipments are affected.",
    )

    # ---- audit ----
    activated_at: datetime | None = Field(
        None, description="UTC timestamp when an operator activated this disruption."
    )
    resolved_at: datetime | None = Field(
        None, description="UTC timestamp when the disruption was resolved."
    )

    @model_validator(mode="after")
    def _check_window_order(self) -> Disruption:
        if self.window_start >= self.window_end:
            raise ValueError(
                f"window_start ({self.window_start}) must be before "
                f"window_end ({self.window_end})"
            )
        return self
