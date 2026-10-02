from __future__ import annotations

"""
Shared enumerations used across ChainShield data contracts.

All enum values are strings so they serialise cleanly to/from JSON and
appear in Pydantic validation error messages without extra conversion.
"""

from enum import Enum


class ShipmentStatus(str, Enum):
    """Lifecycle states of a shipment."""

    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_CUSTOMS = "AT_CUSTOMS"
    DELAYED = "DELAYED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CargoMode(str, Enum):
    """Transport mode used for a shipment or shipment leg."""

    ROAD = "road"
    RAIL = "rail"
    SEA = "sea"
    AIR = "air"
    MULTIMODAL = "multimodal"


class ProductClass(str, Enum):
    """Product classification driving which temperature policy applies."""

    REFRIGERATED_VACCINE = "refrigerated_vaccine"
    FROZEN_VACCINE = "frozen_vaccine"
    BIOLOGICS = "biologics"
    FRESH_PRODUCE = "fresh_produce"
    FROZEN_FOOD = "frozen_food"
    CHEMICALS = "chemicals"
    DRY_GOODS = "dry_goods"
    OTHER = "other"


class ExcursionSeverity(str, Enum):
    """Cold-chain excursion severity levels.

    Order (ascending):  SAFE → OUT_OF_RANGE → EXCURSION_REVIEW
                        → URGENT_ESCALATION → POLICY_REQUIRED

    ``POLICY_REQUIRED`` is a special sentinel returned when no policy
    profile has been matched to the shipment's product class.
    """

    SAFE = "SAFE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    EXCURSION_REVIEW = "EXCURSION_REVIEW"
    URGENT_ESCALATION = "URGENT_ESCALATION"
    POLICY_REQUIRED = "POLICY_REQUIRED"
