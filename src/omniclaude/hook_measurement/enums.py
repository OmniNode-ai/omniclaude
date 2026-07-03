# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Enums for the hook measurement harness (OMN-13278)."""

from __future__ import annotations

from enum import StrEnum


class EnumHookWindow(StrEnum):
    """The two measurement windows compared by the harness.

    ``HOOKS_OFF`` is the OMN-13244 baseline (``hooks.json`` gutted, zero onex
    hooks registered). ``HOOKS_ON`` is any window where hook registrations are
    restored. The operator records the wall-clock boundary at which the toggle
    happened; the harness assigns each tool-call record to a window by its
    ``recorded_at`` timestamp relative to that boundary.
    """

    HOOKS_OFF = "hooks_off"
    HOOKS_ON = "hooks_on"


class EnumTokenProvenance(StrEnum):
    """Provenance of the token counts on a cost record.

    Mirrors the ``token_provenance`` column written by the cost-accounting hook
    (OMN-10619). ``MEASURED`` means the tool response carried real usage data;
    ``ESTIMATED`` means the count was derived from response length.
    """

    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"
