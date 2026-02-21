# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Enum for work unit types within a Plan DAG node."""

from __future__ import annotations

from enum import Enum


class EnumWorkUnitType(str, Enum):
    """Types of work units that can appear as nodes in a Plan DAG.

    Each work unit type corresponds to a category of executable work
    that maps to a specific ticket template at the compilation stage.
    """

    FEATURE_IMPLEMENTATION = "FEATURE_IMPLEMENTATION"
    BUG_FIX = "BUG_FIX"
    REFACTORING = "REFACTORING"
    TEST_SUITE = "TEST_SUITE"
    DOCUMENTATION = "DOCUMENTATION"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SECURITY_PATCH = "SECURITY_PATCH"
    CODE_REVIEW = "CODE_REVIEW"
    INVESTIGATION = "INVESTIGATION"
    EPIC_TICKET = "EPIC_TICKET"
    GENERIC = "GENERIC"


__all__ = ["EnumWorkUnitType"]
