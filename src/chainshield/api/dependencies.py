from __future__ import annotations

"""
ChainShield FastAPI dependency providers.

All application-level singletons (engines, data stores, graph) are created
once at import time and exposed via FastAPI ``Depends()`` callables.  The API
layer never constructs engines inline — it always receives them through these
injectors so they can be swapped in tests.

Offline-first: no network calls, no external credentials required here.
"""

from datetime import datetime, timezone
from functools import lru_cache

import networkx as nx

from chainshield.cold_chain.engine import ColdChainEngine
from chainshield.evidence.store import EvidenceStore
from chainshield.impact.engine import ImpactEngine
from chainshield.models.asset import Asset, AssetMode, AssetStatus, AssetType
from chainshield.models.disruption import (
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
)
from chainshield.models.enums import CargoMode, ProductClass, ShipmentStatus
from chainshield.models.sensor_reading import SensorReading
from chainshield.models.shipment import Shipment
from chainshield.models.temperature_policy import SeverityRules, TemperaturePolicy
from chainshield.optimization.engine import OptimizationEngine


# ---------------------------------------------------------------------------
# Demo / seed data fixtures
# ---------------------------------------------------------------------------

def _build_demo_graph() -> nx.DiGraph:
    """Return the demo route graph used by the preflight scenario."""
    G: nx.DiGraph = nx.DiGraph()
    G.add_edge("HUB-A", "PORT-03", transit_hours=6.0, cost_usd=800.0)
    G.add_edge("PORT-03", "HUB-B", transit_hours=4.0, cost_usd=600.0)
    G.add_edge("HUB-B", "HUB-D", transit_hours=3.0, cost_usd=400.0)
    G.add_edge("HUB-A", "HUB-D", transit_hours=10.0, cost_usd=1200.0)
    # Reverse edges so the graph is traversable bidirectionally
    G.add_edge("PORT-03", "HUB-A", transit_hours=6.0, cost_usd=800.0)
    G.add_edge("HUB-B", "PORT-03", transit_hours=4.0, cost_usd=600.0)
    G.add_edge("HUB-D", "HUB-B", transit_hours=3.0, cost_usd=400.0)
    G.add_edge("HUB-D", "HUB-A", transit_hours=10.0, cost_usd=1200.0)
    return G


def _build_demo_shipments() -> dict[str, Shipment]:
    return {
        "SHP-0042": Shipment(
            shipment_id="SHP-0042",
            cargo_type="reefer",
            product_class=ProductClass.REFRIGERATED_VACCINE,
            temperature_policy_id="POL-CDC-01",
            cargo_value_usd=520_000.0,
            weight_kg=8200.0,
            origin_hub_id="HUB-A",
            destination_hub_id="HUB-D",
            current_node_id="HUB-B",
            route_node_ids=["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
            mode=CargoMode.SEA,
            carrier_id="CARRIER-A",
            planned_departure=datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc),
            planned_arrival=datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc),
            delivery_deadline=datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc),
            status=ShipmentStatus.IN_TRANSIT,
        ),
        "SHP-0099": Shipment(
            shipment_id="SHP-0099",
            cargo_type="dry",
            product_class=ProductClass.DRY_GOODS,
            cargo_value_usd=80_000.0,
            weight_kg=4000.0,
            origin_hub_id="HUB-A",
            destination_hub_id="HUB-D",
            route_node_ids=["HUB-A", "HUB-D"],
            mode=CargoMode.ROAD,
            planned_departure=datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc),
            planned_arrival=datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc),
            delivery_deadline=datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc),
            status=ShipmentStatus.IN_TRANSIT,
        ),
    }


def _build_demo_assets() -> list[Asset]:
    return [
        Asset(
            asset_id="TRUCK-17",
            asset_type=AssetType.REEFER_UNIT,
            mode=AssetMode.ROAD,
            carrier_id="CARRIER-B",
            current_node_id="HUB-B",
            available_at=datetime(2026, 9, 14, 9, 25, tzinfo=timezone.utc),
            capacity_kg=12_000.0,
            reefer_capable=True,
            status=AssetStatus.AVAILABLE,
        ),
        Asset(
            asset_id="TRUCK-22",
            asset_type=AssetType.TRUCK,
            mode=AssetMode.ROAD,
            carrier_id="CARRIER-C",
            current_node_id="HUB-D",
            available_at=datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc),
            capacity_kg=6_000.0,
            reefer_capable=False,
            status=AssetStatus.AVAILABLE,
        ),
    ]


def _build_demo_sensor_readings() -> dict[str, list[SensorReading]]:
    raw = [
        ("2026-09-14T08:00:00+00:00", 6.9),
        ("2026-09-14T08:06:00+00:00", 8.9),
        ("2026-09-14T08:12:00+00:00", 10.4),
        ("2026-09-14T08:18:00+00:00", 9.1),
        ("2026-09-14T08:24:00+00:00", 6.4),
    ]
    return {
        "SHP-0042": [
            SensorReading(sensor_id="SENSOR-9", shipment_id="SHP-0042", ts=ts, temperature_c=temp)
            for ts, temp in raw
        ]
    }


def _build_demo_policies() -> dict[str, TemperaturePolicy]:
    return {
        "POL-CDC-01": TemperaturePolicy(
            policy_id="POL-CDC-01",
            product_class=ProductClass.REFRIGERATED_VACCINE,
            min_celsius=2.0,
            max_celsius=8.0,
            # The demo scenario has a ~18-minute continuous excursion (3 readings × 6 min).
            # Threshold is set to 30 min so the demo run classifies as EXCURSION_REVIEW
            # (out_of_range severity) rather than triggering the sustained_excursion
            # escalation path.  This matches the preflight_demo.py reference scenario
            # comment: "~18 minutes out of the 2-8C policy range → EXCURSION_REVIEW".
            max_continuous_excursion_minutes=30.0,
            sample_interval_minutes=6.0,
            source_reference="CDC Vaccine Storage and Handling Toolkit (demo profile)",
            severity_rules=SeverityRules(),
        )
    }


# ---------------------------------------------------------------------------
# Singleton accessors — injected via FastAPI Depends()
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_graph() -> nx.DiGraph:
    return _build_demo_graph()


@lru_cache(maxsize=1)
def get_shipments() -> dict[str, Shipment]:
    return _build_demo_shipments()


@lru_cache(maxsize=1)
def get_assets() -> list[Asset]:
    return _build_demo_assets()


@lru_cache(maxsize=1)
def get_sensor_readings() -> dict[str, list[SensorReading]]:
    return _build_demo_sensor_readings()


@lru_cache(maxsize=1)
def get_policies() -> dict[str, TemperaturePolicy]:
    return _build_demo_policies()


@lru_cache(maxsize=1)
def get_active_disruptions() -> list[Disruption]:
    return []


@lru_cache(maxsize=1)
def get_impact_engine() -> ImpactEngine:
    return ImpactEngine(get_graph())


@lru_cache(maxsize=1)
def get_cold_chain_engine() -> ColdChainEngine:
    return ColdChainEngine()


@lru_cache(maxsize=1)
def get_optimization_engine() -> OptimizationEngine:
    return OptimizationEngine(get_graph())


@lru_cache(maxsize=1)
def get_evidence_store() -> EvidenceStore:
    return EvidenceStore()


def get_app_config() -> "ChainShieldConfig":
    from chainshield.config import get_config
    return get_config()

