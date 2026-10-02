from __future__ import annotations

"""
ChainShield optional watsonx.ai explanation integration with deterministic fallback.

Design constraints (AGENTS.md)
-------------------------------
- watsonx.ai is purely optional and used for natural language explanation ONLY.
- It never makes or modifies operational decisions.
- If WATSONX_ENABLED=false, NETWORK_REQUIRED=false, or credentials are missing,
  no external network call is ever made; deterministic fallback template is used.
- Any external call is guarded with a strict timeout (2.5s budget) and on any
  failure, error, or timeout, immediately falls back to generate_fallback_explanation().
- The application must never crash when watsonx credentials are absent.
"""

import logging
from typing import Any

from chainshield.config import ChainShieldConfig, get_config
from chainshield.explanation.fallback import generate_fallback_explanation
from chainshield.logging import EVENT_EXPLANATION_GENERATION, get_logger, log_event

logger = get_logger("explanation")



def generate_explanation_with_fallback(
    decision: dict[str, Any],
    config: ChainShieldConfig | None = None,
) -> dict[str, Any]:
    """Generate an explanation for a decision, falling back to deterministic template.

    Parameters
    ----------
    decision:
        Structured decision payload containing kind, shipment_id, reason_codes,
        recommended_route, cold_chain, and evidence.
    config:
        Runtime configuration. If None, loaded from environment via get_config().

    Returns
    -------
    dict[str, Any]
        Dictionary matching the ExplanationResponse schema:
        - summary: str
        - why_affected: list[str]
        - recommended_action: str
        - evidence: list[str]
        - uncertainties: list[str]
        - generated_by: str
        - model_used: str | None
    """
    cfg = config or get_config()

    if not cfg.can_call_watsonx:
        explanation = generate_fallback_explanation(decision)
    else:
        # When watsonx is configured and allowed, attempt guarded call with 2.5s timeout.
        try:
            explanation = _call_watsonx_with_timeout(decision, cfg)
            if explanation is None:
                explanation = generate_fallback_explanation(decision)
        except Exception as exc:
            logger.warning(
                "watsonx.ai explanation failed or timed out (%s: %s); degrading to deterministic fallback",
                type(exc).__name__,
                exc,
            )
            explanation = generate_fallback_explanation(decision)

    log_event(
        logger,
        logging.INFO,
        EVENT_EXPLANATION_GENERATION,
        f"Generated explanation for {decision.get('shipment_id')}",
        shipment_id=decision.get("shipment_id"),
        disruption_id=decision.get("disruption"),
        decision_type=decision.get("kind"),
        reason_codes=decision.get("reason_codes"),
        generated_by=explanation.get("generated_by"),
        model_used=explanation.get("model_used"),
    )

    return explanation


def _call_watsonx_with_timeout(
    decision: dict[str, Any],
    cfg: ChainShieldConfig,
) -> dict[str, Any] | None:
    """Attempt to call IBM watsonx.ai with strict timeout budget.

    Lazy imports ibm_watsonx_ai or requests if available; on any issue, returns None.
    """
    import concurrent.futures

    timeout = cfg.watsonx_timeout_seconds

    def _execute_call() -> dict[str, Any]:
        # Lazy import optional watsonx SDK
        try:
            from ibm_watsonx_ai.foundation_models import Model  # type: ignore
        except ImportError:
            # SDK not installed -> cannot call watsonx
            raise RuntimeError("ibm_watsonx_ai SDK not installed")

        credentials = {
            "url": cfg.watsonx_url or "https://us-south.ml.cloud.ibm.com",
            "apikey": cfg.watsonx_apikey,
        }

        model = Model(
            model_id=cfg.watsonx_model_id,
            credentials=credentials,
            project_id=cfg.watsonx_project_id,
        )

        prompt = (
            f"Explain the following supply-chain decision deterministically:\n"
            f"Shipment: {decision.get('shipment_id')}\n"
            f"Kind: {decision.get('kind')}\n"
            f"Reasons: {decision.get('reason_codes')}\n"
        )
        generated_text = model.generate_text(prompt=prompt)

        # Fallback template provides the baseline structure, enriched with model output
        base = generate_fallback_explanation(decision)
        base["summary"] = str(generated_text).strip() or base["summary"]
        base["generated_by"] = "watsonx.ai"
        base["model_used"] = cfg.watsonx_model_id
        return base

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_execute_call)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(
                f"watsonx.ai call timed out after {timeout:.1f}s budget"
            )
