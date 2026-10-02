// Test 7: Empty states
// Verifies each component shows the appropriate empty state before any data loads.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ActionPlan } from "../components/ActionPlan";
import { ColdChainTimeline } from "../components/ColdChainTimeline";
import { DisruptionOverview } from "../components/DisruptionOverview";
import { IdleAssets } from "../components/IdleAssets";
import { ShipmentDetail } from "../components/ShipmentDetail";
import { IdleAssetsResponse, ActionPlanExportResponse, ColdChainTimelineResponse } from "../api/types";

describe("Empty states", () => {
  it("DisruptionOverview shows empty state with no data", () => {
    render(<DisruptionOverview />);
    expect(screen.getByText(/No active disruption/i)).toBeInTheDocument();
  });

  it("ShipmentDetail shows empty state with no data", () => {
    render(<ShipmentDetail />);
    expect(screen.getByText(/Enter a shipment ID/i)).toBeInTheDocument();
  });

  it("ColdChainTimeline shows empty state with no data", () => {
    render(<ColdChainTimeline />);
    expect(screen.getByText(/Enter a shipment ID/i)).toBeInTheDocument();
  });

  it("IdleAssets shows initial empty state with no data", () => {
    render(<IdleAssets />);
    expect(screen.getByText(/available assets/i)).toBeInTheDocument();
  });

  it("ActionPlan shows empty state with no data", () => {
    render(<ActionPlan />);
    expect(screen.getByText(/Enter a disruption ID/i)).toBeInTheDocument();
  });

  it("ColdChainTimeline shows no-readings empty state when readings array is empty", () => {
    const emptyReadingsData: ColdChainTimelineResponse = {
      shipment_id: "SHP-0099",
      severity: "URGENT_ESCALATION",
      reason_codes: [],
      min_temp_c: null,
      max_temp_c: null,
      total_out_of_range_minutes: 0,
      max_continuous_excursion_minutes: 0,
      out_of_range_count: 0,
      reading_count: 0,
      readings: [],
      policy_id: null,
      evidence: {},
    };
    render(<ColdChainTimeline initialData={emptyReadingsData} />);
    expect(screen.getByText(/No sensor readings/i)).toBeInTheDocument();
  });

  it("IdleAssets shows no-assets empty state when assets array is empty", () => {
    const emptyAssets: IdleAssetsResponse = { assets: [], count: 0 };
    render(<IdleAssets initialData={emptyAssets} />);
    expect(screen.getByText(/No idle assets available/i)).toBeInTheDocument();
  });

  it("ActionPlan shows no-shipments empty state when shipments array is empty", () => {
    const emptyPlan: ActionPlanExportResponse = {
      disruption_id: "UNKNOWN",
      generated_at: "2026-01-01T00:00:00Z",
      format: "json",
      shipments: [],
      markdown: null,
    };
    render(<ActionPlan initialData={emptyPlan} />);
    expect(screen.getByText(/No affected shipments/i)).toBeInTheDocument();
  });
});
