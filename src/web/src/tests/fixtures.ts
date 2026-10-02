// Test fixtures shared across all frontend tests

import type {
  ActionPlanExportResponse,
  AssetResponse,
  ColdChainTimelineResponse,
  DisruptionActivateResponse,
  IdleAssetsResponse,
  ShipmentResponse,
} from "../api/types";

export const DISRUPTION_RESPONSE: DisruptionActivateResponse = {
  disruption_id: "PORT_STRIKE_01",
  affected_shipment_ids: ["SHP-0042"],
  affected_shipment_count: 1,
  cargo_value_at_risk_usd: 520000,
  reason_codes: ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
  evidence: [
    {
      decision_id: "abc-123",
      decision_type: "IMPACT_ANALYSIS",
      shipment_id: "SHP-0042",
      reason_codes: ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
      source_refs: { disruption_id: "PORT_STRIKE_01", node_hits: ["PORT-03"] },
    },
  ],
};

export const SHIPMENT_RESPONSE: ShipmentResponse = {
  shipment_id: "SHP-0042",
  status: "IN_TRANSIT",
  is_disrupted: true,
  disruption_ids: ["PORT_STRIKE_01"],
  reason_codes: ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
  cargo_value_usd: 520000,
  weight_kg: 8200,
  origin_hub_id: "HUB-A",
  destination_hub_id: "HUB-D",
  planned_departure: "2026-09-14T06:00:00Z",
  planned_arrival: "2026-09-16T14:00:00Z",
  delivery_deadline: "2026-09-16T18:00:00Z",
  mode: "sea",
  carrier_id: "CARRIER-A",
  temperature_policy_id: "POL-CDC-01",
};

export const COLD_CHAIN_RESPONSE: ColdChainTimelineResponse = {
  shipment_id: "SHP-0042",
  severity: "EXCURSION_REVIEW",
  reason_codes: ["TEMPERATURE_EXPOSURE_INCREASED"],
  min_temp_c: 6.4,
  max_temp_c: 10.4,
  total_out_of_range_minutes: 18,
  max_continuous_excursion_minutes: 18,
  out_of_range_count: 3,
  reading_count: 5,
  readings: [
    { sensor_id: "SENSOR-9", ts: "2026-09-14T08:00:00Z", temperature_c: 6.9, battery_pct: 91 },
    { sensor_id: "SENSOR-9", ts: "2026-09-14T08:06:00Z", temperature_c: 8.9, battery_pct: 91 },
    { sensor_id: "SENSOR-9", ts: "2026-09-14T08:12:00Z", temperature_c: 10.4, battery_pct: 91 },
    { sensor_id: "SENSOR-9", ts: "2026-09-14T08:18:00Z", temperature_c: 9.1, battery_pct: 91 },
    { sensor_id: "SENSOR-9", ts: "2026-09-14T08:24:00Z", temperature_c: 6.4, battery_pct: 91 },
  ],
  policy_id: "POL-CDC-01",
  evidence: {
    min_celsius: 2,
    max_celsius: 8,
    policy_id: "POL-CDC-01",
    out_of_range_readings: 3,
    duration_minutes: 18,
  },
};

export const ASSET_RESPONSE: AssetResponse = {
  asset_id: "TRUCK-17",
  asset_type: "truck",
  mode: "road",
  carrier_id: "CARRIER-B",
  current_node_id: "HUB-B",
  capacity_kg: 12000,
  reefer_capable: true,
  status: "available",
  available_at: "2026-09-14T09:25:00Z",
};

export const IDLE_ASSETS_RESPONSE: IdleAssetsResponse = {
  assets: [ASSET_RESPONSE],
  count: 1,
};

export const ACTION_PLAN_RESPONSE: ActionPlanExportResponse = {
  disruption_id: "PORT_STRIKE_01",
  generated_at: "2026-09-14T10:00:00Z",
  format: "json",
  shipments: [
    {
      shipment_id: "SHP-0042",
      reason_codes: ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
      cargo_value_usd: 520000,
      cold_chain_severity: "EXCURSION_REVIEW",
      route_alternatives: [
        {
          alternative_id: "alt-001",
          asset_id: "TRUCK-17",
          carrier_id: "CARRIER-B",
          path: ["HUB-A", "HUB-D"],
          mode: "road",
          total_cost_usd: 1800,
          eta_delta_hours: 5.4,
          is_feasible: true,
          reason_codes: ["CAPACITY_OK", "REEFER_CAPACITY_AVAILABLE"],
          rank: 1,
        },
      ],
      rejection_reason_codes: ["ROUTE_INFEASIBLE"],
    },
  ],
  markdown: null,
};
