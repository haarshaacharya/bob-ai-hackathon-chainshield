// Shared UI primitives — loading, error, empty states + reason codes / evidence

import React from "react";

// ---------------------------------------------------------------------------
// LoadingState
// ---------------------------------------------------------------------------
interface LoadingProps {
  message?: string;
}
export function LoadingState({ message = "Loading…" }: LoadingProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        padding: "2rem",
        textAlign: "center",
        color: "#57606a",
        fontStyle: "italic",
      }}
    >
      {message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ErrorState
// ---------------------------------------------------------------------------
interface ErrorProps {
  message: string;
  onRetry?: () => void;
}
export function ErrorState({ message, onRetry }: ErrorProps) {
  return (
    <div
      role="alert"
      style={{
        padding: "1rem 1.5rem",
        background: "#fff3f3",
        border: "1px solid #f5c6c6",
        borderRadius: 6,
        color: "#a01010",
      }}
    >
      <strong>Error:</strong> {message}
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            marginLeft: "1rem",
            padding: "0.25rem 0.75rem",
            background: "#3b82d4",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------
interface EmptyProps {
  message?: string;
}
export function EmptyState({ message = "No data available." }: EmptyProps) {
  return (
    <div
      style={{
        padding: "2rem",
        textAlign: "center",
        color: "#57606a",
        border: "1px dashed #e5e7eb",
        borderRadius: 6,
      }}
    >
      {message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ReasonCodes
// ---------------------------------------------------------------------------
interface ReasonCodesProps {
  codes: string[];
  label?: string;
}
export function ReasonCodes({ codes, label = "Reason codes" }: ReasonCodesProps) {
  if (codes.length === 0) return null;
  return (
    <div style={{ marginTop: "0.5rem" }}>
      <span
        style={{ fontWeight: 600, fontSize: "0.8rem", color: "#57606a", textTransform: "uppercase" }}
      >
        {label}
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", marginTop: "0.3rem" }}>
        {codes.map((c) => (
          <span
            key={c}
            data-testid="reason-code-badge"
            style={{
              fontFamily: "monospace",
              fontSize: "0.75rem",
              padding: "0.15rem 0.5rem",
              background: "#f0f4ff",
              border: "1px solid #c7d4f5",
              borderRadius: 3,
              color: "#1a3a8a",
            }}
          >
            {c}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EvidenceLinks
// ---------------------------------------------------------------------------
interface EvidenceLinksProps {
  evidence: string[] | Record<string, unknown>;
  label?: string;
}
export function EvidenceLinks({
  evidence,
  label = "Evidence",
}: EvidenceLinksProps) {
  const items: string[] = Array.isArray(evidence)
    ? evidence
    : Object.entries(evidence).map(([k, v]) => `${k}: ${JSON.stringify(v)}`);

  if (items.length === 0) return null;

  return (
    <div style={{ marginTop: "0.5rem" }}>
      <span
        style={{ fontWeight: 600, fontSize: "0.8rem", color: "#57606a", textTransform: "uppercase" }}
      >
        {label}
      </span>
      <ul
        data-testid="evidence-list"
        style={{
          margin: "0.3rem 0 0 0",
          paddingLeft: "1.2rem",
          fontSize: "0.8rem",
          color: "#57606a",
        }}
      >
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SeverityBadge
// ---------------------------------------------------------------------------
const SEVERITY_COLOURS: Record<string, { bg: string; color: string }> = {
  SAFE: { bg: "#e6f9ec", color: "#0a5c2e" },
  OUT_OF_RANGE: { bg: "#fff7e6", color: "#7a4a00" },
  EXCURSION_REVIEW: { bg: "#fff0d0", color: "#a04000" },
  URGENT_ESCALATION: { bg: "#ffe0e0", color: "#a01010" },
  POLICY_REQUIRED: { bg: "#f0e6ff", color: "#4a0a8a" },
};

interface SeverityBadgeProps {
  severity: string;
}
export function SeverityBadge({ severity }: SeverityBadgeProps) {
  const colours = SEVERITY_COLOURS[severity] ?? { bg: "#f7f8fa", color: "#1f2328" };
  return (
    <span
      data-testid="severity-badge"
      style={{
        padding: "0.2rem 0.7rem",
        background: colours.bg,
        color: colours.color,
        border: `1px solid ${colours.color}30`,
        borderRadius: 4,
        fontWeight: 700,
        fontSize: "0.8rem",
        letterSpacing: "0.02em",
      }}
    >
      {severity}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Card — generic surface
// ---------------------------------------------------------------------------
interface CardProps {
  title?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}
export function Card({ title, children, style }: CardProps) {
  return (
    <section
      style={{
        background: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: "1rem 1.25rem",
        marginBottom: "1rem",
        ...style,
      }}
    >
      {title && (
        <h2
          style={{
            margin: "0 0 0.75rem 0",
            fontSize: "1rem",
            fontWeight: 700,
            color: "#1f2328",
            borderBottom: "1px solid #e5e7eb",
            paddingBottom: "0.5rem",
          }}
        >
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// KV — key-value row
// ---------------------------------------------------------------------------
interface KVProps {
  label: string;
  value: React.ReactNode;
}
export function KV({ label, value }: KVProps) {
  return (
    <div
      style={{
        display: "flex",
        gap: "0.5rem",
        marginBottom: "0.35rem",
        fontSize: "0.9rem",
      }}
    >
      <span style={{ color: "#57606a", minWidth: 180 }}>{label}</span>
      <span style={{ color: "#1f2328", fontWeight: 500 }}>{value}</span>
    </div>
  );
}
