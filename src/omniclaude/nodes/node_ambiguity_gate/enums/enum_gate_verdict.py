# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Verdict returned by the ambiguity gate for each work unit."""

from __future__ import annotations

from enum import Enum


class EnumGateVerdict(str, Enum):
    """Outcome of the ambiguity gate check for a single work unit.

    PASS  — the work unit is unambiguous; ticket compilation may proceed.
    FAIL  — one or more unresolved ambiguities detected; compilation blocked.
    """

    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"


__all__ = ["EnumGateVerdict"]
