from __future__ import annotations

"""
ChainShield FastAPI application — deterministic API layer.

All six required endpoints are implemented here.  Business logic lives in
the engine modules; this file is deliberately thin.

Endpoint summary
----------------
POST /api/v1/disruptions/activate
    Activate a disruption scenario, run the Impact Engine against all known
    shipments, persist evidence records, and return affected shipment IDs.

GET /api/v1/shipments/{shipment_id}
    Return a single shipment record enriched with any impact metadata.

GET /api/v1/assets/idle
    Return all assets whose status is AVAILABLE.

GET /api/v1/cold-chain/{shipment_id}/timeline
    Run the Cold Chain Engine against sensor readings for a shipment and
    return the full severity timeline.

POST /api/v1/explanations/generate
    Generate a deterministic fallback explanation from structured decision
    data.  watsonx.ai is never used for operational decisions.

POST /api/v1/action-plan/export
    Export an action plan (affected shipments + route alternatives +
    cold-chain status) as structured JSON or Markdown.

Design constraints
------------------
- Operational decisions are always deterministic.
- watsonx.ai is optional (WATSONX_ENABLED env var) and never generates
  operational outputs.
- Core API works offline with no external credentials.
- reason_codes and evidence are returned on every relevant response.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from typing import Annotated, Any

import networkx as nx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from chainshield.logging import (
    EVENT_ACTION_PLAN_EXPORT,
    EVENT_API_ERROR,
    EVENT_APP_STARTUP,
    EVENT_COLD_CHAIN_EVALUATION,
    EVENT_DISRUPTION_ACTIVATION,
    get_logger,
    log_event,
    setup_logging,
)

_logger = get_logger("api")


from chainshield.api.dependencies import (
    get_active_disruptions,
    get_app_config,
    get_assets,
    get_cold_chain_engine,
    get_evidence_store,
    get_graph,
    get_impact_engine,
    get_optimization_engine,
    get_policies,
    get_sensor_readings,
    get_shipments,
)
from chainshield.config import ChainShieldConfig
from chainshield.evidence.events import (
    ColdChainEvidence,
    DecisionType,
    ImpactAnalysisEvidence,
)
from chainshield.explanation import (
    generate_explanation_with_fallback,
    generate_fallback_explanation,
)
from chainshield.models.asset import Asset, AssetStatus
from chainshield.models.disruption import (
    Disruption,
    DisruptionGeometry,
    DisruptionSeverity,
    DisruptionStatus,
    DisruptionType,
)
from chainshield.models.shipment import Shipment

# ---------------------------------------------------------------------------
# Lifespan & App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = get_app_config()
    log_event(
        _logger,
        logging.INFO,
        EVENT_APP_STARTUP,
        "ChainShield API application started",
        extra={
            "demo_mode": cfg.demo_mode,
            "offline": cfg.is_offline,
            "watsonx_enabled": cfg.watsonx_enabled,
        },
    )
    yield


app = FastAPI(
    title="ChainShield API",
    description="Explainable Supply-Chain Resilience Copilot — deterministic core.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Exception Handlers (API Error Logging)
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    log_event(
        _logger,
        logging.WARNING if exc.status_code < 500 else logging.ERROR,
        EVENT_API_ERROR,
        f"HTTP {exc.status_code} error on {request.method} {request.url.path}: {exc.detail}",
        extra={
            "status_code": exc.status_code,
            "path": str(request.url.path),
            "method": request.method,
        },
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log_event(
        _logger,
        logging.ERROR,
        EVENT_API_ERROR,
        f"Unhandled error on {request.method} {request.url.path}: {exc}",
        extra={
            "status_code": 500,
            "path": str(request.url.path),
            "method": request.method,
        },
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Health / Offline Status Endpoint
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    demo_mode: bool
    watsonx_enabled: bool
    network_required: bool
    offline: bool


@app.get("/health", response_model=HealthResponse, summary="Health and offline status.")
@app.get("/api/v1/health", response_model=HealthResponse, summary="Health and offline status.")
def get_health(
    config: Annotated[ChainShieldConfig, Depends(get_app_config)],
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        demo_mode=config.demo_mode,
        watsonx_enabled=config.watsonx_enabled,
        network_required=config.network_required,
        offline=config.is_offline,
    )


# ---------------------------------------------------------------------------
# Request / Response schemas (Pydantic)
# ---------------------------------------------------------------------------

class DisruptionActivateRequest(BaseModel):
    disruption_id: str = Field(..., min_length=1)
    disruption_type: str = Field("port_strike")
    severity: str = Field("HIGH")
    title: str = Field("")
    description: str = Field("")
    window_start: datetime
    window_end: datetime
    blocked_nodes: list[str] = Field(default_factory=list)
    blocked_edges: list[str] = Field(default_factory=list)


class DisruptionActivateResponse(BaseModel):
    disruption_id: str
    affected_shipment_ids: list[str]
    affected_shipment_count: int
    cargo_value_at_risk_usd: float
    reason_codes: list[str]
    evidence: list[dict[str, Any]]


class ShipmentResponse(BaseModel):
    shipment_id: str
    status: str
    is_disrupted: bool
    disruption_ids: list[str]
    reason_codes: list[str]
    cargo_value_usd: float
    weight_kg: float
    origin_hub_id: str
    destination_hub_id: str
    planned_departure: datetime
    planned_arrival: datetime
    delivery_deadline: datetime
    mode: str
    carrier_id: str | None
    temperature_policy_id: str | None


class AssetResponse(BaseModel):
    asset_id: str
    asset_type: str
    mode: str
    carrier_id: str | None
    current_node_id: str
    capacity_kg: float
    reefer_capable: bool
    status: str
    available_at: datetime


class IdleAssetsResponse(BaseModel):
    assets: list[AssetResponse]
    count: int


class SensorReadingOut(BaseModel):
    sensor_id: str
    ts: datetime
    temperature_c: float
    battery_pct: float


class ColdChainTimelineResponse(BaseModel):
    shipment_id: str
    severity: str
    reason_codes: list[str]
    min_temp_c: float | None
    max_temp_c: float | None
    total_out_of_range_minutes: float
    max_continuous_excursion_minutes: float
    out_of_range_count: int
    reading_count: int
    readings: list[SensorReadingOut]
    policy_id: str | None
    evidence: dict[str, Any]


class ExplanationRequest(BaseModel):
    shipment_id: str = Field(..., min_length=1)
    disruption: str = Field("", description="Disruption identifier or label.")
    kind: str = Field("impact", description="Decision kind: impact | routing | cold_chain")
    reason_codes: list[str] = Field(default_factory=list)
    recommended_route: dict[str, Any] = Field(default_factory=dict)
    cold_chain: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class ExplanationResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    summary: str
    why_affected: list[str]
    recommended_action: str
    evidence: list[str]
    uncertainties: list[str]
    generated_by: str
    model_used: str | None
    watsonx_enabled: bool


class ActionPlanExportRequest(BaseModel):
    disruption_id: str = Field(..., min_length=1)
    format: str = Field("json", description="Output format: json | markdown")


class RouteAlternativeOut(BaseModel):
    alternative_id: str
    asset_id: str
    carrier_id: str | None
    path: list[str]
    mode: str
    total_cost_usd: float
    eta_delta_hours: float
    is_feasible: bool
    reason_codes: list[str]
    rank: int


class ActionPlanShipmentEntry(BaseModel):
    shipment_id: str
    reason_codes: list[str]
    cargo_value_usd: float
    cold_chain_severity: str | None
    route_alternatives: list[RouteAlternativeOut]
    rejection_reason_codes: list[str]


class ActionPlanExportResponse(BaseModel):
    disruption_id: str
    generated_at: datetime
    format: str
    shipments: list[ActionPlanShipmentEntry]
    markdown: str | None


# ---------------------------------------------------------------------------
# Helper — resolve disruption type / severity enums safely
# ---------------------------------------------------------------------------

def _parse_disruption_type(value: str) -> DisruptionType:
    try:
        return DisruptionType(value)
    except ValueError:
        return DisruptionType.OTHER


def _parse_disruption_severity(value: str) -> DisruptionSeverity:
    try:
        return DisruptionSeverity(value.upper())
    except ValueError:
        return DisruptionSeverity.HIGH


# ---------------------------------------------------------------------------
# POST /api/v1/disruptions/activate
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/disruptions/activate",
    response_model=DisruptionActivateResponse,
    summary="Activate a disruption and run the Impact Engine.",
)
def activate_disruption(
    body: DisruptionActivateRequest,
    shipments: Annotated[dict[str, Shipment], Depends(get_shipments)],
    impact_engine: Annotated[object, Depends(get_impact_engine)],
    evidence_store: Annotated[object, Depends(get_evidence_store)],
    active_disruptions: Annotated[list[Disruption], Depends(get_active_disruptions)],
) -> DisruptionActivateResponse:
    disruption = Disruption(
        disruption_id=body.disruption_id,
        disruption_type=_parse_disruption_type(body.disruption_type),
        severity=_parse_disruption_severity(body.severity),
        status=DisruptionStatus.ACTIVE,
        title=body.title,
        description=body.description,
        window_start=body.window_start,
        window_end=body.window_end,
        geometry=DisruptionGeometry(
            blocked_nodes=body.blocked_nodes,
            blocked_edges=body.blocked_edges,
        ),
    )

    shipment_list = list(shipments.values())
    results = impact_engine.evaluate_many(shipment_list, disruption)

    affected_ids: list[str] = []
    all_reason_codes: list[str] = []
    cargo_at_risk = 0.0
    evidence_records: list[dict[str, Any]] = []

    for result in results:
        if not result.is_affected:
            continue
        affected_ids.append(result.shipment_id)
        for code in result.reason_codes:
            if code not in all_reason_codes:
                all_reason_codes.append(code)
        cargo_at_risk += result.cargo_value_at_risk_usd

        record = ImpactAnalysisEvidence(
            decision_type=DecisionType.IMPACT_ANALYSIS,
            shipment_id=result.shipment_id,
            reason_codes=result.reason_codes,
            source_refs={
                "disruption_id": disruption.disruption_id,
                "node_hits": result.node_hits,
                "edge_hits": result.edge_hits,
            },
            disruption_ids=[disruption.disruption_id],
            affected_node_ids=result.node_hits,
        )
        evidence_store.add(record)
        evidence_records.append(record.to_dict())

    log_event(
        _logger,
        logging.INFO,
        EVENT_DISRUPTION_ACTIVATION,
        f"Disruption {disruption.disruption_id} activated ({len(affected_ids)} affected)",
        disruption_id=disruption.disruption_id,
        reason_codes=all_reason_codes,
        extra={
            "affected_count": len(affected_ids),
            "cargo_value_at_risk_usd": cargo_at_risk,
        },
    )

    return DisruptionActivateResponse(
        disruption_id=disruption.disruption_id,
        affected_shipment_ids=affected_ids,
        affected_shipment_count=len(affected_ids),
        cargo_value_at_risk_usd=cargo_at_risk,
        reason_codes=all_reason_codes,
        evidence=evidence_records,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/shipments/{shipment_id}
# ---------------------------------------------------------------------------

@app.get(
    "/api/v1/shipments/{shipment_id}",
    response_model=ShipmentResponse,
    summary="Return shipment detail with impact metadata.",
)
def get_shipment(
    shipment_id: str,
    shipments: Annotated[dict[str, Shipment], Depends(get_shipments)],
) -> ShipmentResponse:
    shp = shipments.get(shipment_id)
    if shp is None:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")
    return ShipmentResponse(
        shipment_id=shp.shipment_id,
        status=shp.status.value,
        is_disrupted=shp.is_disrupted,
        disruption_ids=shp.disruption_ids,
        reason_codes=shp.reason_codes,
        cargo_value_usd=shp.cargo_value_usd,
        weight_kg=shp.weight_kg,
        origin_hub_id=shp.origin_hub_id,
        destination_hub_id=shp.destination_hub_id,
        planned_departure=shp.planned_departure,
        planned_arrival=shp.planned_arrival,
        delivery_deadline=shp.delivery_deadline,
        mode=shp.mode.value,
        carrier_id=shp.carrier_id,
        temperature_policy_id=shp.temperature_policy_id,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/assets/idle
# ---------------------------------------------------------------------------

@app.get(
    "/api/v1/assets/idle",
    response_model=IdleAssetsResponse,
    summary="Return all idle (AVAILABLE) assets.",
)
def get_idle_assets(
    assets: Annotated[list[Asset], Depends(get_assets)],
) -> IdleAssetsResponse:
    idle = [a for a in assets if a.status == AssetStatus.AVAILABLE]
    return IdleAssetsResponse(
        assets=[
            AssetResponse(
                asset_id=a.asset_id,
                asset_type=a.asset_type.value,
                mode=a.mode.value,
                carrier_id=a.carrier_id,
                current_node_id=a.current_node_id,
                capacity_kg=a.capacity_kg,
                reefer_capable=a.reefer_capable,
                status=a.status.value,
                available_at=a.available_at,
            )
            for a in idle
        ],
        count=len(idle),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/cold-chain/{shipment_id}/timeline
# ---------------------------------------------------------------------------

@app.get(
    "/api/v1/cold-chain/{shipment_id}/timeline",
    response_model=ColdChainTimelineResponse,
    summary="Cold-chain severity timeline for a shipment.",
)
def cold_chain_timeline(
    shipment_id: str,
    shipments: Annotated[dict[str, Shipment], Depends(get_shipments)],
    sensor_readings: Annotated[dict[str, list], Depends(get_sensor_readings)],
    policies: Annotated[dict, Depends(get_policies)],
    cold_chain_engine: Annotated[object, Depends(get_cold_chain_engine)],
    evidence_store: Annotated[object, Depends(get_evidence_store)],
) -> ColdChainTimelineResponse:
    shp = shipments.get(shipment_id)
    if shp is None:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

    readings = sensor_readings.get(shipment_id, [])
    policy = policies.get(shp.temperature_policy_id) if shp.temperature_policy_id else None

    result = cold_chain_engine.evaluate(policy, readings)

    # Persist evidence
    cc_record = ColdChainEvidence(
        decision_type=DecisionType.COLD_CHAIN_CLASSIFICATION,
        shipment_id=shipment_id,
        reason_codes=result.reason_codes,
        source_refs={"policy_id": shp.temperature_policy_id},
        policy_id=shp.temperature_policy_id or "",
        severity=result.severity.value,
        out_of_range_readings=result.out_of_range_count,
        duration_minutes=result.total_out_of_range_minutes,
        max_celsius=result.max_temp_c,
        min_celsius=result.min_temp_c,
    )
    evidence_store.add(cc_record)

    log_event(
        _logger,
        logging.INFO,
        EVENT_COLD_CHAIN_EVALUATION,
        f"Cold-chain timeline fetched for {shipment_id}: {result.severity.value}",
        shipment_id=shipment_id,
        decision_type="cold_chain_policy",
        reason_codes=result.reason_codes,
        extra={"severity": result.severity.value},
    )

    return ColdChainTimelineResponse(
        shipment_id=shipment_id,
        severity=result.severity.value,
        reason_codes=result.reason_codes,
        min_temp_c=result.min_temp_c,
        max_temp_c=result.max_temp_c,
        total_out_of_range_minutes=result.total_out_of_range_minutes,
        max_continuous_excursion_minutes=result.max_continuous_excursion_minutes,
        out_of_range_count=result.out_of_range_count,
        reading_count=result.reading_count,
        readings=[
            SensorReadingOut(
                sensor_id=r.sensor_id,
                ts=r.ts,
                temperature_c=r.temperature_c,
                battery_pct=r.battery_pct,
            )
            for r in readings
        ],
        policy_id=shp.temperature_policy_id,
        evidence=cc_record.to_dict(),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/explanations/generate
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/explanations/generate",
    response_model=ExplanationResponse,
    summary="Generate a deterministic fallback explanation.",
)
def generate_explanation(
    body: ExplanationRequest,
    shipments: Annotated[dict[str, Shipment], Depends(get_shipments)],
    config: Annotated[ChainShieldConfig, Depends(get_app_config)],
) -> ExplanationResponse:
    if body.shipment_id not in shipments:
        raise HTTPException(status_code=404, detail=f"Shipment '{body.shipment_id}' not found.")

    decision: dict[str, Any] = {
        "kind": body.kind,
        "shipment_id": body.shipment_id,
        "disruption": body.disruption,
        "reason_codes": body.reason_codes,
        "recommended_route": body.recommended_route,
        "cold_chain": body.cold_chain,
        "evidence": body.evidence,
    }

    # watsonx.ai is optional and guarded with timeout + deterministic fallback.
    explanation = generate_explanation_with_fallback(decision, config=config)

    return ExplanationResponse(
        summary=explanation["summary"],
        why_affected=explanation["why_affected"],
        recommended_action=explanation["recommended_action"],
        evidence=explanation["evidence"],
        uncertainties=explanation["uncertainties"],
        generated_by=explanation["generated_by"],
        model_used=explanation.get("model_used"),
        watsonx_enabled=config.watsonx_enabled,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/action-plan/export
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/action-plan/export",
    response_model=ActionPlanExportResponse,
    summary="Export a structured action plan for a disruption.",
)
def export_action_plan(
    body: ActionPlanExportRequest,
    shipments: Annotated[dict[str, Shipment], Depends(get_shipments)],
    assets: Annotated[list[Asset], Depends(get_assets)],
    sensor_readings: Annotated[dict, Depends(get_sensor_readings)],
    policies: Annotated[dict, Depends(get_policies)],
    cold_chain_engine: Annotated[object, Depends(get_cold_chain_engine)],
    optimization_engine: Annotated[object, Depends(get_optimization_engine)],
    evidence_store: Annotated[object, Depends(get_evidence_store)],
) -> ActionPlanExportResponse:
    # Collect all impacted shipments from evidence store
    impact_records = evidence_store.for_disruption(body.disruption_id)
    affected_ids = [r.shipment_id for r in impact_records]

    # If no evidence records exist yet for this disruption, include all disrupted shipments
    if not affected_ids:
        affected_ids = [
            sid for sid, shp in shipments.items()
            if body.disruption_id in shp.disruption_ids or shp.is_disrupted
        ]

    # Reconstruct disruption stub for the optimisation engine (blocked nodes from evidence)
    blocked: list[str] = []
    for rec in impact_records:
        blocked.extend(rec.source_refs.get("node_hits", []))

    plan_entries: list[ActionPlanShipmentEntry] = []

    for shipment_id in affected_ids:
        shp = shipments.get(shipment_id)
        if shp is None:
            continue

        # Cold-chain status
        readings = sensor_readings.get(shipment_id, [])
        policy = policies.get(shp.temperature_policy_id) if shp.temperature_policy_id else None
        cc_result = cold_chain_engine.evaluate(policy, readings)

        # Route alternatives
        idle_assets = [a for a in assets if a.status == AssetStatus.AVAILABLE]
        opt_result = optimization_engine.find_alternatives(shp, idle_assets)

        feasible_alts = [
            RouteAlternativeOut(
                alternative_id=a.alternative_id,
                asset_id=a.asset_id,
                carrier_id=a.carrier_id,
                path=a.path,
                mode=a.mode,
                total_cost_usd=a.total_cost_usd,
                eta_delta_hours=a.eta_delta_hours,
                is_feasible=a.is_feasible,
                reason_codes=a.reason_codes,
                rank=a.rank,
            )
            for a in opt_result.alternatives
            if a.is_feasible
        ]

        # Fetch reason codes from evidence records for this shipment
        impact_codes = shp.reason_codes or [
            code
            for rec in evidence_store.for_shipment(shipment_id)
            if rec.decision_type == DecisionType.IMPACT_ANALYSIS
            for code in rec.reason_codes
        ]

        plan_entries.append(
            ActionPlanShipmentEntry(
                shipment_id=shipment_id,
                reason_codes=list(dict.fromkeys(impact_codes)),  # stable dedup
                cargo_value_usd=shp.cargo_value_usd,
                cold_chain_severity=cc_result.severity.value if shp.temperature_policy_id else None,
                route_alternatives=feasible_alts,
                rejection_reason_codes=opt_result.rejection_reason_codes,
            )
        )

    generated_at = datetime.now(timezone.utc)

    if body.format == "markdown":
        md_lines: list[str] = [
            f"# Action Plan — Disruption {body.disruption_id}",
            f"_Generated at {generated_at.isoformat()}_",
            "",
        ]
        for entry in plan_entries:
            md_lines.append(f"## Shipment {entry.shipment_id}")
            md_lines.append(f"- **Reason codes:** {', '.join(entry.reason_codes) or 'none'}")
            md_lines.append(f"- **Cargo value at risk:** ${entry.cargo_value_usd:,.0f}")
            if entry.cold_chain_severity:
                md_lines.append(f"- **Cold-chain severity:** {entry.cold_chain_severity}")
            if entry.route_alternatives:
                md_lines.append("### Feasible route alternatives")
                for alt in entry.route_alternatives:
                    md_lines.append(
                        f"  {alt.rank}. {alt.asset_id} via {' → '.join(alt.path)} "
                        f"(+{alt.eta_delta_hours:.1f}h, ${alt.total_cost_usd:,.0f})"
                    )
            else:
                md_lines.append(
                    f"- **No feasible alternatives** — {', '.join(entry.rejection_reason_codes) or 'N/A'}"
                )
            md_lines.append("")
        markdown_out: str | None = "\n".join(md_lines)
    else:
        markdown_out = None

    log_event(
        _logger,
        logging.INFO,
        EVENT_ACTION_PLAN_EXPORT,
        f"Action plan exported for disruption {body.disruption_id} ({body.format})",
        disruption_id=body.disruption_id,
        extra={"format": body.format, "shipment_count": len(plan_entries)},
    )

    return ActionPlanExportResponse(
        disruption_id=body.disruption_id,
        generated_at=generated_at,
        format=body.format,
        shipments=plan_entries,
        markdown=markdown_out,
    )
