// ---------------------------------------------------------------------------
// ChainShield API client
// All calls go to the local FastAPI backend.  No hardcoded operational data.
// Proxy is configured in vite.config.ts: /api → http://localhost:8000
// ---------------------------------------------------------------------------

import type {
  ActionPlanExportRequest,
  ActionPlanExportResponse,
  ColdChainTimelineResponse,
  DisruptionActivateRequest,
  DisruptionActivateResponse,
  ExplanationRequest,
  ExplanationResponse,
  IdleAssetsResponse,
  ShipmentResponse,
} from "./types";

const BASE = "/api/v1";

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch (_e) {
      // ignore JSON parse failure — keep the HTTP status message
    }
    console.error(`[ChainShield] API error: ${options?.method ?? "GET"} ${path} (${res.status} - ${detail})`);
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

// POST /api/v1/disruptions/activate
export function activateDisruption(
  body: DisruptionActivateRequest,
): Promise<DisruptionActivateResponse> {
  return apiFetch<DisruptionActivateResponse>("/disruptions/activate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// GET /api/v1/shipments/{shipment_id}
export function fetchShipment(shipmentId: string): Promise<ShipmentResponse> {
  return apiFetch<ShipmentResponse>(`/shipments/${encodeURIComponent(shipmentId)}`);
}

// GET /api/v1/assets/idle
export function fetchIdleAssets(): Promise<IdleAssetsResponse> {
  return apiFetch<IdleAssetsResponse>("/assets/idle");
}

// GET /api/v1/cold-chain/{shipment_id}/timeline
export function fetchColdChainTimeline(
  shipmentId: string,
): Promise<ColdChainTimelineResponse> {
  return apiFetch<ColdChainTimelineResponse>(
    `/cold-chain/${encodeURIComponent(shipmentId)}/timeline`,
  );
}

// POST /api/v1/explanations/generate
export function generateExplanation(
  body: ExplanationRequest,
): Promise<ExplanationResponse> {
  return apiFetch<ExplanationResponse>("/explanations/generate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// POST /api/v1/action-plan/export
export function exportActionPlan(
  body: ActionPlanExportRequest,
): Promise<ActionPlanExportResponse> {
  return apiFetch<ActionPlanExportResponse>("/action-plan/export", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
