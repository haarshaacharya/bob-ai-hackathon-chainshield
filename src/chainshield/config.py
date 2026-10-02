from __future__ import annotations

"""
ChainShield offline-first configuration module.

Responsibilities
----------------
- Centralizes all environment configuration flags:
    DEMO_MODE            (default: True)
    WATSONX_ENABLED      (default: False)
    NETWORK_REQUIRED     (default: False)
    WATSONX_APIKEY       (default: None)
    WATSONX_PROJECT_ID   (default: None)
    WATSONX_URL          (default: None)
- Ensures offline operation by default: no network calls, no external credentials needed.
- Enforces strict external call timeouts (default 2.5s) per AGENTS.md.
- Never crashes when external credentials are absent or invalid.
"""

import os
from dataclasses import dataclass
from typing import Any, Mapping

_TRUE_VALUES = {"true", "1", "yes", "t", "y", "enabled", "on"}
_FALSE_VALUES = {"false", "0", "no", "f", "n", "disabled", "off"}


def _parse_bool(value: Any, default: bool = False) -> bool:
    """Parse a boolean value or string into a bool safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    str_val = str(value).strip().lower()
    if str_val in _TRUE_VALUES:
        return True
    if str_val in _FALSE_VALUES:
        return False
    return default


def _parse_float(value: Any, default: float = 2.5) -> float:
    """Parse a float value safely, falling back to default on error."""
    if value is None:
        return default
    try:
        f = float(value)
        return f if f > 0 else default
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class ChainShieldConfig:
    """Immutable configuration container for ChainShield runtime settings."""

    demo_mode: bool = True
    watsonx_enabled: bool = False
    network_required: bool = False
    watsonx_apikey: str | None = None
    watsonx_project_id: str | None = None
    watsonx_url: str | None = None
    watsonx_model_id: str = "ibm/granite-3-8b-instruct"
    watsonx_timeout_seconds: float = 2.5
    external_call_timeout_seconds: float = 2.5

    @property
    def is_offline(self) -> bool:
        """True when the system operates without mandatory network access."""
        return not self.network_required

    @property
    def can_call_watsonx(self) -> bool:
        """True only if watsonx is enabled, network is allowed, and credentials exist."""
        return bool(
            self.watsonx_enabled
            and self.network_required
            and self.watsonx_apikey
            and self.watsonx_project_id
        )

    def to_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        """Convert config to dictionary, redacting any API credentials by default."""
        apikey_val = self.watsonx_apikey
        if redact_secrets and apikey_val:
            apikey_val = "***REDACTED***"

        return {
            "demo_mode": self.demo_mode,
            "watsonx_enabled": self.watsonx_enabled,
            "network_required": self.network_required,
            "is_offline": self.is_offline,
            "can_call_watsonx": self.can_call_watsonx,
            "watsonx_apikey": apikey_val,
            "watsonx_project_id": self.watsonx_project_id,
            "watsonx_url": self.watsonx_url,
            "watsonx_model_id": self.watsonx_model_id,
            "watsonx_timeout_seconds": self.watsonx_timeout_seconds,
            "external_call_timeout_seconds": self.external_call_timeout_seconds,
        }


def load_config(env: Mapping[str, str] | None = None) -> ChainShieldConfig:
    """Load and parse ChainShield configuration from environment or mapping.

    Never raises exceptions on missing or unexpected values.
    """
    e = os.environ if env is None else env

    demo_mode = _parse_bool(e.get("DEMO_MODE"), default=True)
    watsonx_enabled = _parse_bool(e.get("WATSONX_ENABLED"), default=False)
    network_required = _parse_bool(e.get("NETWORK_REQUIRED"), default=False)

    watsonx_apikey = e.get("WATSONX_APIKEY") or e.get("WATSONX_API_KEY")
    if watsonx_apikey:
        watsonx_apikey = watsonx_apikey.strip()
        if not watsonx_apikey:
            watsonx_apikey = None

    watsonx_project_id = e.get("WATSONX_PROJECT_ID")
    if watsonx_project_id:
        watsonx_project_id = watsonx_project_id.strip()
        if not watsonx_project_id:
            watsonx_project_id = None

    watsonx_url = e.get("WATSONX_URL")
    if watsonx_url:
        watsonx_url = watsonx_url.strip()
        if not watsonx_url:
            watsonx_url = None

    watsonx_model_id = e.get("WATSONX_MODEL_ID", "ibm/granite-3-8b-instruct").strip()
    if not watsonx_model_id:
        watsonx_model_id = "ibm/granite-3-8b-instruct"

    watsonx_timeout = _parse_float(e.get("WATSONX_TIMEOUT_SECONDS"), default=2.5)
    external_timeout = _parse_float(e.get("EXTERNAL_CALL_TIMEOUT_SECONDS"), default=2.5)

    return ChainShieldConfig(
        demo_mode=demo_mode,
        watsonx_enabled=watsonx_enabled,
        network_required=network_required,
        watsonx_apikey=watsonx_apikey,
        watsonx_project_id=watsonx_project_id,
        watsonx_url=watsonx_url,
        watsonx_model_id=watsonx_model_id,
        watsonx_timeout_seconds=watsonx_timeout,
        external_call_timeout_seconds=external_timeout,
    )


def get_config() -> ChainShieldConfig:
    """Return current configuration loaded from environment variables."""
    return load_config()
