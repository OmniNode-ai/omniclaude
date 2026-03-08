# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Skill result model - re-export shim for backward compatibility.

DEPRECATED: Import directly from ``omnibase_core.models.skill`` instead:

    from omnibase_core.models.skill.model_skill_result import ModelSkillResult, SkillResult

This module re-exports ``ModelSkillResult`` and ``SkillResult`` from
``omnibase_core`` when available (requires omnibase_core >= 0.25.0,
pending OMN-3867 / omnibase_core PR #617).

Until then it falls back to the legacy local definition so that existing
callers continue to work without changes.

Migration notes for callers
---------------------------

**SkillResultStatus**: After OMN-3867 lands, ``SkillResultStatus`` is an
alias for ``omnibase_core.enums.EnumSkillResultStatus``.  The string values
``"success"``, ``"failed"``, and ``"partial"`` are identical in both enums
(``StrEnum`` subclasses), so equality comparisons continue to work.  The
new enum adds six additional values: ``"error"``, ``"blocked"``,
``"skipped"``, ``"dry_run"``, ``"pending"``, ``"gated"``.

**correlation_id field — BREAKING on migration** (OMN-3877): The legacy
local ``ModelSkillResult`` has a required ``correlation_id: UUID`` field.
The omnibase_core ``ModelSkillResult`` does NOT include this field
(``extra="forbid"``).  Any caller that constructs
``ModelSkillResult(correlation_id=...)`` will raise ``ValidationError``
the moment omnibase_core >= 0.25.0 is installed.

Affected call sites (must be updated before omnibase_core bump):
  - ``handler_skill_requested.py`` (2 call sites)
  - ``node_claude_code_session_effect/backends/backend_subprocess.py`` (7 call sites)

A follow-up task must audit all ``ModelSkillResult(...)`` constructors and
remove ``correlation_id`` from each before bumping the omnibase_core
constraint.  Track as a blocker on the omnibase_core version-bump ticket.

Dependency: OMN-3867 (omnibase_core PR #617)
"""

from __future__ import annotations

try:
    from omnibase_core.enums.enum_skill_result_status import (
        EnumSkillResultStatus as SkillResultStatus,
    )
    from omnibase_core.models.skill.model_skill_result import (
        ModelSkillResult,
        SkillResult,
    )

    _USING_CORE = True

except ImportError:
    # OMN-3867 not yet merged / released.  Fall back to the legacy local
    # definition so that all existing callers continue to work.
    from enum import StrEnum
    from uuid import UUID

    from pydantic import BaseModel, ConfigDict, Field

    class SkillResultStatus(StrEnum):  # type: ignore[no-redef]
        """Possible outcomes of a skill invocation.

        DEPRECATED: will become an alias for
        ``omnibase_core.enums.EnumSkillResultStatus`` once OMN-3867 lands.
        Only ``SUCCESS``, ``FAILED``, and ``PARTIAL`` are present here;
        the full enum in omnibase_core adds ``error``, ``blocked``,
        ``skipped``, ``dry_run``, ``pending``, and ``gated``.
        """

        SUCCESS = "success"
        FAILED = "failed"
        PARTIAL = "partial"

    class ModelSkillResult(BaseModel):  # type: ignore[no-redef]
        """Output from any skill dispatch node (legacy local definition).

        DEPRECATED: use ``omnibase_core.models.skill.ModelSkillResult``
        once OMN-3867 / omnibase_core PR #617 is merged and released.

        Captures the outcome of a single skill invocation, including the
        structured output (if any) and any error detail.

        Attributes:
            skill_name: Human-readable skill identifier matching the request.
            status: Final status of the skill invocation.
            output: Raw output text from the skill (None if not available).
            error: Error detail, typically populated when status is FAILED or PARTIAL.
            correlation_id: Correlation ID carried through from the request.
                REMOVED in omnibase_core ModelSkillResult — callers must
                drop this field before omnibase_core >= 0.25.0 is installed.
        """

        model_config = ConfigDict(frozen=True, extra="forbid")

        skill_name: str = Field(
            ...,
            min_length=1,
            description="Human-readable skill identifier matching the request",
        )
        status: SkillResultStatus = Field(
            ...,
            description="Final status of the skill invocation",
        )
        output: str | None = Field(
            default=None,
            description="Raw output text from the skill",
        )
        error: str | None = Field(
            default=None,
            description="Error detail when status is FAILED or PARTIAL",
        )
        correlation_id: UUID = Field(
            ...,
            description=(
                "Correlation ID carried through from the request. "
                "DEPRECATED: removed in omnibase_core ModelSkillResult. "
                "Drop this field before bumping omnibase_core >= 0.25.0."
            ),
        )

    #: Alias matching omnibase_core naming; will be the real
    #: ``ModelSkillResult`` once OMN-3867 lands.
    SkillResult = ModelSkillResult

    _USING_CORE = False


__all__ = ["ModelSkillResult", "SkillResult", "SkillResultStatus"]
