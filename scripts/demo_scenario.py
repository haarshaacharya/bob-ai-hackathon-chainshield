#!/usr/bin/env python3
from __future__ import annotations

"""
ChainShield — Complete End-to-End Demo Scenario Orchestrator
=============================================================

Executes one deterministic, repeatable scenario that demonstrates every
required capability of the ChainShield system:

  1.  Active disruption at PORT-03 (port strike).
  2.  Affected shipment SHP-001 (refrigerated vaccines, $520k cargo).
  3.  Cargo value at risk computed and returned.
  4.  Deterministic reason codes on every result.
  5.  Cold-chain sensor excursion for SHP-001 (~18-min excursion window).
  6.  Cold-chain severity: EXCURSION_REVIEW for the 18-min case.
  7.  At least one feasible route alternative (ASSET-REEFER-01 via DEPOT-X).
  8.  At least one rejected alternative with explicit reason code.
  9.  Compatible idle asset identified (ASSET-REEFER-01).
  10. Evidence records linking every decision to its source data.
  11. Deterministic explanation fallback (watsonx.ai not required).
  12. JSON and Markdown action plan exported.

No live APIs.  No external routing services.  No LLM dependency.
Identical inputs always produce identical outputs.

Usage
-----
    python scripts/demo_scenario.py
    python scripts/demo_scenario.py --report reports/demo_scenario.json
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Resolve import paths (mirrors conftest.py pattern)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT / "src", _REPO_ROOT / "scripts"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import networkx as nx

from chainshield.cold_chain.engine import ColdChainEngine
from chainshield.evidence.events import (
    ColdChainEvidence,
    DecisionType,
    ImpactAnalysisEvidence,
    OptimizationRejectionEvidence,
    RouteRecommendationEvidence,
)
from chainshield.evidence.store import EvidenceStore
from chainshield.explanation.fallback import generate_fallback_explanation
from chainshield.impact.engine import ImpactEngine
from chainshield.models.asset import Asset, AssetMode, AssetStatus, AssetType
from chainshield.models.disruption import (
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
)
from chainshield.models.enums import CargoMode, ExcursionSeverity, ProductClass, ShipmentStatus
from chainshield.models.sensor_reading import SensorReading
from chainshield.models.shipment import Shipment
from chainshield.models.temperature_policy import SeverityRules, TemperaturePolicy
from chainshield.optimization.engine import OptimizationEngine
from generate_synthetic_data import generate_scenario


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class DemoScenarioResult:
    """Complete outcome of the end-to-end demo scenario run."""

    disruption_id: str
    affected_shipment_ids: list[str]
    cargo_value_at_risk_usd: float
    impact_reason_codes: list[str]

    cold_chain_severity: str
    cold_chain_reason_codes: list[str]
    cold_chain_duration_minutes: float
    cold_chain_max_celsius: float

    feasible_alternatives: list[dict[str, Any]]
    rejected_alternatives: list[dict[str, Any]]
    idle_compatible_assets: list[str]

    evidence_records: list[dict[str, Any]]
    explanation: dict[str, Any]

    action_plan_json: dict[str, Any]
    action_plan_markdown: str

    all_reason_codes: list[str]
    scenario_passed: bool
    failure_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Route graph builder
# ---------------------------------------------------------------------------

def _build_scenario_graph() -> nx.DiGraph:
    """Return the extended route graph for the full scenario.

    Topology
    --------
    Primary route (blocked): HUB-A → HUB-B → PORT-03 → HUB-D
    Feasible alternative:    HUB-A → HUB-B → DEPOT-X → HUB-C → HUB-D
    Infeasible route:        HUB-E → PORT-03 → HUB-F  (no alternative)
    """
    G: nx.DiGraph = nx.DiGraph()
    # Primary (blocked) route legs
    G.add_edge("HUB-A", "HUB-B", transit_hours=4.0, cost_usd=700.0)
    G.add_edge("HUB-B", "PORT-03", transit_hours=6.0, cost_usd=900.0)
    G.add_edge("PORT-03", "HUB-D", transit_hours=5.0, cost_usd=800.0)
    # Feasible reroute via DEPOT-X / HUB-C
    G.add_edge("HUB-B", "DEPOT-X", transit_hours=3.0, cost_usd=500.0)
    G.add_edge("DEPOT-X", "HUB-C", transit_hours=4.0, cost_usd=600.0)
    G.add_edge("HUB-C", "HUB-D", transit_hours=3.0, cost_usd=450.0)
    # Infeasible shipment route (HUB-E only has PORT-03 as next hop)
    G.add_edge("HUB-E", "PORT-03", transit_hours=8.0, cost_usd=1_200.0)
    G.add_edge("PORT-03", "HUB-F", transit_hours=4.0, cost_usd=600.0)
    # Reverse edges for bidirectional traversal
    G.add_edge("HUB-B", "HUB-A", transit_hours=4.0, cost_usd=700.0)
    G.add_edge("PORT-03", "HUB-B", transit_hours=6.0, cost_usd=900.0)
    G.add_edge("HUB-D", "PORT-03", transit_hours=5.0, cost_usd=800.0)
    G.add_edge("DEPOT-X", "HUB-B", transit_hours=3.0, cost_usd=500.0)
    G.add_edge("HUB-C", "DEPOT-X", transit_hours=4.0, cost_usd=600.0)
    G.add_edge("HUB-D", "HUB-C", transit_hours=3.0, cost_usd=450.0)
    return G


# ---------------------------------------------------------------------------
# Scenario data builder (uses generate_synthetic_data)
# ---------------------------------------------------------------------------

def _build_scenario_data() -> tuple[
    Disruption,
    list[Shipment],
    list[Asset],
    dict[str, list[SensorReading]],
    TemperaturePolicy,
]:
    """Return all scenario objects derived from the deterministic synthetic bundle."""
    bundle = generate_scenario(seed=42)

    # Primary disruption: port strike blocking PORT-03
    disruption = bundle.disruptions[0]  # DISR-PORT-STRIKE-01

    # Shipments from the bundle (SHP-001 is the cold-chain affected shipment)
    shipments = bundle.shipments

    # Assets from bundle
    assets = bundle.assets

    # Sensor readings are for SHP-003 in the bundle; for the demo scenario
    # we want the reference excursion on SHP-001 (the disrupted cold-chain shipment).
    # Build the canonical 5-reading 18-min excursion series matching preflight_demo.py.
    from datetime import datetime, timezone
    base = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
    ref_readings = [
        SensorReading(sensor_id="SENSOR-9", shipment_id="SHP-001",
                      ts=base, temperature_c=6.9),
        SensorReading(sensor_id="SENSOR-9", shipment_id="SHP-001",
                      ts=base.replace(minute=6), temperature_c=8.9),
        SensorReading(sensor_id="SENSOR-9", shipment_id="SHP-001",
                      ts=base.replace(minute=12), temperature_c=10.4),
        SensorReading(sensor_id="SENSOR-9", shipment_id="SHP-001",
                      ts=base.replace(minute=18), temperature_c=9.1),
        SensorReading(sensor_id="SENSOR-9", shipment_id="SHP-001",
                      ts=base.replace(minute=24), temperature_c=6.4),
    ]

    # Include bundle readings for SHP-003 too
    sensor_map: dict[str, list[SensorReading]] = {
        "SHP-001": ref_readings,
        "SHP-003": bundle.sensor_readings,
    }

    # Cold-chain policy for SHP-001 (max_continuous=30 → EXCURSION_REVIEW for 18-min excursion)
    cdc_policy = TemperaturePolicy(
        policy_id="POL-CDC-REFVAX-01",
        product_class=ProductClass.REFRIGERATED_VACCINE,
        jurisdiction="CDC",
        min_celsius=2.0,
        max_celsius=8.0,
        max_continuous_excursion_minutes=30.0,
        sample_interval_minutes=6.0,
        source_reference="CDC Vaccine Storage and Handling Toolkit (demo)",
        severity_rules=SeverityRules(
            out_of_range=ExcursionSeverity.EXCURSION_REVIEW,
            missing_sensor_data=ExcursionSeverity.URGENT_ESCALATION,
            sustained_excursion=ExcursionSeverity.URGENT_ESCALATION,
        ),
    )

    return disruption, shipments, assets, sensor_map, cdc_policy


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_demo_scenario() -> DemoScenarioResult:
    """Execute the complete end-to-end demo scenario and return a result bundle."""
    disruption, shipments, assets, sensor_map, cdc_policy = _build_scenario_data()
    graph = _build_scenario_graph()
    store = EvidenceStore()
    failure_reasons: list[str] = []

    # ── 1. Impact Engine: detect affected shipments ──────────────────────────
    impact_engine = ImpactEngine(graph)
    results = impact_engine.evaluate_many(shipments, disruption)

    affected_ids: list[str] = []
    impact_reason_codes: list[str] = []
    cargo_at_risk = 0.0

    for res in results:
        if not res.is_affected:
            continue
        affected_ids.append(res.shipment_id)
        for code in res.reason_codes:
            if code not in impact_reason_codes:
                impact_reason_codes.append(code)
        cargo_at_risk += res.cargo_value_at_risk_usd

        rec = ImpactAnalysisEvidence(
            decision_type=DecisionType.IMPACT_ANALYSIS,
            shipment_id=res.shipment_id,
            reason_codes=res.reason_codes,
            source_refs={
                "disruption_id": disruption.disruption_id,
                "node_hits": res.node_hits,
                "edge_hits": res.edge_hits,
            },
            disruption_ids=[disruption.disruption_id],
            affected_node_ids=res.node_hits,
        )
        if res.shipment_id == "SHP-001":
            store.add(rec)

    if "SHP-001" not in affected_ids:
        failure_reasons.append("SHP-001 was not identified as affected by the disruption")

    # ── 2. Cold-chain Engine: classify sensor excursion for SHP-001 ──────────
    cc_engine = ColdChainEngine()
    shp_001_readings = sensor_map.get("SHP-001", [])
    cc_result = cc_engine.evaluate(cdc_policy, shp_001_readings)

    cc_record = ColdChainEvidence(
        decision_type=DecisionType.COLD_CHAIN_CLASSIFICATION,
        shipment_id="SHP-001",
        reason_codes=cc_result.reason_codes,
        source_refs={"policy_id": cdc_policy.policy_id},
        disruption_ids=[disruption.disruption_id],
        policy_id=cdc_policy.policy_id,
        severity=cc_result.severity.value,
        out_of_range_readings=cc_result.out_of_range_count,
        duration_minutes=cc_result.total_out_of_range_minutes,
        max_celsius=cc_result.max_temp_c,
        min_celsius=cc_result.min_temp_c,
    )
    store.add(cc_record)

    if cc_result.severity != ExcursionSeverity.EXCURSION_REVIEW:
        failure_reasons.append(
            f"Expected EXCURSION_REVIEW cold-chain severity, got {cc_result.severity.value}"
        )

    # ── 3. Optimization Engine: find route alternatives for SHP-001 ──────────
    shp_001 = next((s for s in shipments if s.shipment_id == "SHP-001"), None)
    if shp_001 is None:
        failure_reasons.append("SHP-001 not found in shipment list")

    opt_engine = OptimizationEngine(graph)
    idle_assets = [a for a in assets if a.status == AssetStatus.AVAILABLE]
    opt_result = opt_engine.find_alternatives(
        shp_001,
        idle_assets,
        active_disruptions=[disruption],
    )

    feasible_alts = [a for a in opt_result.alternatives if a.is_feasible]
    rejected_alts = [a for a in opt_result.alternatives if not a.is_feasible]

    # Emit evidence for the top feasible alternative
    for alt in feasible_alts[:1]:
        route_rec = RouteRecommendationEvidence(
            decision_type=DecisionType.ROUTE_RECOMMENDATION,
            shipment_id="SHP-001",
            reason_codes=["CAPACITY_OK", "REEFER_CAPACITY_AVAILABLE"],
            source_refs={
                "alternative_id": alt.alternative_id,
                "asset_id": alt.asset_id,
                "solver_status": opt_result.solver_status,
            },
            disruption_ids=[disruption.disruption_id],
            asset_ids=[alt.asset_id],
            recommended_route_node_ids=alt.path,
            original_route_node_ids=shp_001.route_node_ids if shp_001 else [],
            estimated_delay_hours=max(alt.eta_delta_hours, 0.0),
        )
        store.add(route_rec)

    # Emit evidence for rejected alternatives (first one is sufficient for demo)
    for alt in rejected_alts[:1]:
        rej_rec = OptimizationRejectionEvidence(
            decision_type=DecisionType.OPTIMIZATION_REJECTION,
            shipment_id="SHP-001",
            reason_codes=alt.reason_codes,
            source_refs={
                "alternative_id": alt.alternative_id,
                "asset_id": alt.asset_id,
            },
            disruption_ids=[disruption.disruption_id],
            asset_ids=[alt.asset_id],
            candidate_route_node_ids=alt.path,
            rejected_asset_ids=[alt.asset_id],
            constraint_violations=alt.reason_codes,
        )
        store.add(rej_rec)

    if not feasible_alts:
        failure_reasons.append("No feasible route alternatives found for SHP-001")
    if not rejected_alts:
        failure_reasons.append("No rejected alternatives recorded for SHP-001")

    # Collect idle compatible assets (reefer capable, passes mode check for SHP-001 multimodal)
    compatible_asset_ids = [
        a.asset_id for a in idle_assets
        if a.reefer_capable and a.capacity_kg >= (shp_001.weight_kg if shp_001 else 0)
    ]

    # ── 4. Explanation fallback ───────────────────────────────────────────────
    best_alt = feasible_alts[0] if feasible_alts else None
    decision = {
        "shipment_id": "SHP-001",
        "disruption": disruption.disruption_id,
        "kind": "impact",
        "reason_codes": impact_reason_codes,
        "recommended_route": {
            "carrier": best_alt.carrier_id or "CARRIER-A",
            "eta_delta_hours": round(best_alt.eta_delta_hours, 1),
            "additional_cost_usd": round(best_alt.total_cost_usd, 0),
        } if best_alt else {},
        "cold_chain": {
            "status": cc_result.severity.value,
            "max_celsius": cc_result.max_temp_c,
            "policy_max_celsius": cdc_policy.max_celsius,
            "duration_minutes": cc_result.total_out_of_range_minutes,
        },
    }
    explanation = generate_fallback_explanation(decision)

    required_keys = {"summary", "why_affected", "recommended_action", "evidence", "uncertainties"}
    if not required_keys.issubset(explanation.keys()):
        failure_reasons.append(
            f"Explanation missing keys: {required_keys - explanation.keys()}"
        )
    if explanation.get("generated_by") != "deterministic_fallback_template":
        failure_reasons.append("Explanation generated_by is not 'deterministic_fallback_template'")

    # ── 5. Action plan export (JSON + Markdown) ───────────────────────────────
    generated_at = datetime.now(timezone.utc)

    plan_entry: dict[str, Any] = {
        "shipment_id": "SHP-001",
        "disruption_id": disruption.disruption_id,
        "reason_codes": impact_reason_codes,
        "cargo_value_usd": shp_001.cargo_value_usd if shp_001 else 0.0,
        "cold_chain_severity": cc_result.severity.value,
        "cold_chain_reason_codes": cc_result.reason_codes,
        "route_alternatives": [
            {
                "alternative_id": a.alternative_id,
                "asset_id": a.asset_id,
                "carrier_id": a.carrier_id,
                "path": a.path,
                "mode": a.mode,
                "total_cost_usd": a.total_cost_usd,
                "eta_delta_hours": a.eta_delta_hours,
                "is_feasible": a.is_feasible,
                "reason_codes": a.reason_codes,
                "rank": a.rank,
            }
            for a in feasible_alts
        ],
        "rejected_alternatives": [
            {
                "alternative_id": a.alternative_id,
                "asset_id": a.asset_id,
                "reason_codes": a.reason_codes,
            }
            for a in rejected_alts
        ],
        "rejection_reason_codes": opt_result.rejection_reason_codes,
        "explanation": explanation,
    }

    action_plan_json: dict[str, Any] = {
        "disruption_id": disruption.disruption_id,
        "generated_at": generated_at.isoformat(),
        "solver_status": opt_result.solver_status,
        "shipments": [plan_entry],
        "evidence_record_count": len(store),
    }

    # Markdown action plan
    md_lines = [
        f"# Action Plan — Disruption {disruption.disruption_id}",
        f"_Generated at {generated_at.isoformat()}_",
        "",
        f"## Shipment SHP-001",
        f"- **Reason codes:** {', '.join(impact_reason_codes) or 'none'}",
        f"- **Cargo value at risk:** ${plan_entry['cargo_value_usd']:,.0f}",
        f"- **Cold-chain severity:** {cc_result.severity.value}",
        f"- **Cold-chain reason codes:** {', '.join(cc_result.reason_codes) or 'none'}",
        "",
    ]
    if feasible_alts:
        md_lines.append("### Feasible route alternatives")
        for alt in feasible_alts:
            md_lines.append(
                f"  {alt.rank}. {alt.asset_id} via {' → '.join(alt.path)} "
                f"(+{alt.eta_delta_hours:.1f}h, ${alt.total_cost_usd:,.0f})"
            )
    else:
        md_lines.append(
            f"- **No feasible alternatives** — "
            f"{', '.join(opt_result.rejection_reason_codes) or 'N/A'}"
        )
    if rejected_alts:
        md_lines.append("")
        md_lines.append("### Rejected alternatives")
        for alt in rejected_alts:
            md_lines.append(
                f"  - {alt.asset_id}: {', '.join(alt.reason_codes)}"
            )
    md_lines.append("")
    md_lines.append("### Explanation (deterministic fallback)")
    md_lines.append(f"> {explanation['summary']}")
    md_lines.append(f"> **Recommended action:** {explanation['recommended_action']}")
    action_plan_markdown = "\n".join(md_lines)

    # ── 6. Collect all unique reason codes ───────────────────────────────────
    all_codes: list[str] = []
    for code in (
        impact_reason_codes
        + cc_result.reason_codes
        + opt_result.rejection_reason_codes
    ):
        if code not in all_codes:
            all_codes.append(code)

    return DemoScenarioResult(
        disruption_id=disruption.disruption_id,
        affected_shipment_ids=affected_ids,
        cargo_value_at_risk_usd=cargo_at_risk,
        impact_reason_codes=impact_reason_codes,
        cold_chain_severity=cc_result.severity.value,
        cold_chain_reason_codes=cc_result.reason_codes,
        cold_chain_duration_minutes=cc_result.total_out_of_range_minutes,
        cold_chain_max_celsius=cc_result.max_temp_c or 0.0,
        feasible_alternatives=[
            {
                "alternative_id": a.alternative_id,
                "asset_id": a.asset_id,
                "path": a.path,
                "total_cost_usd": a.total_cost_usd,
                "eta_delta_hours": a.eta_delta_hours,
                "rank": a.rank,
            }
            for a in feasible_alts
        ],
        rejected_alternatives=[
            {
                "alternative_id": a.alternative_id,
                "asset_id": a.asset_id,
                "reason_codes": a.reason_codes,
            }
            for a in rejected_alts
        ],
        idle_compatible_assets=compatible_asset_ids,
        evidence_records=store.to_dicts(),
        explanation=explanation,
        action_plan_json=action_plan_json,
        action_plan_markdown=action_plan_markdown,
        all_reason_codes=all_codes,
        scenario_passed=len(failure_reasons) == 0,
        failure_reasons=failure_reasons,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="ChainShield end-to-end demo scenario")
    parser.add_argument(
        "--report",
        default="reports/demo_scenario.json",
        help="Path for the JSON report (default: reports/demo_scenario.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress console output")
    args = parser.parse_args()

    result = run_demo_scenario()

    if not args.quiet:
        print("=" * 70)
        print("ChainShield — End-to-End Demo Scenario")
        print("=" * 70)
        print(f"Disruption         : {result.disruption_id}")
        print(f"Affected shipments : {result.affected_shipment_ids}")
        print(f"Cargo at risk      : ${result.cargo_value_at_risk_usd:,.0f}")
        print(f"Impact reason codes: {result.impact_reason_codes}")
        print(f"Cold-chain severity: {result.cold_chain_severity}")
        print(f"CC reason codes    : {result.cold_chain_reason_codes}")
        print(f"CC max temp (°C)   : {result.cold_chain_max_celsius}")
        print(f"CC excursion (min) : {result.cold_chain_duration_minutes}")
        print(f"Feasible alts      : {len(result.feasible_alternatives)}")
        print(f"Rejected alts      : {len(result.rejected_alternatives)}")
        print(f"Idle compatible    : {result.idle_compatible_assets}")
        print(f"Evidence records   : {len(result.evidence_records)}")
        print(f"Explanation by     : {result.explanation.get('generated_by')}")
        print(f"All reason codes   : {result.all_reason_codes}")
        print("-" * 70)
        status = "PASS" if result.scenario_passed else "FAIL"
        print(f"Scenario: {status}")
        for reason in result.failure_reasons:
            print(f"  ✗ {reason}")

    # Write report
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "disruption_id": result.disruption_id,
                "affected_shipment_ids": result.affected_shipment_ids,
                "cargo_value_at_risk_usd": result.cargo_value_at_risk_usd,
                "impact_reason_codes": result.impact_reason_codes,
                "cold_chain_severity": result.cold_chain_severity,
                "cold_chain_reason_codes": result.cold_chain_reason_codes,
                "cold_chain_duration_minutes": result.cold_chain_duration_minutes,
                "cold_chain_max_celsius": result.cold_chain_max_celsius,
                "feasible_alternatives_count": len(result.feasible_alternatives),
                "rejected_alternatives_count": len(result.rejected_alternatives),
                "idle_compatible_assets": result.idle_compatible_assets,
                "evidence_record_count": len(result.evidence_records),
                "explanation_generated_by": result.explanation.get("generated_by"),
                "all_reason_codes": result.all_reason_codes,
                "scenario_passed": result.scenario_passed,
                "failure_reasons": result.failure_reasons,
                "action_plan_json": result.action_plan_json,
                "action_plan_markdown": result.action_plan_markdown,
            },
            indent=2,
            default=str,
        )
    )

    if not args.quiet:
        print(f"Report written to {report_path}")

    return 0 if result.scenario_passed else 1


if __name__ == "__main__":
    sys.exit(main())
