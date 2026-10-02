from __future__ import annotations

from chainshield.explanation.fallback import generate_fallback_explanation
from chainshield.explanation.watsonx import generate_explanation_with_fallback

__all__ = [
    "generate_fallback_explanation",
    "generate_explanation_with_fallback",
]
