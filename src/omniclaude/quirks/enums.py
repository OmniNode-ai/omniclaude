# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Enumerations for the Quirks Detector system.

Defines QuirkType (7 behavioural anti-patterns) and QuirkStage (policy
enforcement tier).  Both are ``str`` enums so they serialise cleanly to JSON
and survive round-trips through Pydantic models and database VARCHAR columns.

Related:
    - OMN-2533: Foundation ticket — models + DB schema
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

from enum import Enum


class QuirkType(str, Enum):
    """Behavioural anti-patterns detected by the Quirks Detector.

    Each value maps to a distinct detection heuristic or model check.
    """

    SYCOPHANCY = "SYCOPHANCY"
    """Agent agrees with the user even when the user is factually wrong."""

    STUB_CODE = "STUB_CODE"
    """Agent emits placeholder or stub code instead of a complete implementation."""

    NO_TESTS = "NO_TESTS"
    """Agent introduces code without writing corresponding tests."""

    LOW_EFFORT_PATCH = "LOW_EFFORT_PATCH"
    """Agent applies a superficial fix that does not address the root cause."""

    UNSAFE_ASSUMPTION = "UNSAFE_ASSUMPTION"
    """Agent assumes context that was not established (e.g. file exists, API available)."""

    IGNORED_INSTRUCTIONS = "IGNORED_INSTRUCTIONS"
    """Agent failed to follow explicit user or system instructions."""

    HALLUCINATED_API = "HALLUCINATED_API"
    """Agent references a function, class, or module that does not exist."""


class QuirkStage(str, Enum):
    """Policy enforcement tier for a detected quirk.

    Stages escalate from passive observation through warning to hard blocking.
    """

    OBSERVE = "OBSERVE"
    """Record the quirk signal; take no visible action."""

    WARN = "WARN"
    """Emit a visible warning to the agent / operator."""

    BLOCK = "BLOCK"
    """Halt the current operation until the quirk is resolved."""
