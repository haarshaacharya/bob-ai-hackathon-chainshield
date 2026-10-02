from __future__ import annotations

"""
TemperaturePolicy — configurable cold-chain policy profile.

Design constraint (AGENTS.md):
  Temperature thresholds and severity rules are loaded from policy dicts /
  profiles — never hardcoded.  ``classify_excursion`` in preflight_demo.py
  is the canonical implementation reference; this model is the validated
  schema for those policy dicts.
"""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import ExcursionSeverity, ProductClass


class SeverityRules(BaseModel):
    """Maps excursion patterns to severity levels.

    Every key maps to an ``ExcursionSeverity`` value so the classifier
    can look up severities without any hardcoded comparisons.
    """

    out_of_range: ExcursionSeverity = ExcursionSeverity.EXCURSION_REVIEW
    """Severity when at least one reading exceeds the min/max range."""

    missing_sensor_data: ExcursionSeverity = ExcursionSeverity.URGENT_ESCALATION
    """Severity when no sensor readings are available for a shipment."""

    sustained_excursion: ExcursionSeverity = ExcursionSeverity.URGENT_ESCALATION
    """Severity when excursion duration exceeds ``max_continuous_excursion_minutes``."""

    drift_detected: ExcursionSeverity = ExcursionSeverity.EXCURSION_REVIEW
    """Severity for gradual but sustained temperature drift toward the boundary."""

    spike_detected: ExcursionSeverity = ExcursionSeverity.EXCURSION_REVIEW
    """Severity for a short-duration spike above the upper threshold."""

    door_open_suspected: ExcursionSeverity = ExcursionSeverity.OUT_OF_RANGE
    """Severity when a door-open pattern is detected (rapid rise + rapid fall)."""

    sensor_failure_suspected: ExcursionSeverity = ExcursionSeverity.URGENT_ESCALATION
    """Severity when sensor readings suggest hardware failure (frozen values, etc.)."""


class TemperaturePolicy(BaseModel):
    """Validated cold-chain temperature policy profile.

    Instances are loaded from policy dicts at runtime (e.g. from DuckDB /
    Parquet fixtures).  No threshold value is hardcoded in application logic.

    Example (CDC refrigerated vaccine demo profile)::

        TemperaturePolicy(
            policy_id="cdc_refrigerated_vaccine_demo",
            product_class=ProductClass.REFRIGERATED_VACCINE,
            min_celsius=2.0,
            max_celsius=8.0,
            max_continuous_excursion_minutes=15,
            sample_interval_minutes=6,
            source_reference="CDC Vaccine Storage and Handling Toolkit",
        )
    """

    policy_id: str = Field(..., min_length=1, description="Unique policy identifier.")

    product_class: ProductClass = Field(
        ..., description="Product class this policy applies to."
    )

    jurisdiction: str = Field(
        "GLOBAL",
        description="Jurisdiction or regulatory body this profile is based on.",
    )

    min_celsius: float = Field(
        ...,
        description="Minimum acceptable temperature in degrees Celsius (inclusive).",
    )

    max_celsius: float = Field(
        ...,
        description="Maximum acceptable temperature in degrees Celsius (inclusive).",
    )

    max_continuous_excursion_minutes: Annotated[float, Field(gt=0)] = Field(
        ...,
        description=(
            "Maximum continuous duration (minutes) outside the min/max range before "
            "the severity escalates to ``sustained_excursion``."
        ),
    )

    sample_interval_minutes: Annotated[float, Field(gt=0)] = Field(
        6.0,
        description=(
            "Expected interval between consecutive sensor readings (minutes).  "
            "Used to estimate excursion duration when only reading counts are available."
        ),
    )

    source_reference: str = Field(
        "",
        description=(
            "Human-readable citation for the regulatory / manufacturer source. "
            "Not used in classification logic — for audit trail only."
        ),
    )

    severity_rules: SeverityRules = Field(
        default_factory=SeverityRules,
        description="Mapping of excursion patterns to severity levels.",
    )

    notes: str = Field(
        "",
        description="Free-text notes for operators and auditors.",
    )

    @field_validator("min_celsius", "max_celsius", mode="before")
    @classmethod
    def _coerce_temperature(cls, v: object) -> float:
        """Accept int or numeric string in addition to float."""
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Temperature must be numeric, got {v!r}") from exc

    @model_validator(mode="after")
    def _check_range_order(self) -> TemperaturePolicy:
        if self.min_celsius >= self.max_celsius:
            raise ValueError(
                f"min_celsius ({self.min_celsius}) must be strictly less than "
                f"max_celsius ({self.max_celsius})"
            )
        return self
