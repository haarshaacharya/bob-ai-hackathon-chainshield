from __future__ import annotations

"""
ChainShield Deterministic Impact Engine
========================================

Detects which shipments are affected by an active disruption using:

  1. **Graph intersection** — shipment ``route_node_ids`` ∩ disruption
     ``blocked_nodes`` (node-level) and ``blocked_edges`` (edge-level).
  2. **Time-window overlap** — shipment transit window vs. disruption window
     (half-open interval comparison, both bounds required).
  3. **SLA breach detection** — if the disruption forces the shipment past its
     ``delivery_deadline``, ``ETA_SLA_BREACH`` is added to reason codes.
  4. **Cold-chain exposure** — if the shipment carries temperature-sensitive
     cargo (``temperature_policy_id`` is set) and a node or edge on the route
     is blocked, ``TEMPERATURE_EXPOSURE_INCREASED`` is added.

No LLM, no external API, no live routing.  All logic is deterministic given
the same inputs; repeated calls with identical arguments produce identical
output (``ImpactResult`` is a frozen dataclass).

Supported reason codes
----------------------
PORT_NODE_BLOCKED
    A ``blocked_node`` from the disruption's geometry is present in the
    shipment's ``route_node_ids``.

ROUTE_EDGE_BLOCKED
    A ``blocked_edge`` (``"ORIGIN_ID:DEST_ID"``) from the disruption's geometry
    spans two consecutive nodes in the shipment's ``route_node_ids``.

ETA_SLA_BREACH
    The disruption's ``window_end`` is later than the shipment's
    ``delivery_deadline`` AND the shipment is affected on route + time.

TEMPERATURE_EXPOSURE_INCREASED
    The shipment has a ``temperature_policy_id`` set (i.e. is temperature-
    sensitive) and is affected by the disruption.

Usage
-----
    from chainshield.impact.engine import ImpactEngine

    engine = ImpactEngine(graph)
    result = engine.evaluate(shipment, disruption)
    if result.is_affected:
        print(result.reason_codes, result.cargo_value_at_risk_usd)
"""

import copy
from dataclasses import dataclass, field
from datetime import datetime
import logging

import networkx as nx

from chainshield.logging import EVENT_IMPACT_EVALUATION, get_logger, log_event
from chainshield.models.disruption import Disruption
from chainshield.models.shipment import Shipment

_logger = get_logger("impact")



# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImpactResult:
    """Immutable result of a single shipment × disruption evaluation.

    Fields
    ------
    shipment_id
        ID of the evaluated shipment.
    disruption_id
        ID of the evaluated disruption.
    is_affected
        ``True`` iff route intersects AND time windows overlap.
    reason_codes
        ``SCREAMING_SNAKE_CASE`` codes explaining the impact.
    cargo_value_at_risk_usd
        ``shipment.cargo_value_usd`` when affected, 0.0 otherwise.
    node_hits
        Subset of ``route_node_ids`` that matched ``blocked_nodes``.
    edge_hits
        Subset of route edges that matched ``blocked_edges``.
    """

    shipment_id: str
    disruption_id: str
    is_affected: bool
    reason_codes: list[str] = field(default_factory=list)
    cargo_value_at_risk_usd: float = 0.0
    node_hits: list[str] = field(default_factory=list)
    edge_hits: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ImpactEngine:
    """Deterministic supply-chain disruption Impact Engine.

    Parameters
    ----------
    graph:
        A ``networkx.Graph`` (or DiGraph) whose node keys match the
        ``node_id`` values used in ``Shipment.route_node_ids`` and
        ``DisruptionGeometry.blocked_nodes``.  The engine does not mutate
        the graph; pass in a read-only view or a copy if needed.

    Examples
    --------
    >>> import networkx as nx
    >>> from chainshield.impact.engine import ImpactEngine
    >>> G = nx.Graph()
    >>> G.add_edges_from([("HUB-A", "PORT-03"), ("PORT-03", "HUB-B")])
    >>> engine = ImpactEngine(G)
    """

    def __init__(self, graph: nx.Graph) -> None:
        self._graph: nx.Graph = graph

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, shipment: Shipment, disruption: Disruption) -> ImpactResult:
        """Evaluate whether *shipment* is affected by *disruption*.

        Parameters
        ----------
        shipment:
            The shipment to evaluate.  Only ``ACTIVE`` (``status`` !=
            ``DELIVERED`` / ``CANCELLED``) shipments are ever flagged;
            completed shipments are returned as *unaffected* immediately.
        disruption:
            The disruption to evaluate against.  Only disruptions with
            ``status == ACTIVE`` are considered; others return unaffected.

        Returns
        -------
        ImpactResult
            Frozen dataclass — safe to cache, compare, or sort.
        """
        _base = dict(
            shipment_id=shipment.shipment_id,
            disruption_id=disruption.disruption_id,
        )

        # Skip resolved/cancelled disruptions and completed shipments
        if disruption.status.value not in ("ACTIVE", "MONITORING"):
            return ImpactResult(**_base, is_affected=False)
        if shipment.status.value in ("DELIVERED", "CANCELLED"):
            return ImpactResult(**_base, is_affected=False)

        # ── 1. Route intersection ──────────────────────────────────────
        node_hits, edge_hits = self._route_intersection(shipment, disruption)
        route_blocked = bool(node_hits or edge_hits)

        # ── 2. Time-window overlap ─────────────────────────────────────
        time_hit = _windows_overlap(
            a_start=shipment.planned_departure,
            a_end=shipment.planned_arrival,
            b_start=disruption.window_start,
            b_end=disruption.window_end,
        )

        if not (route_blocked and time_hit):
            return ImpactResult(**_base, is_affected=False)

        # ── 3. Build reason codes ──────────────────────────────────────
        codes: list[str] = []
        if node_hits:
            codes.append("PORT_NODE_BLOCKED")
        if edge_hits:
            codes.append("ROUTE_EDGE_BLOCKED")

        # SLA breach: disruption extends past the delivery deadline
        if disruption.window_end > shipment.delivery_deadline:
            codes.append("ETA_SLA_BREACH")

        # Cold-chain exposure
        if shipment.temperature_policy_id is not None:
            codes.append("TEMPERATURE_EXPOSURE_INCREASED")

        # Deduplicate while preserving order (stable across repeated calls)
        seen: set[str] = set()
        unique_codes: list[str] = []
        for c in codes:
            if c not in seen:
                seen.add(c)
                unique_codes.append(c)

        # ── 4. Cargo value at risk ─────────────────────────────────────
        value_at_risk = shipment.cargo_value_usd

        result = ImpactResult(
            **_base,
            is_affected=True,
            reason_codes=unique_codes,
            cargo_value_at_risk_usd=value_at_risk,
            node_hits=list(node_hits),
            edge_hits=list(edge_hits),
        )

        log_event(
            _logger,
            logging.INFO,
            EVENT_IMPACT_EVALUATION,
            f"Evaluated impact for {shipment.shipment_id}: affected=True",
            shipment_id=shipment.shipment_id,
            disruption_id=disruption.disruption_id,
            decision_type="impact_analysis",
            reason_codes=result.reason_codes,
            is_affected=True,
            cargo_value_at_risk_usd=value_at_risk,
        )

        return result

    def evaluate_many(
        self,
        shipments: list[Shipment],
        disruption: Disruption,
    ) -> list[ImpactResult]:
        """Evaluate every shipment in *shipments* against *disruption*.

        Results are returned in the same order as the input list.
        The method is a simple sequential wrapper; it does not mutate
        any input object.
        """
        return [self.evaluate(s, disruption) for s in shipments]

    def apply_results(
        self,
        shipments: list[Shipment],
        disruption: Disruption,
        results: list[ImpactResult],
    ) -> tuple[list[Shipment], Disruption]:
        """Return new model instances with impact fields populated.

        Neither the input shipments nor the disruption are mutated.
        Pydantic ``model_copy(update=...)`` is used to produce new objects
        with the impact fields filled in.

        Parameters
        ----------
        shipments:
            Original shipment list (unchanged).
        disruption:
            Original disruption (unchanged).
        results:
            Results from :meth:`evaluate_many` (must be same length and order).

        Returns
        -------
        updated_shipments, updated_disruption
            New model objects with ``is_disrupted``, ``reason_codes``,
            ``disruption_ids``, ``cargo_value_at_risk_usd``, and
            ``affected_shipment_ids`` filled in.
        """
        result_by_id = {r.shipment_id: r for r in results}

        updated_shipments: list[Shipment] = []
        total_value_at_risk = 0.0
        affected_ids: list[str] = []

        for shp in shipments:
            res = result_by_id.get(shp.shipment_id)
            if res and res.is_affected:
                updated_shipments.append(
                    shp.model_copy(
                        update={
                            "is_disrupted": True,
                            "disruption_ids": sorted(
                                set(shp.disruption_ids) | {disruption.disruption_id}
                            ),
                            "reason_codes": sorted(
                                set(shp.reason_codes) | set(res.reason_codes)
                            ),
                        }
                    )
                )
                total_value_at_risk += res.cargo_value_at_risk_usd
                affected_ids.append(shp.shipment_id)
            else:
                updated_shipments.append(shp)

        updated_disruption = disruption.model_copy(
            update={
                "affected_shipment_ids": sorted(
                    set(disruption.affected_shipment_ids) | set(affected_ids)
                ),
                "affected_shipment_count": len(
                    set(disruption.affected_shipment_ids) | set(affected_ids)
                ),
                "cargo_value_at_risk_usd": (
                    disruption.cargo_value_at_risk_usd + total_value_at_risk
                ),
            }
        )

        return updated_shipments, updated_disruption

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _route_intersection(
        self,
        shipment: Shipment,
        disruption: Disruption,
    ) -> tuple[list[str], list[str]]:
        """Return (node_hits, edge_hits) for the shipment's route."""
        blocked_nodes: set[str] = set(disruption.geometry.blocked_nodes)
        blocked_edges: set[frozenset[str]] = set()
        for edge_str in disruption.geometry.blocked_edges:
            parts = edge_str.split(":", 1)
            if len(parts) == 2:
                blocked_edges.add(frozenset(parts))

        route = shipment.route_node_ids

        # Node hits
        node_hits = sorted(set(route) & blocked_nodes)

        # Edge hits — check consecutive node pairs in the route
        edge_hits: list[str] = []
        for i in range(len(route) - 1):
            pair = frozenset([route[i], route[i + 1]])
            if pair in blocked_edges:
                # Use canonical "A:B" ordering (lexicographic) for stability
                a, b = sorted(pair)
                hit = f"{a}:{b}"
                if hit not in edge_hits:
                    edge_hits.append(hit)

        return node_hits, edge_hits


# ---------------------------------------------------------------------------
# Pure utility — no dependency on model objects
# ---------------------------------------------------------------------------


def _windows_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    """Return True iff [a_start, a_end] and [b_start, b_end] overlap.

    Two intervals overlap iff neither ends before the other begins.
    Both bounds are inclusive (closed interval).
    """
    return a_start <= b_end and b_start <= a_end
