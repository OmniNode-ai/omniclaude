#!/usr/bin/env python3
"""
Intent Model Hints - Configurable intent-class → model/behavior mapping

Maps classified intent classes to model recommendations, temperature hints,
validator sets, and sandbox requirements. All mappings are configurable via
Pydantic Settings (environment variables), never hardcoded.

The hint output is injected into additionalContext as human-readable text
that Claude can act on, but is NOT an override — explicit user instructions
always take precedence.

Environment variables (prefix: OMNICLAUDE_INTENT_):
    OMNICLAUDE_INTENT_SECURITY_MODEL=claude-opus-4-6
    OMNICLAUDE_INTENT_SECURITY_TEMPERATURE=0.1
    OMNICLAUDE_INTENT_SECURITY_VALIDATORS=security_audit,least_privilege
    OMNICLAUDE_INTENT_SECURITY_SANDBOX=enforced

    OMNICLAUDE_INTENT_CODE_MODEL=claude-sonnet-4-6
    OMNICLAUDE_INTENT_CODE_TEMPERATURE=0.3
    OMNICLAUDE_INTENT_CODE_VALIDATORS=code_quality,style
    OMNICLAUDE_INTENT_CODE_SANDBOX=standard

    OMNICLAUDE_INTENT_GENERAL_MODEL=claude-sonnet-4-6
    OMNICLAUDE_INTENT_GENERAL_TEMPERATURE=0.5
    OMNICLAUDE_INTENT_GENERAL_VALIDATORS=
    OMNICLAUDE_INTENT_GENERAL_SANDBOX=none
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentModelHint:
    """Model and behavioral hints for a classified intent class.

    All fields are informational recommendations, not hard overrides.
    Claude may choose to deviate based on user instruction or context.
    """

    intent_class: str
    recommended_model: str
    temperature_hint: float
    validators: list[str]
    sandbox: str  # "none", "standard", "enforced"


# ---------------------------------------------------------------------------
# Default hint table (overridable via env vars)
# ---------------------------------------------------------------------------

_DEFAULT_HINTS: dict[str, IntentModelHint] = {
    "SECURITY": IntentModelHint(
        intent_class="SECURITY",
        recommended_model="claude-opus-4-6",
        temperature_hint=0.1,
        validators=["security_audit", "least_privilege"],
        sandbox="enforced",
    ),
    "CODE": IntentModelHint(
        intent_class="CODE",
        recommended_model="claude-sonnet-4-6",
        temperature_hint=0.3,
        validators=["code_quality"],
        sandbox="standard",
    ),
    "REFACTOR": IntentModelHint(
        intent_class="REFACTOR",
        recommended_model="claude-sonnet-4-6",
        temperature_hint=0.3,
        validators=["code_quality", "style"],
        sandbox="standard",
    ),
    "TESTING": IntentModelHint(
        intent_class="TESTING",
        recommended_model="claude-sonnet-4-6",
        temperature_hint=0.2,
        validators=["test_coverage"],
        sandbox="standard",
    ),
    "DOCUMENTATION": IntentModelHint(
        intent_class="DOCUMENTATION",
        recommended_model="claude-sonnet-4-6",
        temperature_hint=0.5,
        validators=[],
        sandbox="none",
    ),
    "REVIEW": IntentModelHint(
        intent_class="REVIEW",
        recommended_model="claude-opus-4-6",
        temperature_hint=0.2,
        validators=["code_quality", "style"],
        sandbox="standard",
    ),
    "DEBUGGING": IntentModelHint(
        intent_class="DEBUGGING",
        recommended_model="claude-sonnet-4-6",
        temperature_hint=0.2,
        validators=[],
        sandbox="standard",
    ),
    "GENERAL": IntentModelHint(
        intent_class="GENERAL",
        recommended_model="claude-sonnet-4-6",
        temperature_hint=0.5,
        validators=[],
        sandbox="none",
    ),
}

_FALLBACK_HINT = IntentModelHint(
    intent_class="GENERAL",
    recommended_model="claude-sonnet-4-6",
    temperature_hint=0.5,
    validators=[],
    sandbox="none",
)


def _env_key(intent_class: str, field_name: str) -> str:
    """Build environment variable key for an intent field."""
    return f"OMNICLAUDE_INTENT_{intent_class.upper()}_{field_name.upper()}"


def _load_hint_from_env(intent_class: str, default: IntentModelHint) -> IntentModelHint:
    """Load intent hint, applying any environment variable overrides.

    Reads OMNICLAUDE_INTENT_<CLASS>_<FIELD> env vars and applies them
    over the default hint. Silently ignores invalid values (bad float, etc.)
    to preserve fail-safe behavior in hooks.

    Args:
        intent_class: The intent class to load hints for.
        default: Default hint to use as base.

    Returns:
        IntentModelHint with env overrides applied.
    """
    model = os.environ.get(_env_key(intent_class, "MODEL"), default.recommended_model)
    temperature = default.temperature_hint
    temperature_raw = os.environ.get(_env_key(intent_class, "TEMPERATURE"), "")
    if temperature_raw:
        try:
            temperature = float(temperature_raw)
        except ValueError:
            pass

    validators = list(default.validators)
    validators_raw = os.environ.get(_env_key(intent_class, "VALIDATORS"), "")
    if validators_raw is not None:
        # Empty string means no validators; only override if env var is explicitly set
        if _env_key(intent_class, "VALIDATORS") in os.environ:
            validators = [v.strip() for v in validators_raw.split(",") if v.strip()]

    sandbox = os.environ.get(_env_key(intent_class, "SANDBOX"), default.sandbox)

    return IntentModelHint(
        intent_class=intent_class,
        recommended_model=model,
        temperature_hint=temperature,
        validators=validators,
        sandbox=sandbox,
    )


def get_hint_for_intent(intent_class: str) -> IntentModelHint:
    """Get model hint for an intent class, applying env overrides.

    Args:
        intent_class: Intent class string (case-insensitive).

    Returns:
        IntentModelHint for the intent class. Falls back to GENERAL if unknown.
    """
    normalized = intent_class.upper() if intent_class else "GENERAL"
    default = _DEFAULT_HINTS.get(normalized, _FALLBACK_HINT)
    return _load_hint_from_env(normalized, default)


def format_intent_context(
    *,
    intent_class: str,
    confidence: float,
    intent_id: str = "",
) -> str:
    """Format intent classification result as human-readable additionalContext.

    Produces text that Claude can parse to understand the classified intent
    and apply appropriate model selection/validator hints.

    Args:
        intent_class: Classified intent class.
        confidence: Classification confidence (0.0-1.0).
        intent_id: Optional UUID for tracing.

    Returns:
        Multi-line string for injection into additionalContext.
    """
    hint = get_hint_for_intent(intent_class)

    confidence_pct = f"{confidence * 100:.0f}%"
    validators_str = ", ".join(hint.validators) if hint.validators else "none"
    sandbox_str = hint.sandbox

    lines: list[str] = [
        "========================================================================",
        "INTENT CLASSIFICATION",
        "========================================================================",
        f"Intent: {hint.intent_class} (confidence: {confidence_pct})",
        f"Recommended model: {hint.recommended_model}",
        f"Temperature hint: {hint.temperature_hint}",
        f"Validators: {validators_str}",
        f"Sandbox: {sandbox_str}",
    ]

    if intent_id:
        lines.append(f"Intent-Id: {intent_id}")

    lines.append(
        "NOTE: These are recommendations only. User instructions take precedence."
    )
    lines.append(
        "========================================================================"
    )

    return "\n".join(lines)
