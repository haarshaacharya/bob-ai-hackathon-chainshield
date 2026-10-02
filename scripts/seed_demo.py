from __future__ import annotations

"""
seed_demo.py
============
CLI script that generates the deterministic synthetic scenario and writes
it to ``data/demo/`` as JSON fixtures.

Usage
-----
    python scripts/seed_demo.py
    python scripts/seed_demo.py --seed 42 --out data/demo

Output files
------------
    data/demo/disruptions.json
    data/demo/shipments.json
    data/demo/assets.json
    data/demo/temperature_policies.json
    data/demo/sensor_readings.json
    data/demo/route_graph.json
    data/demo/routes.json          (feasible + infeasible)

All files are UTF-8 JSON using Pydantic's ``model_dump_json()`` for
domain objects, ensuring round-trip fidelity with the data models.

Design notes
------------
- Entirely offline — no external APIs or datasets.
- Safe to run multiple times; existing files are overwritten deterministically.
- Creates output directory via ``mkdir(parents=True, exist_ok=True)``.
"""

import argparse
import json
import sys
from pathlib import Path

# Allow running this script directly without installing the package
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from generate_synthetic_data import generate_scenario  # noqa: E402 (local script)


def _write_json(path: Path, data: object) -> None:
    """Write ``data`` as pretty-printed JSON to ``path``, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
    print(f"  wrote {path}")


def seed(seed_value: int = 42, out_dir: str = "data/demo") -> Path:
    """Generate the scenario and persist fixtures to *out_dir*.

    Parameters
    ----------
    seed_value
        Random seed forwarded to ``generate_scenario``.
    out_dir
        Output directory (relative to repo root or absolute).

    Returns
    -------
    Path
        Resolved output directory.
    """
    bundle = generate_scenario(seed=seed_value)
    out = Path(out_dir)

    print(f"Seeding demo data → {out.resolve()}")

    # Disruptions
    _write_json(
        out / "disruptions.json",
        [json.loads(d.model_dump_json()) for d in bundle.disruptions],
    )

    # Shipments (include legs inline)
    _write_json(
        out / "shipments.json",
        [json.loads(s.model_dump_json()) for s in bundle.shipments],
    )

    # Assets
    _write_json(
        out / "assets.json",
        [json.loads(a.model_dump_json()) for a in bundle.assets],
    )

    # Temperature policies
    _write_json(
        out / "temperature_policies.json",
        [json.loads(p.model_dump_json()) for p in bundle.temperature_policies],
    )

    # Sensor readings
    _write_json(
        out / "sensor_readings.json",
        [json.loads(r.model_dump_json()) for r in bundle.sensor_readings],
    )

    # Route graph
    _write_json(out / "route_graph.json", bundle.route_graph)

    # Routes (feasible + infeasible combined)
    _write_json(
        out / "routes.json",
        {
            "feasible": bundle.feasible_routes,
            "infeasible": bundle.infeasible_routes,
        },
    )

    resolved = out.resolve()
    print(f"Done — {sum(1 for _ in out.glob('*.json'))} files in {resolved}")
    return resolved


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and persist ChainShield demo fixtures."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42).",
    )
    parser.add_argument(
        "--out",
        default="data/demo",
        help="Output directory for JSON fixtures (default: data/demo).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    seed(seed_value=args.seed, out_dir=args.out)
