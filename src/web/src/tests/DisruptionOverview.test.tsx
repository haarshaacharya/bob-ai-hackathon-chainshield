// Test 1: DisruptionOverview rendering
// Verifies affected count, cargo value at risk, and reason codes are displayed.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DisruptionOverview } from "../components/DisruptionOverview";
import { DISRUPTION_RESPONSE } from "./fixtures";

describe("DisruptionOverview", () => {
  it("renders disruption overview with initial data", () => {
    render(<DisruptionOverview initialData={DISRUPTION_RESPONSE} />);
    expect(screen.getByTestId("disruption-overview")).toBeInTheDocument();
  });

  it("shows affected shipment count", () => {
    render(<DisruptionOverview initialData={DISRUPTION_RESPONSE} />);
    expect(screen.getByTestId("affected-count")).toHaveTextContent("1");
  });

  it("shows cargo value at risk", () => {
    render(<DisruptionOverview initialData={DISRUPTION_RESPONSE} />);
    // $520,000 formatted
    expect(screen.getByTestId("cargo-value")).toHaveTextContent("520,000");
  });

  it("shows all reason codes as badges", () => {
    render(<DisruptionOverview initialData={DISRUPTION_RESPONSE} />);
    const badges = screen.getAllByTestId("reason-code-badge");
    const texts = badges.map((b) => b.textContent);
    expect(texts).toContain("PORT_NODE_BLOCKED");
    expect(texts).toContain("ETA_SLA_BREACH");
  });

  it("shows disruption ID", () => {
    render(<DisruptionOverview initialData={DISRUPTION_RESPONSE} />);
    expect(screen.getByText("PORT_STRIKE_01")).toBeInTheDocument();
  });

  it("shows Activate button", () => {
    render(<DisruptionOverview />);
    expect(screen.getByText(/Activate PORT_STRIKE_01/i)).toBeInTheDocument();
  });

  it("shows empty state when no data", () => {
    render(<DisruptionOverview />);
    expect(screen.getByText(/No active disruption/i)).toBeInTheDocument();
  });
});
