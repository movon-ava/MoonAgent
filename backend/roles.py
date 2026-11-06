"""Role → model routing.

Solvers are expensive; auxiliary work (writeups, digests, triage notes) does not
need the strongest model. ``ROLE_MODELS`` maps a role to a model spec::

    ROLE_MODELS={"writeup": "deepseek/deepseek-flash", "triage": "..."}

Unset roles fall back to the first configured solver model, so the feature is
invisible until someone opts in.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

ROLES = ("writeup", "triage", "digest")


def role_models(settings: Any) -> dict[str, str]:
    raw = str(getattr(settings, "role_models", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("role_models is not valid JSON: %r", raw[:120])
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(v).strip()}


def model_for(role: str, settings: Any, default: str | None = None) -> str:
    mapping = role_models(settings)
    if role in mapping and mapping[role].strip():
        return mapping[role].strip()
    if default:
        return default
    from backend.models import default_model_specs

    specs = default_model_specs(settings)
    return specs[0] if specs else "deepseek/deepseek-flash"
