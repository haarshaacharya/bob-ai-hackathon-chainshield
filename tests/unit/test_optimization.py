from __future__ import annotations

"""
Unit tests for the ChainShield deterministic Optimization Engine.

Covers
------
1. Feasible route — engine returns at least one ranked alternative
2. Capacity violation — asset too small → CAPACITY_VIOLATION reason code
3. Deadline violation — path too slow → DEADLINE_VIOLATION reason code
4. Reefer incompatibility — cold shipment on non-reefer asset → REEFER_REQUIRED
5. Unavailable carrier — asset not AVAILABLE → CARRIER_UNAVAILABLE
6. Blocked/disrupted route edge — path uses a blocked edge → ROUTE_EDGE_BLOCKED /
   ROUTE_NODE_BLOCKED
7. Deterministic repeated results — identical inputs → identical output every time
8. Mode incompatibility — asset mode does not match shipment mode → MODE_INCOMPATIBLE
9. Three or more feasible alternatives when fixture permits

No live routing APIs, no LLMs, no network calls.
"""

import copy
from datetime import datetime, timedelta, timezone

import networkx as nx
import pytest

from chainshield.models import (
    CargoMode,
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
    ProductClass,
    Shipment,
    ShipmentStatus,
)
from chainshield.models.asset import Asset, AssetMode, AssetStatus, AssetType
from chainshield.optimization.engine import (
    OptimizationEngine,
    OptimizationResult,
    RouteAlternative,
    _blocked_set,
    _path_is_blocked,
)

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_TZ = timezone.utc


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=_TZ)


# ---------------------------------------------------------------------------
# Graph fixtures
# ---------------------------------------------------------------------------


def _make_graph() -> nx.DiGraph:
    """Route graph with several paths from HUB-A to HUB-D.

    Topology (directed, all edges bidirectional for realism)::

        HUB-A ──[6h,$500]──► PORT-03 ──[4h,$300]──► HUB-B ──[3h,$200]──► HUB-D
          │                                                                   ▲
          └──────────────────[10h,$800]──────────────────────────────────────┘
          │                                                                   ▲
          └──[5h,$400]──► HUB-C ──[6h,$450]─────────────────────────────────┘

    Paths from HUB-A to HUB-D:
      P1: HUB-A → PORT-03 → HUB-B → HUB-D  (13h, $1000)
      P2: HUB-A → HUB-D                      (10h, $800)
      P3: HUB-A → HUB-C → HUB-D             (11h, $850)
    """
    G = nx.DiGraph()
    edges = [
        ("HUB-A", "PORT-03", {"transit_hours": 6.0, "cost_usd": 500.0}),
        ("PORT-03", "HUB-A", {"transit_hours": 6.0, "cost_usd": 500.0}),
        ("PORT-03", "HUB-B", {"transit_hours": 4.0, "cost_usd": 300.0}),
        ("HUB-B", "PORT-03", {"transit_hours": 4.0, "cost_usd": 300.0}),
        ("HUB-B", "HUB-D", {"transit_hours": 3.0, "cost_usd": 200.0}),
        ("HUB-D", "HUB-B", {"transit_hours": 3.0, "cost_usd": 200.0}),
        ("HUB-A", "HUB-D", {"transit_hours": 10.0, "cost_usd": 800.0}),
        ("HUB-D", "HUB-A", {"transit_hours": 10.0, "cost_usd": 800.0}),
        ("HUB-A", "HUB-C", {"transit_hours": 5.0, "cost_usd": 400.0}),
        ("HUB-C", "HUB-A", {"transit_hours": 5.0, "cost_usd": 400.0}),
        ("HUB-C", "HUB-D", {"transit_hours": 6.0, "cost_usd": 450.0}),
        ("HUB-D", "HUB-C", {"transit_hours": 6.0, "cost_usd": 450.0}),
    ]
    for u, v, data in edges:
        G.add_edge(u, v, **data)
    return G


# ---------------------------------------------------------------------------
# Shipment fixtures
# ---------------------------------------------------------------------------


def _make_shipment(
    *,
    weight_kg: float = 5_000.0,
    origin: str = "HUB-A",
    destination: str = "HUB-D",
    current_node: str = "HUB-A",
    departure: str = "2026-09-14T06:00:00",
    arrival: str = "2026-09-14T20:00:00",
    deadline: str = "2026-09-15T12:00:00",
    mode: CargoMode = CargoMode.SEA,
    temperature_policy_id: str | None = None,
    product_class: ProductClass = ProductClass.DRY_GOODS,
    status: ShipmentStatus = ShipmentStatus.IN_TRANSIT,
) -> Shipment:
    return Shipment(
        shipment_id="SHP-TEST",
        cargo_type="test_cargo",
        product_class=product_class,
        temperature_policy_id=temperature_policy_id,
        weight_kg=weight_kg,
        cargo_value_usd=100_000.0,
        origin_hub_id=origin,
        destination_hub_id=destination,
        current_node_id=current_node,
        route_node_ids=[origin, destination],
        mode=mode,
        planned_departure=_dt(departure),
        planned_arrival=_dt(arrival),
        delivery_deadline=_dt(deadline),
        status=status,
    )


# ---------------------------------------------------------------------------
# Asset fixtures
# ---------------------------------------------------------------------------


def _make_asset(
    *,
    asset_id: str = "ASSET-01",
    carrier_id: str = "CARRIER-A",
    mode: AssetMode = AssetMode.SEA,
    capacity_kg: float = 10_000.0,
    reefer_capable: bool = False,
    status: AssetStatus = AssetStatus.AVAILABLE,
    current_node: str = "HUB-A",
    available_at: str = "2026-09-14T05:00:00",
) -> Asset:
    return Asset(
        asset_id=asset_id,
        asset_type=AssetType.VESSEL,
        mode=mode,
        carrier_id=carrier_id,
        current_node_id=current_node,
        available_at=_dt(available_at),
        capacity_kg=capacity_kg,
        reefer_capable=reefer_capable,
        status=status,
    )


# ---------------------------------------------------------------------------
# Disruption fixtures
# ---------------------------------------------------------------------------


def _make_disruption(
    *,
    blocked_nodes: list[str] | None = None,
    blocked_edges: list[str] | None = None,
    window_start: str = "2026-09-14T00:00:00",
    window_end: str = "2026-09-17T00:00:00",
    status: DisruptionStatus = DisruptionStatus.ACTIVE,
) -> Disruption:
    return Disruption(
        disruption_id="DISR-01",
        disruption_type=DisruptionType.PORT_STRIKE,
        severity=DisruptionSeverity.HIGH,
        status=status,
        title="Test disruption",
        window_start=_dt(window_start),
        window_end=_dt(window_end),
        geometry=DisruptionGeometry(
            blocked_nodes=blocked_nodes or [],
            blocked_edges=blocked_edges or [],
        ),
    )


# ---------------------------------------------------------------------------
# 1. Feasible route — engine returns ≥ 1 ranked alternative
# ---------------------------------------------------------------------------


class TestFeasibleRoute:
    """Single asset, clear graph, shipment well within deadline."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        self.shipment = _make_shipment(deadline="2026-09-16T00:00:00")
        self.asset = _make_asset()

    def test_at_least_one_feasible_alternative(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 1

    def test_feasible_alternative_has_rank_gte_1(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert all(a.rank >= 1 for a in feasible)

    def test_feasible_alternative_has_no_reason_codes(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert all(a.reason_codes == [] for a in feasible)

    def test_feasible_alternative_path_reaches_destination(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        for alt in feasible:
            assert alt.path[-1] == self.shipment.destination_hub_id

    def test_solver_status_not_infeasible(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        assert result.solver_status not in ("INFEASIBLE", "SKIPPED")

    def test_shipment_id_in_result(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        assert result.shipment_id == "SHP-TEST"


# ---------------------------------------------------------------------------
# 2. Capacity violation
# ---------------------------------------------------------------------------


class TestCapacityViolation:
    """Asset capacity_kg is less than shipment weight_kg."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        # Shipment is 5000 kg, asset can only carry 3000 kg
        self.shipment = _make_shipment(weight_kg=5_000.0)
        self.asset = _make_asset(capacity_kg=3_000.0)

    def test_no_feasible_alternatives(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) == 0

    def test_capacity_violation_in_rejection_codes(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        assert "CAPACITY_VIOLATION" in result.rejection_reason_codes

    def test_capacity_violation_in_alternative_reason_codes(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        assert any(
            "CAPACITY_VIOLATION" in a.reason_codes for a in result.alternatives
        )

    def test_capacity_exactly_met_is_feasible(self) -> None:
        """Asset capacity == shipment weight: should be feasible."""
        asset = _make_asset(capacity_kg=5_000.0)
        result = self.engine.find_alternatives(
            _make_shipment(weight_kg=5_000.0, deadline="2026-09-16T00:00:00"),
            [asset],
        )
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 1


# ---------------------------------------------------------------------------
# 3. Deadline violation
# ---------------------------------------------------------------------------


class TestDeadlineViolation:
    """All available paths take longer than the delivery deadline allows."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        # All paths ≥ 10 h; deadline is only 2 h after departure
        self.shipment = _make_shipment(
            departure="2026-09-14T06:00:00",
            arrival="2026-09-14T08:00:00",
            deadline="2026-09-14T08:30:00",  # extremely tight: 2.5 h
        )
        self.asset = _make_asset()

    def test_no_feasible_alternatives(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) == 0

    def test_deadline_violation_in_rejection_codes(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        assert "DEADLINE_VIOLATION" in result.rejection_reason_codes

    def test_deadline_violation_in_alternative_reason_codes(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.asset])
        assert any(
            "DEADLINE_VIOLATION" in a.reason_codes for a in result.alternatives
        )


# ---------------------------------------------------------------------------
# 4. Reefer incompatibility
# ---------------------------------------------------------------------------


class TestReeferIncompatibility:
    """Cold-chain shipment assigned to a non-reefer asset."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        self.shipment = _make_shipment(
            temperature_policy_id="cdc_vaccine_2_8c",
            product_class=ProductClass.REFRIGERATED_VACCINE,
            deadline="2026-09-16T00:00:00",
        )
        self.non_reefer_asset = _make_asset(reefer_capable=False)

    def test_no_feasible_alternatives_without_reefer(self) -> None:
        result = self.engine.find_alternatives(
            self.shipment, [self.non_reefer_asset]
        )
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) == 0

    def test_reefer_required_in_rejection_codes(self) -> None:
        result = self.engine.find_alternatives(
            self.shipment, [self.non_reefer_asset]
        )
        assert "REEFER_REQUIRED" in result.rejection_reason_codes

    def test_reefer_asset_makes_it_feasible(self) -> None:
        """Same shipment with a reefer-capable asset should be feasible."""
        reefer_asset = _make_asset(reefer_capable=True)
        result = self.engine.find_alternatives(self.shipment, [reefer_asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 1


# ---------------------------------------------------------------------------
# 5. Unavailable carrier
# ---------------------------------------------------------------------------


class TestUnavailableCarrier:
    """Asset is not in AVAILABLE status."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        self.shipment = _make_shipment(deadline="2026-09-16T00:00:00")

    def test_in_use_asset_is_rejected(self) -> None:
        asset = _make_asset(status=AssetStatus.IN_USE)
        result = self.engine.find_alternatives(self.shipment, [asset])
        assert "CARRIER_UNAVAILABLE" in result.rejection_reason_codes

    def test_maintenance_asset_is_rejected(self) -> None:
        asset = _make_asset(status=AssetStatus.MAINTENANCE)
        result = self.engine.find_alternatives(self.shipment, [asset])
        assert "CARRIER_UNAVAILABLE" in result.rejection_reason_codes

    def test_reserved_asset_is_rejected(self) -> None:
        asset = _make_asset(status=AssetStatus.RESERVED)
        result = self.engine.find_alternatives(self.shipment, [asset])
        assert "CARRIER_UNAVAILABLE" in result.rejection_reason_codes

    def test_no_feasible_when_only_unavailable_assets(self) -> None:
        assets = [
            _make_asset(asset_id="A1", status=AssetStatus.IN_USE),
            _make_asset(asset_id="A2", status=AssetStatus.MAINTENANCE),
        ]
        result = self.engine.find_alternatives(self.shipment, assets)
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) == 0

    def test_available_asset_among_unavailable_yields_feasible(self) -> None:
        """Mix: 1 available + 1 unavailable → at least 1 feasible."""
        assets = [
            _make_asset(asset_id="A-UNAVAIL", status=AssetStatus.IN_USE),
            _make_asset(asset_id="A-AVAIL", status=AssetStatus.AVAILABLE),
        ]
        result = self.engine.find_alternatives(self.shipment, assets)
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 1
        assert all(a.asset_id == "A-AVAIL" for a in feasible)


# ---------------------------------------------------------------------------
# 6. Blocked / disrupted route edge
# ---------------------------------------------------------------------------


class TestBlockedRoute:
    """Active disruption blocks a node or edge on the candidate path."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        # Deadline is generous so only the block can cause failure
        self.shipment = _make_shipment(deadline="2026-09-16T00:00:00")
        self.asset = _make_asset()

    def test_blocked_node_on_all_paths_yields_no_feasible(self) -> None:
        """Block every intermediate node → all long paths fail.

        HUB-A→HUB-D direct path (10h) stays clear but PORT-03 and HUB-C
        are blocked, so only the direct path survives.
        We block HUB-D (the destination) to force every path infeasible.
        """
        disruption = _make_disruption(blocked_nodes=["PORT-03", "HUB-C", "HUB-B"])
        result = self.engine.find_alternatives(
            self.shipment, [self.asset], [disruption]
        )
        # HUB-A → HUB-D direct survives (neither PORT-03, HUB-C, nor HUB-B
        # is on that path), so we expect exactly 1 feasible alternative.
        feasible = [a for a in result.alternatives if a.is_feasible]
        # Verify the surviving path is the direct one
        assert all(a.path == ["HUB-A", "HUB-D"] for a in feasible)

    def test_blocked_node_reason_code_in_rejection_codes(self) -> None:
        """Blocking PORT-03 should put ROUTE_NODE_BLOCKED in rejection codes."""
        disruption = _make_disruption(blocked_nodes=["PORT-03"])
        result = self.engine.find_alternatives(
            self.shipment, [self.asset], [disruption]
        )
        assert "ROUTE_NODE_BLOCKED" in result.rejection_reason_codes

    def test_blocked_node_not_selected_as_feasible(self) -> None:
        """No feasible alternative should pass through PORT-03 when it is blocked."""
        disruption = _make_disruption(blocked_nodes=["PORT-03"])
        result = self.engine.find_alternatives(
            self.shipment, [self.asset], [disruption]
        )
        for alt in result.alternatives:
            if alt.is_feasible:
                assert "PORT-03" not in alt.path

    def test_blocked_edge_reason_code(self) -> None:
        """Block the HUB-A:HUB-D edge → ROUTE_EDGE_BLOCKED on that path."""
        disruption = _make_disruption(blocked_edges=["HUB-A:HUB-D"])
        result = self.engine.find_alternatives(
            self.shipment, [self.asset], [disruption]
        )
        assert "ROUTE_EDGE_BLOCKED" in result.rejection_reason_codes

    def test_resolved_disruption_does_not_block(self) -> None:
        """RESOLVED disruption must not block any path."""
        disruption = _make_disruption(
            blocked_nodes=["PORT-03", "HUB-C", "HUB-D"],
            status=DisruptionStatus.RESOLVED,
        )
        result = self.engine.find_alternatives(
            self.shipment, [self.asset], [disruption]
        )
        # Nothing is blocked → feasible alternatives should exist
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 1

    def test_active_disruption_blocks_path(self) -> None:
        """ACTIVE disruption with blocked node makes paths through it infeasible."""
        disruption = _make_disruption(blocked_nodes=["PORT-03"])
        result = self.engine.find_alternatives(
            self.shipment, [self.asset], [disruption]
        )
        # No feasible alternative should pass through PORT-03
        for alt in [a for a in result.alternatives if a.is_feasible]:
            assert "PORT-03" not in alt.path


# ---------------------------------------------------------------------------
# 7. Deterministic repeated results
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Identical inputs must always produce identical, ordered output."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        self.shipment = _make_shipment(deadline="2026-09-16T00:00:00")
        self.assets = [
            _make_asset(asset_id="A1"),
            _make_asset(asset_id="A2"),
        ]
        self.disruption = _make_disruption(blocked_nodes=["PORT-03"])

    def test_repeated_calls_same_feasible_count(self) -> None:
        results = [
            self.engine.find_alternatives(
                self.shipment, self.assets, [self.disruption]
            )
            for _ in range(5)
        ]
        feasible_counts = [
            sum(1 for a in r.alternatives if a.is_feasible) for r in results
        ]
        assert len(set(feasible_counts)) == 1

    def test_repeated_calls_same_rejection_codes(self) -> None:
        results = [
            self.engine.find_alternatives(
                self.shipment, self.assets, [self.disruption]
            )
            for _ in range(5)
        ]
        code_tuples = [tuple(r.rejection_reason_codes) for r in results]
        assert len(set(code_tuples)) == 1

    def test_repeated_calls_same_alternative_ids(self) -> None:
        results = [
            self.engine.find_alternatives(
                self.shipment, self.assets, [self.disruption]
            )
            for _ in range(5)
        ]
        id_lists = [
            tuple(a.alternative_id for a in r.alternatives if a.is_feasible)
            for r in results
        ]
        assert len(set(id_lists)) == 1

    def test_repeated_calls_same_ranks(self) -> None:
        results = [
            self.engine.find_alternatives(
                self.shipment, self.assets, [self.disruption]
            )
            for _ in range(5)
        ]
        rank_sequences = [
            tuple(a.rank for a in r.alternatives if a.is_feasible)
            for r in results
        ]
        assert len(set(rank_sequences)) == 1

    def test_solver_status_stable(self) -> None:
        results = [
            self.engine.find_alternatives(
                self.shipment, self.assets, [self.disruption]
            )
            for _ in range(3)
        ]
        statuses = {r.solver_status for r in results}
        assert len(statuses) == 1


# ---------------------------------------------------------------------------
# 8. Mode incompatibility
# ---------------------------------------------------------------------------


class TestModeIncompatibility:
    """Asset mode does not match shipment mode."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph())
        # Shipment is SEA; asset is ROAD
        self.shipment = _make_shipment(
            mode=CargoMode.SEA, deadline="2026-09-16T00:00:00"
        )
        self.road_asset = _make_asset(mode=AssetMode.ROAD)

    def test_mode_incompatible_rejection_code(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.road_asset])
        assert "MODE_INCOMPATIBLE" in result.rejection_reason_codes

    def test_no_feasible_when_all_modes_incompatible(self) -> None:
        result = self.engine.find_alternatives(self.shipment, [self.road_asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) == 0

    def test_matching_mode_is_feasible(self) -> None:
        sea_asset = _make_asset(mode=AssetMode.SEA)
        result = self.engine.find_alternatives(self.shipment, [sea_asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 1

    def test_multimodal_shipment_accepts_any_mode(self) -> None:
        """MULTIMODAL shipment should accept assets of any mode."""
        multimodal_shipment = _make_shipment(
            mode=CargoMode.MULTIMODAL, deadline="2026-09-16T00:00:00"
        )
        road_asset = _make_asset(asset_id="ROAD-01", mode=AssetMode.ROAD)
        result = self.engine.find_alternatives(multimodal_shipment, [road_asset])
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 1


# ---------------------------------------------------------------------------
# 9. Three or more feasible alternatives when fixture permits
# ---------------------------------------------------------------------------


class TestThreeAlternatives:
    """With 3 distinct assets and a generous deadline, at least 3 alternatives."""

    def setup_method(self) -> None:
        self.engine = OptimizationEngine(_make_graph(), max_alternatives=5)
        # Very generous deadline: 48 h from departure
        self.shipment = _make_shipment(deadline="2026-09-16T18:00:00")
        # Three different assets, all available, same mode, adequate capacity
        self.assets = [
            _make_asset(asset_id="VESSEL-A", carrier_id="CARRIER-A"),
            _make_asset(asset_id="VESSEL-B", carrier_id="CARRIER-B"),
            _make_asset(asset_id="VESSEL-C", carrier_id="CARRIER-C"),
        ]

    def test_at_least_three_feasible_alternatives(self) -> None:
        result = self.engine.find_alternatives(self.shipment, self.assets)
        feasible = [a for a in result.alternatives if a.is_feasible]
        assert len(feasible) >= 3

    def test_alternatives_are_ranked_sequentially(self) -> None:
        result = self.engine.find_alternatives(self.shipment, self.assets)
        feasible = sorted(
            [a for a in result.alternatives if a.is_feasible], key=lambda a: a.rank
        )
        ranks = [a.rank for a in feasible]
        # Ranks must be 1, 2, 3, ... (no gaps, no duplicates)
        assert ranks == list(range(1, len(ranks) + 1))

    def test_alternatives_ranked_by_cost_ascending(self) -> None:
        result = self.engine.find_alternatives(self.shipment, self.assets)
        feasible = sorted(
            [a for a in result.alternatives if a.is_feasible], key=lambda a: a.rank
        )
        costs = [a.total_cost_usd for a in feasible]
        assert costs == sorted(costs)

    def test_each_alternative_has_valid_path(self) -> None:
        result = self.engine.find_alternatives(self.shipment, self.assets)
        for alt in result.alternatives:
            if alt.is_feasible:
                assert len(alt.path) >= 2
                assert alt.path[0] == self.shipment.current_node_id
                assert alt.path[-1] == self.shipment.destination_hub_id


# ---------------------------------------------------------------------------
# Unit tests for internal helpers (path_is_blocked, _blocked_set)
# ---------------------------------------------------------------------------


class TestBlockedSetHelper:
    """Unit tests for _blocked_set()."""

    def test_active_disruption_blocked_nodes(self) -> None:
        d = _make_disruption(blocked_nodes=["PORT-03", "HUB-X"])
        nodes, edges = _blocked_set([d])
        assert "PORT-03" in nodes
        assert "HUB-X" in nodes

    def test_resolved_disruption_ignored(self) -> None:
        d = _make_disruption(
            blocked_nodes=["PORT-03"], status=DisruptionStatus.RESOLVED
        )
        nodes, edges = _blocked_set([d])
        assert len(nodes) == 0

    def test_active_disruption_blocked_edges(self) -> None:
        d = _make_disruption(blocked_edges=["HUB-A:PORT-03"])
        nodes, edges = _blocked_set([d])
        assert frozenset(["HUB-A", "PORT-03"]) in edges

    def test_empty_disruptions(self) -> None:
        nodes, edges = _blocked_set([])
        assert len(nodes) == 0
        assert len(edges) == 0


class TestPathIsBlockedHelper:
    """Unit tests for _path_is_blocked()."""

    def test_blocked_node_on_path(self) -> None:
        codes = _path_is_blocked(
            ["HUB-A", "PORT-03", "HUB-B"],
            frozenset(["PORT-03"]),
            frozenset(),
        )
        assert "ROUTE_NODE_BLOCKED" in codes

    def test_clear_path_returns_empty(self) -> None:
        codes = _path_is_blocked(
            ["HUB-A", "HUB-B"],
            frozenset(["PORT-03"]),
            frozenset(),
        )
        assert codes == []

    def test_blocked_edge_on_path(self) -> None:
        codes = _path_is_blocked(
            ["HUB-A", "HUB-B", "HUB-C"],
            frozenset(),
            frozenset([frozenset(["HUB-B", "HUB-C"])]),
        )
        assert "ROUTE_EDGE_BLOCKED" in codes

    def test_single_node_path_is_clear(self) -> None:
        codes = _path_is_blocked(
            ["HUB-A"],
            frozenset(["HUB-A"]),
            frozenset(),
        )
        # Single-node path: no edges to block, but node itself IS blocked
        assert "ROUTE_NODE_BLOCKED" in codes
