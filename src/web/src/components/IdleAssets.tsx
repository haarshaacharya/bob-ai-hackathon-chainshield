// IdleAssets — lists available compatible assets from GET /api/v1/assets/idle

import { useEffect, useState } from "react";
import { fetchIdleAssets } from "../api/client";
import type { AssetResponse, IdleAssetsResponse } from "../api/types";
import {
  Card,
  EmptyState,
  ErrorState,
  KV,
  LoadingState,
} from "./ui/primitives";

interface IdleAssetsProps {
  /** Injected for tests. */
  initialData?: IdleAssetsResponse | null;
}

function AssetCard({ asset }: { asset: AssetResponse }) {
  return (
    <div
      data-testid="asset-card"
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        padding: "0.75rem 1rem",
        marginBottom: "0.75rem",
        background: "#f7f8fa",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "0.5rem",
        }}
      >
        <span style={{ fontWeight: 700, fontFamily: "monospace", fontSize: "0.9rem" }}>
          {asset.asset_id}
        </span>
        <span
          data-testid="asset-status"
          style={{
            padding: "0.15rem 0.6rem",
            background: asset.status === "available" ? "#e6f9ec" : "#f7f8fa",
            color: asset.status === "available" ? "#0a5c2e" : "#57606a",
            border: "1px solid currentColor",
            borderRadius: 3,
            fontSize: "0.75rem",
            fontWeight: 700,
            opacity: 0.8,
          }}
        >
          {asset.status.toUpperCase()}
        </span>
      </div>
      <KV label="Type" value={asset.asset_type} />
      <KV label="Mode" value={asset.mode} />
      <KV label="Carrier" value={asset.carrier_id ?? "—"} />
      <KV label="Current node" value={asset.current_node_id} />
      <KV
        label="Capacity"
        value={`${asset.capacity_kg.toLocaleString("en-US")} kg`}
      />
      <KV
        label="Reefer capable"
        value={
          <span
            data-testid="reefer-badge"
            style={{
              color: asset.reefer_capable ? "#0a5c2e" : "#57606a",
              fontWeight: asset.reefer_capable ? 700 : 400,
            }}
          >
            {asset.reefer_capable ? "Yes" : "No"}
          </span>
        }
      />
      <KV
        label="Available at"
        value={new Date(asset.available_at).toLocaleString()}
      />
    </div>
  );
}

export function IdleAssets({ initialData = null }: IdleAssetsProps) {
  const [data, setData] = useState<IdleAssetsResponse | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData !== null) {
      setData(initialData);
      return;
    }
  }, [initialData]);

  async function handleLoad() {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchIdleAssets();
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div data-testid="idle-assets">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1rem",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700 }}>
          Idle Assets
        </h1>
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
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {loading && <LoadingState message="Querying available assets…" />}
      {error && <ErrorState message={error} onRetry={handleLoad} />}

      {!loading && !error && !data && (
        <EmptyState message="Use the button above to load available assets." />
      )}

      {data && (
        <Card title={`Available Assets (${data.count})`}>
          {data.assets.length === 0 ? (
            <EmptyState message="No idle assets available." />
          ) : (
            data.assets.map((asset) => (
              <AssetCard key={asset.asset_id} asset={asset} />
            ))
          )}
        </Card>
      )}
    </div>
  );
}
