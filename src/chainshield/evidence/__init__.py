from __future__ import annotations

"""
chainshield.evidence
====================
Deterministic Evidence/Audit Layer for ChainShield.

Public API
----------
from chainshield.evidence import (
    DecisionType,
    EvidenceRecord,
    RouteRecommendationEvidence,
    ImpactAnalysisEvidence,
    ColdChainEvidence,
    OptimizationRejectionEvidence,
    EvidenceStore,
)
"""

from .events import (
    ColdChainEvidence,
    DecisionType,
    EvidenceRecord,
    ImpactAnalysisEvidence,
    OptimizationRejectionEvidence,
    RouteRecommendationEvidence,
)
from .store import EvidenceStore

__all__ = [
    "DecisionType",
    "EvidenceRecord",
    "RouteRecommendationEvidence",
    "ImpactAnalysisEvidence",
    "ColdChainEvidence",
    "OptimizationRejectionEvidence",
    "EvidenceStore",
]
