from __future__ import annotations

"""
generate_synthetic_data.py
==========================
Deterministic synthetic data layer for ChainShield demos and tests.

All data is generated from a fixed random seed so output is reproducible
across runs and environments.  No external APIs, datasets, or network
calls are used.

Public API
----------
    generate_scenario(seed: int = 42) -> ScenarioBundle

``ScenarioBundle`` is a dataclass containing lists of every domain object
type needed by the Impact Engine, Cold Chain Engine, and Optimization Engine:

    disruptions         – at least one ACTIVE disruption
    shipments           – affected and unaffected shipments
    assets              – idle compatible assets (and one incompatible)
    temperature_policies – cold-chain policy profiles
    sensor_readings     – normal readings + at least one excursion
    route_graph         – adjacency dict used by routing feasibility checks

Routing feasibility
-------------------
The ``route_graph`` is a simple dict[node_id, list[node_id]] describing
directed edges.  Each entry in ``feasible_routes`` is a list of node IDs
that forms a valid path avoiding disrupted nodes.  ``infeasible_routes``
are paths where the only route passes through a blocked node — i.e. no
feasible alternative exists given the graph topology.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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
    ExcursionSeverity,
    ProductClass,
    SensorQualityFlag,
    SensorReading,
    SeverityRules,
    Shipment,
    ShipmentLeg,
    ShipmentStatus,
    TemperaturePolicy,
)

# ---------------------------------------------------------------------------
# Constants — fixed reference timestamps (UTC)
# ---------------------------------------------------------------------------

_EPOCH = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# ScenarioBundle
# ---------------------------------------------------------------------------


@dataclass
class ScenarioBundle:
    """Container for a complete deterministic synthetic scenario.

    Attributes
    ----------
    disruptions
        Active disruption events.
    shipments
        All shipments (affected, unaffected, cold-chain).
    assets
        Fleet assets (idle compatible, idle incompatible, in-use).
    temperature_policies
        Cold-chain policy profiles keyed to product classes.
    sensor_readings
        Temperature time-series including at least one excursion.
    route_graph
        Directed adjacency dict: ``{node_id: [neighbour_ids]}`` for the
        demo logistics network.
    feasible_routes
        List of node-ID paths that avoid disrupted nodes.
    infeasible_routes
        List of node-ID paths where all paths pass through blocked nodes.
    """

    disruptions: list[Disruption] = field(default_factory=list)
    shipments: list[Shipment] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    temperature_policies: list[TemperaturePolicy] = field(default_factory=list)
    sensor_readings: list[SensorReading] = field(default_factory=list)
    route_graph: dict[str, list[str]] = field(default_factory=dict)
    feasible_routes: list[list[str]] = field(default_factory=list)
    infeasible_routes: list[list[str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc(offset_hours: float) -> datetime:
    """Return _EPOCH + offset_hours as a UTC datetime."""
    return _EPOCH + timedelta(hours=offset_hours)


def _make_temperature_policies() -> list[TemperaturePolicy]:
    """Return the set of cold-chain policy profiles used in the scenario."""
    refrigerated_vaccine = TemperaturePolicy(
        policy_id="POL-CDC-REFVAX-01",
        product_class=ProductClass.REFRIGERATED_VACCINE,
        jurisdiction="CDC",
        min_celsius=2.0,
        max_celsius=8.0,
        max_continuous_excursion_minutes=15.0,
        sample_interval_minutes=6.0,
        source_reference="CDC Vaccine Storage and Handling Toolkit",
        severity_rules=SeverityRules(
            out_of_range=ExcursionSeverity.EXCURSION_REVIEW,
            missing_sensor_data=ExcursionSeverity.URGENT_ESCALATION,
            sustained_excursion=ExcursionSeverity.URGENT_ESCALATION,
        ),
    )
    biologics = TemperaturePolicy(
        policy_id="POL-BIO-01",
        product_class=ProductClass.BIOLOGICS,
        jurisdiction="EU-GMP",
        min_celsius=2.0,
        max_celsius=8.0,
        max_continuous_excursion_minutes=30.0,
        sample_interval_minutes=10.0,
        source_reference="EU GMP Annex 13",
        severity_rules=SeverityRules(),
    )
    frozen_food = TemperaturePolicy(
        policy_id="POL-FROZEN-01",
        product_class=ProductClass.FROZEN_FOOD,
        jurisdiction="GLOBAL",
        min_celsius=-25.0,
        max_celsius=-15.0,
        max_continuous_excursion_minutes=60.0,
        sample_interval_minutes=15.0,
        source_reference="Codex Alimentarius",
        severity_rules=SeverityRules(),
    )
    return [refrigerated_vaccine, biologics, frozen_food]


def _make_disruptions() -> list[Disruption]:
    """Return the active disruptions for the demo scenario."""
    port_strike = Disruption(
        disruption_id="DISR-PORT-STRIKE-01",
        disruption_type=DisruptionType.PORT_STRIKE,
        severity=DisruptionSeverity.HIGH,
        status=DisruptionStatus.ACTIVE,
        title="Port of Aden strike action",
        description=(
            "Dock workers at PORT-03 have initiated industrial action. "
            "All container throughput is suspended."
        ),
        window_start=_utc(0),
        window_end=_utc(72),
        geometry=DisruptionGeometry(
            blocked_nodes=["PORT-03"],
            blocked_edges=["HUB-B:PORT-03", "PORT-03:HUB-C"],
            center_lat=12.8,
            center_lon=45.0,
            radius_km=50.0,
        ),
        reason_codes=["PORT_NODE_BLOCKED", "CARRIER_STRIKE_ACTIVE"],
        activated_at=_utc(-1),
    )
    weather = Disruption(
        disruption_id="DISR-WEATHER-01",
        disruption_type=DisruptionType.SEVERE_WEATHER,
        severity=DisruptionSeverity.MEDIUM,
        status=DisruptionStatus.MONITORING,
        title="Cyclone watch — Gulf of Aden",
        description="Tropical cyclone forecast to impact sea lane HUB-C to PORT-04.",
        window_start=_utc(48),
        window_end=_utc(96),
        geometry=DisruptionGeometry(
            blocked_nodes=[],
            blocked_edges=["HUB-C:PORT-04"],
            center_lat=13.5,
            center_lon=48.2,
            radius_km=200.0,
        ),
        reason_codes=["WEATHER_ZONE_OVERLAP"],
        activated_at=_utc(-2),
    )
    return [port_strike, weather]


def _make_route_graph() -> dict[str, list[str]]:
    """
    Return a directed adjacency dict for the demo logistics network.

    Topology::

        HUB-A → HUB-B → PORT-03 → HUB-C → HUB-D   (primary — PORT-03 blocked)
        HUB-A → HUB-B → DEPOT-X → HUB-C → HUB-D   (feasible reroute)
        HUB-E → PORT-03 → HUB-F                     (infeasible — no alt path)
    """
    return {
        "HUB-A": ["HUB-B"],
        "HUB-B": ["PORT-03", "DEPOT-X"],
        "PORT-03": ["HUB-C", "HUB-F"],
        "DEPOT-X": ["HUB-C"],
        "HUB-C": ["HUB-D", "PORT-04"],
        "HUB-D": [],
        "HUB-E": ["PORT-03"],
        "HUB-F": [],
        "PORT-04": ["HUB-D"],
    }


def _make_shipments(rng: random.Random) -> list[Shipment]:
    """Return demo shipments covering all required scenario types."""
    # ------------------------------------------------------------------ #
    # SHP-001 — affected (passes through PORT-03, disruption window)
    # ------------------------------------------------------------------ #
    leg_0 = ShipmentLeg(
        leg_id="LEG-001-00",
        shipment_id="SHP-001",
        sequence=0,
        origin_node_id="HUB-A",
        destination_node_id="HUB-B",
        mode=CargoMode.ROAD,
        planned_departure=_utc(2),
        planned_arrival=_utc(6),
        distance_km=320.0,
        cost_usd=1_200.0,
    )
    leg_1 = ShipmentLeg(
        leg_id="LEG-001-01",
        shipment_id="SHP-001",
        sequence=1,
        origin_node_id="HUB-B",
        destination_node_id="PORT-03",
        mode=CargoMode.SEA,
        planned_departure=_utc(8),
        planned_arrival=_utc(30),
        distance_km=1_450.0,
        cost_usd=8_500.0,
        is_disrupted=True,
        reason_codes=["PORT_NODE_BLOCKED"],
    )
    leg_2 = ShipmentLeg(
        leg_id="LEG-001-02",
        shipment_id="SHP-001",
        sequence=2,
        origin_node_id="PORT-03",
        destination_node_id="HUB-D",
        mode=CargoMode.ROAD,
        planned_departure=_utc(32),
        planned_arrival=_utc(40),
        distance_km=280.0,
        cost_usd=900.0,
    )
    shp_affected = Shipment(
        shipment_id="SHP-001",
        cargo_type="reefer",
        product_class=ProductClass.REFRIGERATED_VACCINE,
        temperature_policy_id="POL-CDC-REFVAX-01",
        cargo_value_usd=520_000.0,
        weight_kg=8_200.0,
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-D",
        route_node_ids=["HUB-A", "HUB-B", "PORT-03", "HUB-D"],
        current_node_id="HUB-B",
        mode=CargoMode.MULTIMODAL,
        carrier_id="CARRIER-A",
        planned_departure=_utc(2),
        planned_arrival=_utc(40),
        delivery_deadline=_utc(48),
        status=ShipmentStatus.IN_TRANSIT,
        is_disrupted=True,
        disruption_ids=["DISR-PORT-STRIKE-01"],
        reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
        confidence=0.94,
        legs=[leg_0, leg_1, leg_2],
    )

    # ------------------------------------------------------------------ #
    # SHP-002 — unaffected (does not pass through any blocked node)
    # ------------------------------------------------------------------ #
    shp_unaffected = Shipment(
        shipment_id="SHP-002",
        cargo_type="dry bulk",
        product_class=ProductClass.DRY_GOODS,
        temperature_policy_id=None,
        cargo_value_usd=75_000.0,
        weight_kg=22_000.0,
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-C",
        route_node_ids=["HUB-A", "HUB-B", "DEPOT-X", "HUB-C"],
        current_node_id="HUB-A",
        mode=CargoMode.ROAD,
        carrier_id="CARRIER-B",
        planned_departure=_utc(4),
        planned_arrival=_utc(20),
        delivery_deadline=_utc(36),
        status=ShipmentStatus.PLANNED,
        is_disrupted=False,
    )

    # ------------------------------------------------------------------ #
    # SHP-003 — cold-chain biologics (temperature excursion scenario)
    # ------------------------------------------------------------------ #
    shp_coldchain = Shipment(
        shipment_id="SHP-003",
        cargo_type="biologics",
        product_class=ProductClass.BIOLOGICS,
        temperature_policy_id="POL-BIO-01",
        cargo_value_usd=1_200_000.0,
        weight_kg=1_800.0,
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-D",
        route_node_ids=["HUB-A", "HUB-B", "DEPOT-X", "HUB-C", "HUB-D"],
        current_node_id="DEPOT-X",
        mode=CargoMode.AIR,
        carrier_id="CARRIER-C",
        planned_departure=_utc(1),
        planned_arrival=_utc(14),
        delivery_deadline=_utc(18),
        status=ShipmentStatus.IN_TRANSIT,
        is_disrupted=False,
    )

    # ------------------------------------------------------------------ #
    # SHP-004 — infeasible routing (only path is through PORT-03, no alt)
    # ------------------------------------------------------------------ #
    shp_infeasible = Shipment(
        shipment_id="SHP-004",
        cargo_type="chemicals",
        product_class=ProductClass.CHEMICALS,
        temperature_policy_id=None,
        cargo_value_usd=340_000.0,
        weight_kg=5_500.0,
        origin_hub_id="HUB-E",
        destination_hub_id="HUB-F",
        route_node_ids=["HUB-E", "PORT-03", "HUB-F"],
        current_node_id="HUB-E",
        mode=CargoMode.SEA,
        carrier_id="CARRIER-A",
        planned_departure=_utc(5),
        planned_arrival=_utc(28),
        delivery_deadline=_utc(32),
        status=ShipmentStatus.DELAYED,
        is_disrupted=True,
        disruption_ids=["DISR-PORT-STRIKE-01"],
        reason_codes=["PORT_NODE_BLOCKED", "NO_FEASIBLE_REROUTE"],
        confidence=0.99,
    )

    return [shp_affected, shp_unaffected, shp_coldchain, shp_infeasible]


def _make_assets() -> list[Asset]:
    """Return fleet assets: idle+compatible, idle+incompatible, in-use."""
    idle_reefer = Asset(
        asset_id="ASSET-REEFER-01",
        asset_type=AssetType.REEFER_UNIT,
        mode=AssetMode.SEA,
        carrier_id="CARRIER-A",
        current_node_id="HUB-B",
        location_lat=11.5,
        location_lon=43.1,
        status=AssetStatus.AVAILABLE,
        available_at=_utc(0),
        capacity_kg=20_000.0,
        capacity_m3=33.0,
        reefer_capable=True,
        reefer_min_celsius=-25.0,
        reefer_max_celsius=8.0,
        reposition_distance_km=0.0,
        reposition_eta_minutes=0.0,
        compatibility_score=0.95,
    )
    idle_dry_truck = Asset(
        asset_id="ASSET-TRUCK-02",
        asset_type=AssetType.TRUCK,
        mode=AssetMode.ROAD,
        carrier_id="CARRIER-B",
        current_node_id="HUB-A",
        location_lat=12.1,
        location_lon=44.5,
        status=AssetStatus.AVAILABLE,
        available_at=_utc(1),
        capacity_kg=18_000.0,
        reefer_capable=False,
        reposition_distance_km=320.0,
        reposition_eta_minutes=240.0,
        compatibility_score=0.60,
    )
    # Incompatible: reefer required but this truck is dry
    idle_incompatible = Asset(
        asset_id="ASSET-TRUCK-03",
        asset_type=AssetType.TRUCK,
        mode=AssetMode.ROAD,
        carrier_id="CARRIER-D",
        current_node_id="HUB-C",
        status=AssetStatus.AVAILABLE,
        available_at=_utc(2),
        capacity_kg=10_000.0,
        reefer_capable=False,
        compatibility_score=0.10,
    )
    in_use_vessel = Asset(
        asset_id="ASSET-VESSEL-04",
        asset_type=AssetType.VESSEL,
        mode=AssetMode.SEA,
        carrier_id="CARRIER-A",
        current_node_id="PORT-04",
        status=AssetStatus.IN_USE,
        available_at=_utc(80),
        capacity_kg=50_000.0,
        reefer_capable=True,
        reefer_min_celsius=-20.0,
        reefer_max_celsius=5.0,
    )
    return [idle_reefer, idle_dry_truck, idle_incompatible, in_use_vessel]


def _make_sensor_readings(rng: random.Random) -> list[SensorReading]:
    """
    Generate temperature time-series for SHP-003 (biologics, 2–8 °C).

    Includes:
      - Normal in-range readings
      - One temperature excursion (reading above 8 °C)
      - One DOOR_OPEN quality event
    """
    readings: list[SensorReading] = []
    sensor_id = "SENSOR-BIO-001"
    shipment_id = "SHP-003"
    # 20 readings at 6-minute intervals starting 1 h into transit
    base_ts = _utc(1)
    for i in range(20):
        ts = base_ts + timedelta(minutes=6 * i)
        # Normal: temperature stays near 5 °C with small noise
        temp = 5.0 + rng.uniform(-0.8, 0.8)
        quality = SensorQualityFlag.OK
        readings.append(
            SensorReading(
                sensor_id=sensor_id,
                shipment_id=shipment_id,
                ts=ts,
                temperature_c=round(temp, 2),
                battery_pct=97.0 - i * 0.3,
                quality_flag=quality,
            )
        )

    # Excursion event: reading 11 — temperature spikes to 11.5 °C (above 8 °C)
    excursion_ts = base_ts + timedelta(minutes=6 * 11)
    readings[11] = SensorReading(
        sensor_id=sensor_id,
        shipment_id=shipment_id,
        ts=excursion_ts,
        temperature_c=11.5,
        battery_pct=93.7,
        quality_flag=SensorQualityFlag.DOOR_OPEN,
    )
    # Reading 12 — another out-of-range reading before recovery
    excursion_ts2 = base_ts + timedelta(minutes=6 * 12)
    readings[12] = SensorReading(
        sensor_id=sensor_id,
        shipment_id=shipment_id,
        ts=excursion_ts2,
        temperature_c=9.2,
        battery_pct=93.5,
        quality_flag=SensorQualityFlag.OK,
    )
    return readings


def _make_routes() -> tuple[list[list[str]], list[list[str]]]:
    """
    Return (feasible_routes, infeasible_routes).

    Feasible
    --------
    HUB-A → HUB-B → DEPOT-X → HUB-C → HUB-D  (avoids PORT-03)

    Infeasible
    ----------
    HUB-E → PORT-03 → HUB-F  (PORT-03 is the only path; no alternative)
    """
    feasible = [["HUB-A", "HUB-B", "DEPOT-X", "HUB-C", "HUB-D"]]
    infeasible = [["HUB-E", "PORT-03", "HUB-F"]]
    return feasible, infeasible


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_scenario(seed: int = 42) -> ScenarioBundle:
    """Generate and return a fully deterministic ``ScenarioBundle``.

    Parameters
    ----------
    seed
        Random seed for reproducibility (default 42).

    Returns
    -------
    ScenarioBundle
        All domain objects required by the Impact Engine, Cold Chain Engine,
        and Optimization Engine for offline demo and testing.
    """
    rng = random.Random(seed)

    policies = _make_temperature_policies()
    disruptions = _make_disruptions()
    shipments = _make_shipments(rng)
    assets = _make_assets()
    sensor_readings = _make_sensor_readings(rng)
    route_graph = _make_route_graph()
    feasible_routes, infeasible_routes = _make_routes()

    return ScenarioBundle(
        disruptions=disruptions,
        shipments=shipments,
        assets=assets,
        temperature_policies=policies,
        sensor_readings=sensor_readings,
        route_graph=route_graph,
        feasible_routes=feasible_routes,
        infeasible_routes=infeasible_routes,
    )


if __name__ == "__main__":
    bundle = generate_scenario()
    print(f"Disruptions      : {len(bundle.disruptions)}")
    print(f"Shipments        : {len(bundle.shipments)}")
    print(f"Assets           : {len(bundle.assets)}")
    print(f"Temperature policies: {len(bundle.temperature_policies)}")
    print(f"Sensor readings  : {len(bundle.sensor_readings)}")
    print(f"Feasible routes  : {bundle.feasible_routes}")
    print(f"Infeasible routes: {bundle.infeasible_routes}")
