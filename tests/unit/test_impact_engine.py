from __future__ import annotations

"""
Unit tests for the ChainShield deterministic Impact Engine.

Covers
------
1. Route intersects disruption AND time windows overlap → AFFECTED
2. Route intersects disruption BUT time windows do NOT overlap → UNAFFECTED
3. Route does NOT intersect disruption → UNAFFECTED
4. Multiple shipments with mixed impact (evaluate_many)
5. Deterministic repeated execution (same input → identical output)

Each test constructs its own minimal NetworkX graph, Shipment, and
Disruption objects from the existing Pydantic models — no external
dependencies, no LLM, no live routing.

Reason codes verified
---------------------
PORT_NODE_BLOCKED, ROUTE_EDGE_BLOCKED, ETA_SLA_BREACH,
TEMPERATURE_EXPOSURE_INCREASED
"""

from datetime import datetime, timezone

import networkx as nx
import pytest

from chainshield.impact.engine import ImpactEngine, ImpactResult, _windows_overlap
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

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_TZ = timezone.utc


def _dt(iso: str) -> datetime:
    """Parse a naive ISO string and attach UTC timezone."""
    return datetime.fromisoformat(iso).replace(tzinfo=_TZ)


def _make_graph() -> nx.Graph:
    """Canonical demo route graph used across most tests.

    Topology::

        HUB-A ── PORT-03 ── HUB-B ── HUB-D
          └──────────────────────────────┘  (bypass edge — never hits PORT-03)
    """
    G = nx.Graph()
    G.add_nodes_from(["HUB-A", "PORT-03", "HUB-B", "HUB-D"])
    G.add_edges_from(
        [
            ("HUB-A", "PORT-03"),
            ("PORT-03", "HUB-B"),
            ("HUB-B", "HUB-D"),
            ("HUB-A", "HUB-D"),  # bypass — never touches PORT-03
        ]
    )
    return G


def _make_disruption(
    *,
    blocked_nodes: list[str] | None = None,
    blocked_edges: list[str] | None = None,
    window_start: str = "2026-09-14T00:00:00",
    window_end: str = "2026-09-17T00:00:00",
    status: DisruptionStatus = DisruptionStatus.ACTIVE,
) -> Disruption:
    return Disruption(
        disruption_id="PORT_STRIKE_01",
        disruption_type=DisruptionType.PORT_STRIKE,
        severity=DisruptionSeverity.HIGH,
        status=status,
        title="Port of Aden strike action",
        window_start=_dt(window_start),
        window_end=_dt(window_end),
        geometry=DisruptionGeometry(
            blocked_nodes=blocked_nodes or [],
            blocked_edges=blocked_edges or [],
        ),
    )


_SENTINEL = object()


def _make_shipment(
    *,
    shipment_id: str = "SHP-0042",
    route_node_ids: list[str] | None = _SENTINEL,  # type: ignore[assignment]
    planned_departure: str = "2026-09-14T06:00:00",
    planned_arrival: str = "2026-09-16T14:00:00",
    delivery_deadline: str = "2026-09-16T18:00:00",
    cargo_value_usd: float = 520_000.0,
    temperature_policy_id: str | None = None,
    status: ShipmentStatus = ShipmentStatus.IN_TRANSIT,
    product_class: ProductClass = ProductClass.DRY_GOODS,
) -> Shipment:
    if route_node_ids is _SENTINEL:
        route_node_ids = ["HUB-A", "PORT-03", "HUB-B", "HUB-D"]
    return Shipment(
        shipment_id=shipment_id,
        cargo_type="reefer",
        product_class=product_class,
        temperature_policy_id=temperature_policy_id,
        cargo_value_usd=cargo_value_usd,
        weight_kg=8_200.0,
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-D",
        route_node_ids=route_node_ids,
        mode=CargoMode.SEA,
        planned_departure=_dt(planned_departure),
        planned_arrival=_dt(planned_arrival),
        delivery_deadline=_dt(delivery_deadline),
        status=status,
    )


# ---------------------------------------------------------------------------
# 1. Route intersects AND time windows overlap → AFFECTED
# ---------------------------------------------------------------------------


class TestAffected:
    """Scenario: SHP-0042 routes through PORT-03 which is blocked."""

    def setup_method(self) -> None:
        self.engine = ImpactEngine(_make_graph())
        self.shipment = _make_shipment()
        self.disruption = _make_disruption(blocked_nodes=["PORT-03"])

    def test_is_affected(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.is_affected is True

    def test_reason_code_port_node_blocked(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert "PORT_NODE_BLOCKED" in result.reason_codes

    def test_node_hits_contains_blocked_node(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert "PORT-03" in result.node_hits

    def test_cargo_value_at_risk(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.cargo_value_at_risk_usd == pytest.approx(520_000.0)

    def test_shipment_and_disruption_ids_recorded(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.shipment_id == "SHP-0042"
        assert result.disruption_id == "PORT_STRIKE_01"

    def test_eta_sla_breach_when_disruption_exceeds_deadline(self) -> None:
        """Disruption window_end (2026-09-18) > delivery_deadline (2026-09-16)."""
        disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            window_end="2026-09-18T00:00:00",
        )
        result = self.engine.evaluate(self.shipment, disruption)
        assert result.is_affected is True
        assert "ETA_SLA_BREACH" in result.reason_codes

    def test_no_eta_sla_breach_when_disruption_within_deadline(self) -> None:
        """Disruption window_end (2026-09-15) < delivery_deadline (2026-09-16)."""
        disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            window_end="2026-09-15T00:00:00",
        )
        result = self.engine.evaluate(self.shipment, disruption)
        assert result.is_affected is True
        assert "ETA_SLA_BREACH" not in result.reason_codes

    def test_temperature_exposure_increased_for_cold_cargo(self) -> None:
        """Shipment with temperature_policy_id should get TEMPERATURE_EXPOSURE_INCREASED."""
        shipment = _make_shipment(
            temperature_policy_id="cdc_refrigerated_vaccine_demo",
            product_class=ProductClass.REFRIGERATED_VACCINE,
        )
        result = self.engine.evaluate(shipment, self.disruption)
        assert result.is_affected is True
        assert "TEMPERATURE_EXPOSURE_INCREASED" in result.reason_codes

    def test_no_temperature_code_for_dry_goods(self) -> None:
        """Shipment without temperature_policy_id should NOT get TEMPERATURE_EXPOSURE_INCREASED."""
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert "TEMPERATURE_EXPOSURE_INCREASED" not in result.reason_codes


# ---------------------------------------------------------------------------
# 2. Route intersects BUT time windows do NOT overlap → UNAFFECTED
# ---------------------------------------------------------------------------


class TestTimeWindowNoOverlap:
    """Shipment transits 2026-09-10–11, disruption is 2026-09-14–17."""

    def setup_method(self) -> None:
        self.engine = ImpactEngine(_make_graph())
        # Shipment is entirely before the disruption window
        self.shipment = _make_shipment(
            planned_departure="2026-09-10T06:00:00",
            planned_arrival="2026-09-11T14:00:00",
            delivery_deadline="2026-09-11T18:00:00",
        )
        # Disruption starts after the shipment has already arrived
        self.disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            window_start="2026-09-14T00:00:00",
            window_end="2026-09-17T00:00:00",
        )

    def test_not_affected(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.is_affected is False

    def test_no_reason_codes(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.reason_codes == []

    def test_zero_value_at_risk(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.cargo_value_at_risk_usd == 0.0

    def test_adjacent_windows_do_not_overlap(self) -> None:
        """Boundary check: shipment ends exactly when disruption begins — no overlap."""
        shipment = _make_shipment(
            planned_departure="2026-09-12T00:00:00",
            planned_arrival="2026-09-13T23:59:59",
            delivery_deadline="2026-09-14T00:00:00",
        )
        disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            window_start="2026-09-14T00:00:00",
            window_end="2026-09-17T00:00:00",
        )
        # planned_arrival (2026-09-13T23:59:59) < window_start (2026-09-14T00:00:00)
        # → no overlap
        result = self.engine.evaluate(shipment, disruption)
        assert result.is_affected is False

    def test_disruption_ends_before_shipment_departs(self) -> None:
        """Disruption was already resolved before the shipment even departs."""
        disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            window_start="2026-09-01T00:00:00",
            window_end="2026-09-05T00:00:00",
        )
        shipment = _make_shipment(
            planned_departure="2026-09-14T06:00:00",
            planned_arrival="2026-09-16T14:00:00",
            delivery_deadline="2026-09-16T18:00:00",
        )
        result = self.engine.evaluate(shipment, disruption)
        assert result.is_affected is False


# ---------------------------------------------------------------------------
# 3. Route does NOT intersect disruption → UNAFFECTED
# ---------------------------------------------------------------------------


class TestRouteNoIntersection:
    """Shipment uses the bypass edge (HUB-A → HUB-D), never hits PORT-03."""

    def setup_method(self) -> None:
        self.engine = ImpactEngine(_make_graph())
        # Route via bypass — node PORT-03 is not on this route
        self.shipment = _make_shipment(
            shipment_id="SHP-0099",
            route_node_ids=["HUB-A", "HUB-D"],
        )
        self.disruption = _make_disruption(blocked_nodes=["PORT-03"])

    def test_not_affected(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.is_affected is False

    def test_no_reason_codes(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.reason_codes == []

    def test_zero_value_at_risk(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.cargo_value_at_risk_usd == 0.0

    def test_disjoint_blocked_nodes_not_on_route(self) -> None:
        """A disruption at PORT-99 (not in the graph) should not affect any route."""
        disruption = _make_disruption(blocked_nodes=["PORT-99"])
        shipment = _make_shipment(route_node_ids=["HUB-A", "PORT-03", "HUB-B"])
        result = self.engine.evaluate(shipment, disruption)
        assert result.is_affected is False


class TestRouteEdgeBlocked:
    """ROUTE_EDGE_BLOCKED is triggered when a blocked edge spans two consecutive
    route nodes, even if neither node alone is in blocked_nodes."""

    def setup_method(self) -> None:
        G = nx.Graph()
        G.add_edges_from([("HUB-A", "HUB-B"), ("HUB-B", "HUB-C")])
        self.engine = ImpactEngine(G)
        self.disruption = _make_disruption(
            blocked_edges=["HUB-B:HUB-C"],  # edge, not a node
        )
        self.shipment = _make_shipment(
            route_node_ids=["HUB-A", "HUB-B", "HUB-C"],
        )

    def test_route_edge_blocked_code(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert result.is_affected is True
        assert "ROUTE_EDGE_BLOCKED" in result.reason_codes

    def test_edge_hit_in_result(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert len(result.edge_hits) > 0

    def test_edge_not_hit_when_route_does_not_traverse_it(self) -> None:
        """Route HUB-A → HUB-B does not traverse the HUB-B:HUB-C edge."""
        shipment = _make_shipment(route_node_ids=["HUB-A", "HUB-B"])
        result = self.engine.evaluate(shipment, self.disruption)
        assert result.is_affected is False


# ---------------------------------------------------------------------------
# 4. Multiple shipments with mixed impact (evaluate_many)
# ---------------------------------------------------------------------------


class TestEvaluateMany:
    """evaluate_many correctly classifies a mixed batch of shipments."""

    def setup_method(self) -> None:
        self.engine = ImpactEngine(_make_graph())
        self.disruption = _make_disruption(blocked_nodes=["PORT-03"])
        self.shipments = [
            # Affected: route through PORT-03, overlapping time window
            _make_shipment(
                shipment_id="SHP-AFFECTED",
                route_node_ids=["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
            ),
            # Unaffected: uses bypass edge
            _make_shipment(
                shipment_id="SHP-BYPASS",
                route_node_ids=["HUB-A", "HUB-D"],
            ),
            # Unaffected: time window before disruption
            _make_shipment(
                shipment_id="SHP-EARLY",
                route_node_ids=["HUB-A", "PORT-03", "HUB-B"],
                planned_departure="2026-09-10T00:00:00",
                planned_arrival="2026-09-11T00:00:00",
                delivery_deadline="2026-09-11T12:00:00",
            ),
            # Affected: cold cargo through blocked node
            _make_shipment(
                shipment_id="SHP-COLD",
                route_node_ids=["HUB-A", "PORT-03", "HUB-D"],
                temperature_policy_id="cdc_refrigerated_vaccine_demo",
                product_class=ProductClass.REFRIGERATED_VACCINE,
                cargo_value_usd=300_000.0,
            ),
        ]

    def test_result_count_matches_shipment_count(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        assert len(results) == len(self.shipments)

    def test_only_expected_shipments_affected(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        affected = {r.shipment_id for r in results if r.is_affected}
        assert affected == {"SHP-AFFECTED", "SHP-COLD"}

    def test_unaffected_shipments_not_flagged(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        unaffected = {r.shipment_id for r in results if not r.is_affected}
        assert "SHP-BYPASS" in unaffected
        assert "SHP-EARLY" in unaffected

    def test_cold_shipment_has_temperature_code(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        cold_result = next(r for r in results if r.shipment_id == "SHP-COLD")
        assert "TEMPERATURE_EXPOSURE_INCREASED" in cold_result.reason_codes

    def test_total_value_at_risk_is_sum_of_affected(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        total = sum(r.cargo_value_at_risk_usd for r in results)
        assert total == pytest.approx(520_000.0 + 300_000.0)

    def test_result_order_matches_input_order(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        input_ids = [s.shipment_id for s in self.shipments]
        result_ids = [r.shipment_id for r in results]
        assert result_ids == input_ids

    def test_apply_results_updates_disruption_fields(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        _, updated_disruption = self.engine.apply_results(
            self.shipments, self.disruption, results
        )
        assert updated_disruption.affected_shipment_count == 2
        assert set(updated_disruption.affected_shipment_ids) == {
            "SHP-AFFECTED",
            "SHP-COLD",
        }
        assert updated_disruption.cargo_value_at_risk_usd == pytest.approx(820_000.0)

    def test_apply_results_updates_shipment_fields(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        updated_shipments, _ = self.engine.apply_results(
            self.shipments, self.disruption, results
        )
        affected_shp = next(
            s for s in updated_shipments if s.shipment_id == "SHP-AFFECTED"
        )
        assert affected_shp.is_disrupted is True
        assert "PORT_STRIKE_01" in affected_shp.disruption_ids
        assert "PORT_NODE_BLOCKED" in affected_shp.reason_codes

    def test_apply_results_leaves_unaffected_shipments_unchanged(self) -> None:
        results = self.engine.evaluate_many(self.shipments, self.disruption)
        updated_shipments, _ = self.engine.apply_results(
            self.shipments, self.disruption, results
        )
        bypass_shp = next(
            s for s in updated_shipments if s.shipment_id == "SHP-BYPASS"
        )
        assert bypass_shp.is_disrupted is False
        assert bypass_shp.disruption_ids == []


# ---------------------------------------------------------------------------
# 5. Deterministic repeated execution
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Identical inputs must produce identical, equal ImpactResult objects."""

    def setup_method(self) -> None:
        self.engine = ImpactEngine(_make_graph())
        self.shipment = _make_shipment(
            temperature_policy_id="cdc_refrigerated_vaccine_demo",
            product_class=ProductClass.REFRIGERATED_VACCINE,
        )
        self.disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            window_end="2026-09-18T00:00:00",  # exceeds deadline → ETA_SLA_BREACH
        )

    def test_repeated_calls_produce_equal_results(self) -> None:
        r1 = self.engine.evaluate(self.shipment, self.disruption)
        r2 = self.engine.evaluate(self.shipment, self.disruption)
        assert r1 == r2

    def test_repeated_calls_identical_reason_codes(self) -> None:
        results = [self.engine.evaluate(self.shipment, self.disruption) for _ in range(10)]
        code_sets = [tuple(r.reason_codes) for r in results]
        assert len(set(code_sets)) == 1, f"Reason codes differ across runs: {code_sets}"

    def test_all_expected_reason_codes_present(self) -> None:
        result = self.engine.evaluate(self.shipment, self.disruption)
        assert "PORT_NODE_BLOCKED" in result.reason_codes
        assert "ETA_SLA_BREACH" in result.reason_codes
        assert "TEMPERATURE_EXPOSURE_INCREASED" in result.reason_codes

    def test_reason_codes_stable_order(self) -> None:
        r1 = self.engine.evaluate(self.shipment, self.disruption)
        r2 = self.engine.evaluate(self.shipment, self.disruption)
        assert r1.reason_codes == r2.reason_codes

    def test_evaluate_many_deterministic(self) -> None:
        shipments = [
            _make_shipment(shipment_id=f"SHP-{i:03d}") for i in range(5)
        ]
        r1 = self.engine.evaluate_many(shipments, self.disruption)
        r2 = self.engine.evaluate_many(shipments, self.disruption)
        assert r1 == r2

    def test_value_at_risk_stable(self) -> None:
        results = [self.engine.evaluate(self.shipment, self.disruption) for _ in range(5)]
        values = [r.cargo_value_at_risk_usd for r in results]
        assert len(set(values)) == 1


# ---------------------------------------------------------------------------
# Edge / boundary cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Guard-rail tests for boundary conditions and status filters."""

    def test_resolved_disruption_returns_unaffected(self) -> None:
        engine = ImpactEngine(_make_graph())
        disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            status=DisruptionStatus.RESOLVED,
        )
        result = engine.evaluate(_make_shipment(), disruption)
        assert result.is_affected is False

    def test_cancelled_disruption_returns_unaffected(self) -> None:
        engine = ImpactEngine(_make_graph())
        disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            status=DisruptionStatus.CANCELLED,
        )
        result = engine.evaluate(_make_shipment(), disruption)
        assert result.is_affected is False

    def test_delivered_shipment_returns_unaffected(self) -> None:
        engine = ImpactEngine(_make_graph())
        shipment = _make_shipment(status=ShipmentStatus.DELIVERED)
        result = engine.evaluate(shipment, _make_disruption(blocked_nodes=["PORT-03"]))
        assert result.is_affected is False

    def test_cancelled_shipment_returns_unaffected(self) -> None:
        engine = ImpactEngine(_make_graph())
        shipment = _make_shipment(status=ShipmentStatus.CANCELLED)
        result = engine.evaluate(shipment, _make_disruption(blocked_nodes=["PORT-03"]))
        assert result.is_affected is False

    def test_empty_route_returns_unaffected(self) -> None:
        """Shipment with no route_node_ids should never be flagged."""
        engine = ImpactEngine(_make_graph())
        shipment = _make_shipment(route_node_ids=[])
        result = engine.evaluate(shipment, _make_disruption(blocked_nodes=["PORT-03"]))
        assert result.is_affected is False

    def test_no_blocked_nodes_returns_unaffected(self) -> None:
        """Disruption with no blocked_nodes/edges should affect nobody."""
        engine = ImpactEngine(_make_graph())
        result = engine.evaluate(
            _make_shipment(),
            _make_disruption(blocked_nodes=[], blocked_edges=[]),
        )
        assert result.is_affected is False

    def test_result_is_frozen_dataclass(self) -> None:
        """ImpactResult must be immutable (frozen=True)."""
        engine = ImpactEngine(_make_graph())
        result = engine.evaluate(
            _make_shipment(), _make_disruption(blocked_nodes=["PORT-03"])
        )
        with pytest.raises((AttributeError, TypeError)):
            result.is_affected = False  # type: ignore[misc]

    def test_monitoring_disruption_is_evaluated(self) -> None:
        """MONITORING status should still trigger impact evaluation."""
        engine = ImpactEngine(_make_graph())
        disruption = _make_disruption(
            blocked_nodes=["PORT-03"],
            status=DisruptionStatus.MONITORING,
        )
        result = engine.evaluate(_make_shipment(), disruption)
        assert result.is_affected is True


# ---------------------------------------------------------------------------
# Pure-utility helper tests
# ---------------------------------------------------------------------------


class TestWindowsOverlap:
    """Verify the _windows_overlap utility independently."""

    def test_fully_overlapping(self) -> None:
        assert _windows_overlap(
            _dt("2026-09-14T00:00:00"),
            _dt("2026-09-17T00:00:00"),
            _dt("2026-09-14T00:00:00"),
            _dt("2026-09-17T00:00:00"),
        )

    def test_partial_overlap(self) -> None:
        assert _windows_overlap(
            _dt("2026-09-13T00:00:00"),
            _dt("2026-09-15T00:00:00"),
            _dt("2026-09-14T00:00:00"),
            _dt("2026-09-17T00:00:00"),
        )

    def test_no_overlap_a_before_b(self) -> None:
        assert not _windows_overlap(
            _dt("2026-09-10T00:00:00"),
            _dt("2026-09-11T00:00:00"),
            _dt("2026-09-14T00:00:00"),
            _dt("2026-09-17T00:00:00"),
        )

    def test_no_overlap_b_before_a(self) -> None:
        assert not _windows_overlap(
            _dt("2026-09-18T00:00:00"),
            _dt("2026-09-20T00:00:00"),
            _dt("2026-09-14T00:00:00"),
            _dt("2026-09-17T00:00:00"),
        )

    def test_touching_boundary_counts_as_overlap(self) -> None:
        """a_end == b_start: boundary point is shared → overlap."""
        assert _windows_overlap(
            _dt("2026-09-13T00:00:00"),
            _dt("2026-09-14T00:00:00"),
            _dt("2026-09-14T00:00:00"),
            _dt("2026-09-17T00:00:00"),
        )
