"""Enumeration of gap categories for the gap-analysis skill."""

from __future__ import annotations

from enum import Enum


class EnumGapCategory(str, Enum):
    """Categories of integration drift found during gap analysis."""

    CONTRACT_DRIFT = "CONTRACT_DRIFT"
    MISSING_TEST = "MISSING_TEST"
    ARCHITECTURE_VIOLATION = "ARCHITECTURE_VIOLATION"
    MISSING_NODE_TYPE = "MISSING_NODE_TYPE"
    UNCOVERED_REQUIREMENT = "UNCOVERED_REQUIREMENT"
