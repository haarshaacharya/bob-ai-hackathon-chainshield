// Test 3: ColdChainTimeline rendering
// Verifies severity, readings table, sparkline, and evidence are displayed.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ColdChainTimeline } from "../components/ColdChainTimeline";
import { COLD_CHAIN_RESPONSE } from "./fixtures";

describe("ColdChainTimeline", () => {
  it("renders cold-chain timeline panel", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getByTestId("cold-chain-timeline")).toBeInTheDocument();
  });

  it("shows the correct severity badge", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getByTestId("severity-badge")).toHaveTextContent("EXCURSION_REVIEW");
  });

  it("shows out-of-range reading count", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    // "3 of 5"
    expect(screen.getByText(/3 of 5/)).toBeInTheDocument();
  });

  it("shows total out-of-range duration", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getByText(/18 min/)).toBeInTheDocument();
  });

  it("renders a row for each sensor reading", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    const rows = screen.getAllByTestId("reading-row");
    expect(rows).toHaveLength(5);
  });

  it("renders the temperature sparkline SVG", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getByTestId("temperature-sparkline")).toBeInTheDocument();
  });

  it("shows the reason codes", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getByTestId("reason-code-badge")).toHaveTextContent("TEMPERATURE_EXPOSURE_INCREASED");
  });

  it("shows the policy ID", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getAllByText("POL-CDC-01").length).toBeGreaterThan(0);
  });

  it("shows evidence list", () => {
    render(<ColdChainTimeline initialData={COLD_CHAIN_RESPONSE} />);
    expect(screen.getByTestId("evidence-list")).toBeInTheDocument();
  });

  it("shows empty state when no data", () => {
    render(<ColdChainTimeline />);
    expect(screen.getByText(/Enter a shipment ID/i)).toBeInTheDocument();
  });
});
