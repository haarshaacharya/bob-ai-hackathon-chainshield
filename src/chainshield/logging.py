from __future__ import annotations

"""
ChainShield Deterministic Structured Logging & Observability Layer.

Design Constraints (AGENTS.md & Task 14)
---------------------------------------
- Standard Python ``logging`` library only (no mandatory third-party network aggregators).
- Consistent structured log fields:
    - timestamp (ISO-8601 UTC)
    - level (INFO, WARNING, ERROR, DEBUG)
    - event (operational event identifier)
    - shipment_id
    - disruption_id
    - asset_id
    - decision_type
    - reason_codes
    - message
- Sensitive credentials, API keys, tokens, and secrets are strictly redacted.
- Deterministic, offline-compatible, and avoids duplicate logging.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Operational Event Constants
# ---------------------------------------------------------------------------

EVENT_APP_STARTUP = "APP_STARTUP"
EVENT_DISRUPTION_ACTIVATION = "DISRUPTION_ACTIVATION"
EVENT_IMPACT_EVALUATION = "IMPACT_EVALUATION"
EVENT_COLD_CHAIN_EVALUATION = "COLD_CHAIN_EVALUATION"
EVENT_OPTIMIZATION_EXECUTION = "OPTIMIZATION_EXECUTION"
EVENT_EVIDENCE_CREATION = "EVIDENCE_CREATION"
EVENT_EXPLANATION_GENERATION = "EXPLANATION_GENERATION"
EVENT_ACTION_PLAN_EXPORT = "ACTION_PLAN_EXPORT"
EVENT_API_ERROR = "API_ERROR"

ALL_EVENTS = {
    EVENT_APP_STARTUP,
    EVENT_DISRUPTION_ACTIVATION,
    EVENT_IMPACT_EVALUATION,
    EVENT_COLD_CHAIN_EVALUATION,
    EVENT_OPTIMIZATION_EXECUTION,
    EVENT_EVIDENCE_CREATION,
    EVENT_EXPLANATION_GENERATION,
    EVENT_ACTION_PLAN_EXPORT,
    EVENT_API_ERROR,
}

# ---------------------------------------------------------------------------
# Secret Redaction
# ---------------------------------------------------------------------------

_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|password|bearer|auth|credentials)",
)
_BEARER_STRING_PATTERN = re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{10,}")
_APIKEY_STRING_PATTERN = re.compile(r"(?i)(?:key|token|secret)=['\"][^'\"]{10,}['\"]")


def redact_secrets(val: Any) -> Any:
    """Recursively mask sensitive values in dicts, lists, and strings."""
    if isinstance(val, Mapping):
        redacted_dict: dict[str, Any] = {}
        for k, v in val.items():
            if _SECRET_KEY_PATTERN.search(str(k)):
                redacted_dict[k] = "***REDACTED***"
            else:
                redacted_dict[k] = redact_secrets(v)
        return redacted_dict

    if isinstance(val, (list, tuple, set)):
        return [redact_secrets(item) for item in val]

    if isinstance(val, str):
        masked = _BEARER_STRING_PATTERN.sub("bearer ***REDACTED***", val)
        masked = _APIKEY_STRING_PATTERN.sub("key=***REDACTED***", masked)
        return masked

    return val


# ---------------------------------------------------------------------------
# Structured Formatter
# ---------------------------------------------------------------------------

class StructuredLogFormatter(logging.Formatter):
    """Formats log records with standard structured fields and secret redaction."""

    def __init__(self, json_format: bool = False) -> None:
        super().__init__()
        self.json_format = json_format

    def format(self, record: logging.LogRecord) -> str:
        # Generate ISO-8601 UTC timestamp
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        # Extract structured context fields
        event = getattr(record, "event", "GENERIC_LOG")
        shipment_id = getattr(record, "shipment_id", None)
        disruption_id = getattr(record, "disruption_id", None)
        asset_id = getattr(record, "asset_id", None)
        decision_type = getattr(record, "decision_type", None)
        reason_codes = getattr(record, "reason_codes", None)
        extra_data = getattr(record, "extra_data", None)

        msg = record.getMessage()
        msg = str(redact_secrets(msg))

        log_dict: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "event": event,
            "shipment_id": shipment_id,
            "disruption_id": disruption_id,
            "asset_id": asset_id,
            "decision_type": decision_type,
            "reason_codes": reason_codes,
            "message": msg,
        }

        if extra_data and isinstance(extra_data, dict):
            for k, v in extra_data.items():
                if k not in log_dict:
                    log_dict[k] = redact_secrets(v)

        # Redact the whole payload to ensure no keys/values leak
        safe_dict = redact_secrets(log_dict)

        if self.json_format:
            return json.dumps(safe_dict, default=str)

        # Text format: compact structured key-value line
        parts: list[str] = [
            timestamp,
            f"[{record.levelname}]",
            f"event={event}",
        ]
        if shipment_id is not None:
            parts.append(f"shipment_id={shipment_id}")
        if disruption_id is not None:
            parts.append(f"disruption_id={disruption_id}")
        if asset_id is not None:
            parts.append(f"asset_id={asset_id}")
        if decision_type is not None:
            parts.append(f"decision_type={decision_type}")
        if reason_codes:
            parts.append(f"reason_codes={reason_codes}")

        parts.append(f"msg={msg}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Helper: log_event
# ---------------------------------------------------------------------------

def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str = "",
    *,
    shipment_id: str | None = None,
    disruption_id: str | None = None,
    asset_id: str | None = None,
    decision_type: str | None = None,
    reason_codes: list[str] | None = None,
    **extra: Any,
) -> None:
    """Log an event with guaranteed structured context fields."""
    if not logger.isEnabledFor(level):
        return

    # If a dict was explicitly passed as extra=..., merge it into extra
    if "extra" in extra and isinstance(extra["extra"], dict):
        nested = extra.pop("extra")
        extra.update(nested)

    clean_extra = redact_secrets(extra) if extra else {}

    record_extra: dict[str, Any] = {
        "event": event,
        "shipment_id": shipment_id,
        "disruption_id": disruption_id,
        "asset_id": asset_id,
        "decision_type": decision_type,
        "reason_codes": reason_codes,
        "extra_data": clean_extra,
    }

    logger.log(level, message, extra=record_extra)


# ---------------------------------------------------------------------------
# Setup / Configuration
# ---------------------------------------------------------------------------

_CHAINSHIELD_LOGGER_NAME = "chainshield"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the chainshield namespace."""
    if not name or name == _CHAINSHIELD_LOGGER_NAME:
        return logging.getLogger(_CHAINSHIELD_LOGGER_NAME)
    if not name.startswith(_CHAINSHIELD_LOGGER_NAME):
        return logging.getLogger(f"{_CHAINSHIELD_LOGGER_NAME}.{name}")
    return logging.getLogger(name)


def setup_logging(
    level: int = logging.INFO,
    json_format: bool = False,
    handler: logging.Handler | None = None,
) -> logging.Logger:
    """Configure chainshield package-level logging idempotently."""
    logger = logging.getLogger(_CHAINSHIELD_LOGGER_NAME)
    logger.setLevel(level)

    # Avoid adding multiple duplicate handlers on repeated calls
    existing_handlers = [
        h for h in logger.handlers
        if isinstance(getattr(h, "formatter", None), StructuredLogFormatter)
    ]
    for h in existing_handlers:
        logger.removeHandler(h)

    target_handler = handler if handler is not None else logging.StreamHandler()
    target_handler.setLevel(level)
    target_handler.setFormatter(StructuredLogFormatter(json_format=json_format))
    logger.addHandler(target_handler)

    return logger
