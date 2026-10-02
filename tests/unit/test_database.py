from __future__ import annotations

"""
tests/unit/test_database.py
============================
Unit tests for the ChainShield local DuckDB demo store
(``src/chainshield/database.py``).

All tests use an in-memory DuckDB connection so nothing is written to disk.
The ``generate_synthetic_data`` script is used only via ``seed_demo()``; no
network access occurs.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Allow importing chainshield and generate_synthetic_data without install
_REPO_ROOT = Path(__file__).parent.parent.parent
for _p in (_REPO_ROOT / "src", _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from chainshield.database import (
    connect,
    create_tables,
    insert_assets,
    insert_disruptions,
    insert_sensor_readings,
    insert_shipments,
    insert_temperature_policies,
    query_idle_assets,
    query_sensor_readings,
    query_shipments,
    seed_demo,
    validate_schema,
)
from chainshield.models import (
    Asset,
    AssetMode,
    AssetStatus,
    AssetType,
    CargoMode,
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
    ProductClass,
    SensorQualityFlag,
    SensorReading,
    Shipment,
    ShipmentStatus,
    TemperaturePolicy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con():
    """Fresh in-memory DuckDB connection per test."""
    c = connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def seeded_con():
    """In-memory DuckDB connection pre-populated with seed=42 scenario."""
    c = connect(":memory:")
    seed_demo(c, seed=42)
    yield c
    c.close()


def _make_shipment(**overrides) -> Shipment:
    defaults = dict(
        shipment_id="TEST-SHP-001",
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-D",
        mode=CargoMode.SEA,
        weight_kg=5000.0,
        planned_departure=datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc),
        planned_arrival=datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc),
        delivery_deadline=datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc),
        status=ShipmentStatus.IN_TRANSIT,
    )
    defaults.update(overrides)
    return Shipment(**defaults)


def _make_asset(**overrides) -> Asset:
    defaults = dict(
        asset_id="TEST-TRUCK-01",
        asset_type=AssetType.TRUCK,
        mode=AssetMode.ROAD,
        current_node_id="HUB-B",
        available_at=datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc),
        capacity_kg=12000.0,
        reefer_capable=True,
        status=AssetStatus.AVAILABLE,
    )
    defaults.update(overrides)
    return Asset(**defaults)


def _make_sensor_reading(**overrides) -> SensorReading:
    defaults = dict(
        sensor_id="SENSOR-9",
        shipment_id="TEST-SHP-001",
        ts=datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc),
        temperature_c=6.9,
        battery_pct=91.0,
    )
    defaults.update(overrides)
    return SensorReading(**defaults)


def _make_policy(**overrides) -> TemperaturePolicy:
    defaults = dict(
        policy_id="TEST-POL-01",
        product_class=ProductClass.REFRIGERATED_VACCINE,
        min_celsius=2.0,
        max_celsius=8.0,
        max_continuous_excursion_minutes=15.0,
        sample_interval_minutes=6.0,
    )
    defaults.update(overrides)
    return TemperaturePolicy(**defaults)


def _make_disruption(**overrides) -> Disruption:
    defaults = dict(
        disruption_id="TEST-DIS-001",
        disruption_type=DisruptionType.PORT_STRIKE,
        severity=DisruptionSeverity.HIGH,
        status=DisruptionStatus.ACTIVE,
        window_start=datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc),
        geometry=DisruptionGeometry(blocked_nodes=["PORT-03"]),
    )
    defaults.update(overrides)
    return Disruption(**defaults)


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


class TestConnect:
    def test_returns_connection(self):
        c = connect(":memory:")
        assert c is not None
        c.close()

    def test_independent_connections_do_not_share_state(self):
        c1 = connect(":memory:")
        c2 = connect(":memory:")
        create_tables(c1)
        c1.execute("INSERT INTO shipments (shipment_id, origin_hub_id, destination_hub_id, mode, weight_kg, status, planned_departure, planned_arrival, delivery_deadline) VALUES ('X','A','B','sea',1,'PLANNED','2026-01-01','2026-01-02','2026-01-02')")
        count = c2.execute("SELECT COUNT(*) FROM shipments").fetchone() if False else None
        # c2 has no tables — executing on it should raise
        with pytest.raises(Exception):
            c2.execute("SELECT COUNT(*) FROM shipments").fetchone()
        c1.close()
        c2.close()


# ---------------------------------------------------------------------------
# create_tables()
# ---------------------------------------------------------------------------


class TestCreateTables:
    def test_all_tables_created(self, con):
        create_tables(con)
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert {"shipments", "assets", "sensor_readings",
                "temperature_policies", "disruptions"} <= tables

    def test_idempotent(self, con):
        create_tables(con)
        create_tables(con)  # second call must not raise


# ---------------------------------------------------------------------------
# validate_schema()
# ---------------------------------------------------------------------------


class TestValidateSchema:
    def test_valid_schema_returns_empty_dict(self, con):
        create_tables(con)
        missing = validate_schema(con)
        assert missing == {}

    def test_reports_missing_column_on_altered_table(self, con):
        # Build a minimal shipments table that omits weight_kg
        con.execute(
            "CREATE TABLE shipments (shipment_id VARCHAR, origin_hub_id VARCHAR)"
        )
        con.execute("CREATE TABLE assets (asset_id VARCHAR)")
        con.execute("CREATE TABLE sensor_readings (sensor_id VARCHAR, shipment_id VARCHAR, ts TIMESTAMP, temperature_c DOUBLE)")
        con.execute("CREATE TABLE temperature_policies (policy_id VARCHAR, product_class VARCHAR, min_celsius DOUBLE, max_celsius DOUBLE, max_continuous_excursion_minutes DOUBLE)")
        con.execute("CREATE TABLE disruptions (disruption_id VARCHAR, disruption_type VARCHAR, severity VARCHAR, status VARCHAR, window_start TIMESTAMP, window_end TIMESTAMP)")
        missing = validate_schema(con)
        # shipments is missing several required columns
        assert "shipments" in missing
        assert "weight_kg" in missing["shipments"]


# ---------------------------------------------------------------------------
# insert_shipments()
# ---------------------------------------------------------------------------


class TestInsertShipments:
    def test_insert_returns_count(self, con):
        create_tables(con)
        shp = _make_shipment()
        n = insert_shipments(con, [shp])
        assert n == 1

    def test_row_persisted(self, con):
        create_tables(con)
        insert_shipments(con, [_make_shipment()])
        count = con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        assert count == 1

    def test_shipment_id_matches(self, con):
        create_tables(con)
        insert_shipments(con, [_make_shipment(shipment_id="SHP-XYZ")])
        row = con.execute(
            "SELECT shipment_id FROM shipments WHERE shipment_id = 'SHP-XYZ'"
        ).fetchone()
        assert row is not None

    def test_disrupted_flag_stored(self, con):
        create_tables(con)
        shp = _make_shipment(
            is_disrupted=True,
            disruption_ids=["DIS-1"],
            reason_codes=["PORT_NODE_BLOCKED"],
        )
        insert_shipments(con, [shp])
        row = con.execute(
            "SELECT is_disrupted, disruption_ids, reason_codes FROM shipments"
        ).fetchone()
        assert row[0] is True
        assert "DIS-1" in json.loads(row[1])
        assert "PORT_NODE_BLOCKED" in json.loads(row[2])

    def test_multiple_shipments(self, con):
        create_tables(con)
        ships = [_make_shipment(shipment_id=f"SHP-{i:03d}") for i in range(5)]
        n = insert_shipments(con, ships)
        assert n == 5
        count = con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        assert count == 5

    def test_upsert_replaces_existing(self, con):
        create_tables(con)
        shp = _make_shipment(shipment_id="SHP-DUP", status=ShipmentStatus.PLANNED)
        insert_shipments(con, [shp])
        shp2 = _make_shipment(shipment_id="SHP-DUP", status=ShipmentStatus.IN_TRANSIT)
        insert_shipments(con, [shp2])
        rows = con.execute("SELECT COUNT(*) FROM shipments WHERE shipment_id = 'SHP-DUP'").fetchone()
        assert rows[0] == 1


# ---------------------------------------------------------------------------
# insert_assets()
# ---------------------------------------------------------------------------


class TestInsertAssets:
    def test_insert_returns_count(self, con):
        create_tables(con)
        n = insert_assets(con, [_make_asset()])
        assert n == 1

    def test_reefer_capable_stored(self, con):
        create_tables(con)
        insert_assets(con, [_make_asset(reefer_capable=True)])
        val = con.execute("SELECT reefer_capable FROM assets").fetchone()[0]
        assert val is True

    def test_non_reefer_stored(self, con):
        create_tables(con)
        insert_assets(con, [_make_asset(asset_id="TRUCK-DRY", reefer_capable=False)])
        val = con.execute(
            "SELECT reefer_capable FROM assets WHERE asset_id = 'TRUCK-DRY'"
        ).fetchone()[0]
        assert val is False


# ---------------------------------------------------------------------------
# insert_sensor_readings()
# ---------------------------------------------------------------------------


class TestInsertSensorReadings:
    def test_insert_returns_count(self, con):
        create_tables(con)
        n = insert_sensor_readings(con, [_make_sensor_reading()])
        assert n == 1

    def test_temperature_stored(self, con):
        create_tables(con)
        insert_sensor_readings(con, [_make_sensor_reading(temperature_c=10.4)])
        temp = con.execute("SELECT temperature_c FROM sensor_readings").fetchone()[0]
        assert abs(temp - 10.4) < 1e-6

    def test_quality_flag_stored(self, con):
        create_tables(con)
        r = _make_sensor_reading()
        r2 = SensorReading(
            sensor_id="S1",
            shipment_id="TEST-SHP-001",
            ts=datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc),
            temperature_c=5.0,
            quality_flag=SensorQualityFlag.DOOR_OPEN,
        )
        insert_sensor_readings(con, [r, r2])
        flags = {
            row[0]
            for row in con.execute("SELECT quality_flag FROM sensor_readings").fetchall()
        }
        assert "DOOR_OPEN" in flags

    def test_multiple_readings_ordered_by_ts(self, con):
        create_tables(con)
        readings = [
            _make_sensor_reading(
                ts=datetime(2026, 9, 14, 8, i * 6, tzinfo=timezone.utc),
                temperature_c=float(i),
            )
            for i in range(5)
        ]
        insert_sensor_readings(con, readings)
        temps = [
            r[0]
            for r in con.execute(
                "SELECT temperature_c FROM sensor_readings ORDER BY ts"
            ).fetchall()
        ]
        assert temps == [0.0, 1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# insert_temperature_policies()
# ---------------------------------------------------------------------------


class TestInsertTemperaturePolicies:
    def test_insert_returns_count(self, con):
        create_tables(con)
        n = insert_temperature_policies(con, [_make_policy()])
        assert n == 1

    def test_policy_stored(self, con):
        create_tables(con)
        insert_temperature_policies(con, [_make_policy(min_celsius=2.0, max_celsius=8.0)])
        row = con.execute(
            "SELECT min_celsius, max_celsius FROM temperature_policies"
        ).fetchone()
        assert row[0] == 2.0
        assert row[1] == 8.0

    def test_severity_rules_json_roundtrip(self, con):
        create_tables(con)
        pol = _make_policy()
        insert_temperature_policies(con, [pol])
        raw = con.execute("SELECT severity_rules_json FROM temperature_policies").fetchone()[0]
        rules = json.loads(raw)
        assert "out_of_range" in rules
        assert "missing_sensor_data" in rules


# ---------------------------------------------------------------------------
# insert_disruptions()
# ---------------------------------------------------------------------------


class TestInsertDisruptions:
    def test_insert_returns_count(self, con):
        create_tables(con)
        n = insert_disruptions(con, [_make_disruption()])
        assert n == 1

    def test_blocked_nodes_stored(self, con):
        create_tables(con)
        insert_disruptions(
            con, [_make_disruption(geometry=DisruptionGeometry(blocked_nodes=["PORT-03", "HUB-X"]))]
        )
        raw = con.execute("SELECT blocked_nodes FROM disruptions").fetchone()[0]
        nodes = json.loads(raw)
        assert "PORT-03" in nodes
        assert "HUB-X" in nodes


# ---------------------------------------------------------------------------
# query_shipments()
# ---------------------------------------------------------------------------


class TestQueryShipments:
    def test_returns_all_by_default(self, con):
        create_tables(con)
        insert_shipments(con, [_make_shipment(shipment_id=f"S{i}") for i in range(3)])
        rows = query_shipments(con)
        assert len(rows) == 3

    def test_disrupted_only_filter(self, con):
        create_tables(con)
        insert_shipments(con, [
            _make_shipment(shipment_id="S1", is_disrupted=True),
            _make_shipment(shipment_id="S2", is_disrupted=False),
        ])
        rows = query_shipments(con, disrupted_only=True)
        assert len(rows) == 1
        assert rows[0]["shipment_id"] == "S1"

    def test_row_contains_expected_keys(self, con):
        create_tables(con)
        insert_shipments(con, [_make_shipment()])
        rows = query_shipments(con)
        assert "shipment_id" in rows[0]
        assert "status" in rows[0]
        assert "weight_kg" in rows[0]


# ---------------------------------------------------------------------------
# query_idle_assets()
# ---------------------------------------------------------------------------


class TestQueryIdleAssets:
    def test_returns_available_only(self, con):
        create_tables(con)
        insert_assets(con, [
            _make_asset(asset_id="A1", status=AssetStatus.AVAILABLE),
            _make_asset(asset_id="A2", status=AssetStatus.IN_USE),
        ])
        rows = query_idle_assets(con)
        assert len(rows) == 1
        assert rows[0]["asset_id"] == "A1"

    def test_reefer_only_filter(self, con):
        create_tables(con)
        insert_assets(con, [
            _make_asset(asset_id="R1", reefer_capable=True, status=AssetStatus.AVAILABLE),
            _make_asset(asset_id="D1", reefer_capable=False, status=AssetStatus.AVAILABLE),
        ])
        rows = query_idle_assets(con, reefer_only=True)
        ids = {r["asset_id"] for r in rows}
        assert "R1" in ids
        assert "D1" not in ids


# ---------------------------------------------------------------------------
# query_sensor_readings()
# ---------------------------------------------------------------------------


class TestQuerySensorReadings:
    def test_returns_readings_for_shipment(self, con):
        create_tables(con)
        insert_sensor_readings(con, [
            _make_sensor_reading(shipment_id="SHP-A"),
            _make_sensor_reading(shipment_id="SHP-B"),
        ])
        rows = query_sensor_readings(con, "SHP-A")
        assert len(rows) == 1
        assert rows[0]["shipment_id"] == "SHP-A"

    def test_returns_empty_for_unknown_shipment(self, con):
        create_tables(con)
        rows = query_sensor_readings(con, "UNKNOWN")
        assert rows == []

    def test_ordered_by_timestamp(self, con):
        create_tables(con)
        readings = [
            _make_sensor_reading(
                ts=datetime(2026, 9, 14, 8, i * 6, tzinfo=timezone.utc),
                temperature_c=float(10 - i),
            )
            for i in range(4)
        ]
        insert_sensor_readings(con, readings)
        rows = query_sensor_readings(con, "TEST-SHP-001")
        temps = [r["temperature_c"] for r in rows]
        assert temps == sorted(temps, reverse=True)  # ts ascending → temp descending here


# ---------------------------------------------------------------------------
# seed_demo() — full integration over the in-memory store
# ---------------------------------------------------------------------------


class TestSeedDemo:
    def test_returns_nonzero_counts(self, seeded_con):
        counts = seed_demo(connect(":memory:"), seed=42)
        assert counts["shipments"] > 0
        assert counts["assets"] > 0
        assert counts["sensor_readings"] > 0
        assert counts["temperature_policies"] > 0
        assert counts["disruptions"] > 0

    def test_deterministic_row_counts(self):
        c1, c2 = connect(":memory:"), connect(":memory:")
        r1 = seed_demo(c1, seed=42)
        r2 = seed_demo(c2, seed=42)
        assert r1 == r2
        c1.close()
        c2.close()

    def test_shipments_table_populated(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        assert count > 0

    def test_assets_table_populated(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        assert count > 0

    def test_sensor_readings_table_populated(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
        assert count > 0

    def test_temperature_policies_table_populated(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM temperature_policies").fetchone()[0]
        assert count > 0

    def test_disruptions_table_populated(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM disruptions").fetchone()[0]
        assert count > 0

    def test_schema_valid_after_seed(self, seeded_con):
        missing = validate_schema(seeded_con)
        assert missing == {}

    def test_referential_integrity_no_orphan_sensor_readings(self, seeded_con):
        """Every sensor reading must reference a known shipment_id."""
        orphans = seeded_con.execute(
            """
            SELECT COUNT(*) FROM sensor_readings sr
            LEFT JOIN shipments sh ON sr.shipment_id = sh.shipment_id
            WHERE sh.shipment_id IS NULL
            """
        ).fetchone()[0]
        assert orphans == 0

    def test_at_least_one_disrupted_shipment(self, seeded_con):
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM shipments WHERE is_disrupted = TRUE"
        ).fetchone()[0]
        assert count >= 1

    def test_at_least_one_available_reefer_asset(self, seeded_con):
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM assets WHERE status = 'available' AND reefer_capable = TRUE"
        ).fetchone()[0]
        assert count >= 1

    def test_temperature_excursion_readings_exist(self, seeded_con):
        """At least one sensor reading must be outside its policy bounds."""
        rows = seeded_con.execute(
            """
            SELECT sr.temperature_c, tp.min_celsius, tp.max_celsius
            FROM sensor_readings sr
            JOIN shipments sh ON sr.shipment_id = sh.shipment_id
            JOIN temperature_policies tp ON sh.temperature_policy_id = tp.policy_id
            WHERE sr.temperature_c < tp.min_celsius OR sr.temperature_c > tp.max_celsius
            """
        ).fetchall()
        assert len(rows) >= 1

    def test_active_disruptions_have_blocked_nodes(self, seeded_con):
        rows = seeded_con.execute(
            "SELECT blocked_nodes FROM disruptions WHERE status = 'ACTIVE'"
        ).fetchall()
        assert len(rows) >= 1
        for (raw,) in rows:
            nodes = json.loads(raw)
            assert len(nodes) >= 1

    def test_query_helpers_return_data_after_seed(self, seeded_con):
        ships = query_shipments(seeded_con)
        assert len(ships) > 0
        idle = query_idle_assets(seeded_con)
        assert len(idle) > 0
