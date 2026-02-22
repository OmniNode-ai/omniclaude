# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Default Ambiguity Gate handler.

Enforces zero-ambiguity at the Plan→Ticket boundary.

Ambiguity is expected and permitted upstream (NL→Intent stage).
Past this gate, any unresolved ambiguity causes the work unit to be
quarantined: compilation is blocked and a typed AmbiguityGateError is
raised with the full set of detected flags.

Resolution paths (CLARIFICATION or INFERENCE) must be recorded in the
Intent object before reaching this gate; they are surfaced via the
resolution_path field in ModelGateCheckRequest context.
"""

from __future__ import annotations

import logging

from omniclaude.nodes.node_ambiguity_gate.enums.enum_ambiguity_type import (
    EnumAmbiguityType,
)
from omniclaude.nodes.node_ambiguity_gate.enums.enum_gate_verdict import EnumGateVerdict
from omniclaude.nodes.node_ambiguity_gate.models.model_ambiguity_flag import (
    ModelAmbiguityFlag,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_ambiguity_gate_error import (
    AmbiguityGateError,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_gate_check_request import (
    ModelGateCheckRequest,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_gate_check_result import (
    ModelGateCheckResult,
)

__all__ = ["HandlerAmbiguityGateDefault"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ambiguity detection thresholds
# ---------------------------------------------------------------------------

# A title shorter than this is considered too vague to describe a work unit
_TITLE_MIN_WORDS = 3

# A description shorter than this many characters is considered missing
_DESCRIPTION_MIN_CHARS = 10

# Unit types that are considered unmapped / unknown
_UNKNOWN_UNIT_TYPES = frozenset({"UNKNOWN", "GENERIC"})

# Context keys that are required for specific unit types
_REQUIRED_CONTEXT_KEYS: dict[str, frozenset[str]] = {
    "SECURITY_PATCH": frozenset({"vulnerability"}),
    "INFRASTRUCTURE": frozenset({"component"}),
    "CODE_REVIEW": frozenset({"pr_url"}),
}


class HandlerAmbiguityGateDefault:
    """Default handler for the Plan→Ticket ambiguity gate.

    Evaluates each work unit for ambiguity and either passes it cleanly
    (PASS verdict) or raises an AmbiguityGateError (FAIL verdict) listing
    all detected flags with suggested resolutions.
    """

    @property
    def handler_key(self) -> str:
        """Registry key for handler lookup."""
        return "default"

    def check(
        self,
        request: ModelGateCheckRequest,
    ) -> ModelGateCheckResult:
        """Evaluate a work unit for ambiguity.

        Args:
            request: Gate check request containing work unit metadata.

        Returns:
            ModelGateCheckResult with PASS verdict if no ambiguity detected.

        Raises:
            AmbiguityGateError: If any unresolved ambiguity is detected.
                The error carries the full ModelGateCheckResult with FAIL
                verdict and all flags.
        """
        flags = list(_detect_ambiguities(request))

        verdict = EnumGateVerdict.FAIL if flags else EnumGateVerdict.PASS

        result = ModelGateCheckResult(
            unit_id=request.unit_id,
            verdict=verdict,
            ambiguity_flags=tuple(flags),
            dag_id=request.dag_id,
            intent_id=request.intent_id,
        )

        if verdict == EnumGateVerdict.FAIL:
            logger.warning(
                "Ambiguity gate FAILED for unit=%s (dag=%s, flags=%d)",
                request.unit_id,
                request.dag_id,
                len(flags),
            )
            raise AmbiguityGateError(result)

        logger.debug(
            "Ambiguity gate PASSED for unit=%s (dag=%s)",
            request.unit_id,
            request.dag_id,
        )
        return result


# ---------------------------------------------------------------------------
# Internal detection helpers
# ---------------------------------------------------------------------------


def _detect_ambiguities(
    request: ModelGateCheckRequest,
) -> list[ModelAmbiguityFlag]:
    """Run all ambiguity detectors on a work unit request.

    Returns a list of all detected ambiguity flags.  An empty list means
    the work unit is unambiguous and may proceed to ticket compilation.
    """
    flags: list[ModelAmbiguityFlag] = []

    _check_title(request, flags)
    _check_description(request, flags)
    _check_unit_type(request, flags)
    _check_required_context(request, flags)

    return flags


def _check_title(
    request: ModelGateCheckRequest,
    flags: list[ModelAmbiguityFlag],
) -> None:
    """Flag titles that are too vague (fewer than _TITLE_MIN_WORDS meaningful words)."""
    words = [w for w in request.unit_title.split() if w]
    if len(words) < _TITLE_MIN_WORDS:
        flags.append(
            ModelAmbiguityFlag(
                ambiguity_type=EnumAmbiguityType.TITLE_TOO_VAGUE,
                description=(
                    f"Work unit title {request.unit_title!r} has {len(words)} word(s); "
                    f"at least {_TITLE_MIN_WORDS} words are required to describe "
                    "a concrete unit of work."
                ),
                suggested_resolution=(
                    "Expand the title to clearly describe what must be done, "
                    "e.g. 'Add OAuth2 login endpoint to AuthService'."
                ),
                field_name="unit_title",
            )
        )


def _check_description(
    request: ModelGateCheckRequest,
    flags: list[ModelAmbiguityFlag],
) -> None:
    """Flag work units with a missing or effectively empty description."""
    if len(request.unit_description.strip()) < _DESCRIPTION_MIN_CHARS:
        flags.append(
            ModelAmbiguityFlag(
                ambiguity_type=EnumAmbiguityType.DESCRIPTION_MISSING,
                description=(
                    "Work unit description is absent or too short to describe "
                    "the required work."
                ),
                suggested_resolution=(
                    "Provide a description of at least one sentence that explains "
                    "what this work unit must accomplish and why."
                ),
                field_name="unit_description",
            )
        )


def _check_unit_type(
    request: ModelGateCheckRequest,
    flags: list[ModelAmbiguityFlag],
) -> None:
    """Flag work units whose type cannot be mapped to a ticket template."""
    if request.unit_type.upper() in _UNKNOWN_UNIT_TYPES:
        flags.append(
            ModelAmbiguityFlag(
                ambiguity_type=EnumAmbiguityType.UNKNOWN_UNIT_TYPE,
                description=(
                    f"Work unit type {request.unit_type!r} cannot be mapped "
                    "to a known ticket template."
                ),
                suggested_resolution=(
                    "Set unit_type to one of the known types: "
                    "FEATURE_IMPLEMENTATION, BUG_FIX, REFACTORING, TEST_SUITE, "
                    "DOCUMENTATION, INFRASTRUCTURE, SECURITY_PATCH, CODE_REVIEW, "
                    "INVESTIGATION, EPIC_TICKET."
                ),
                field_name="unit_type",
            )
        )


def _check_required_context(
    request: ModelGateCheckRequest,
    flags: list[ModelAmbiguityFlag],
) -> None:
    """Flag work units missing required context keys for their type."""
    required_keys = _REQUIRED_CONTEXT_KEYS.get(request.unit_type.upper(), frozenset())
    if not required_keys:
        return

    present_keys = {k for k, _ in request.context}
    missing = required_keys - present_keys
    if missing:
        for key in sorted(missing):
            flags.append(
                ModelAmbiguityFlag(
                    ambiguity_type=EnumAmbiguityType.MISSING_REQUIRED_CONTEXT,
                    description=(
                        f"Work unit of type {request.unit_type!r} requires context "
                        f"key {key!r} but it was not provided."
                    ),
                    suggested_resolution=(
                        f"Add context entry ({key!r}, <value>) to the work unit "
                        "before ticket compilation."
                    ),
                    field_name="context",
                )
            )
