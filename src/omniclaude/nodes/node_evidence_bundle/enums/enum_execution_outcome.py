# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Execution outcome for a ticket that produced an evidence bundle."""

from __future__ import annotations

from enum import Enum


class EnumExecutionOutcome(str, Enum):
    """Overall outcome of a ticket execution.

    SUCCESS — all acceptance criteria passed.
    FAILURE — one or more acceptance criteria failed.
    PARTIAL — some criteria passed; execution halted early.
    TIMEOUT — execution exceeded the maximum allowed duration.
    SKIPPED — execution was not attempted (e.g. blocked by gate).
    """

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"


__all__ = ["EnumExecutionOutcome"]
