// Task 12 — End-to-End Frontend Flow Verification
// Verifies full user journey across all screens:
// Disruption -> Shipment Detail -> Cold Chain -> Idle Assets -> Action Plan

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "../App";
import {
  ACTION_PLAN_RESPONSE,
  COLD_CHAIN_RESPONSE,
  DISRUPTION_RESPONSE,
  IDLE_ASSETS_RESPONSE,
  SHIPMENT_RESPONSE,
} from "./fixtures";
import { DisruptionOverview } from "../components/DisruptionOverview";
import { ShipmentDetail } from "../components/ShipmentDetail";
import { ColdChainTimeline } from "../components/ColdChainTimeline";
import { IdleAssets } from "../components/IdleAssets";
import { ActionPlan } from "../components/ActionPlan";

describe("Task 12 — End-to-End Frontend Flow Verification", () => {
  it("renders the main app shell with all 5 navigation screens", () => {
    render(<App />);
    expect(screen.getByText(/ChainShield/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Disruption Overview/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Shipment Detail/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cold-Chain Timeline/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Idle Assets/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Action Plan/i })).toBeInTheDocument();
  });

  it("navigates through all screens seamlessly", () => {
    render(<App />);

    // Screen 1: Disruption Overview
    expect(screen.getByRole("heading", { name: /^Disruption Overview$/i })).toBeInTheDocument();

    // Screen 2: Shipment Detail
    fireEvent.click(screen.getByRole("button", { name: /^Shipment Detail$/i }));
    expect(screen.getByRole("heading", { name: /^Shipment Detail$/i })).toBeInTheDocument();

    // Screen 3: Cold-Chain Timeline
    fireEvent.click(screen.getByRole("button", { name: /^Cold-Chain Timeline$/i }));
    expect(screen.getByRole("heading", { name: /^Cold-Chain Timeline$/i })).toBeInTheDocument();

    // Screen 4: Idle Assets
    fireEvent.click(screen.getByRole("button", { name: /^Idle Assets$/i }));
    expect(screen.getByRole("heading", { name: /^Idle Assets$/i })).toBeInTheDocument();

    // Screen 5: Action Plan
    fireEvent.click(screen.getByRole("button", { name: /^Action Plan$/i }));
    expect(screen.getByRole("heading", { name: /^Action Plan$/i })).toBeInTheDocument();
  });

  it("verifies DisruptionOverview consumes and renders disruption data", () => {
    render(<DisruptionOverview initialData={DISRUPTION_RESPONSE} />);
    expect(screen.getByText("PORT_STRIKE_01")).toBeInTheDocument();
    expect(screen.getByText(/520,000/)).toBeInTheDocument();
    expect(screen.getByText("SHP-0042")).toBeInTheDocument();
    expect(screen.getByText("PORT_NODE_BLOCKED")).toBeInTheDocument();
  });

  it("verifies ShipmentDetail consumes and displays cargo value and reason codes", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByText("SHP-0042")).toBeInTheDocument();
    expect(screen.getByText(/520,000/)).toBeInTheDocument();
    expect(screen.getByText("PORT_NODE_BLOCKED")).toBeInTheDocument();
    expect(screen.getByText("POL-CDC-01")).toBeInTheDocument();
  });

  it("verifies ColdChainTimeline displays EXCURSION_REVIEW and readings", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getByTestId("severity-badge")).toHaveTextContent("EXCURSION_REVIEW");
    expect(screen.getByText(/18 min/i)).toBeInTheDocument();
    expect(screen.getAllByText(/10\.4/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("SENSOR-9").length).toBeGreaterThan(0);
  });

  it("verifies IdleAssets displays reefer-capable available assets", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getByText("TRUCK-17")).toBeInTheDocument();
    expect(screen.getByText(/12,000 kg/i)).toBeInTheDocument();
    expect(screen.getByTestId("reefer-badge")).toHaveTextContent("Yes");
  });

  it("verifies ActionPlan displays alternatives, rejections, and evidence", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByText("PORT_STRIKE_01")).toBeInTheDocument();
    expect(screen.getByText(/520,000/)).toBeInTheDocument();
    expect(screen.getByText(/TRUCK-17/)).toBeInTheDocument();
    expect(screen.getAllByText("PORT_NODE_BLOCKED").length).toBeGreaterThan(0);
    expect(screen.getByText("ROUTE_INFEASIBLE")).toBeInTheDocument();
  });
});
