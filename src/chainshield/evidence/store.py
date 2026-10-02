from __future__ import annotations

"""
ChainShield Evidence/Audit Layer — In-Process Evidence Store
=============================================================

``EvidenceStore`` is a lightweight, fully in-memory, offline-first audit log
for ``EvidenceRecord`` instances produced by ChainShield's deterministic
engines.

Design notes
------------
- No external dependencies beyond the standard library.
- Records are stored in a plain list; lookups are O(n) which is acceptable for
  the demo-scale datasets (tens to low-hundreds of records).
- The store is NOT thread-safe by design — ChainShield's deterministic core is
  single-threaded.  Thread safety can be layered on top when a FastAPI endpoint
  is wired up.
- ``add()`` is idempotent: adding the same ``record_id`` a second time is
  silently ignored so callers do not have to guard against double-emit.
- All query helpers return **new lists** (never internal references) so callers
  cannot mutate store state accidentally.
"""

import json
import logging
from typing import Any

from chainshield.logging import EVENT_EVIDENCE_CREATION, get_logger, log_event
from .events import (
    DecisionType,
    EvidenceRecord,
)

_logger = get_logger("evidence")



class EvidenceStore:
    """In-process append-only store for ``EvidenceRecord`` instances.

    Usage example
    -------------
    >>> store = EvidenceStore()
    >>> store.add(some_evidence_record)
    >>> records = store.for_shipment("SHP-001")
    >>> all_json = store.to_json()
    """

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []
        self._ids: set[str] = set()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(self, record: EvidenceRecord) -> None:
        """Append *record* to the store.  Idempotent on ``record_id``."""
        if record.record_id in self._ids:
            return
        self._records.append(record)
        self._ids.add(record.record_id)

        disruption_id = None
        if isinstance(record.source_refs, dict):
            disruption_id = record.source_refs.get("disruption_id")

        log_event(
            _logger,
            logging.INFO,
            EVENT_EVIDENCE_CREATION,
            f"Recorded evidence {record.record_id} for shipment {record.shipment_id}",
            shipment_id=record.shipment_id,
            disruption_id=disruption_id,
            decision_type=record.decision_type.value,
            reason_codes=record.reason_codes,
            record_id=record.record_id,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def all(self) -> list[EvidenceRecord]:
        """Return all stored records (newest-appended last)."""
        return list(self._records)

    def for_shipment(self, shipment_id: str) -> list[EvidenceRecord]:
        """Return all records whose ``shipment_id`` matches *shipment_id*."""
        return [r for r in self._records if r.shipment_id == shipment_id]

    def for_disruption(self, disruption_id: str) -> list[EvidenceRecord]:
        """Return all records that reference *disruption_id*."""
        return [r for r in self._records if disruption_id in r.disruption_ids]

    def for_decision_type(self, decision_type: DecisionType) -> list[EvidenceRecord]:
        """Return all records of the given ``DecisionType``."""
        return [r for r in self._records if r.decision_type == decision_type]

    def get(self, record_id: str) -> EvidenceRecord | None:
        """Return the record with *record_id*, or ``None`` if not found."""
        for r in self._records:
            if r.record_id == record_id:
                return r
        return None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return a list of plain JSON-serialisable dicts, one per record."""
        return [r.to_dict() for r in self._records]

    def to_json(self, indent: int = 2) -> str:
        """Return a JSON array of all records."""
        return json.dumps(self.to_dicts(), indent=indent, default=str)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:  # pragma: no cover
        return f"EvidenceStore(records={len(self._records)})"
