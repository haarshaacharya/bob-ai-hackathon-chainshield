// ShipmentDetail — shows full shipment record, disruption status, and
// generates a deterministic explanation via the backend.

import { useEffect, useState } from "react";
import { fetchShipment, generateExplanation } from "../api/client";
import type { ExplanationResponse, ShipmentResponse } from "../api/types";
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

interface ShipmentDetailProps {
  shipmentId?: string;
  /** Injected data for tests — skips fetch when provided. */
  initialData?: ShipmentResponse | null;
}

export function ShipmentDetail({ shipmentId, initialData = null }: ShipmentDetailProps) {
  const [inputId, setInputId] = useState(shipmentId ?? "SHP-0042");
  const [data, setData] = useState<ShipmentResponse | null>(initialData);
  const [explanation, setExplanation] = useState<ExplanationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingExpl, setLoadingExpl] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData !== null) {
      setData(initialData);
    }
  }, [initialData]);

  async function handleLoad() {
    setLoading(true);
    setError(null);
    setExplanation(null);
    try {
      const result = await fetchShipment(inputId.trim());
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleExplain() {
    if (!data) return;
    setLoadingExpl(true);
    try {
      const expl = await generateExplanation({
        shipment_id: data.shipment_id,
        disruption: data.disruption_ids[0] ?? "",
        kind: "impact",
        reason_codes: data.reason_codes,
      });
      setExplanation(expl);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Explanation failed");
    } finally {
      setLoadingExpl(false);
    }
  }

  return (
    <div data-testid="shipment-detail">
      <h1 style={{ margin: "0 0 1rem 0", fontSize: "1.25rem", fontWeight: 700 }}>
        Shipment Detail
      </h1>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <input
          value={inputId}
          onChange={(e) => setInputId(e.target.value)}
          placeholder="Shipment ID"
          aria-label="Shipment ID"
          style={{
            padding: "0.4rem 0.75rem",
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            width: 200,
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
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      {loading && <LoadingState message="Fetching shipment…" />}
      {error && <ErrorState message={error} onRetry={handleLoad} />}
      {!loading && !error && !data && (
        <EmptyState message="Enter a shipment ID above and click Load." />
      )}

      {data && (
        <>
          <Card title="Shipment Information">
            <KV label="Shipment ID" value={data.shipment_id} />
            <KV
              label="Status"
              value={
                <span data-testid="shipment-status">{data.status}</span>
              }
            />
            <KV
              label="Disrupted"
              value={
                <SeverityBadge
                  severity={data.is_disrupted ? "URGENT_ESCALATION" : "SAFE"}
                />
              }
            />
            <KV label="Mode" value={data.mode} />
            <KV label="Carrier" value={data.carrier_id ?? "—"} />
            <KV label="Origin → Destination" value={`${data.origin_hub_id} → ${data.destination_hub_id}`} />
            <KV
              label="Cargo value"
              value={`$${data.cargo_value_usd.toLocaleString("en-US", { minimumFractionDigits: 0 })}`}
            />
            <KV label="Weight" value={`${data.weight_kg.toLocaleString("en-US")} kg`} />
            <KV label="Planned departure" value={new Date(data.planned_departure).toLocaleString()} />
            <KV label="Planned arrival" value={new Date(data.planned_arrival).toLocaleString()} />
            <KV label="Delivery deadline" value={new Date(data.delivery_deadline).toLocaleString()} />
            <KV label="Temperature policy" value={data.temperature_policy_id ?? "none"} />
          </Card>

          {data.is_disrupted && (
            <Card title="Disruption Impact">
              <KV label="Affecting disruptions" value={data.disruption_ids.join(", ")} />
              <ReasonCodes codes={data.reason_codes} />
            </Card>
          )}

          <div style={{ marginTop: "0.5rem" }}>
            <button
              onClick={handleExplain}
              disabled={loadingExpl}
              style={{
                padding: "0.4rem 1rem",
                background: loadingExpl ? "#9ca3af" : "#7c5cd8",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                cursor: loadingExpl ? "not-allowed" : "pointer",
              }}
            >
              {loadingExpl ? "Generating…" : "Generate Explanation"}
            </button>
          </div>

          {explanation && (
            <Card title="Deterministic Explanation">
              <p style={{ margin: "0 0 0.5rem 0" }}>
                <strong>Summary:</strong> {explanation.summary}
              </p>
              <p style={{ margin: "0 0 0.5rem 0" }}>
                <strong>Recommended action:</strong> {explanation.recommended_action}
              </p>
              {explanation.why_affected.length > 0 && (
                <div>
                  <strong>Why affected:</strong>
                  <ul style={{ margin: "0.25rem 0 0 0", paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
                    {explanation.why_affected.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}
              {explanation.uncertainties.length > 0 && (
                <div style={{ marginTop: "0.5rem", color: "#7a4a00" }}>
                  <strong>Uncertainties:</strong>
                  <ul style={{ margin: "0.25rem 0 0 0", paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
                    {explanation.uncertainties.map((u, i) => <li key={i}>{u}</li>)}
                  </ul>
                </div>
              )}
              <EvidenceLinks evidence={explanation.evidence} />
              <KV label="Generated by" value={explanation.generated_by} />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
