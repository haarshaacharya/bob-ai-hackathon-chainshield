// Test 2: ShipmentDetail rendering
// Verifies shipment fields, disruption status, and reason codes are shown.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ShipmentDetail } from "../components/ShipmentDetail";
import { SHIPMENT_RESPONSE } from "./fixtures";

describe("ShipmentDetail", () => {
  it("renders shipment detail panel", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByTestId("shipment-detail")).toBeInTheDocument();
  });

  it("shows the shipment ID", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByText("SHP-0042")).toBeInTheDocument();
  });

  it("shows the shipment status", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByTestId("shipment-status")).toHaveTextContent("IN_TRANSIT");
  });

  it("shows origin and destination", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByText(/HUB-A.*HUB-D/)).toBeInTheDocument();
  });

  it("shows disruption reason codes", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    const badges = screen.getAllByTestId("reason-code-badge");
    const texts = badges.map((b) => b.textContent);
    expect(texts).toContain("PORT_NODE_BLOCKED");
    expect(texts).toContain("ETA_SLA_BREACH");
  });

  it("shows the cargo value", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByText(/520,000/)).toBeInTheDocument();
  });

  it("shows the temperature policy", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByText("POL-CDC-01")).toBeInTheDocument();
  });

  it("shows Generate Explanation button", () => {
    render(<ShipmentDetail initialData={SHIPMENT_RESPONSE} />);
    expect(screen.getByText(/Generate Explanation/i)).toBeInTheDocument();
  });

  it("shows empty state when no data", () => {
    render(<ShipmentDetail />);
    expect(screen.getByText(/Enter a shipment ID/i)).toBeInTheDocument();
  });
});
