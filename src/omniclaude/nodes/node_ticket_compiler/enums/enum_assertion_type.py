# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Enum for verifiable assertion types in ticket test contracts."""

from __future__ import annotations

from enum import Enum


class EnumAssertionType(str, Enum):
    """Types of verifiable assertions in a ticket's test contract.

    Each assertion type maps to a specific verification mechanism that can
    be executed without manual interpretation.
    """

    COMMAND_EXIT_CODE = "COMMAND_EXIT_CODE"
    FILE_EXISTS = "FILE_EXISTS"
    FILE_CONTAINS = "FILE_CONTAINS"
    TEST_PASSES = "TEST_PASSES"
    LINT_CLEAN = "LINT_CLEAN"
    TYPE_CHECK_PASSES = "TYPE_CHECK_PASSES"
    API_RESPONSE = "API_RESPONSE"
    METRIC_THRESHOLD = "METRIC_THRESHOLD"
    PR_REVIEW_APPROVED = "PR_REVIEW_APPROVED"
    MANUAL_VERIFICATION = "MANUAL_VERIFICATION"


__all__ = ["EnumAssertionType"]
