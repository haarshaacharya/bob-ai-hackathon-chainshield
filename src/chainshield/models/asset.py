from __future__ import annotations

"""
Asset data contract — fleet assets available for disruption redeployment.

An ``Asset`` represents a physical transport unit (truck, container, reefer
unit, railcar, vessel) tracked by the fleet management system.  The
Optimization Engine uses assets to find idle, compatible units for
redeployment when disruptions occur.

Fields mirror the DuckDB ``assets`` table defined in
``scripts/preflight_demo.py`` with additional Pydantic validation.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    """Physical asset category."""

    TRUCK = "truck"
    CONTAINER = "container"
    REEFER_UNIT = "reefer_unit"
    RAILCAR = "railcar"
    VESSEL = "vessel"
    OTHER = "other"


class AssetMode(str, Enum):
    """Transport mode the asset operates on."""

    ROAD = "road"
    RAIL = "rail"
    SEA = "sea"
    AIR = "air"


class AssetStatus(str, Enum):
    """Operational status of the asset."""

    AVAILABLE = "available"
    """Idle and available for redeployment."""
    IN_USE = "in_use"
    """Currently hauling cargo."""
    MAINTENANCE = "maintenance"
    """Under maintenance; not available."""
    RESERVED = "reserved"
    """Reserved for an upcoming assignment."""
    DECOMMISSIONED = "decommissioned"


class Asset(BaseModel):
    """A physical fleet asset.

    Designed to be the unit of data fed into the Optimization Engine for
    idle-asset matching and redeployment ranking.

    Compatibility checks (mode, reefer, capacity) are done by the engine;
    this model enforces structural validity only.
    """

    asset_id: str = Field(..., min_length=1, description="Unique asset identifier.")

    asset_type: AssetType = Field(..., description="Physical asset category.")

    mode: AssetMode = Field(..., description="Transport mode the asset operates on.")

    carrier_id: str | None = Field(
        None, description="Carrier that owns or operates this asset."
    )

    # ---- location ----
    current_node_id: str = Field(
        ...,
        min_length=1,
        description="Current hub/depot node ID in the route graph.",
    )
    location_lat: float | None = Field(
        None, ge=-90.0, le=90.0, description="Current GPS latitude (optional)."
    )
    location_lon: float | None = Field(
        None, ge=-180.0, le=180.0, description="Current GPS longitude (optional)."
    )

    # ---- availability ----
    status: AssetStatus = Field(AssetStatus.AVAILABLE)

    available_at: datetime = Field(
        ...,
        description=(
            "UTC datetime from which the asset is available for new assignment.  "
            "Used by the Optimization Engine to check reach-before-departure feasibility."
        ),
    )

    # ---- physical specs ----
    capacity_kg: Annotated[float, Field(gt=0.0)] = Field(
        ..., description="Maximum payload capacity in kilograms."
    )
    capacity_m3: Annotated[float, Field(gt=0.0)] | None = Field(
        None, description="Volume capacity in cubic metres (optional)."
    )

    reefer_capable: bool = Field(
        False,
        description=(
            "True when the asset has active temperature-control capability.  "
            "Hard constraint for cold-chain shipments in the Optimization Engine."
        ),
    )
    reefer_min_celsius: float | None = Field(
        None,
        description="Minimum temperature the reefer unit can maintain (°C).",
    )
    reefer_max_celsius: float | None = Field(
        None,
        description="Maximum temperature the reefer unit can maintain (°C).",
    )

    # ---- repositioning (populated by the Optimization Engine) ----
    reposition_distance_km: float | None = Field(
        None,
        ge=0.0,
        description="Distance to the affected shipment's origin (set by the engine).",
    )
    reposition_eta_minutes: float | None = Field(
        None,
        ge=0.0,
        description="Estimated minutes to reach the shipment origin (set by the engine).",
    )
    compatibility_score: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Composite compatibility score (0.0–1.0) from the engine.",
    )
