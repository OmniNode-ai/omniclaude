# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Enum for intent types recognised by the NL Intent Pipeline.

This enum is the cross-process authority for intent classification — used
at the plan DAG generator, ambiguity gate, and ticket compiler boundaries.
"""

from __future__ import annotations

from enum import Enum


class EnumIntentType(str, Enum):
    """Typed intent classifications for the NL Intent-Plan-Ticket Compiler.

    Variants align with the intent classes produced by the OMN-2348 Intent
    Intelligence Framework (e.g. SECURITY, CODE, REFACTOR). Additional
    compiler-specific variants (FEATURE, EPIC_DECOMPOSITION, BUG_FIX) are
    defined here for plan-level work.
    """

    # --- Inherited from OMN-2348 intent classes ---
    SECURITY = "SECURITY"
    CODE = "CODE"
    REFACTOR = "REFACTOR"
    TESTING = "TESTING"
    DOCUMENTATION = "DOCUMENTATION"
    REVIEW = "REVIEW"
    DEBUGGING = "DEBUGGING"
    GENERAL = "GENERAL"

    # --- Compiler-specific intent types ---
    FEATURE = "FEATURE"
    BUG_FIX = "BUG_FIX"
    EPIC_DECOMPOSITION = "EPIC_DECOMPOSITION"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    UNKNOWN = "UNKNOWN"


__all__ = ["EnumIntentType"]
