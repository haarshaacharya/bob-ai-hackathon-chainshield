// Test 5: ActionPlan rendering
// Verifies route alternatives, rejection reasons, evidence links are displayed.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ActionPlan } from "../components/ActionPlan";
import { ACTION_PLAN_RESPONSE } from "./fixtures";

describe("ActionPlan", () => {
  it("renders action plan panel", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByTestId("action-plan")).toBeInTheDocument();
  });

  it("shows the disruption ID", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getAllByText("PORT_STRIKE_01").length).toBeGreaterThan(0);
  });

  it("shows the affected shipment entry", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByText(/Shipment SHP-0042/i)).toBeInTheDocument();
  });

  it("shows cargo value at risk", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByText(/520,000/)).toBeInTheDocument();
  });

  it("shows cold-chain severity badge", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByTestId("severity-badge")).toHaveTextContent("EXCURSION_REVIEW");
  });

  it("shows the route alternative card", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByTestId("route-alternative")).toBeInTheDocument();
  });

  it("shows asset ID in the route alternative", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByText(/TRUCK-17/)).toBeInTheDocument();
  });

  it("shows ETA delta", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByText(/\+5\.4 h/)).toBeInTheDocument();
  });

  it("shows reason codes for the shipment", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    const badges = screen.getAllByTestId("reason-code-badge");
    const texts = badges.map((b) => b.textContent);
    expect(texts).toContain("PORT_NODE_BLOCKED");
  });

  it("shows rejection reason codes", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    const badges = screen.getAllByTestId("reason-code-badge");
    const texts = badges.map((b) => b.textContent);
    expect(texts).toContain("ROUTE_INFEASIBLE");
  });

  it("shows evidence links section", () => {
    render(<ActionPlan initialData={ACTION_PLAN_RESPONSE} />);
    expect(screen.getByTestId("evidence-list")).toBeInTheDocument();
  });

  it("shows empty state when no data", () => {
    render(<ActionPlan />);
    expect(screen.getByText(/Enter a disruption ID/i)).toBeInTheDocument();
  });
});
