// ActionPlan — displays recommended actions, route/asset choices,
// rejection reasons, and evidence links for a disruption.

import { useEffect, useState } from "react";
import { exportActionPlan } from "../api/client";
import type { ActionPlanExportResponse, RouteAlternativeOut } from "../api/types";
import {
  Card,
  EmptyState,
  ErrorState,
  EvidenceLinks,
  KV,
  LoadingState,
  ReasonCodes,
  SeverityBadge,
} from "./ui/primitives";

// ---------------------------------------------------------------------------
// Route alternative card
// ---------------------------------------------------------------------------
function RouteAlternativeCard({
  alt,
  rank,
}: {
  alt: RouteAlternativeOut;
  rank: number;
}) {
  return (
    <div
      data-testid="route-alternative"
      style={{
        border: `1px solid ${alt.is_feasible ? "#c7d4f5" : "#e5e7eb"}`,
        borderRadius: 6,
        padding: "0.75rem 1rem",
        marginBottom: "0.5rem",
        background: alt.is_feasible ? "#f0f4ff" : "#f7f8fa",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 700, fontFamily: "monospace" }}>
          #{rank} — {alt.asset_id}
        </span>
        <span
          style={{
            padding: "0.15rem 0.6rem",
            background: alt.is_feasible ? "#e6f9ec" : "#ffe0e0",
            color: alt.is_feasible ? "#0a5c2e" : "#a01010",
            borderRadius: 3,
            fontSize: "0.75rem",
            fontWeight: 700,
          }}
        >
          {alt.is_feasible ? "FEASIBLE" : "INFEASIBLE"}
        </span>
      </div>
      <div style={{ marginTop: "0.5rem" }}>
        <KV label="Path" value={alt.path.join(" → ")} />
        <KV label="Mode" value={alt.mode} />
        <KV label="Carrier" value={alt.carrier_id ?? "—"} />
        <KV
          label="ETA delta"
          value={`+${alt.eta_delta_hours.toFixed(1)} h`}
        />
        <KV
          label="Additional cost"
          value={`$${alt.total_cost_usd.toLocaleString("en-US", { minimumFractionDigits: 0 })}`}
        />
      </div>
      <ReasonCodes codes={alt.reason_codes} label="Reason codes" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActionPlan component
// ---------------------------------------------------------------------------

interface ActionPlanProps {
  disruptionId?: string;
  /** Injected for tests. */
  initialData?: ActionPlanExportResponse | null;
}

export function ActionPlan({
  disruptionId,
  initialData = null,
}: ActionPlanProps) {
  const [inputId, setInputId] = useState(disruptionId ?? "PORT_STRIKE_01");
  const [data, setData] = useState<ActionPlanExportResponse | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData !== null) setData(initialData);
  }, [initialData]);

  async function handleLoad() {
    setLoading(true);
    setError(null);
    try {
      const result = await exportActionPlan({
        disruption_id: inputId.trim(),
        format: "json",
      });
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div data-testid="action-plan">
      <h1 style={{ margin: "0 0 1rem 0", fontSize: "1.25rem", fontWeight: 700 }}>
        Action Plan
      </h1>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <input
          value={inputId}
          onChange={(e) => setInputId(e.target.value)}
          placeholder="Disruption ID"
          aria-label="Disruption ID"
          style={{
            padding: "0.4rem 0.75rem",
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            width: 220,
          }}
        />
        <button
          onClick={handleLoad}
          disabled={loading}
          style={{
            padding: "0.4rem 1rem",
            background: loading ? "#9ca3af" : "#3b82d4",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Loading…" : "Load Action Plan"}
        </button>
      </div>

      {loading && <LoadingState message="Compiling action plan…" />}
      {error && <ErrorState message={error} onRetry={handleLoad} />}
      {!loading && !error && !data && (
        <EmptyState message="Enter a disruption ID above and use the Load button to fetch the action plan." />
      )}

      {data && (
        <>
          <Card title="Plan Summary">
            <KV label="Disruption" value={data.disruption_id} />
            <KV
              label="Generated at"
              value={new Date(data.generated_at).toLocaleString()}
            />
            <KV label="Affected shipments" value={data.shipments.length} />
          </Card>

          {data.shipments.length === 0 ? (
            <EmptyState message="No affected shipments found for this disruption." />
          ) : (
            data.shipments.map((entry) => (
              <Card key={entry.shipment_id} title={`Shipment ${entry.shipment_id}`}>
                <KV
                  label="Cargo value at risk"
                  value={`$${entry.cargo_value_usd.toLocaleString("en-US", { minimumFractionDigits: 0 })}`}
                />
                {entry.cold_chain_severity && (
                  <KV
                    label="Cold-chain severity"
                    value={<SeverityBadge severity={entry.cold_chain_severity} />}
                  />
                )}
                <ReasonCodes codes={entry.reason_codes} />

                <div style={{ marginTop: "0.75rem" }}>
                  <strong style={{ fontSize: "0.9rem" }}>Route Alternatives</strong>
                  {entry.route_alternatives.length === 0 ? (
                    <div style={{ marginTop: "0.5rem" }}>
                      <EmptyState message="No feasible route alternatives." />
                      {entry.rejection_reason_codes.length > 0 && (
                        <ReasonCodes
                          codes={entry.rejection_reason_codes}
                          label="Rejection reasons"
                        />
                      )}
                    </div>
                  ) : (
                    <div style={{ marginTop: "0.5rem" }}>
                      {entry.route_alternatives.map((alt) => (
                        <RouteAlternativeCard
                          key={alt.alternative_id}
                          alt={alt}
                          rank={alt.rank}
                        />
                      ))}
                      {entry.rejection_reason_codes.length > 0 && (
                        <ReasonCodes
                          codes={entry.rejection_reason_codes}
                          label="Rejected alternatives"
                        />
                      )}
                    </div>
                  )}
                </div>
              </Card>
            ))
          )}

          {data.shipments.length > 0 && (
            <Card title="Evidence">
              {data.shipments.map((entry) => (
                <EvidenceLinks
                  key={entry.shipment_id}
                  evidence={entry.reason_codes}
                  label={`${entry.shipment_id} reason codes`}
                />
              ))}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
