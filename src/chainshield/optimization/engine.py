from __future__ import annotations

"""
ChainShield Deterministic Route Feasibility & Optimization Engine
=================================================================

Generates feasible route alternatives for a disrupted shipment using
Google OR-Tools CP-SAT.  All logic is deterministic: identical inputs
always produce identical, ordered output.

No live routing APIs, no external traffic APIs, no LLMs.

Algorithm
---------
1. Build candidate alternatives from the supplied ``route_graph`` and
   ``candidate_assets`` by filtering out:
   - Assets whose mode does not match an allowed mode for the shipment.
   - Assets whose carrier is unavailable (``AssetStatus != AVAILABLE``).
   - Assets whose capacity is insufficient for the shipment weight.
   - Assets that lack reefer capability when the shipment needs it.
   - Route paths that traverse any blocked node or blocked edge from
     ``active_disruptions``.
   - Paths whose transit time would cause the shipment to miss its
     ``delivery_deadline``.
2. Feed surviving candidates to CP-SAT as a binary assignment problem
   (select ≤ ``max_alternatives`` assignments, prefer lower cost /
   lower ETA delta).
3. Return ``RouteAlternative`` results ranked deterministically
   (primary: total_cost_usd ascending; secondary: eta_delta_hours
   ascending; tertiary: alternative_id lexicographic).

Output contract
---------------
Each ``RouteAlternative`` carries ``reason_codes: list[str]`` if it was
*rejected* (non-empty codes → infeasible/rejected).  Feasible results
carry empty ``reason_codes``.  The ``OptimizationResult`` carries the
union of all *rejection* codes encountered so that the caller can
explain to the operator why certain options were not surfaced.

Supported reason codes
----------------------
CAPACITY_VIOLATION
    Asset capacity_kg < shipment weight_kg.
DEADLINE_VIOLATION
    Estimated arrival exceeds shipment delivery_deadline.
REEFER_REQUIRED
    Shipment needs temperature control; asset is not reefer_capable.
CARRIER_UNAVAILABLE
    Asset status is not AVAILABLE.
MODE_INCOMPATIBLE
    Asset mode does not match any allowed mode for this shipment.
ROUTE_EDGE_BLOCKED
    Candidate path traverses a blocked edge from an active disruption.
ROUTE_NODE_BLOCKED
    Candidate path traverses a blocked node from an active disruption.
NO_FEASIBLE_ALTERNATIVE
    CP-SAT found zero feasible assignments from the candidate pool.

Usage
-----
    import networkx as nx
    from chainshield.optimization.engine import OptimizationEngine

    G = nx.DiGraph()
    G.add_edges_from([...], transit_hours=..., cost_usd=...)
    engine = OptimizationEngine(G)
    result = engine.find_alternatives(shipment, assets, disruptions)
    for alt in result.alternatives:
        print(alt.asset_id, alt.path, alt.reason_codes)
"""

import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import networkx as nx

from chainshield.logging import EVENT_OPTIMIZATION_EXECUTION, get_logger, log_event
from chainshield.models.asset import Asset, AssetStatus
from chainshield.models.disruption import Disruption
from chainshield.models.shipment import Shipment

_logger = get_logger("optimization")



# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------


@dataclass
class RouteAlternative:
    """One candidate route alternative for a disrupted shipment.

    Fields
    ------
    alternative_id
        Stable string key: ``"{asset_id}|{path_str}"``.
    asset_id
        The asset assigned to this alternative.
    carrier_id
        Carrier operating the asset (may be None).
    path
        Ordered list of node IDs from current_node → destination.
    mode
        Transport mode of the assigned asset.
    total_cost_usd
        Estimated total cost for this alternative (sum of edge costs).
    eta_delta_hours
        Hours added relative to the shipment's original planned_arrival.
    estimated_arrival
        Absolute UTC datetime of estimated arrival under this alternative.
    is_feasible
        True iff all hard constraints are satisfied.
    reason_codes
        SCREAMING_SNAKE_CASE rejection codes (empty when is_feasible=True).
    rank
        1-based rank among feasible alternatives (0 for rejected).
    """

    alternative_id: str
    asset_id: str
    carrier_id: str | None
    path: list[str]
    mode: str
    total_cost_usd: float
    eta_delta_hours: float
    estimated_arrival: datetime
    is_feasible: bool
    reason_codes: list[str] = field(default_factory=list)
    rank: int = 0


@dataclass
class OptimizationResult:
    """Result of a route-feasibility optimisation run.

    Fields
    ------
    shipment_id
        ID of the shipment that was evaluated.
    alternatives
        All feasible alternatives, ranked (rank ≥ 1), followed by any
        rejected candidates (rank == 0), sorted by rank then
        alternative_id.
    rejection_reason_codes
        Union of all reason codes from rejected candidates encountered
        during the run.  Empty only when every candidate was feasible.
    solver_status
        OR-Tools solver status string (e.g. ``"OPTIMAL"``).
    """

    shipment_id: str
    alternatives: list[RouteAlternative]
    rejection_reason_codes: list[str]
    solver_status: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_BLOCKED_NODE_CODE = "ROUTE_NODE_BLOCKED"
_BLOCKED_EDGE_CODE = "ROUTE_EDGE_BLOCKED"
_CAPACITY_CODE = "CAPACITY_VIOLATION"
_DEADLINE_CODE = "DEADLINE_VIOLATION"
_REEFER_CODE = "REEFER_REQUIRED"
_CARRIER_CODE = "CARRIER_UNAVAILABLE"
_MODE_CODE = "MODE_INCOMPATIBLE"
_NO_FEASIBLE_CODE = "NO_FEASIBLE_ALTERNATIVE"


def _blocked_set(
    disruptions: list[Disruption],
) -> tuple[frozenset[str], frozenset[frozenset[str]]]:
    """Return (blocked_nodes, blocked_edges) from all active disruptions."""
    nodes: set[str] = set()
    edges: set[frozenset[str]] = set()
    for d in disruptions:
        if d.status.value not in ("ACTIVE", "MONITORING"):
            continue
        nodes.update(d.geometry.blocked_nodes)
        for edge_str in d.geometry.blocked_edges:
            parts = edge_str.split(":", 1)
            if len(parts) == 2:
                edges.add(frozenset(parts))
    return frozenset(nodes), frozenset(edges)


def _path_is_blocked(
    path: list[str],
    blocked_nodes: frozenset[str],
    blocked_edges: frozenset[frozenset[str]],
) -> list[str]:
    """Return reason codes if *path* traverses any blocked node or edge.

    Returns an empty list when the path is clear.
    """
    codes: list[str] = []
    for node in path:
        if node in blocked_nodes:
            codes.append(_BLOCKED_NODE_CODE)
            break  # one code per path is enough; don't duplicate
    for i in range(len(path) - 1):
        pair = frozenset([path[i], path[i + 1]])
        if pair in blocked_edges:
            if _BLOCKED_EDGE_CODE not in codes:
                codes.append(_BLOCKED_EDGE_CODE)
            break
    return codes


def _path_cost_and_hours(
    graph: nx.DiGraph,
    path: list[str],
) -> tuple[float, float]:
    """Return (total_cost_usd, total_transit_hours) for *path* using edge attrs.

    Edge attributes ``cost_usd`` and ``transit_hours`` are expected.
    Missing attributes default to 0.0.
    """
    total_cost = 0.0
    total_hours = 0.0
    for u, v in zip(path[:-1], path[1:]):
        data = graph.get_edge_data(u, v) or {}
        total_cost += float(data.get("cost_usd", 0.0))
        total_hours += float(data.get("transit_hours", 0.0))
    return total_cost, total_hours


def _candidate_paths(
    graph: nx.DiGraph,
    origin: str,
    destination: str,
    max_paths: int = 10,
) -> list[list[str]]:
    """Return up to *max_paths* simple paths from *origin* to *destination*.

    Uses ``nx.all_simple_paths`` with a cutoff to avoid blowup on large
    graphs.  Results are sorted lexicographically for determinism.
    """
    if origin not in graph or destination not in graph:
        return []
    try:
        paths = list(
            itertools.islice(
                nx.all_simple_paths(graph, origin, destination, cutoff=8),
                max_paths,
            )
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    # Sort for determinism: primarily by path length (shorter first),
    # secondarily by lexicographic node sequence.
    return sorted(paths, key=lambda p: (len(p), p))


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class OptimizationEngine:
    """Deterministic route feasibility and optimization engine.

    Parameters
    ----------
    route_graph:
        A ``networkx.DiGraph`` whose edges carry ``transit_hours`` and
        ``cost_usd`` attributes.  Undirected graphs are accepted and
        converted to DiGraph internally.
    max_alternatives:
        Maximum number of feasible alternatives to return (default 5).
    solver_timeout_seconds:
        CP-SAT hard timeout (default 2.0 s, per the project constraint).

    Examples
    --------
    >>> import networkx as nx
    >>> G = nx.DiGraph()
    >>> G.add_edge("HUB-A", "HUB-B", transit_hours=6.0, cost_usd=500.0)
    >>> engine = OptimizationEngine(G)
    """

    def __init__(
        self,
        route_graph: nx.Graph,
        *,
        max_alternatives: int = 5,
        solver_timeout_seconds: float = 2.0,
    ) -> None:
        if isinstance(route_graph, nx.DiGraph):
            self._graph: nx.DiGraph = route_graph
        else:
            self._graph = route_graph.to_directed()
        self._max_alternatives = max_alternatives
        self._solver_timeout = solver_timeout_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_alternatives(
        self,
        shipment: Shipment,
        candidate_assets: list[Asset],
        active_disruptions: list[Disruption] | None = None,
    ) -> OptimizationResult:
        """Find feasible route alternatives for a disrupted *shipment*.

        Parameters
        ----------
        shipment:
            The disrupted shipment requiring rerouting.
        candidate_assets:
            Pool of assets to consider for reassignment.
        active_disruptions:
            Disruptions whose blocked nodes/edges must be respected.
            May be ``None`` (treated as empty list).

        Returns
        -------
        OptimizationResult
            Contains ranked feasible alternatives plus all rejection
            reason codes encountered.
        """
        try:
            from ortools.sat.python import cp_model as _cp_model
        except (ImportError, OSError):
            res = OptimizationResult(
                shipment_id=shipment.shipment_id,
                alternatives=[],
                rejection_reason_codes=["DEPENDENCY_MISSING_ORTOOLS"],
                solver_status="SKIPPED",
            )
            log_event(
                _logger,
                logging.WARNING,
                EVENT_OPTIMIZATION_EXECUTION,
                f"Optimization skipped for {shipment.shipment_id}: dependency missing",
                shipment_id=shipment.shipment_id,
                decision_type="route_reassignment",
                reason_codes=res.rejection_reason_codes,
                solver_status="SKIPPED",
                feasible_count=0,
                total_candidates=0,
            )
            return res

        disruptions = active_disruptions or []
        blocked_nodes, blocked_edges = _blocked_set(disruptions)

        origin = shipment.current_node_id or shipment.origin_hub_id
        destination = shipment.destination_hub_id
        needs_reefer = shipment.temperature_policy_id is not None

        # ── 1. Build and filter candidates ──────────────────────────────
        all_candidates: list[RouteAlternative] = []
        all_rejection_codes: set[str] = set()

        for asset in candidate_assets:
            codes = self._check_asset_constraints(shipment, asset, needs_reefer)
            if codes:
                all_rejection_codes.update(codes)
                # Still record as rejected alternative for full visibility
                all_candidates.append(
                    RouteAlternative(
                        alternative_id=f"{asset.asset_id}|{origin}->{destination}",
                        asset_id=asset.asset_id,
                        carrier_id=asset.carrier_id,
                        path=[origin, destination],
                        mode=asset.mode.value,
                        total_cost_usd=0.0,
                        eta_delta_hours=0.0,
                        estimated_arrival=shipment.planned_arrival,
                        is_feasible=False,
                        reason_codes=sorted(codes),
                        rank=0,
                    )
                )
                continue

            # Asset passed asset-level checks — evaluate all candidate paths
            paths = _candidate_paths(self._graph, origin, destination)
            if not paths:
                # No path exists in the graph
                all_rejection_codes.add(_NO_FEASIBLE_CODE)
                all_candidates.append(
                    RouteAlternative(
                        alternative_id=f"{asset.asset_id}|NO_PATH",
                        asset_id=asset.asset_id,
                        carrier_id=asset.carrier_id,
                        path=[],
                        mode=asset.mode.value,
                        total_cost_usd=0.0,
                        eta_delta_hours=0.0,
                        estimated_arrival=shipment.planned_arrival,
                        is_feasible=False,
                        reason_codes=[_NO_FEASIBLE_CODE],
                        rank=0,
                    )
                )
                continue

            for path in paths:
                alt = self._evaluate_path(
                    shipment=shipment,
                    asset=asset,
                    path=path,
                    blocked_nodes=blocked_nodes,
                    blocked_edges=blocked_edges,
                )
                if not alt.is_feasible:
                    all_rejection_codes.update(alt.reason_codes)
                all_candidates.append(alt)

        feasible = [a for a in all_candidates if a.is_feasible]

        if not feasible:
            all_rejection_codes.add(_NO_FEASIBLE_CODE)
            res = OptimizationResult(
                shipment_id=shipment.shipment_id,
                alternatives=all_candidates,
                rejection_reason_codes=sorted(all_rejection_codes),
                solver_status="INFEASIBLE",
            )
            log_event(
                _logger,
                logging.INFO,
                EVENT_OPTIMIZATION_EXECUTION,
                f"Optimization executed for {shipment.shipment_id}: INFEASIBLE",
                shipment_id=shipment.shipment_id,
                asset_id=None,
                decision_type="route_reassignment",
                reason_codes=res.rejection_reason_codes,
                solver_status="INFEASIBLE",
                feasible_count=0,
                total_candidates=len(all_candidates),
            )
            return res

        # ── 2. CP-SAT: select up to max_alternatives from feasible pool ─
        selected, solver_status = self._solve_selection(feasible, _cp_model)

        # ── 3. Rank selected alternatives deterministically ──────────────
        selected_sorted = sorted(
            selected,
            key=lambda a: (a.total_cost_usd, a.eta_delta_hours, a.alternative_id),
        )
        for rank, alt in enumerate(selected_sorted, start=1):
            alt.rank = rank

        # Combine: ranked feasible first, then rejected (rank=0)
        rejected = [a for a in all_candidates if not a.is_feasible]
        combined = selected_sorted + sorted(rejected, key=lambda a: a.alternative_id)

        result = OptimizationResult(
            shipment_id=shipment.shipment_id,
            alternatives=combined,
            rejection_reason_codes=sorted(all_rejection_codes),
            solver_status=solver_status,
        )

        chosen_asset = selected_sorted[0].asset_id if selected_sorted else None
        log_event(
            _logger,
            logging.INFO,
            EVENT_OPTIMIZATION_EXECUTION,
            f"Optimization executed for {shipment.shipment_id}: {solver_status}",
            shipment_id=shipment.shipment_id,
            asset_id=chosen_asset,
            decision_type="route_reassignment",
            reason_codes=result.rejection_reason_codes,
            solver_status=solver_status,
            feasible_count=len(selected_sorted),
            total_candidates=len(all_candidates),
        )

        return result

    # ------------------------------------------------------------------
    # Private: constraint checks
    # ------------------------------------------------------------------

    def _check_asset_constraints(
        self,
        shipment: Shipment,
        asset: Asset,
        needs_reefer: bool,
    ) -> list[str]:
        """Return rejection reason codes for asset-level hard constraints.

        Returns an empty list when the asset passes all checks.
        """
        codes: list[str] = []

        # Carrier availability
        if asset.status != AssetStatus.AVAILABLE:
            codes.append(_CARRIER_CODE)

        # Capacity
        if asset.capacity_kg < shipment.weight_kg:
            codes.append(_CAPACITY_CODE)

        # Reefer capability
        if needs_reefer and not asset.reefer_capable:
            codes.append(_REEFER_CODE)

        # Mode compatibility: asset mode must match shipment primary mode
        # OR shipment mode must be MULTIMODAL (any mode is acceptable)
        if (
            shipment.mode.value != "multimodal"
            and asset.mode.value != shipment.mode.value
        ):
            codes.append(_MODE_CODE)

        return codes

    def _evaluate_path(
        self,
        *,
        shipment: Shipment,
        asset: Asset,
        path: list[str],
        blocked_nodes: frozenset[str],
        blocked_edges: frozenset[frozenset[str]],
    ) -> RouteAlternative:
        """Evaluate one (asset, path) pair against all hard constraints."""
        path_str = "->".join(path)
        alt_id = f"{asset.asset_id}|{path_str}"

        codes: list[str] = []

        # Blocked route check
        route_codes = _path_is_blocked(path, blocked_nodes, blocked_edges)
        codes.extend(route_codes)

        # Cost and ETA
        total_cost, transit_hours = _path_cost_and_hours(self._graph, path)

        # Asset availability offset: if the asset isn't available until later,
        # the effective departure is max(now, asset.available_at).
        # We use shipment.planned_departure as the reference "now".
        asset_avail = asset.available_at
        effective_departure = (
            asset_avail
            if asset_avail > shipment.planned_departure
            else shipment.planned_departure
        )
        estimated_arrival = effective_departure + timedelta(hours=transit_hours)

        eta_delta_hours = (
            estimated_arrival - shipment.planned_arrival
        ).total_seconds() / 3600.0

        # Deadline check
        if estimated_arrival > shipment.delivery_deadline:
            codes.append(_DEADLINE_CODE)

        is_feasible = len(codes) == 0

        return RouteAlternative(
            alternative_id=alt_id,
            asset_id=asset.asset_id,
            carrier_id=asset.carrier_id,
            path=path,
            mode=asset.mode.value,
            total_cost_usd=total_cost,
            eta_delta_hours=eta_delta_hours,
            estimated_arrival=estimated_arrival,
            is_feasible=is_feasible,
            reason_codes=sorted(codes),
            rank=0,
        )

    # ------------------------------------------------------------------
    # Private: CP-SAT selection
    # ------------------------------------------------------------------

    def _solve_selection(
        self,
        feasible: list[RouteAlternative],
        cp_model_module: object,
    ) -> tuple[list[RouteAlternative], str]:
        """Use CP-SAT to select up to *max_alternatives* from *feasible*.

        Objective: minimise total_cost_usd (scaled to integers) of the
        selected set, subject to selecting exactly
        ``min(max_alternatives, len(feasible))`` alternatives.

        Returns (selected_alternatives, solver_status_name).
        """
        cp_model = cp_model_module  # type: ignore[assignment]
        model = cp_model.CpModel()

        n = len(feasible)
        k = min(self._max_alternatives, n)

        # Binary selection variables
        select = [model.NewBoolVar(f"sel_{i}") for i in range(n)]

        # Exactly k alternatives selected
        model.Add(sum(select) == k)

        # Uniqueness: at most 1 path per asset (avoid selecting the same
        # asset twice on different paths)
        asset_ids = list({alt.asset_id for alt in feasible})
        for asset_id in asset_ids:
            indices = [i for i, a in enumerate(feasible) if a.asset_id == asset_id]
            if len(indices) > 1:
                model.Add(sum(select[i] for i in indices) <= 1)

        # Objective: minimise total cost (scale to integer cents)
        scale = 100
        costs = [int(a.total_cost_usd * scale) for a in feasible]
        model.Minimize(sum(select[i] * costs[i] for i in range(n)))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self._solver_timeout
        status_code = solver.Solve(model)
        status_name = solver.StatusName(status_code)

        if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # Fallback: return top-k by cost without solver
            sorted_fallback = sorted(
                feasible,
                key=lambda a: (a.total_cost_usd, a.eta_delta_hours, a.alternative_id),
            )
            return sorted_fallback[:k], "FALLBACK_SORTED"

        selected = [feasible[i] for i in range(n) if solver.Value(select[i]) == 1]
        return selected, status_name
