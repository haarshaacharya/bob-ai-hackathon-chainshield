from __future__ import annotations

"""
Unit tests for SensorReading data contract.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from chainshield.models.sensor_reading import SensorQualityFlag, SensorReading


VALID_READING = dict(
    sensor_id="SENSOR-9",
    shipment_id="SHP-0042",
    ts=datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc),
    temperature_c=6.9,
    battery_pct=91.0,
)


class TestSensorReading:
    def test_valid_reading(self):
        r = SensorReading(**VALID_READING)
        assert r.sensor_id == "SENSOR-9"
        assert r.temperature_c == 6.9
        assert r.quality_flag == SensorQualityFlag.OK

    def test_iso_string_ts_parsed(self):
        r = SensorReading(**{**VALID_READING, "ts": "2026-09-14T08:00:00"})
        assert isinstance(r.ts, datetime)
        assert r.ts.year == 2026

    def test_temperature_coercion_from_int(self):
        r = SensorReading(**{**VALID_READING, "temperature_c": 7})
        assert r.temperature_c == 7.0
        assert isinstance(r.temperature_c, float)

    def test_battery_pct_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            SensorReading(**{**VALID_READING, "battery_pct": 101.0})
        with pytest.raises(ValidationError):
            SensorReading(**{**VALID_READING, "battery_pct": -1.0})

    def test_humidity_pct_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            SensorReading(**{**VALID_READING, "humidity_pct": 110.0})

    def test_lat_lon_bounds(self):
        with pytest.raises(ValidationError):
            SensorReading(**{**VALID_READING, "location_lat": 91.0})
        with pytest.raises(ValidationError):
            SensorReading(**{**VALID_READING, "location_lon": 181.0})

    def test_optional_fields_default_to_none(self):
        r = SensorReading(**VALID_READING)
        assert r.humidity_pct is None
        assert r.shock_g is None
        assert r.location_lat is None
        assert r.location_lon is None

    def test_quality_flag_door_open(self):
        r = SensorReading(**{**VALID_READING, "quality_flag": SensorQualityFlag.DOOR_OPEN})
        assert r.quality_flag == SensorQualityFlag.DOOR_OPEN

    def test_missing_sensor_id_rejected(self):
        data = {k: v for k, v in VALID_READING.items() if k != "sensor_id"}
        with pytest.raises(ValidationError):
            SensorReading(**data)

    def test_negative_temperature_accepted(self):
        """Frozen cargo may legitimately read below 0°C."""
        r = SensorReading(**{**VALID_READING, "temperature_c": -20.5})
        assert r.temperature_c == -20.5

    def test_json_round_trip(self):
        r = SensorReading(**VALID_READING)
        reloaded = SensorReading.model_validate_json(r.model_dump_json())
        assert reloaded == r
