from __future__ import annotations

"""
tests/unit/test_synthetic_data.py
==================================
Unit tests for the deterministic synthetic data layer.

Verifies that ``generate_scenario()`` produces a ``ScenarioBundle`` that
satisfies every domain requirement listed in the task specification:

  ✓ at least one affected shipment
  ✓ at least one unaffected shipment
  ✓ at least one active disruption
  ✓ at least one idle compatible asset
  ✓ at least one cold-chain shipment
  ✓ at least one temperature excursion in the sensor readings
  ✓ at least one feasible rerouting scenario
  ✓ at least one infeasible routing condition

Also checks:
  - Determinism: same seed → identical output
  - Different seed → different output (sanity)
  - All Pydantic models validate cleanly (no construction errors)
  - JSON round-trip fidelity for every domain object
  - Structural invariants (e.g. route_graph adjacency, blocked_nodes non-empty)
"""

import sys
from pathlib import Path

import pytest

# Allow pytest to import the scripts and src directories without package install
_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SRC_DIR = _REPO_ROOT / "src"
for _p in (_SRC_DIR, _SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from generate_synthetic_data import ScenarioBundle, generate_scenario

from chainshield.models import (
    Asset,
    AssetStatus,
    Disruption,
    DisruptionStatus,
    SensorQualityFlag,
    SensorReading,
    Shipment,
    TemperaturePolicy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bundle() -> ScenarioBundle:
    """A single scenario bundle shared across all tests (module scope = fast)."""
    return generate_scenario(seed=42)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_seed_identical_shipment_ids(self):
        b1 = generate_scenario(seed=42)
        b2 = generate_scenario(seed=42)
        ids1 = sorted(s.shipment_id for s in b1.shipments)
        ids2 = sorted(s.shipment_id for s in b2.shipments)
        assert ids1 == ids2

    def test_same_seed_identical_sensor_temperatures(self):
        b1 = generate_scenario(seed=42)
        b2 = generate_scenario(seed=42)
        temps1 = [r.temperature_c for r in b1.sensor_readings]
        temps2 = [r.temperature_c for r in b2.sensor_readings]
        assert temps1 == temps2

    def test_different_seed_different_sensor_temperatures(self):
        b1 = generate_scenario(seed=42)
        b2 = generate_scenario(seed=99)
        temps1 = [r.temperature_c for r in b1.sensor_readings]
        temps2 = [r.temperature_c for r in b2.sensor_readings]
        # At least some readings must differ; excursion readings are fixed so
        # we compare the full list.
        assert temps1 != temps2


# ---------------------------------------------------------------------------
# Affected shipment
# ---------------------------------------------------------------------------


class TestAffectedShipment:
    def test_at_least_one_affected(self, bundle: ScenarioBundle):
        affected = [s for s in bundle.shipments if s.is_disrupted]
        assert len(affected) >= 1, "Expected at least one affected shipment"

    def test_affected_shipment_has_disruption_ids(self, bundle: ScenarioBundle):
        affected = [s for s in bundle.shipments if s.is_disrupted]
        for shp in affected:
            assert len(shp.disruption_ids) >= 1

    def test_affected_shipment_has_reason_codes(self, bundle: ScenarioBundle):
        affected = [s for s in bundle.shipments if s.is_disrupted]
        for shp in affected:
            assert len(shp.reason_codes) >= 1

    def test_affected_shipment_reason_codes_are_screaming_snake(
        self, bundle: ScenarioBundle
    ):
        affected = [s for s in bundle.shipments if s.is_disrupted]
        for shp in affected:
            for code in shp.reason_codes:
                assert code == code.upper() and " " not in code, (
                    f"Reason code {code!r} is not SCREAMING_SNAKE_CASE"
                )

    def test_affected_shipment_confidence_set(self, bundle: ScenarioBundle):
        affected = [s for s in bundle.shipments if s.is_disrupted]
        for shp in affected:
            assert shp.confidence is not None
            assert 0.0 <= shp.confidence <= 1.0

    def test_affected_shipment_route_passes_through_blocked_node(
        self, bundle: ScenarioBundle
    ):
        blocked: set[str] = set()
        for d in bundle.disruptions:
            blocked.update(d.geometry.blocked_nodes)
        affected = [s for s in bundle.shipments if s.is_disrupted]
        for shp in affected:
            assert set(shp.route_node_ids) & blocked, (
                f"Affected shipment {shp.shipment_id} route does not overlap "
                f"blocked nodes {blocked}"
            )


# ---------------------------------------------------------------------------
# Unaffected shipment
# ---------------------------------------------------------------------------


class TestUnaffectedShipment:
    def test_at_least_one_unaffected(self, bundle: ScenarioBundle):
        unaffected = [s for s in bundle.shipments if not s.is_disrupted]
        assert len(unaffected) >= 1, "Expected at least one unaffected shipment"

    def test_unaffected_shipment_has_no_disruption_ids(self, bundle: ScenarioBundle):
        unaffected = [s for s in bundle.shipments if not s.is_disrupted]
        for shp in unaffected:
            assert shp.disruption_ids == []

    def test_unaffected_shipment_route_avoids_blocked_nodes(
        self, bundle: ScenarioBundle
    ):
        active_disruptions = [
            d for d in bundle.disruptions if d.status == DisruptionStatus.ACTIVE
        ]
        blocked: set[str] = set()
        for d in active_disruptions:
            blocked.update(d.geometry.blocked_nodes)

        unaffected = [s for s in bundle.shipments if not s.is_disrupted]
        for shp in unaffected:
            overlap = set(shp.route_node_ids) & blocked
            assert not overlap, (
                f"Unaffected shipment {shp.shipment_id} route overlaps blocked "
                f"nodes {overlap}"
            )


# ---------------------------------------------------------------------------
# Active disruption
# ---------------------------------------------------------------------------


class TestActiveDisruption:
    def test_at_least_one_active_disruption(self, bundle: ScenarioBundle):
        active = [d for d in bundle.disruptions if d.status == DisruptionStatus.ACTIVE]
        assert len(active) >= 1, "Expected at least one ACTIVE disruption"

    def test_active_disruption_window_order(self, bundle: ScenarioBundle):
        active = [d for d in bundle.disruptions if d.status == DisruptionStatus.ACTIVE]
        for d in active:
            assert d.window_start < d.window_end

    def test_active_disruption_has_blocked_nodes(self, bundle: ScenarioBundle):
        active = [d for d in bundle.disruptions if d.status == DisruptionStatus.ACTIVE]
        for d in active:
            assert len(d.geometry.blocked_nodes) >= 1, (
                f"Active disruption {d.disruption_id} has no blocked_nodes"
            )

    def test_active_disruption_reason_codes_screaming_snake(
        self, bundle: ScenarioBundle
    ):
        for d in bundle.disruptions:
            for code in d.reason_codes:
                assert code == code.upper() and " " not in code


# ---------------------------------------------------------------------------
# Idle compatible asset
# ---------------------------------------------------------------------------


class TestIdleCompatibleAsset:
    def test_at_least_one_idle_compatible_asset(self, bundle: ScenarioBundle):
        idle = [
            a for a in bundle.assets if a.status == AssetStatus.AVAILABLE
        ]
        assert len(idle) >= 1, "Expected at least one AVAILABLE asset"

    def test_idle_reefer_asset_exists(self, bundle: ScenarioBundle):
        """An idle reefer-capable asset must exist (for cold-chain rerouting)."""
        idle_reefer = [
            a
            for a in bundle.assets
            if a.status == AssetStatus.AVAILABLE and a.reefer_capable
        ]
        assert len(idle_reefer) >= 1, "Expected at least one idle reefer-capable asset"

    def test_incompatible_asset_exists(self, bundle: ScenarioBundle):
        """An incompatible (non-reefer) asset must also exist for contrast."""
        incompatible = [
            a
            for a in bundle.assets
            if a.status == AssetStatus.AVAILABLE and not a.reefer_capable
        ]
        assert len(incompatible) >= 1

    def test_idle_asset_available_at_is_set(self, bundle: ScenarioBundle):
        idle = [a for a in bundle.assets if a.status == AssetStatus.AVAILABLE]
        for asset in idle:
            assert asset.available_at is not None

    def test_idle_asset_capacity_positive(self, bundle: ScenarioBundle):
        for asset in bundle.assets:
            assert asset.capacity_kg > 0.0


# ---------------------------------------------------------------------------
# Cold-chain shipment
# ---------------------------------------------------------------------------


class TestColdChainShipment:
    def test_at_least_one_cold_chain_shipment(self, bundle: ScenarioBundle):
        cold = [s for s in bundle.shipments if s.temperature_policy_id is not None]
        assert len(cold) >= 1, "Expected at least one cold-chain shipment"

    def test_cold_chain_shipment_has_policy(self, bundle: ScenarioBundle):
        cold = [s for s in bundle.shipments if s.temperature_policy_id is not None]
        policy_ids = {p.policy_id for p in bundle.temperature_policies}
        for shp in cold:
            assert shp.temperature_policy_id in policy_ids, (
                f"Shipment {shp.shipment_id} references unknown policy "
                f"{shp.temperature_policy_id!r}"
            )

    def test_temperature_policies_have_valid_ranges(self, bundle: ScenarioBundle):
        for pol in bundle.temperature_policies:
            assert pol.min_celsius < pol.max_celsius
            assert pol.max_continuous_excursion_minutes > 0
            assert pol.sample_interval_minutes > 0


# ---------------------------------------------------------------------------
# Temperature excursion
# ---------------------------------------------------------------------------


class TestTemperatureExcursion:
    def test_sensor_readings_exist(self, bundle: ScenarioBundle):
        assert len(bundle.sensor_readings) > 0

    def test_at_least_one_excursion_reading(self, bundle: ScenarioBundle):
        """At least one reading must be outside the cold-chain policy range."""
        cold_shipments = {
            s.shipment_id: s
            for s in bundle.shipments
            if s.temperature_policy_id is not None
        }
        policy_map = {p.policy_id: p for p in bundle.temperature_policies}

        excursions = []
        for r in bundle.sensor_readings:
            shp = cold_shipments.get(r.shipment_id)
            if shp is None:
                continue
            pol = policy_map.get(shp.temperature_policy_id or "")
            if pol is None:
                continue
            if r.temperature_c < pol.min_celsius or r.temperature_c > pol.max_celsius:
                excursions.append(r)

        assert len(excursions) >= 1, (
            "Expected at least one temperature reading outside policy range"
        )

    def test_excursion_reading_temperature_above_max(self, bundle: ScenarioBundle):
        """The excursion reading for SHP-003 must exceed 8 °C."""
        shp003_readings = [
            r for r in bundle.sensor_readings if r.shipment_id == "SHP-003"
        ]
        above_max = [r for r in shp003_readings if r.temperature_c > 8.0]
        assert len(above_max) >= 1

    def test_door_open_quality_flag_present(self, bundle: ScenarioBundle):
        flags = {r.quality_flag for r in bundle.sensor_readings}
        assert SensorQualityFlag.DOOR_OPEN in flags

    def test_all_readings_have_valid_timestamps(self, bundle: ScenarioBundle):
        for r in bundle.sensor_readings:
            assert r.ts is not None
            assert r.ts.tzinfo is not None  # UTC-aware

    def test_readings_for_cold_chain_shipment_exist(self, bundle: ScenarioBundle):
        cold_ids = {
            s.shipment_id
            for s in bundle.shipments
            if s.temperature_policy_id is not None
        }
        reading_shipment_ids = {r.shipment_id for r in bundle.sensor_readings}
        assert cold_ids & reading_shipment_ids, (
            "No sensor readings found for any cold-chain shipment"
        )


# ---------------------------------------------------------------------------
# Feasible rerouting
# ---------------------------------------------------------------------------


class TestFeasibleRerouting:
    def test_at_least_one_feasible_route(self, bundle: ScenarioBundle):
        assert len(bundle.feasible_routes) >= 1

    def test_feasible_route_avoids_blocked_nodes(self, bundle: ScenarioBundle):
        blocked: set[str] = set()
        for d in bundle.disruptions:
            if d.status == DisruptionStatus.ACTIVE:
                blocked.update(d.geometry.blocked_nodes)

        for route in bundle.feasible_routes:
            overlap = set(route) & blocked
            assert not overlap, (
                f"Feasible route {route} passes through blocked node(s) {overlap}"
            )

    def test_feasible_route_nodes_exist_in_graph(self, bundle: ScenarioBundle):
        for route in bundle.feasible_routes:
            for node in route:
                assert node in bundle.route_graph, (
                    f"Route node {node!r} not found in route_graph"
                )

    def test_feasible_route_is_connected(self, bundle: ScenarioBundle):
        """Every consecutive pair of nodes must share a graph edge."""
        for route in bundle.feasible_routes:
            for src, dst in zip(route[:-1], route[1:]):
                assert dst in bundle.route_graph.get(src, []), (
                    f"No edge {src!r} → {dst!r} in route_graph"
                )


# ---------------------------------------------------------------------------
# Infeasible routing condition
# ---------------------------------------------------------------------------


class TestInfeasibleRouting:
    def test_at_least_one_infeasible_route(self, bundle: ScenarioBundle):
        assert len(bundle.infeasible_routes) >= 1

    def test_infeasible_route_passes_through_blocked_node(
        self, bundle: ScenarioBundle
    ):
        blocked: set[str] = set()
        for d in bundle.disruptions:
            if d.status == DisruptionStatus.ACTIVE:
                blocked.update(d.geometry.blocked_nodes)

        for route in bundle.infeasible_routes:
            overlap = set(route) & blocked
            assert overlap, (
                f"Infeasible route {route} does not pass through any blocked node; "
                f"it should be infeasible because all paths go through {blocked}"
            )

    def test_infeasible_shipment_has_no_feasible_reroute_reason_code(
        self, bundle: ScenarioBundle
    ):
        """SHP-004 must carry the NO_FEASIBLE_REROUTE reason code."""
        infeasible_shp = next(
            (s for s in bundle.shipments if "NO_FEASIBLE_REROUTE" in s.reason_codes),
            None,
        )
        assert infeasible_shp is not None, (
            "Expected a shipment with reason code NO_FEASIBLE_REROUTE"
        )


# ---------------------------------------------------------------------------
# JSON round-trip fidelity
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_shipments_round_trip(self, bundle: ScenarioBundle):
        for shp in bundle.shipments:
            reloaded = Shipment.model_validate_json(shp.model_dump_json())
            assert reloaded == shp

    def test_disruptions_round_trip(self, bundle: ScenarioBundle):
        for d in bundle.disruptions:
            reloaded = Disruption.model_validate_json(d.model_dump_json())
            assert reloaded == d

    def test_assets_round_trip(self, bundle: ScenarioBundle):
        for a in bundle.assets:
            reloaded = Asset.model_validate_json(a.model_dump_json())
            assert reloaded == a

    def test_temperature_policies_round_trip(self, bundle: ScenarioBundle):
        for pol in bundle.temperature_policies:
            reloaded = TemperaturePolicy.model_validate_json(pol.model_dump_json())
            assert reloaded == pol

    def test_sensor_readings_round_trip(self, bundle: ScenarioBundle):
        for r in bundle.sensor_readings:
            reloaded = SensorReading.model_validate_json(r.model_dump_json())
            assert reloaded == r


# ---------------------------------------------------------------------------
# Route graph structural invariants
# ---------------------------------------------------------------------------


class TestRouteGraph:
    def test_route_graph_not_empty(self, bundle: ScenarioBundle):
        assert len(bundle.route_graph) > 0

    def test_all_graph_values_are_lists(self, bundle: ScenarioBundle):
        for node, neighbours in bundle.route_graph.items():
            assert isinstance(neighbours, list), (
                f"Neighbours of {node!r} must be a list, got {type(neighbours)}"
            )

    def test_all_neighbour_nodes_defined_in_graph(self, bundle: ScenarioBundle):
        for node, neighbours in bundle.route_graph.items():
            for nb in neighbours:
                assert nb in bundle.route_graph, (
                    f"Neighbour {nb!r} of {node!r} is not defined in route_graph"
                )
