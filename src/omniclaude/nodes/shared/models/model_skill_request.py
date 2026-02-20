# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Skill request model - input to any skill dispatch node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelSkillRequest(BaseModel):
    """Input to any skill dispatch node.

    Describes a single skill invocation: which skill to run, where its
    definition lives, what arguments to pass, and a correlation ID for
    end-to-end tracing.

    Attributes:
        skill_name: Human-readable skill identifier (e.g. "pr-review").
        skill_path: Absolute or relative path to the skill's SKILL.md file.
            Must be non-empty and must end with "SKILL.md".
        args: Key/value argument pairs. An empty string or the literal value
            "true" produces a bare flag (``--key``); any other value produces
            a ``--key value`` pair.
        correlation_id: Correlation ID for end-to-end request tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str = Field(
        ...,
        min_length=1,
        description="Human-readable skill identifier",
    )
    skill_path: str = Field(
        ...,
        description="Path to the skill's SKILL.md file",
    )
    args: dict[str, str] = Field(
        default_factory=dict,
        description="Argument pairs; empty/true → bare flag, else --flag value",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for end-to-end request tracing",
    )

    @field_validator("skill_name")
    @classmethod
    def _validate_skill_name(cls, value: str) -> str:
        """Reject whitespace-only skill_name values."""
        if not value.strip():
            raise ValueError("skill_name must not be blank or whitespace-only")
        return value

    @field_validator("skill_path")
    @classmethod
    def _validate_skill_path(cls, value: str) -> str:
        """Reject empty strings and paths that do not end in SKILL.md."""
        if not value:
            raise ValueError("skill_path must not be empty")
        if not value.endswith("SKILL.md"):
            raise ValueError(f"skill_path must end with 'SKILL.md', got: {value!r}")
        return value

    @field_validator("args")
    @classmethod
    def _validate_args_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject args dicts that contain empty or whitespace-only keys."""
        for key in value:
            if not key.strip():
                raise ValueError(
                    f"args keys must not be empty or whitespace-only, got: {key!r}"
                )
        return value


__all__ = ["ModelSkillRequest"]
