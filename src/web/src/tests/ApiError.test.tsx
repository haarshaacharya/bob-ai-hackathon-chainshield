// Test 6: API error state
// Verifies each component shows the ErrorState with the correct message
// when the API returns an error (mocked via vi.mock).

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the entire API client module
vi.mock("../api/client", () => ({
  activateDisruption: vi.fn(),
  fetchShipment: vi.fn(),
  fetchIdleAssets: vi.fn(),
  fetchColdChainTimeline: vi.fn(),
  exportActionPlan: vi.fn(),
  generateExplanation: vi.fn(),
}));

import * as client from "../api/client";
import { ActionPlan } from "../components/ActionPlan";
import { ColdChainTimeline } from "../components/ColdChainTimeline";
import { DisruptionOverview } from "../components/DisruptionOverview";
import { IdleAssets } from "../components/IdleAssets";
import { ShipmentDetail } from "../components/ShipmentDetail";

const API_ERROR = new Error("Service unavailable");

beforeEach(() => {
  vi.resetAllMocks();
});

describe("API error states", () => {
  it("DisruptionOverview shows error on activation failure", async () => {
    vi.mocked(client.activateDisruption).mockRejectedValueOnce(API_ERROR);
    render(<DisruptionOverview />);
    await userEvent.click(screen.getByText(/Activate PORT_STRIKE_01/i));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable"),
    );
  });

  it("ShipmentDetail shows error on fetch failure", async () => {
    vi.mocked(client.fetchShipment).mockRejectedValueOnce(API_ERROR);
    render(<ShipmentDetail />);
    await userEvent.click(screen.getByText(/^Load$/i));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable"),
    );
  });

  it("ColdChainTimeline shows error on fetch failure", async () => {
    vi.mocked(client.fetchColdChainTimeline).mockRejectedValueOnce(API_ERROR);
    render(<ColdChainTimeline />);
    await userEvent.click(screen.getByText(/Load Timeline/i));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable"),
    );
  });

  it("IdleAssets shows error on fetch failure", async () => {
    vi.mocked(client.fetchIdleAssets).mockRejectedValueOnce(API_ERROR);
    render(<IdleAssets />);
    await userEvent.click(screen.getByText(/Refresh/i));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable"),
    );
  });

  it("ActionPlan shows error on fetch failure", async () => {
    vi.mocked(client.exportActionPlan).mockRejectedValueOnce(API_ERROR);
    render(<ActionPlan />);
    await userEvent.click(screen.getByText(/Load Action Plan/i));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable"),
    );
  });

  it("error state includes a Retry button", async () => {
    vi.mocked(client.activateDisruption).mockRejectedValue(API_ERROR);
    render(<DisruptionOverview />);
    await userEvent.click(screen.getByText(/Activate PORT_STRIKE_01/i));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});
