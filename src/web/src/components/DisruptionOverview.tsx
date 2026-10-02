// DisruptionOverview — shows active disruption details after activation.
// Never invents data; all values come from the API response.

import { useState } from "react";
import { activateDisruption } from "../api/client";
import type { DisruptionActivateResponse } from "../api/types";
import {
  Card,
  EmptyState,
  ErrorState,
  EvidenceLinks,
  KV,
  LoadingState,
  ReasonCodes,
} from "./ui/primitives";

interface DisruptionOverviewProps {
  /** Pre-loaded response for testing or initial render from parent. */
  initialData?: DisruptionActivateResponse | null;
}

export function DisruptionOverview({ initialData = null }: DisruptionOverviewProps) {
  const [data, setData] = useState<DisruptionActivateResponse | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Demo activation — uses the reference scenario from preflight_demo.py
  async function handleActivate() {
    setLoading(true);
    setError(null);
    try {
      const result = await activateDisruption({
        disruption_id: "PORT_STRIKE_01",
        disruption_type: "port_strike",
        severity: "HIGH",
        title: "Port strike — PORT-03",
        description: "Industrial action closing PORT-03 to all traffic.",
        window_start: "2026-09-14T00:00:00Z",
        window_end: "2026-09-17T00:00:00Z",
        blocked_nodes: ["PORT-03"],
        blocked_edges: [],
      });
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div data-testid="disruption-overview">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1rem",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700 }}>
          Disruption Overview
        </h1>
        <button
          onClick={handleActivate}
          disabled={loading}
          style={{
            padding: "0.4rem 1rem",
            background: loading ? "#9ca3af" : "#3b82d4",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: loading ? "not-allowed" : "pointer",
            fontWeight: 600,
          }}
        >
          {loading ? "Activating…" : "Activate PORT_STRIKE_01"}
        </button>
      </div>

      {loading && <LoadingState message="Running Impact Engine…" />}
      {error && (
        <ErrorState message={error} onRetry={handleActivate} />
      )}

      {!loading && !error && !data && (
        <EmptyState message="No active disruption. Use the Activate button above to run the Impact Engine." />
      )}

      {data && (
        <>
          <Card title="Active Disruption">
            <KV label="Disruption ID" value={data.disruption_id} />
            <KV
              label="Affected shipments"
              value={
                <span data-testid="affected-count">
                  {data.affected_shipment_count}
                </span>
              }
            />
            <KV
              label="Cargo value at risk"
              value={
                <span data-testid="cargo-value">
                  ${data.cargo_value_at_risk_usd.toLocaleString("en-US", {
                    minimumFractionDigits: 0,
                    maximumFractionDigits: 0,
                  })}
                </span>
              }
            />
            <KV
              label="Affected shipment IDs"
              value={data.affected_shipment_ids.join(", ") || "—"}
            />
            <ReasonCodes codes={data.reason_codes} />
          </Card>

          {data.evidence.length > 0 && (
            <Card title="Evidence Records">
              {data.evidence.map((ev, i) => (
                <EvidenceLinks
                  key={i}
                  evidence={ev as Record<string, unknown>}
                  label={`Record ${i + 1}`}
                />
              ))}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
