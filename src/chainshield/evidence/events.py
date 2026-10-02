from __future__ import annotations

"""
ChainShield Evidence/Audit Layer — Evidence Event Records
==========================================================

Every operational recommendation or result produced by ChainShield's
deterministic engines must be wrapped in an ``EvidenceRecord`` before being
surfaced to the caller.  Records are immutable once created, serialise cleanly
to JSON, and are stored in the in-process ``EvidenceStore``.

Record types
------------
- ``RouteRecommendationEvidence``   — an alternative route chosen by the
                                      Optimization Engine.
- ``ImpactAnalysisEvidence``        — disruption-impact assessment produced by
                                      the Impact Engine.
- ``ColdChainEvidence``             — cold-chain classification result produced
                                      by the Cold Chain Engine.
- ``OptimizationRejectionEvidence`` — a candidate route/asset rejected by the
                                      Optimization Engine with explicit reason
                                      codes.

Design notes
------------
- ``from __future__ import annotations`` at the top per project rules.
- Dataclasses are used for structured results (project rules).
- All timestamps are UTC ISO-8601 strings so records are trivially JSON-serialisable.
- ``record_id`` is a deterministic UUID-5 derived from the record's content so
  the same logical event always produces the same ID (idempotent ingestion).
- No external dependencies beyond the standard library.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _deterministic_id(namespace: str, content: dict[str, Any]) -> str:
    """Return a deterministic UUID-5 derived from *namespace* + JSON of *content*.

    Sorting keys guarantees that two records with the same logical content but
    different insertion order always produce the same ID.
    """
    payload = namespace + json.dumps(content, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode()).digest()  # noqa: S324 — not for security
    return str(uuid.UUID(bytes=digest[:16], version=5))


# ---------------------------------------------------------------------------
# Decision type enumeration
# ---------------------------------------------------------------------------

class DecisionType(str, Enum):
    """The kind of decision or result captured by an evidence record."""

    ROUTE_RECOMMENDATION = "ROUTE_RECOMMENDATION"
    IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
    COLD_CHAIN_CLASSIFICATION = "COLD_CHAIN_CLASSIFICATION"
    OPTIMIZATION_REJECTION = "OPTIMIZATION_REJECTION"


# ---------------------------------------------------------------------------
# Base evidence record
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRecord:
    """Base class for all ChainShield evidence records.

    Fields required by the Evidence/Audit Layer contract
    ----------------------------------------------------
    record_id      : deterministic UUID-5 derived from content.
    decision_type  : ``DecisionType`` value identifying the producing engine.
    shipment_id    : shipment this record is attached to (always required).
    disruption_ids : zero-or-more disruption IDs relevant to this record.
    asset_ids      : zero-or-more asset IDs relevant to this record.
    reason_codes   : SCREAMING_SNAKE_CASE codes explaining the decision.
    source_refs    : references to the source data used (node lists, policy
                     IDs, solver status, …).
    timestamp      : UTC ISO-8601 string set at record creation time.
    extra          : arbitrary extra context; must be JSON-serialisable.
    """

    decision_type: DecisionType
    shipment_id: str
    reason_codes: list[str]
    source_refs: dict[str, Any]

    # optional identifiers
    disruption_ids: list[str] = field(default_factory=list)
    asset_ids: list[str] = field(default_factory=list)

    # extra free-form context
    extra: dict[str, Any] = field(default_factory=dict)

    # auto-populated
    timestamp: str = field(default_factory=_utc_now_iso)
    record_id: str = field(init=False)

    def __post_init__(self) -> None:
        # Derive a deterministic ID from the record's stable fields.
        self.record_id = _deterministic_id(
            namespace=self.decision_type.value,
            content={
                "shipment_id": self.shipment_id,
                "decision_type": self.decision_type.value,
                "reason_codes": sorted(self.reason_codes),
                "source_refs": self.source_refs,
                "disruption_ids": sorted(self.disruption_ids),
                "asset_ids": sorted(self.asset_ids),
                "extra": self.extra,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a plain JSON-serialisable dict representation."""
        return {
            "record_id": self.record_id,
            "decision_type": self.decision_type.value,
            "shipment_id": self.shipment_id,
            "disruption_ids": list(self.disruption_ids),
            "asset_ids": list(self.asset_ids),
            "reason_codes": list(self.reason_codes),
            "source_refs": self.source_refs,
            "timestamp": self.timestamp,
            "extra": self.extra,
        }

    def to_json(self) -> str:
        """Return a JSON string of this record."""
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# Concrete evidence record types
# ---------------------------------------------------------------------------

@dataclass
class RouteRecommendationEvidence(EvidenceRecord):
    """Evidence for an alternative route recommended by the Optimization Engine.

    Additional fields
    -----------------
    recommended_route_node_ids : ordered list of node IDs in the new route.
    original_route_node_ids    : ordered list of node IDs in the blocked route.
    estimated_delay_hours      : expected additional transit time.
    """

    recommended_route_node_ids: list[str] = field(default_factory=list)
    original_route_node_ids: list[str] = field(default_factory=list)
    estimated_delay_hours: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["recommended_route_node_ids"] = list(self.recommended_route_node_ids)
        d["original_route_node_ids"] = list(self.original_route_node_ids)
        d["estimated_delay_hours"] = self.estimated_delay_hours
        return d


@dataclass
class ImpactAnalysisEvidence(EvidenceRecord):
    """Evidence for a disruption-impact assessment by the Impact Engine.

    Additional fields
    -----------------
    affected_node_ids  : graph nodes inside the disruption radius/polygon.
    affected_leg_ids   : shipment legs that traverse an affected node.
    impact_score       : 0.0–1.0 confidence score from the Impact Engine.
    """

    affected_node_ids: list[str] = field(default_factory=list)
    affected_leg_ids: list[str] = field(default_factory=list)
    impact_score: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["affected_node_ids"] = list(self.affected_node_ids)
        d["affected_leg_ids"] = list(self.affected_leg_ids)
        d["impact_score"] = self.impact_score
        return d


@dataclass
class ColdChainEvidence(EvidenceRecord):
    """Evidence for a cold-chain classification by the Cold Chain Engine.

    Additional fields
    -----------------
    policy_id              : ID of the policy profile used.
    severity               : ExcursionSeverity value string.
    out_of_range_readings  : count of readings outside policy bounds.
    duration_minutes       : estimated excursion duration in minutes.
    max_celsius            : observed maximum temperature.
    min_celsius            : observed minimum temperature.
    """

    policy_id: str = ""
    severity: str = ""
    out_of_range_readings: int = 0
    duration_minutes: float = 0.0
    max_celsius: float | None = None
    min_celsius: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["policy_id"] = self.policy_id
        d["severity"] = self.severity
        d["out_of_range_readings"] = self.out_of_range_readings
        d["duration_minutes"] = self.duration_minutes
        d["max_celsius"] = self.max_celsius
        d["min_celsius"] = self.min_celsius
        return d


@dataclass
class OptimizationRejectionEvidence(EvidenceRecord):
    """Evidence for a candidate route or asset rejected by the Optimization Engine.

    Additional fields
    -----------------
    candidate_route_node_ids : the route that was evaluated and rejected.
    rejected_asset_ids       : asset IDs considered but rejected.
    constraint_violations    : list of constraint names that were violated.
    """

    candidate_route_node_ids: list[str] = field(default_factory=list)
    rejected_asset_ids: list[str] = field(default_factory=list)
    constraint_violations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["candidate_route_node_ids"] = list(self.candidate_route_node_ids)
        d["rejected_asset_ids"] = list(self.rejected_asset_ids)
        d["constraint_violations"] = list(self.constraint_violations)
        return d
