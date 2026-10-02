from __future__ import annotations

"""
ChainShield Deterministic Cold-Chain Engine
============================================

Evaluates a sequence of ``SensorReading`` objects against a
``TemperaturePolicy`` and returns a severity classification, reason codes,
and a statistics summary.  Every threshold comes from the policy — nothing
is hardcoded in this module.

Classification rules (precedence: top = highest priority)
----------------------------------------------------------
1. ``policy is None``          → ``POLICY_REQUIRED``
2. ``readings`` is empty        → ``missing_sensor_data`` severity (from policy)
3. Any reading outside range AND total out-of-range time
   exceeds ``max_continuous_excursion_minutes`` → ``sustained_excursion`` severity
4. Any reading outside range    → ``out_of_range`` severity
5. No out-of-range readings     → ``SAFE``

Reason codes (SCREAMING_SNAKE_CASE)
------------------------------------
TEMPERATURE_ABOVE_MAX
    At least one reading exceeded ``policy.max_celsius``.
TEMPERATURE_BELOW_MIN
    At least one reading fell below ``policy.min_celsius``.
SUSTAINED_EXCURSION
    The maximum continuous out-of-range window exceeded
    ``policy.max_continuous_excursion_minutes``.
MISSING_SENSOR_WINDOW
    A gap between two consecutive readings is larger than
    twice the policy ``sample_interval_minutes`` (expected
    interval × 2 = first missed window).
NO_SENSOR_DATA
    The reading list was empty.
POLICY_REQUIRED
    No policy profile was supplied.

Usage
-----
    from chainshield.cold_chain.engine import ColdChainEngine
    from chainshield.models import TemperaturePolicy, SensorReading

    engine = ColdChainEngine()
    result = engine.evaluate(policy, readings)
    print(result.severity, result.reason_codes)
"""

from dataclasses import dataclass
from datetime import timedelta
import logging

from chainshield.logging import EVENT_COLD_CHAIN_EVALUATION, get_logger, log_event
from chainshield.models.enums import ExcursionSeverity
from chainshield.models.sensor_reading import SensorReading
from chainshield.models.temperature_policy import TemperaturePolicy

_logger = get_logger("cold_chain")



# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColdChainResult:
    """Immutable result of a cold-chain evaluation.

    Fields
    ------
    severity
        Highest severity reached during this evaluation window.
    reason_codes
        ``SCREAMING_SNAKE_CASE`` codes explaining the classification.
    min_temp_c
        Minimum observed temperature across all readings (``None`` if no data).
    max_temp_c
        Maximum observed temperature across all readings (``None`` if no data).
    total_out_of_range_minutes
        Estimated total time outside the policy range, in minutes, calculated
        as ``len(out_of_range_readings) × policy.sample_interval_minutes``.
    max_continuous_excursion_minutes
        Duration of the longest unbroken out-of-range window, in minutes.
    out_of_range_count
        Number of individual readings outside the policy range.
    missing_window_count
        Number of detected gaps larger than 2 × ``sample_interval_minutes``.
    reading_count
        Total number of readings that were evaluated.
    """

    severity: ExcursionSeverity
    reason_codes: list[str]
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    total_out_of_range_minutes: float = 0.0
    max_continuous_excursion_minutes: float = 0.0
    out_of_range_count: int = 0
    missing_window_count: int = 0
    reading_count: int = 0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ColdChainEngine:
    """Deterministic cold-chain excursion classifier.

    The engine is stateless; the same instance can evaluate multiple
    shipments concurrently without side effects.

    Examples
    --------
    >>> from chainshield.cold_chain.engine import ColdChainEngine
    >>> from chainshield.models import TemperaturePolicy, ProductClass
    >>> policy = TemperaturePolicy(
    ...     policy_id="demo",
    ...     product_class=ProductClass.REFRIGERATED_VACCINE,
    ...     min_celsius=2.0,
    ...     max_celsius=8.0,
    ...     max_continuous_excursion_minutes=15,
    ... )
    >>> engine = ColdChainEngine()
    >>> result = engine.evaluate(policy, [])
    >>> result.severity.value
    'URGENT_ESCALATION'
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        policy: TemperaturePolicy | None,
        readings: list[SensorReading],
    ) -> ColdChainResult:
        """Evaluate *readings* against *policy* and return a classification.

        Parameters
        ----------
        policy:
            The temperature policy for this shipment.  Pass ``None`` when no
            policy profile has been matched; the result will be
            ``POLICY_REQUIRED``.
        readings:
            Raw sensor readings.  They need not be pre-sorted; the engine
            sorts by timestamp internally.  An empty list triggers the
            ``missing_sensor_data`` severity rule.

        Returns
        -------
        ColdChainResult
            Frozen dataclass — safe to cache, compare, or store.
        """
        # ── 1. No policy ──────────────────────────────────────────────
        if policy is None:
            return ColdChainResult(
                severity=ExcursionSeverity.POLICY_REQUIRED,
                reason_codes=["POLICY_REQUIRED"],
            )

        # ── 2. No readings ────────────────────────────────────────────
        if not readings:
            severity = policy.severity_rules.missing_sensor_data
            return ColdChainResult(
                severity=severity,
                reason_codes=["NO_SENSOR_DATA"],
                reading_count=0,
            )

        # ── 3. Sort by timestamp ──────────────────────────────────────
        ordered = sorted(readings, key=lambda r: r.ts)

        # ── 4. Basic statistics ───────────────────────────────────────
        temps = [r.temperature_c for r in ordered]
        min_temp = min(temps)
        max_temp = max(temps)
        lo = policy.min_celsius
        hi = policy.max_celsius

        # ── 5. Missing-window detection ───────────────────────────────
        gap_threshold = timedelta(minutes=policy.sample_interval_minutes * 2)
        missing_windows = 0
        for i in range(len(ordered) - 1):
            gap = ordered[i + 1].ts - ordered[i].ts
            if gap > gap_threshold:
                missing_windows += 1

        # ── 6. Out-of-range detection and excursion windows ──────────
        oor_flags = [not (lo <= r.temperature_c <= hi) for r in ordered]
        out_of_range_count = sum(oor_flags)

        # Calculate total out-of-range time (count × sample interval)
        total_oor_minutes = out_of_range_count * policy.sample_interval_minutes

        # Calculate maximum continuous out-of-range window
        max_continuous = _max_continuous_run(oor_flags) * policy.sample_interval_minutes

        # ── 7. Build reason codes ─────────────────────────────────────
        reason_codes: list[str] = []
        if max_temp > hi:
            reason_codes.append("TEMPERATURE_ABOVE_MAX")
        if min_temp < lo:
            reason_codes.append("TEMPERATURE_BELOW_MIN")
        if max_continuous > policy.max_continuous_excursion_minutes:
            reason_codes.append("SUSTAINED_EXCURSION")
        if missing_windows > 0:
            reason_codes.append("MISSING_SENSOR_WINDOW")

        # ── 8. Determine severity ─────────────────────────────────────
        if out_of_range_count == 0:
            severity = ExcursionSeverity.SAFE
        elif max_continuous > policy.max_continuous_excursion_minutes:
            severity = policy.severity_rules.sustained_excursion
        else:
            severity = policy.severity_rules.out_of_range

        res = ColdChainResult(
            severity=severity,
            reason_codes=reason_codes,
            min_temp_c=min_temp,
            max_temp_c=max_temp,
            total_out_of_range_minutes=total_oor_minutes,
            max_continuous_excursion_minutes=max_continuous,
            out_of_range_count=out_of_range_count,
            missing_window_count=missing_windows,
            reading_count=len(ordered),
        )

        shipment_id_candidate = ordered[0].shipment_id if ordered else None
        log_event(
            _logger,
            logging.INFO,
            EVENT_COLD_CHAIN_EVALUATION,
            f"Cold-chain evaluated: severity={severity.value}",
            shipment_id=shipment_id_candidate,
            decision_type="cold_chain_policy",
            reason_codes=res.reason_codes,
            severity=severity.value,
            total_out_of_range_minutes=total_oor_minutes,
        )

        return res


# ---------------------------------------------------------------------------
# Pure utility — no dependency on model objects
# ---------------------------------------------------------------------------


def _max_continuous_run(flags: list[bool]) -> int:
    """Return the length of the longest contiguous ``True`` run in *flags*.

    Parameters
    ----------
    flags:
        Sequence of booleans where ``True`` indicates an out-of-range reading.

    Returns
    -------
    int
        Length of the longest contiguous ``True`` run (0 if none).
    """
    max_run = 0
    current = 0
    for f in flags:
        if f:
            current += 1
            if current > max_run:
                max_run = current
        else:
            current = 0
    return max_run
