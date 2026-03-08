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

Migration note for callers that import ``SkillResultStatus``:
  - After OMN-3867 lands, ``SkillResultStatus`` is an alias for
    ``omnibase_core.enums.EnumSkillResultStatus``.
  - The string values (``"success"``, ``"failed"``, ``"partial"``) are
    identical; the new enum adds additional values
    (``"error"``, ``"blocked"``, ``"skipped"``, ``"dry_run"``,
    ``"pending"``, ``"gated"``).
  - Comparisons against ``SkillResultStatus.SUCCESS`` / ``.FAILED`` /
    ``.PARTIAL`` continue to work after the migration because both enums
    are ``StrEnum`` subclasses with the same string values for those three
    members.

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

    __all__ = ["ModelSkillResult", "SkillResult", "SkillResultStatus"]

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
            description="Correlation ID carried through from the request",
        )

    #: Alias matching omnibase_core naming; will be the real
    #: ``ModelSkillResult`` once OMN-3867 lands.
    SkillResult = ModelSkillResult

    __all__ = ["ModelSkillResult", "SkillResult", "SkillResultStatus"]
