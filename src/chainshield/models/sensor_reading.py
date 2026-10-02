from __future__ import annotations

"""
SensorReading — IoT temperature sensor data contract.

Represents a single timestamped reading from a cold-chain sensor attached
to a shipment.  Quality flags allow the Cold Chain Engine to detect sensor
failure, battery warnings, and frozen/stuck values without modifying
classification logic.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class SensorQualityFlag(str, Enum):
    """Quality / diagnostic flag for a sensor reading."""

    OK = "OK"
    BATTERY_LOW = "BATTERY_LOW"
    BATTERY_CRITICAL = "BATTERY_CRITICAL"
    FROZEN_VALUE = "FROZEN_VALUE"
    """Reading identical to prior N readings — possible stuck sensor."""
    DOOR_OPEN = "DOOR_OPEN"
    """Rapid temperature rise followed by rapid fall — door-open pattern."""
    OUT_OF_SENSOR_RANGE = "OUT_OF_SENSOR_RANGE"
    """Reading outside the sensor's physical measurement range."""
    SENSOR_FAILURE = "SENSOR_FAILURE"
    """Sensor hardware failure suspected."""
    MISSING = "MISSING"
    """Expected reading absent from the log (gap in time series)."""


class SensorReading(BaseModel):
    """A single temperature reading from a cold-chain IoT sensor.

    Units
    -----
    - ``temperature_c``: degrees Celsius (°C)
    - ``battery_pct``: percentage (0.0–100.0)
    - ``humidity_pct``: percentage (0.0–100.0), optional
    - ``shock_g``: gravitational acceleration (g), optional
    """

    sensor_id: str = Field(..., min_length=1, description="Unique sensor device ID.")

    shipment_id: str = Field(
        ..., min_length=1, description="Shipment this sensor is attached to."
    )

    ts: datetime = Field(..., description="UTC timestamp of the reading.")

    temperature_c: float = Field(
        ..., description="Measured temperature in degrees Celsius."
    )

    battery_pct: Annotated[float, Field(ge=0.0, le=100.0)] = Field(
        100.0, description="Battery level as a percentage (0–100)."
    )

    humidity_pct: Annotated[float, Field(ge=0.0, le=100.0)] | None = Field(
        None, description="Relative humidity percentage (optional)."
    )

    shock_g: float | None = Field(
        None,
        description="Peak shock event in g-force (optional, for fragile cargo).",
    )

    quality_flag: SensorQualityFlag = Field(
        SensorQualityFlag.OK,
        description="Quality / diagnostic classification for this reading.",
    )

    location_lat: float | None = Field(
        None,
        ge=-90.0,
        le=90.0,
        description="GPS latitude at time of reading (optional).",
    )

    location_lon: float | None = Field(
        None,
        ge=-180.0,
        le=180.0,
        description="GPS longitude at time of reading (optional).",
    )

    @field_validator("ts", mode="before")
    @classmethod
    def _parse_ts(cls, v: object) -> datetime:
        """Accept ISO-8601 strings in addition to datetime objects."""
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        if isinstance(v, datetime):
            return v
        raise ValueError(f"ts must be a datetime or ISO-8601 string, got {type(v)}")

    @field_validator("temperature_c", mode="before")
    @classmethod
    def _coerce_temp(cls, v: object) -> float:
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"temperature_c must be numeric, got {v!r}") from exc
