from __future__ import annotations

"""
Unit tests for Asset data contract.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from chainshield.models.asset import Asset, AssetMode, AssetStatus, AssetType


T_AVAILABLE = datetime(2026, 9, 14, 9, 25, tzinfo=timezone.utc)

VALID_ASSET = dict(
    asset_id="TRUCK-17",
    asset_type=AssetType.TRUCK,
    mode=AssetMode.ROAD,
    carrier_id="CARRIER-B",
    current_node_id="HUB-B",
    status=AssetStatus.AVAILABLE,
    available_at=T_AVAILABLE,
    capacity_kg=12_000.0,
    reefer_capable=True,
)


class TestAsset:
    def test_valid_asset(self):
        asset = Asset(**VALID_ASSET)
        assert asset.asset_id == "TRUCK-17"
        assert asset.reefer_capable is True
        assert asset.status == AssetStatus.AVAILABLE

    def test_capacity_must_be_positive(self):
        with pytest.raises(ValidationError):
            Asset(**{**VALID_ASSET, "capacity_kg": 0.0})

    def test_capacity_negative_rejected(self):
        with pytest.raises(ValidationError):
            Asset(**{**VALID_ASSET, "capacity_kg": -100.0})

    def test_reefer_defaults_to_false(self):
        asset = Asset(**{k: v for k, v in VALID_ASSET.items() if k != "reefer_capable"})
        assert asset.reefer_capable is False

    def test_compatibility_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            Asset(**{**VALID_ASSET, "compatibility_score": 1.5})
        with pytest.raises(ValidationError):
            Asset(**{**VALID_ASSET, "compatibility_score": -0.1})

    def test_lat_lon_bounds(self):
        with pytest.raises(ValidationError):
            Asset(**{**VALID_ASSET, "location_lat": -91.0})
        with pytest.raises(ValidationError):
            Asset(**{**VALID_ASSET, "location_lon": 200.0})

    def test_optional_fields_default_none(self):
        asset = Asset(**VALID_ASSET)
        assert asset.capacity_m3 is None
        assert asset.reposition_distance_km is None
        assert asset.reposition_eta_minutes is None
        assert asset.compatibility_score is None
        assert asset.reefer_min_celsius is None
        assert asset.reefer_max_celsius is None

    def test_reposition_distance_non_negative(self):
        with pytest.raises(ValidationError):
            Asset(**{**VALID_ASSET, "reposition_distance_km": -5.0})

    def test_asset_status_enum_values(self):
        for status in AssetStatus:
            asset = Asset(**{**VALID_ASSET, "status": status})
            assert asset.status == status

    def test_no_carrier_id(self):
        asset = Asset(**{k: v for k, v in VALID_ASSET.items() if k != "carrier_id"})
        assert asset.carrier_id is None

    def test_json_round_trip(self):
        asset = Asset(**VALID_ASSET)
        reloaded = Asset.model_validate_json(asset.model_dump_json())
        assert reloaded == asset
