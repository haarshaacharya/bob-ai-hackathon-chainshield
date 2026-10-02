import { useState } from "react";
import { DisruptionOverview } from "./components/DisruptionOverview";
import { ShipmentDetail } from "./components/ShipmentDetail";
import { ColdChainTimeline } from "./components/ColdChainTimeline";
import { IdleAssets } from "./components/IdleAssets";
import { ActionPlan } from "./components/ActionPlan";

type Screen =
  | "disruption"
  | "shipment"
  | "cold-chain"
  | "idle-assets"
  | "action-plan";

const NAV_ITEMS: { id: Screen; label: string }[] = [
  { id: "disruption", label: "Disruption Overview" },
  { id: "shipment", label: "Shipment Detail" },
  { id: "cold-chain", label: "Cold-Chain Timeline" },
  { id: "idle-assets", label: "Idle Assets" },
  { id: "action-plan", label: "Action Plan" },
];

export function App() {
  const [screen, setScreen] = useState<Screen>("disruption");

  return (
    <div
      style={{
        fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif',
        fontSize: "14px",
        lineHeight: 1.6,
        color: "#1f2328",
        background: "#f7f8fa",
        minHeight: "100vh",
      }}
    >
      {/* Header */}
      <header
        style={{
          background: "#1f2328",
          color: "#fff",
          padding: "0.75rem 1.5rem",
          display: "flex",
          alignItems: "center",
          gap: "1.5rem",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: "1rem", letterSpacing: "0.02em" }}>
          ⛓️ ChainShield
        </span>
        <span style={{ color: "#9ca3af", fontSize: "0.85rem" }}>
          Supply-Chain Resilience Copilot — deterministic core
        </span>
      </header>

      {/* Navigation */}
      <nav
        role="navigation"
        aria-label="Main navigation"
        style={{
          background: "#fff",
          borderBottom: "1px solid #e5e7eb",
          display: "flex",
          gap: "0",
          overflowX: "auto",
        }}
      >
        {NAV_ITEMS.map(({ id, label }) => (
          <button
            key={id}
            aria-current={screen === id ? "page" : undefined}
            onClick={() => setScreen(id)}
            style={{
              padding: "0.65rem 1.1rem",
              border: "none",
              borderBottom: screen === id ? "2px solid #3b82d4" : "2px solid transparent",
              background: "none",
              color: screen === id ? "#3b82d4" : "#57606a",
              fontWeight: screen === id ? 700 : 400,
              cursor: "pointer",
              whiteSpace: "nowrap",
              fontSize: "0.875rem",
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Main content */}
      <main
        style={{
          maxWidth: 900,
          margin: "0 auto",
          padding: "1.5rem 1rem",
        }}
      >
        {screen === "disruption" && <DisruptionOverview />}
        {screen === "shipment" && <ShipmentDetail />}
        {screen === "cold-chain" && <ColdChainTimeline />}
        {screen === "idle-assets" && <IdleAssets />}
        {screen === "action-plan" && <ActionPlan />}
      </main>
    </div>
  );
}
