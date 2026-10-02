// ColdChainTimeline — temperature readings, policy min/max band, excursion
// periods, severity, and evidence.  Uses an SVG sparkline for the readings.

import React, { useEffect, useState } from "react";
import { fetchColdChainTimeline } from "../api/client";
import type { ColdChainTimelineResponse } from "../api/types";
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
// Temperature sparkline (pure SVG, no external charting library required)
// ---------------------------------------------------------------------------
interface SparklineProps {
  readings: { ts: string; temperature_c: number }[];
  policyMin: number;
  policyMax: number;
}

function TemperatureSparkline({ readings, policyMin, policyMax }: SparklineProps) {
  if (readings.length === 0) return null;

  const W = 560;
  const H = 160;
  const PAD = { top: 16, right: 16, bottom: 32, left: 40 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const temps = readings.map((r) => r.temperature_c);
  const minT = Math.min(...temps, policyMin) - 1;
  const maxT = Math.max(...temps, policyMax) + 1;
  const rangeT = maxT - minT || 1;

  const toX = (i: number) => PAD.left + (i / Math.max(readings.length - 1, 1)) * innerW;
  const toY = (t: number) => PAD.top + (1 - (t - minT) / rangeT) * innerH;

  const polyline = readings.map((r, i) => `${toX(i)},${toY(r.temperature_c)}`).join(" ");

  const policyMaxY = toY(policyMax);
  const policyMinY = toY(policyMin);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Temperature timeline chart"
      data-testid="temperature-sparkline"
      style={{ width: "100%", maxWidth: W, display: "block", marginTop: "0.5rem" }}
    >
      {/* Policy band */}
      <rect
        x={PAD.left}
        y={policyMaxY}
        width={innerW}
        height={policyMinY - policyMaxY}
        fill="#e6f9ec"
        opacity="0.7"
      />
      {/* Policy min/max labels */}
      <line x1={PAD.left} y1={policyMaxY} x2={PAD.left + innerW} y2={policyMaxY} stroke="#0a5c2e" strokeDasharray="4 3" strokeWidth={1} />
      <text x={PAD.left - 4} y={policyMaxY + 4} textAnchor="end" fontSize={10} fill="#0a5c2e">{policyMax}°C</text>
      <line x1={PAD.left} y1={policyMinY} x2={PAD.left + innerW} y2={policyMinY} stroke="#0a5c2e" strokeDasharray="4 3" strokeWidth={1} />
      <text x={PAD.left - 4} y={policyMinY + 4} textAnchor="end" fontSize={10} fill="#0a5c2e">{policyMin}°C</text>

      {/* Reading dots — colour by in/out of range */}
      {readings.map((r, i) => {
        const outOfRange = r.temperature_c < policyMin || r.temperature_c > policyMax;
        return (
          <circle
            key={i}
            cx={toX(i)}
            cy={toY(r.temperature_c)}
            r={4}
            fill={outOfRange ? "#a01010" : "#3b82d4"}
          />
        );
      })}

      {/* Temperature polyline */}
      <polyline
        points={polyline}
        fill="none"
        stroke="#3b82d4"
        strokeWidth={2}
      />

      {/* X-axis time labels (first & last) */}
      {readings.length > 0 && (
        <>
          <text x={PAD.left} y={H - 4} fontSize={9} fill="#57606a">
            {new Date(readings[0].ts).toLocaleTimeString()}
          </text>
          <text x={PAD.left + innerW} y={H - 4} textAnchor="end" fontSize={9} fill="#57606a">
            {new Date(readings[readings.length - 1].ts).toLocaleTimeString()}
          </text>
        </>
      )}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// ColdChainTimeline component
// ---------------------------------------------------------------------------

interface ColdChainTimelineProps {
  shipmentId?: string;
  /** Injected for tests. */
  initialData?: ColdChainTimelineResponse | null;
}

export function ColdChainTimeline({
  shipmentId,
  initialData = null,
}: ColdChainTimelineProps) {
  const [inputId, setInputId] = useState(shipmentId ?? "SHP-0042");
  const [data, setData] = useState<ColdChainTimelineResponse | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData !== null) setData(initialData);
  }, [initialData]);

  async function handleLoad() {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchColdChainTimeline(inputId.trim());
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  // Determine policy min/max from evidence or readings fallback
  const policyMin: number =
    typeof data?.evidence?.["min_celsius"] === "number" ? (data.evidence["min_celsius"] as number) : 2;
  const policyMax: number =
    typeof data?.evidence?.["max_celsius"] === "number" ? (data.evidence["max_celsius"] as number) : 8;

  return (
    <div data-testid="cold-chain-timeline">
      <h1 style={{ margin: "0 0 1rem 0", fontSize: "1.25rem", fontWeight: 700 }}>
        Cold-Chain Timeline
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
          {loading ? "Loading…" : "Load Timeline"}
        </button>
      </div>

      {loading && <LoadingState message="Evaluating cold-chain policy…" />}
      {error && <ErrorState message={error} onRetry={handleLoad} />}
      {!loading && !error && !data && (
        <EmptyState message="Enter a shipment ID above to load the cold-chain timeline." />
      )}

      {data && (
        <>
          <Card title="Severity Summary">
            <KV label="Shipment" value={data.shipment_id} />
            <KV
              label="Severity"
              value={<SeverityBadge severity={data.severity} />}
            />
            <KV label="Policy" value={data.policy_id ?? "none"} />
            <KV
              label="Min / Max observed"
              value={`${data.min_temp_c ?? "—"}°C / ${data.max_temp_c ?? "—"}°C`}
            />
            <KV
              label="Out-of-range readings"
              value={`${data.out_of_range_count} of ${data.reading_count}`}
            />
            <KV
              label="Total out-of-range"
              value={`${data.total_out_of_range_minutes} min`}
            />
            <KV
              label="Max continuous excursion (min)"
              value={`${data.max_continuous_excursion_minutes}`}
            />
            <ReasonCodes codes={data.reason_codes} />
          </Card>

          <Card title="Temperature Readings">
            {data.readings.length === 0 ? (
              <EmptyState message="No sensor readings for this shipment." />
            ) : (
              <>
                <TemperatureSparkline
                  readings={data.readings}
                  policyMin={policyMin}
                  policyMax={policyMax}
                />
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: "0.85rem",
                    marginTop: "0.75rem",
                  }}
                >
                  <thead>
                    <tr style={{ background: "#f7f8fa", borderBottom: "1px solid #e5e7eb" }}>
                      <th style={thStyle}>Sensor</th>
                      <th style={thStyle}>Timestamp</th>
                      <th style={thStyle}>Temp (°C)</th>
                      <th style={thStyle}>Battery (%)</th>
                      <th style={thStyle}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.readings.map((r, i) => {
                      const oor = r.temperature_c < policyMin || r.temperature_c > policyMax;
                      return (
                        <tr
                          key={i}
                          data-testid="reading-row"
                          style={{ borderBottom: "1px solid #f0f0f0" }}
                        >
                          <td style={tdStyle}>{r.sensor_id}</td>
                          <td style={tdStyle}>{new Date(r.ts).toLocaleString()}</td>
                          <td
                            style={{
                              ...tdStyle,
                              color: oor ? "#a01010" : "#0a5c2e",
                              fontWeight: oor ? 700 : 400,
                            }}
                          >
                            {r.temperature_c}
                          </td>
                          <td style={tdStyle}>{r.battery_pct}</td>
                          <td style={tdStyle}>
                            {oor ? (
                              <span style={{ color: "#a01010", fontWeight: 700 }}>OUT OF RANGE</span>
                            ) : (
                              <span style={{ color: "#0a5c2e" }}>OK</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>
            )}
          </Card>

          <Card title="Evidence">
            <EvidenceLinks evidence={data.evidence} />
          </Card>
        </>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "0.4rem 0.6rem",
  textAlign: "left",
  fontWeight: 600,
  color: "#57606a",
};

const tdStyle: React.CSSProperties = {
  padding: "0.35rem 0.6rem",
  color: "#1f2328",
};
