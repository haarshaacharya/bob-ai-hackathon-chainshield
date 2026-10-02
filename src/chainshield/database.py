from __future__ import annotations

"""
ChainShield local DuckDB demo store.

Responsibilities
----------------
- Create the five canonical tables (shipments, assets, sensor_readings,
  temperature_policies, disruptions) in an in-memory or file-backed
  DuckDB connection.
- Validate the schema after creation (column presence).
- Insert the deterministic synthetic demo data produced by
  ``generate_synthetic_data.generate_scenario()``.
- Expose thin query helpers that return validated Pydantic model instances.

Design constraints (AGENTS.md)
-------------------------------
- ``duckdb`` is imported lazily inside ``connect()`` — absence degrades
  gracefully with an ``ImportError`` that names the install hint.
- No network calls, no live APIs, no FastAPI endpoints.
- Tests use ``:memory:`` — never write to disk during tests.
- All timestamps are stored as ISO-8601 strings because DuckDB TIMESTAMP
  columns handle them transparently and Pydantic parses them back cleanly.
"""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Allow the package to be imported without a full package install when
# ``src/`` is on sys.path (mirrors conftest.py behaviour).
_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from chainshield.models import (
    Asset,
    Disruption,
    SensorReading,
    Shipment,
    TemperaturePolicy,
)

if TYPE_CHECKING:
    import duckdb as _duckdb

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_SHIPMENTS = """
CREATE TABLE IF NOT EXISTS shipments (
    shipment_id            VARCHAR PRIMARY KEY,
    cargo_type             VARCHAR,
    product_class          VARCHAR,
    temperature_policy_id  VARCHAR,
    origin_hub_id          VARCHAR NOT NULL,
    destination_hub_id     VARCHAR NOT NULL,
    current_node_id        VARCHAR,
    mode                   VARCHAR NOT NULL,
    carrier_id             VARCHAR,
    planned_departure      TIMESTAMP NOT NULL,
    planned_arrival        TIMESTAMP NOT NULL,
    delivery_deadline      TIMESTAMP NOT NULL,
    cargo_value_usd        DOUBLE  NOT NULL DEFAULT 0.0,
    weight_kg              DOUBLE  NOT NULL,
    status                 VARCHAR NOT NULL,
    is_disrupted           BOOLEAN NOT NULL DEFAULT FALSE,
    disruption_ids         VARCHAR NOT NULL DEFAULT '[]',
    reason_codes           VARCHAR NOT NULL DEFAULT '[]',
    route_node_ids         VARCHAR NOT NULL DEFAULT '[]',
    confidence             DOUBLE
)
"""

_DDL_ASSETS = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id               VARCHAR PRIMARY KEY,
    asset_type             VARCHAR NOT NULL,
    mode                   VARCHAR NOT NULL,
    current_node_id        VARCHAR NOT NULL,
    available_at           TIMESTAMP NOT NULL,
    capacity_kg            DOUBLE  NOT NULL,
    reefer_capable         BOOLEAN NOT NULL DEFAULT FALSE,
    carrier_id             VARCHAR,
    status                 VARCHAR NOT NULL
)
"""

_DDL_SENSOR_READINGS = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    sensor_id              VARCHAR NOT NULL,
    shipment_id            VARCHAR NOT NULL,
    ts                     TIMESTAMP NOT NULL,
    temperature_c          DOUBLE  NOT NULL,
    battery_pct            DOUBLE  NOT NULL DEFAULT 100.0,
    quality_flag           VARCHAR NOT NULL DEFAULT 'OK'
)
"""

_DDL_TEMPERATURE_POLICIES = """
CREATE TABLE IF NOT EXISTS temperature_policies (
    policy_id                         VARCHAR PRIMARY KEY,
    product_class                     VARCHAR NOT NULL,
    jurisdiction                      VARCHAR NOT NULL DEFAULT 'GLOBAL',
    min_celsius                       DOUBLE  NOT NULL,
    max_celsius                       DOUBLE  NOT NULL,
    max_continuous_excursion_minutes  DOUBLE  NOT NULL,
    sample_interval_minutes           DOUBLE  NOT NULL DEFAULT 6.0,
    source_reference                  VARCHAR NOT NULL DEFAULT '',
    severity_rules_json               VARCHAR NOT NULL DEFAULT '{}'
)
"""

_DDL_DISRUPTIONS = """
CREATE TABLE IF NOT EXISTS disruptions (
    disruption_id          VARCHAR PRIMARY KEY,
    disruption_type        VARCHAR NOT NULL,
    severity               VARCHAR NOT NULL,
    status                 VARCHAR NOT NULL,
    title                  VARCHAR NOT NULL DEFAULT '',
    window_start           TIMESTAMP NOT NULL,
    window_end             TIMESTAMP NOT NULL,
    blocked_nodes          VARCHAR NOT NULL DEFAULT '[]',
    reason_codes           VARCHAR NOT NULL DEFAULT '[]'
)
"""

_ALL_DDL = [
    _DDL_SHIPMENTS,
    _DDL_ASSETS,
    _DDL_SENSOR_READINGS,
    _DDL_TEMPERATURE_POLICIES,
    _DDL_DISRUPTIONS,
]

# Required columns per table used by ``validate_schema``.
_REQUIRED_COLUMNS: dict[str, list[str]] = {
    "shipments": [
        "shipment_id", "origin_hub_id", "destination_hub_id",
        "mode", "weight_kg", "status",
        "planned_departure", "planned_arrival", "delivery_deadline",
    ],
    "assets": [
        "asset_id", "asset_type", "mode", "current_node_id",
        "available_at", "capacity_kg", "reefer_capable", "status",
    ],
    "sensor_readings": [
        "sensor_id", "shipment_id", "ts", "temperature_c",
    ],
    "temperature_policies": [
        "policy_id", "product_class", "min_celsius", "max_celsius",
        "max_continuous_excursion_minutes",
    ],
    "disruptions": [
        "disruption_id", "disruption_type", "severity", "status",
        "window_start", "window_end",
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def connect(database: str = ":memory:") -> "_duckdb.DuckDBPyConnection":
    """Open (or create) a DuckDB connection and return it.

    Parameters
    ----------
    database:
        ``":memory:"`` for in-process ephemeral store (default; used in tests),
        or a file path string for a persistent file-backed store.

    Raises
    ------
    ImportError
        When ``duckdb`` is not installed — lists the install command.
    """
    try:
        import duckdb
    except ImportError as exc:
        raise ImportError(
            "duckdb is required for the database layer. "
            "Install with: pip install duckdb"
        ) from exc

    return duckdb.connect(database=database)


def create_tables(con: "_duckdb.DuckDBPyConnection") -> None:
    """Execute all DDL statements on *con*, creating tables if absent."""
    for ddl in _ALL_DDL:
        con.execute(ddl)


def validate_schema(con: "_duckdb.DuckDBPyConnection") -> dict[str, list[str]]:
    """Verify that every required column exists in each table.

    Returns
    -------
    dict[str, list[str]]
        Mapping of table name → list of **missing** column names.
        An empty dict means the schema is valid.
    """
    missing: dict[str, list[str]] = {}
    for table, required in _REQUIRED_COLUMNS.items():
        rows = con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?",
            [table],
        ).fetchall()
        present = {row[0] for row in rows}
        absent = [col for col in required if col not in present]
        if absent:
            missing[table] = absent
    return missing


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def insert_shipments(
    con: "_duckdb.DuckDBPyConnection", shipments: list[Shipment]
) -> int:
    """Insert *shipments* into the ``shipments`` table.

    Returns the number of rows inserted.
    """
    for s in shipments:
        con.execute(
            """
            INSERT OR REPLACE INTO shipments VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                s.shipment_id,
                s.cargo_type,
                s.product_class.value,
                s.temperature_policy_id,
                s.origin_hub_id,
                s.destination_hub_id,
                s.current_node_id,
                s.mode.value,
                s.carrier_id,
                s.planned_departure.isoformat(),
                s.planned_arrival.isoformat(),
                s.delivery_deadline.isoformat(),
                s.cargo_value_usd,
                s.weight_kg,
                s.status.value,
                s.is_disrupted,
                json.dumps(s.disruption_ids),
                json.dumps(s.reason_codes),
                json.dumps(s.route_node_ids),
                s.confidence,
            ],
        )
    return len(shipments)


def insert_assets(
    con: "_duckdb.DuckDBPyConnection", assets: list[Asset]
) -> int:
    """Insert *assets* into the ``assets`` table."""
    for a in assets:
        con.execute(
            """
            INSERT OR REPLACE INTO assets VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                a.asset_id,
                a.asset_type.value,
                a.mode.value,
                a.current_node_id,
                a.available_at.isoformat(),
                a.capacity_kg,
                a.reefer_capable,
                a.carrier_id,
                a.status.value,
            ],
        )
    return len(assets)


def insert_sensor_readings(
    con: "_duckdb.DuckDBPyConnection", readings: list[SensorReading]
) -> int:
    """Insert *readings* into the ``sensor_readings`` table."""
    for r in readings:
        con.execute(
            """
            INSERT INTO sensor_readings VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                r.sensor_id,
                r.shipment_id,
                r.ts.isoformat(),
                r.temperature_c,
                r.battery_pct,
                r.quality_flag.value,
            ],
        )
    return len(readings)


def insert_temperature_policies(
    con: "_duckdb.DuckDBPyConnection", policies: list[TemperaturePolicy]
) -> int:
    """Insert *policies* into the ``temperature_policies`` table."""
    for p in policies:
        con.execute(
            """
            INSERT OR REPLACE INTO temperature_policies VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                p.policy_id,
                p.product_class.value,
                p.jurisdiction,
                p.min_celsius,
                p.max_celsius,
                p.max_continuous_excursion_minutes,
                p.sample_interval_minutes,
                p.source_reference,
                p.severity_rules.model_dump_json(),
            ],
        )
    return len(policies)


def insert_disruptions(
    con: "_duckdb.DuckDBPyConnection", disruptions: list[Disruption]
) -> int:
    """Insert *disruptions* into the ``disruptions`` table."""
    for d in disruptions:
        con.execute(
            """
            INSERT OR REPLACE INTO disruptions VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                d.disruption_id,
                d.disruption_type.value,
                d.severity.value,
                d.status.value,
                d.title,
                d.window_start.isoformat(),
                d.window_end.isoformat(),
                json.dumps(d.geometry.blocked_nodes),
                json.dumps(d.reason_codes),
            ],
        )
    return len(disruptions)


# ---------------------------------------------------------------------------
# Query helpers — return validated Pydantic instances
# ---------------------------------------------------------------------------

def query_shipments(
    con: "_duckdb.DuckDBPyConnection",
    *,
    disrupted_only: bool = False,
) -> list[dict[str, Any]]:
    """Return raw row dicts from ``shipments`` (for lightweight use).

    Parameters
    ----------
    disrupted_only:
        When ``True``, filter to rows where ``is_disrupted = TRUE``.
    """
    sql = "SELECT * FROM shipments"
    if disrupted_only:
        sql += " WHERE is_disrupted = TRUE"

    rows = con.execute(sql).fetchall()
    desc = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'shipments' ORDER BY ordinal_position"
    ).fetchall()
    cols = [r[0] for r in desc]
    return [dict(zip(cols, row)) for row in rows]


def query_idle_assets(
    con: "_duckdb.DuckDBPyConnection",
    *,
    reefer_only: bool = False,
) -> list[dict[str, Any]]:
    """Return raw row dicts for assets with ``status = 'available'``."""
    sql = "SELECT * FROM assets WHERE status = 'available'"
    if reefer_only:
        sql += " AND reefer_capable = TRUE"

    rows = con.execute(sql).fetchall()
    desc = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'assets' ORDER BY ordinal_position"
    ).fetchall()
    cols = [r[0] for r in desc]
    return [dict(zip(cols, row)) for row in rows]


def query_sensor_readings(
    con: "_duckdb.DuckDBPyConnection",
    shipment_id: str,
) -> list[dict[str, Any]]:
    """Return raw row dicts for all sensor readings for *shipment_id*."""
    rows = con.execute(
        "SELECT * FROM sensor_readings WHERE shipment_id = ? ORDER BY ts",
        [shipment_id],
    ).fetchall()
    desc = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'sensor_readings' ORDER BY ordinal_position"
    ).fetchall()
    cols = [r[0] for r in desc]
    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------------------
# Convenience: seed from generate_scenario
# ---------------------------------------------------------------------------

def seed_demo(
    con: "_duckdb.DuckDBPyConnection",
    *,
    seed: int = 42,
) -> dict[str, int]:
    """Create tables and populate them with deterministic synthetic demo data.

    Parameters
    ----------
    con:
        Open DuckDB connection (use ``:memory:`` for tests).
    seed:
        Random seed forwarded to ``generate_scenario``.

    Returns
    -------
    dict[str, int]
        Row counts per table: ``{"shipments": N, "assets": N, ...}``.
    """
    from generate_synthetic_data import generate_scenario  # lazy import

    bundle = generate_scenario(seed=seed)
    create_tables(con)

    return {
        "shipments": insert_shipments(con, bundle.shipments),
        "assets": insert_assets(con, bundle.assets),
        "sensor_readings": insert_sensor_readings(con, bundle.sensor_readings),
        "temperature_policies": insert_temperature_policies(
            con, bundle.temperature_policies
        ),
        "disruptions": insert_disruptions(con, bundle.disruptions),
    }
