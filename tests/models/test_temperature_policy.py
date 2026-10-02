from __future__ import annotations

"""
Unit tests for TemperaturePolicy and SeverityRules data contracts.
"""

import pytest
from pydantic import ValidationError

from chainshield.models.temperature_policy import SeverityRules, TemperaturePolicy
from chainshield.models.enums import ExcursionSeverity, ProductClass


# ---------------------------------------------------------------------------
# SeverityRules
# ---------------------------------------------------------------------------


class TestSeverityRules:
    def test_defaults(self):
        rules = SeverityRules()
        assert rules.out_of_range == ExcursionSeverity.EXCURSION_REVIEW
        assert rules.missing_sensor_data == ExcursionSeverity.URGENT_ESCALATION

    def test_custom_values(self):
        rules = SeverityRules(
            out_of_range=ExcursionSeverity.URGENT_ESCALATION,
            missing_sensor_data=ExcursionSeverity.OUT_OF_RANGE,
        )
        assert rules.out_of_range == ExcursionSeverity.URGENT_ESCALATION
        assert rules.missing_sensor_data == ExcursionSeverity.OUT_OF_RANGE

    def test_all_severity_fields_accept_valid_enum(self):
        rules = SeverityRules(
            out_of_range=ExcursionSeverity.SAFE,
            missing_sensor_data=ExcursionSeverity.SAFE,
            sustained_excursion=ExcursionSeverity.SAFE,
            drift_detected=ExcursionSeverity.SAFE,
            spike_detected=ExcursionSeverity.SAFE,
            door_open_suspected=ExcursionSeverity.SAFE,
            sensor_failure_suspected=ExcursionSeverity.SAFE,
        )
        assert rules.out_of_range == ExcursionSeverity.SAFE


# ---------------------------------------------------------------------------
# TemperaturePolicy
# ---------------------------------------------------------------------------


CDC_VACCINE_POLICY = dict(
    policy_id="cdc_refrigerated_vaccine_demo",
    product_class=ProductClass.REFRIGERATED_VACCINE,
    min_celsius=2.0,
    max_celsius=8.0,
    max_continuous_excursion_minutes=15,
    sample_interval_minutes=6,
    source_reference="CDC Vaccine Storage and Handling Toolkit (demo profile)",
    severity_rules=SeverityRules(
        out_of_range=ExcursionSeverity.EXCURSION_REVIEW,
        missing_sensor_data=ExcursionSeverity.URGENT_ESCALATION,
    ),
)


class TestTemperaturePolicy:
    def test_valid_cdc_profile(self):
        policy = TemperaturePolicy(**CDC_VACCINE_POLICY)
        assert policy.policy_id == "cdc_refrigerated_vaccine_demo"
        assert policy.min_celsius == 2.0
        assert policy.max_celsius == 8.0
        assert policy.product_class == ProductClass.REFRIGERATED_VACCINE

    def test_inverted_range_rejected(self):
        """min_celsius >= max_celsius must be rejected."""
        with pytest.raises(ValidationError, match="min_celsius"):
            TemperaturePolicy(**{**CDC_VACCINE_POLICY, "min_celsius": 8.0, "max_celsius": 2.0})

    def test_equal_range_rejected(self):
        with pytest.raises(ValidationError, match="min_celsius"):
            TemperaturePolicy(**{**CDC_VACCINE_POLICY, "min_celsius": 5.0, "max_celsius": 5.0})

    def test_negative_temperature_range_valid(self):
        """Frozen cargo: -25°C to -15°C is a valid range."""
        policy = TemperaturePolicy(
            **{
                **CDC_VACCINE_POLICY,
                "policy_id": "frozen_demo",
                "product_class": ProductClass.FROZEN_VACCINE,
                "min_celsius": -25.0,
                "max_celsius": -15.0,
            }
        )
        assert policy.min_celsius == -25.0
        assert policy.max_celsius == -15.0

    def test_temperature_coercion_from_int(self):
        """Integer temperatures should be accepted and coerced to float."""
        policy = TemperaturePolicy(**{**CDC_VACCINE_POLICY, "min_celsius": 2, "max_celsius": 8})
        assert isinstance(policy.min_celsius, float)

    def test_missing_policy_id_rejected(self):
        data = {k: v for k, v in CDC_VACCINE_POLICY.items() if k != "policy_id"}
        with pytest.raises(ValidationError):
            TemperaturePolicy(**data)

    def test_sample_interval_must_be_positive(self):
        with pytest.raises(ValidationError):
            TemperaturePolicy(**{**CDC_VACCINE_POLICY, "sample_interval_minutes": 0})

    def test_excursion_minutes_must_be_positive(self):
        with pytest.raises(ValidationError):
            TemperaturePolicy(**{**CDC_VACCINE_POLICY, "max_continuous_excursion_minutes": -1})

    def test_default_severity_rules_created_when_not_supplied(self):
        """If severity_rules is omitted, defaults should be populated."""
        data = {k: v for k, v in CDC_VACCINE_POLICY.items() if k != "severity_rules"}
        policy = TemperaturePolicy(**data)
        assert policy.severity_rules.out_of_range == ExcursionSeverity.EXCURSION_REVIEW

    def test_json_round_trip(self):
        policy = TemperaturePolicy(**CDC_VACCINE_POLICY)
        reloaded = TemperaturePolicy.model_validate_json(policy.model_dump_json())
        assert reloaded == policy
