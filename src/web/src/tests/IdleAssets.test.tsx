// Test 4: IdleAssets rendering
// Verifies each asset card shows reefer capability, mode, capacity, status.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IdleAssets } from "../components/IdleAssets";
import { IDLE_ASSETS_RESPONSE } from "./fixtures";

describe("IdleAssets", () => {
  it("renders idle assets panel", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getByTestId("idle-assets")).toBeInTheDocument();
  });

  it("shows one asset card per asset", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getAllByTestId("asset-card")).toHaveLength(1);
  });

  it("shows the asset ID", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getByText("TRUCK-17")).toBeInTheDocument();
  });

  it("shows reefer capability badge", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getByTestId("reefer-badge")).toHaveTextContent("Yes");
  });

  it("shows asset mode", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getByText("road")).toBeInTheDocument();
  });

  it("shows asset capacity", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getByText(/12,000 kg/)).toBeInTheDocument();
  });

  it("shows asset status badge", () => {
    render(<IdleAssets initialData={IDLE_ASSETS_RESPONSE} />);
    expect(screen.getByTestId("asset-status")).toHaveTextContent("AVAILABLE");
  });

  it("shows empty state when count is zero", () => {
    render(<IdleAssets initialData={{ assets: [], count: 0 }} />);
    expect(screen.getByText(/No idle assets available/i)).toBeInTheDocument();
  });

  it("shows refresh button when no data", () => {
    render(<IdleAssets />);
    expect(screen.getByText(/Refresh/i)).toBeInTheDocument();
  });
});
