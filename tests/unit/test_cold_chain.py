from __future__ import annotations

"""
Unit tests for the ChainShield deterministic Cold-Chain Engine.

Covers
------
1.  SAFE — normal shipment (all readings within 2–8 °C)
2.  EXCURSION_REVIEW — reference demo scenario: max 10.4 °C, ~18-min excursion
3.  URGENT_ESCALATION — sustained excursion (continuous window > policy limit)
4.  Return-to-normal after excursion (only a short spike → EXCURSION_REVIEW)
5.  Missing sensor data (empty readings list) → severity_rules.missing_sensor_data
6.  POLICY_REQUIRED — no policy supplied
7.  Missing reading window detection (large gap between timestamps)
8.  Different configurable temperature policy (frozen vaccine: −25–−15 °C)
9.  Determinism — identical inputs → identical outputs across repeated calls
10. Reason codes: TEMPERATURE_ABOVE_MAX, TEMPERATURE_BELOW_MIN, SUSTAINED_EXCURSION,
    MISSING_SENSOR_WINDOW, NO_SENSOR_DATA, POLICY_REQUIRED
11. Statistics: min_temp_c, max_temp_c, total_out_of_range_minutes,
    max_continuous_excursion_minutes, out_of_range_count, reading_count
12. Timestamp order — engine must sort readings regardless of input order
13. Boundary values — readings exactly at min/max are SAFE (inclusive range)
14. _max_continuous_run utility helper
"""

from datetime import datetime, timedelta, timezone

import pytest

from chainshield.cold_chain.engine import ColdChainEngine, ColdChainResult, _max_continuous_run
from chainshield.models.enums import ExcursionSeverity, ProductClass
from chainshield.models.sensor_reading import SensorReading
from chainshield.models.temperature_policy import SeverityRules, TemperaturePolicy

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_TZ = timezone.utc
_BASE_TS = datetime(2026, 9, 14, 8, 0, 0, tzinfo=_TZ)


def _ts(offset_minutes: float) -> datetime:
    """Return _BASE_TS + offset_minutes."""
    return _BASE_TS + timedelta(minutes=offset_minutes)


def _reading(temp_c: float, offset_minutes: float = 0.0) -> SensorReading:
    """Minimal SensorReading at _BASE_TS + offset_minutes."""
    return SensorReading(
        sensor_id="SENSOR-9",
        shipment_id="SHP-0042",
        ts=_ts(offset_minutes),
        temperature_c=temp_c,
    )


def _cdc_policy(
    *,
    min_celsius: float = 2.0,
    max_celsius: float = 8.0,
    max_continuous_excursion_minutes: float = 30.0,
    sample_interval_minutes: float = 6.0,
) -> TemperaturePolicy:
    """Return the demo CDC refrigerated-vaccine policy (configurable overrides).

    The default ``max_continuous_excursion_minutes=30`` keeps the primary demo
    scenario (18 min out-of-range) in EXCURSION_REVIEW territory, matching the
    preflight CHK-4 expectation.  Tests that want to trigger sustained-excursion
    escalation pass an explicit lower limit (e.g. 15.0).
    """
    return TemperaturePolicy(
        policy_id="cdc_refrigerated_vaccine_demo",
        product_class=ProductClass.REFRIGERATED_VACCINE,
        jurisdiction="US",
        min_celsius=min_celsius,
        max_celsius=max_celsius,
        max_continuous_excursion_minutes=max_continuous_excursion_minutes,
        sample_interval_minutes=sample_interval_minutes,
        source_reference="CDC Vaccine Storage and Handling Toolkit (demo profile)",
        severity_rules=SeverityRules(
            out_of_range=ExcursionSeverity.EXCURSION_REVIEW,
            missing_sensor_data=ExcursionSeverity.URGENT_ESCALATION,
            sustained_excursion=ExcursionSeverity.URGENT_ESCALATION,
        ),
    )


def _frozen_vaccine_policy() -> TemperaturePolicy:
    """A second, distinct policy for frozen vaccines (−25–−15 °C)."""
    return TemperaturePolicy(
        policy_id="who_frozen_vaccine_demo",
        product_class=ProductClass.FROZEN_VACCINE,
        jurisdiction="GLOBAL",
        min_celsius=-25.0,
        max_celsius=-15.0,
        max_continuous_excursion_minutes=10.0,
        sample_interval_minutes=5.0,
        source_reference="WHO EPI Cold-Chain Guidelines (demo profile)",
        severity_rules=SeverityRules(
            out_of_range=ExcursionSeverity.OUT_OF_RANGE,
            missing_sensor_data=ExcursionSeverity.URGENT_ESCALATION,
            sustained_excursion=ExcursionSeverity.URGENT_ESCALATION,
        ),
    )


# The demo readings from the preflight script / slide 8:
#   08:00 → 6.9 °C (SAFE)
#   08:06 → 8.9 °C (OOR)
#   08:12 → 10.4 °C (OOR)
#   08:18 → 9.1 °C (OOR)
#   08:24 → 6.4 °C (SAFE)
_DEMO_READINGS = [
    _reading(6.9, 0),
    _reading(8.9, 6),
    _reading(10.4, 12),
    _reading(9.1, 18),
    _reading(6.4, 24),
]

_ENGINE = ColdChainEngine()


# ---------------------------------------------------------------------------
# 1. SAFE — normal shipment, all readings within range
# ---------------------------------------------------------------------------


class TestSafe:
    """All readings within 2–8 °C → SAFE, no reason codes."""

    def _result(self) -> ColdChainResult:
        readings = [
            _reading(2.0, 0),   # exactly at min (inclusive)
            _reading(5.0, 6),
            _reading(8.0, 12),  # exactly at max (inclusive)
            _reading(4.5, 18),
        ]
        return _ENGINE.evaluate(_cdc_policy(), readings)

    def test_severity_safe(self) -> None:
        assert self._result().severity == ExcursionSeverity.SAFE

    def test_no_reason_codes(self) -> None:
        assert self._result().reason_codes == []

    def test_statistics_correct(self) -> None:
        r = self._result()
        assert r.min_temp_c == pytest.approx(2.0)
        assert r.max_temp_c == pytest.approx(8.0)
        assert r.out_of_range_count == 0
        assert r.total_out_of_range_minutes == pytest.approx(0.0)
        assert r.reading_count == 4

    def test_boundary_values_are_safe(self) -> None:
        """Readings exactly at min/max must be treated as in-range (inclusive)."""
        result = _ENGINE.evaluate(
            _cdc_policy(),
            [_reading(2.0, 0), _reading(8.0, 6)],
        )
        assert result.severity == ExcursionSeverity.SAFE


# ---------------------------------------------------------------------------
# 2. Reference demo scenario — 10.4 °C excursion, ~18 minutes out of range
# ---------------------------------------------------------------------------


class TestDemoExcursionScenario:
    """Reference scenario from preflight CHK-4 / presentation slide 8."""

    def _result(self) -> ColdChainResult:
        return _ENGINE.evaluate(_cdc_policy(), _DEMO_READINGS)

    def test_severity_excursion_review(self) -> None:
        assert self._result().severity == ExcursionSeverity.EXCURSION_REVIEW

    def test_temperature_above_max_code(self) -> None:
        assert "TEMPERATURE_ABOVE_MAX" in self._result().reason_codes

    def test_max_temp_is_10_4(self) -> None:
        assert self._result().max_temp_c == pytest.approx(10.4)

    def test_min_temp_is_6_4(self) -> None:
        assert self._result().min_temp_c == pytest.approx(6.4)

    def test_out_of_range_count_is_3(self) -> None:
        # 8.9, 10.4, 9.1 are out of range
        assert self._result().out_of_range_count == 3

    def test_total_out_of_range_minutes_is_18(self) -> None:
        # 3 readings × 6-minute sample interval = 18 min
        assert self._result().total_out_of_range_minutes == pytest.approx(18.0)

    def test_reading_count_is_5(self) -> None:
        assert self._result().reading_count == 5

    def test_no_below_min_code(self) -> None:
        assert "TEMPERATURE_BELOW_MIN" not in self._result().reason_codes


# ---------------------------------------------------------------------------
# 3. Sustained excursion exceeds max_continuous_excursion_minutes
# ---------------------------------------------------------------------------


class TestSustainedExcursion:
    """Continuous excursion window longer than policy limit → URGENT_ESCALATION."""

    def _result(self) -> ColdChainResult:
        # 3 consecutive OOR readings × 6 min = 18 min > policy limit of 15 min
        readings = [
            _reading(5.0, 0),   # SAFE
            _reading(9.0, 6),   # OOR start
            _reading(10.0, 12), # OOR
            _reading(9.5, 18),  # OOR end  (18 min continuous)
            _reading(5.0, 24),  # SAFE
        ]
        return _ENGINE.evaluate(_cdc_policy(max_continuous_excursion_minutes=15.0), readings)

    def test_severity_urgent_escalation(self) -> None:
        assert self._result().severity == ExcursionSeverity.URGENT_ESCALATION

    def test_sustained_excursion_code(self) -> None:
        assert "SUSTAINED_EXCURSION" in self._result().reason_codes

    def test_max_continuous_excursion_minutes_is_18(self) -> None:
        assert self._result().max_continuous_excursion_minutes == pytest.approx(18.0)

    def test_policy_limit_of_15_triggers_escalation(self) -> None:
        """Exactly at the boundary (18 > 15) must escalate."""
        result = _ENGINE.evaluate(
            _cdc_policy(max_continuous_excursion_minutes=15.0),
            [_reading(9.0, 0), _reading(9.0, 6), _reading(9.0, 12)],  # 18 min continuous
        )
        assert result.severity == ExcursionSeverity.URGENT_ESCALATION

    def test_below_limit_does_not_escalate(self) -> None:
        """Exactly 2 OOR readings × 6 min = 12 min ≤ 15 → EXCURSION_REVIEW, not URGENT."""
        result = _ENGINE.evaluate(
            _cdc_policy(max_continuous_excursion_minutes=15.0),
            [_reading(9.0, 0), _reading(9.0, 6), _reading(5.0, 12)],  # 12 min
        )
        assert result.severity == ExcursionSeverity.EXCURSION_REVIEW
        assert "SUSTAINED_EXCURSION" not in result.reason_codes


# ---------------------------------------------------------------------------
# 4. Return to normal after excursion
# ---------------------------------------------------------------------------


class TestReturnToNormal:
    """Short spike followed by return to normal → EXCURSION_REVIEW (not URGENT)."""

    def test_spike_then_normal(self) -> None:
        # Single out-of-range reading (6 min < 15 min policy limit)
        readings = [
            _reading(5.0, 0),
            _reading(10.0, 6),  # single spike
            _reading(5.0, 12),
            _reading(4.0, 18),
            _reading(6.0, 24),
        ]
        result = _ENGINE.evaluate(_cdc_policy(), readings)
        assert result.severity == ExcursionSeverity.EXCURSION_REVIEW
        assert "SUSTAINED_EXCURSION" not in result.reason_codes
        assert result.out_of_range_count == 1
        assert result.total_out_of_range_minutes == pytest.approx(6.0)

    def test_returns_safe_after_all_readings_normal(self) -> None:
        readings = [
            _reading(9.0, 0),   # OOR
            _reading(5.0, 6),   # SAFE
            _reading(5.0, 12),
            _reading(5.0, 18),
        ]
        result = _ENGINE.evaluate(_cdc_policy(), readings)
        # Severity reflects the OOR reading
        assert result.severity != ExcursionSeverity.SAFE
        # If we had only in-range readings, it's SAFE
        safe_result = _ENGINE.evaluate(_cdc_policy(), readings[1:])
        assert safe_result.severity == ExcursionSeverity.SAFE


# ---------------------------------------------------------------------------
# 5. Missing sensor data (empty readings list)
# ---------------------------------------------------------------------------


class TestMissingSensorData:
    """Empty readings list → severity_rules.missing_sensor_data."""

    def test_severity_uses_policy_rule(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [])
        assert result.severity == ExcursionSeverity.URGENT_ESCALATION

    def test_no_sensor_data_reason_code(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [])
        assert "NO_SENSOR_DATA" in result.reason_codes

    def test_reading_count_is_zero(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [])
        assert result.reading_count == 0

    def test_min_max_are_none(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [])
        assert result.min_temp_c is None
        assert result.max_temp_c is None

    def test_custom_policy_missing_sensor_severity(self) -> None:
        """Policy can configure missing_sensor_data to a different severity."""
        policy = TemperaturePolicy(
            policy_id="custom",
            product_class=ProductClass.FRESH_PRODUCE,
            min_celsius=0.0,
            max_celsius=4.0,
            max_continuous_excursion_minutes=30.0,
            severity_rules=SeverityRules(
                missing_sensor_data=ExcursionSeverity.EXCURSION_REVIEW,
            ),
        )
        result = _ENGINE.evaluate(policy, [])
        assert result.severity == ExcursionSeverity.EXCURSION_REVIEW


# ---------------------------------------------------------------------------
# 6. POLICY_REQUIRED — no policy supplied
# ---------------------------------------------------------------------------


class TestPolicyRequired:
    """policy=None → POLICY_REQUIRED regardless of readings."""

    def test_severity_policy_required_with_no_readings(self) -> None:
        result = _ENGINE.evaluate(None, [])
        assert result.severity == ExcursionSeverity.POLICY_REQUIRED

    def test_severity_policy_required_with_readings(self) -> None:
        result = _ENGINE.evaluate(None, _DEMO_READINGS)
        assert result.severity == ExcursionSeverity.POLICY_REQUIRED

    def test_policy_required_reason_code(self) -> None:
        result = _ENGINE.evaluate(None, _DEMO_READINGS)
        assert "POLICY_REQUIRED" in result.reason_codes

    def test_policy_required_is_highest_priority(self) -> None:
        """Even with urgent-looking data, POLICY_REQUIRED must take precedence."""
        readings = [_reading(50.0, 0)]  # clearly dangerous
        result = _ENGINE.evaluate(None, readings)
        assert result.severity == ExcursionSeverity.POLICY_REQUIRED


# ---------------------------------------------------------------------------
# 7. Missing reading window detection
# ---------------------------------------------------------------------------


class TestMissingReadingWindow:
    """Engine detects large time gaps between consecutive readings."""

    def test_gap_larger_than_two_intervals_is_flagged(self) -> None:
        # Sample interval = 6 min; threshold = 12 min; gap = 30 min
        readings = [
            _reading(5.0, 0),
            _reading(5.0, 30),   # 30-minute gap > 12-minute threshold
        ]
        result = _ENGINE.evaluate(_cdc_policy(sample_interval_minutes=6.0), readings)
        assert result.missing_window_count == 1
        assert "MISSING_SENSOR_WINDOW" in result.reason_codes

    def test_normal_gap_not_flagged(self) -> None:
        # 6-min gap ≤ 12-min threshold → no missing window
        readings = [
            _reading(5.0, 0),
            _reading(5.0, 6),
            _reading(5.0, 12),
        ]
        result = _ENGINE.evaluate(_cdc_policy(), readings)
        assert result.missing_window_count == 0
        assert "MISSING_SENSOR_WINDOW" not in result.reason_codes

    def test_multiple_gaps_counted(self) -> None:
        readings = [
            _reading(5.0, 0),
            _reading(5.0, 60),   # gap 1
            _reading(5.0, 120),  # gap 2
        ]
        result = _ENGINE.evaluate(_cdc_policy(), readings)
        assert result.missing_window_count == 2

    def test_single_reading_has_no_gaps(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(5.0, 0)])
        assert result.missing_window_count == 0


# ---------------------------------------------------------------------------
# 8. Different configurable temperature policy
# ---------------------------------------------------------------------------


class TestFrozenVaccinePolicy:
    """Frozen-vaccine policy (−25–−15 °C) classifies a room-temperature
    reading as an excursion, confirming that no thresholds are hardcoded."""

    def test_safe_within_frozen_range(self) -> None:
        result = _ENGINE.evaluate(
            _frozen_vaccine_policy(),
            [_reading(-20.0, 0), _reading(-18.0, 5), _reading(-22.0, 10)],
        )
        assert result.severity == ExcursionSeverity.SAFE

    def test_room_temperature_is_out_of_range(self) -> None:
        result = _ENGINE.evaluate(
            _frozen_vaccine_policy(),
            [_reading(-20.0, 0), _reading(4.0, 5)],   # 4 °C is way above −15 °C
        )
        assert result.severity != ExcursionSeverity.SAFE
        assert "TEMPERATURE_ABOVE_MAX" in result.reason_codes

    def test_below_frozen_range_detected(self) -> None:
        result = _ENGINE.evaluate(
            _frozen_vaccine_policy(),
            [_reading(-30.0, 0), _reading(-20.0, 5)],  # −30 < −25 lower bound
        )
        assert "TEMPERATURE_BELOW_MIN" in result.reason_codes

    def test_frozen_policy_sustained_excursion(self) -> None:
        # 3 readings × 5-min interval = 15 min > policy limit of 10 min
        readings = [
            _reading(-14.0, 0),   # OOR (above -15)
            _reading(-14.0, 5),   # OOR
            _reading(-14.0, 10),  # OOR  — 15 min continuous > 10 min limit
        ]
        result = _ENGINE.evaluate(_frozen_vaccine_policy(), readings)
        assert result.severity == ExcursionSeverity.URGENT_ESCALATION
        assert "SUSTAINED_EXCURSION" in result.reason_codes

    def test_frozen_out_of_range_severity_is_out_of_range(self) -> None:
        """Frozen policy uses OUT_OF_RANGE (not EXCURSION_REVIEW) for short excursions."""
        result = _ENGINE.evaluate(
            _frozen_vaccine_policy(),
            [_reading(-20.0, 0), _reading(-14.0, 5), _reading(-20.0, 10)],  # 1 reading OOR
        )
        assert result.severity == ExcursionSeverity.OUT_OF_RANGE


# ---------------------------------------------------------------------------
# 9. Determinism — identical inputs → identical outputs
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Repeated calls with the same inputs must produce equal results."""

    def test_repeated_calls_are_equal(self) -> None:
        policy = _cdc_policy()
        r1 = _ENGINE.evaluate(policy, _DEMO_READINGS)
        r2 = _ENGINE.evaluate(policy, _DEMO_READINGS)
        assert r1 == r2

    def test_reason_codes_stable_across_calls(self) -> None:
        policy = _cdc_policy()
        results = [_ENGINE.evaluate(policy, _DEMO_READINGS) for _ in range(10)]
        codes = [tuple(r.reason_codes) for r in results]
        assert len(set(codes)) == 1, f"Reason codes differ: {codes}"

    def test_severity_stable_across_calls(self) -> None:
        policy = _cdc_policy()
        severities = {_ENGINE.evaluate(policy, _DEMO_READINGS).severity for _ in range(10)}
        assert len(severities) == 1

    def test_unsorted_input_gives_same_result_as_sorted(self) -> None:
        """Engine must sort readings internally; input order must not matter."""
        policy = _cdc_policy()
        sorted_result = _ENGINE.evaluate(policy, _DEMO_READINGS)
        reversed_result = _ENGINE.evaluate(policy, list(reversed(_DEMO_READINGS)))
        assert sorted_result == reversed_result

    def test_statistics_stable(self) -> None:
        policy = _cdc_policy()
        stats = [
            (r.min_temp_c, r.max_temp_c, r.total_out_of_range_minutes)
            for r in (_ENGINE.evaluate(policy, _DEMO_READINGS) for _ in range(5))
        ]
        assert len(set(stats)) == 1


# ---------------------------------------------------------------------------
# 10–11. Reason codes and statistics (combined spot checks)
# ---------------------------------------------------------------------------


class TestReasonCodesAndStats:
    """Focused checks on each individual reason code and statistic field."""

    def test_no_above_max_code_when_all_in_range(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(5.0, 0)])
        assert "TEMPERATURE_ABOVE_MAX" not in result.reason_codes

    def test_below_min_code_added(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(1.0, 0)])
        assert "TEMPERATURE_BELOW_MIN" in result.reason_codes

    def test_both_above_and_below_codes_can_coexist(self) -> None:
        result = _ENGINE.evaluate(
            _cdc_policy(),
            [_reading(10.0, 0), _reading(1.0, 6)],  # above max then below min
        )
        assert "TEMPERATURE_ABOVE_MAX" in result.reason_codes
        assert "TEMPERATURE_BELOW_MIN" in result.reason_codes

    def test_total_oor_minutes_counts_all_oor_readings(self) -> None:
        # 2 OOR readings × 6 min = 12 min
        result = _ENGINE.evaluate(
            _cdc_policy(),
            [_reading(9.0, 0), _reading(9.0, 6), _reading(5.0, 12)],
        )
        assert result.total_out_of_range_minutes == pytest.approx(12.0)

    def test_max_continuous_excursion_for_non_contiguous_oor(self) -> None:
        # OOR, SAFE, OOR, OOR  → longest run = 2 × 6 min = 12 min
        result = _ENGINE.evaluate(
            _cdc_policy(),
            [_reading(9.0, 0), _reading(5.0, 6), _reading(9.0, 12), _reading(9.0, 18)],
        )
        assert result.max_continuous_excursion_minutes == pytest.approx(12.0)

    def test_result_is_frozen(self) -> None:
        """ColdChainResult must be immutable (frozen=True)."""
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(5.0, 0)])
        with pytest.raises((AttributeError, TypeError)):
            result.severity = ExcursionSeverity.URGENT_ESCALATION  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 12. Timestamp sort order correctness
# ---------------------------------------------------------------------------


class TestTimestampSorting:
    """Readings passed in reverse chronological order must give the same
    result as readings in forward order."""

    def test_reverse_order_same_as_forward(self) -> None:
        forward = [
            _reading(5.0, 0),
            _reading(9.0, 6),   # OOR
            _reading(5.0, 12),
        ]
        backward = list(reversed(forward))
        r_fwd = _ENGINE.evaluate(_cdc_policy(), forward)
        r_bwd = _ENGINE.evaluate(_cdc_policy(), backward)
        assert r_fwd.severity == r_bwd.severity
        assert r_fwd.reason_codes == r_bwd.reason_codes
        assert r_fwd.out_of_range_count == r_bwd.out_of_range_count

    def test_gap_detection_uses_sorted_order(self) -> None:
        """Gap between readings is only meaningful after sorting."""
        # If unsorted, naïve consecutive-diff would give wrong gaps.
        readings = [
            _reading(5.0, 60),  # later reading first
            _reading(5.0, 0),   # earlier reading second
        ]
        result = _ENGINE.evaluate(_cdc_policy(), readings)
        # gap = 60 min > 12 min threshold → 1 missing window
        assert result.missing_window_count == 1


# ---------------------------------------------------------------------------
# 13. Boundary values
# ---------------------------------------------------------------------------


class TestBoundaryValues:
    """Values exactly at policy min/max are SAFE (inclusive bounds)."""

    def test_exact_min_is_safe(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(2.0, 0)])
        assert result.severity == ExcursionSeverity.SAFE
        assert result.out_of_range_count == 0

    def test_exact_max_is_safe(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(8.0, 0)])
        assert result.severity == ExcursionSeverity.SAFE
        assert result.out_of_range_count == 0

    def test_just_above_max_is_oor(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(8.001, 0)])
        assert result.out_of_range_count == 1
        assert result.severity != ExcursionSeverity.SAFE

    def test_just_below_min_is_oor(self) -> None:
        result = _ENGINE.evaluate(_cdc_policy(), [_reading(1.999, 0)])
        assert result.out_of_range_count == 1
        assert result.severity != ExcursionSeverity.SAFE


# ---------------------------------------------------------------------------
# 14. _max_continuous_run utility
# ---------------------------------------------------------------------------


class TestMaxContinuousRun:
    """Direct tests of the _max_continuous_run pure helper."""

    def test_empty_list_returns_zero(self) -> None:
        assert _max_continuous_run([]) == 0

    def test_all_false_returns_zero(self) -> None:
        assert _max_continuous_run([False, False, False]) == 0

    def test_all_true_returns_length(self) -> None:
        assert _max_continuous_run([True, True, True]) == 3

    def test_single_true(self) -> None:
        assert _max_continuous_run([True]) == 1

    def test_non_contiguous(self) -> None:
        # [T, F, T, T, F, T] → longest run = 2
        assert _max_continuous_run([True, False, True, True, False, True]) == 2

    def test_run_at_start(self) -> None:
        assert _max_continuous_run([True, True, False, True]) == 2

    def test_run_at_end(self) -> None:
        assert _max_continuous_run([False, True, True, True]) == 3

    def test_interleaved(self) -> None:
        assert _max_continuous_run([True, False, True, False, True]) == 1
