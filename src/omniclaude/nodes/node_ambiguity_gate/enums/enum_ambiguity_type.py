# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Enumeration of ambiguity types detectable in Plan DAG work units."""

from __future__ import annotations

from enum import Enum


class EnumAmbiguityType(str, Enum):
    """Typed ambiguity categories for Plan DAG nodes.

    Ambiguity is expected and permitted at the NL→Intent stage.  Past
    the Plan→Ticket boundary it is illegal — each variant here
    corresponds to a distinct reason a work unit cannot be compiled into
    an unambiguous ticket.
    """

    # The work unit scope cannot be determined (no size signal)
    SCOPE_UNDEFINED = "SCOPE_UNDEFINED"

    # The work unit title is too vague to identify what must be done
    TITLE_TOO_VAGUE = "TITLE_TOO_VAGUE"

    # The work unit description is missing or empty
    DESCRIPTION_MISSING = "DESCRIPTION_MISSING"

    # The work unit type is unknown / cannot be mapped to a template
    UNKNOWN_UNIT_TYPE = "UNKNOWN_UNIT_TYPE"

    # The work unit has conflicting or contradictory signals
    CONFLICTING_SIGNALS = "CONFLICTING_SIGNALS"

    # Required context key/value pairs are absent
    MISSING_REQUIRED_CONTEXT = "MISSING_REQUIRED_CONTEXT"

    # The work unit references entities that cannot be resolved
    UNRESOLVED_ENTITY_REFERENCE = "UNRESOLVED_ENTITY_REFERENCE"


__all__ = ["EnumAmbiguityType"]
