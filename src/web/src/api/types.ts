// ---------------------------------------------------------------------------
// ChainShield API — TypeScript type definitions
// Mirrors the Pydantic response schemas in src/chainshield/api/main.py
// ---------------------------------------------------------------------------

// --- Disruption ---

export interface DisruptionActivateRequest {
  disruption_id: string;
  disruption_type?: string;
  severity?: string;
  title?: string;
  description?: string;
  window_start: string; // ISO datetime
  window_end: string; // ISO datetime
  blocked_nodes?: string[];
  blocked_edges?: string[];
}

export interface DisruptionActivateResponse {
  disruption_id: string;
  affected_shipment_ids: string[];
  affected_shipment_count: number;
  cargo_value_at_risk_usd: number;
  reason_codes: string[];
  evidence: Record<string, unknown>[];
}

// --- Shipment ---

export interface ShipmentResponse {
  shipment_id: string;
  status: string;
  is_disrupted: boolean;
  disruption_ids: string[];
  reason_codes: string[];
  cargo_value_usd: number;
  weight_kg: number;
  origin_hub_id: string;
  destination_hub_id: string;
  planned_departure: string;
  planned_arrival: string;
  delivery_deadline: string;
  mode: string;
  carrier_id: string | null;
  temperature_policy_id: string | null;
}

// --- Assets ---

export interface AssetResponse {
  asset_id: string;
  asset_type: string;
  mode: string;
  carrier_id: string | null;
  current_node_id: string;
  capacity_kg: number;
  reefer_capable: boolean;
  status: string;
  available_at: string;
}

export interface IdleAssetsResponse {
  assets: AssetResponse[];
  count: number;
}

// --- Cold chain ---

export interface SensorReadingOut {
  sensor_id: string;
  ts: string;
  temperature_c: number;
  battery_pct: number;
}

export interface ColdChainTimelineResponse {
  shipment_id: string;
  severity: string;
  reason_codes: string[];
  min_temp_c: number | null;
  max_temp_c: number | null;
  total_out_of_range_minutes: number;
  max_continuous_excursion_minutes: number;
  out_of_range_count: number;
  reading_count: number;
  readings: SensorReadingOut[];
  policy_id: string | null;
  evidence: Record<string, unknown>;
}

// --- Explanation ---

export interface ExplanationRequest {
  shipment_id: string;
  disruption?: string;
  kind?: string;
  reason_codes?: string[];
  recommended_route?: Record<string, unknown>;
  cold_chain?: Record<string, unknown>;
  evidence?: string[];
}

export interface ExplanationResponse {
  summary: string;
  why_affected: string[];
  recommended_action: string;
  evidence: string[];
  uncertainties: string[];
  generated_by: string;
  model_used: string | null;
  watsonx_enabled: boolean;
}

// --- Action plan ---

export interface ActionPlanExportRequest {
  disruption_id: string;
  format?: "json" | "markdown";
}

export interface RouteAlternativeOut {
  alternative_id: string;
  asset_id: string;
  carrier_id: string | null;
  path: string[];
  mode: string;
  total_cost_usd: number;
  eta_delta_hours: number;
  is_feasible: boolean;
  reason_codes: string[];
  rank: number;
}

export interface ActionPlanShipmentEntry {
  shipment_id: string;
  reason_codes: string[];
  cargo_value_usd: number;
  cold_chain_severity: string | null;
  route_alternatives: RouteAlternativeOut[];
  rejection_reason_codes: string[];
}

export interface ActionPlanExportResponse {
  disruption_id: string;
  generated_at: string;
  format: string;
  shipments: ActionPlanShipmentEntry[];
  markdown: string | null;
}

// --- Generic API error ---

export interface ApiError {
  detail: string;
}
