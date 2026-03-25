# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pydantic models for friction autofix classification and execution."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class EnumFrictionDisposition(StrEnum):
    """Whether a friction event is auto-fixable or needs escalation."""

    FIXABLE = "fixable"
    ESCALATE = "escalate"


class EnumFixCategory(StrEnum):
    """Category of structural fix for a friction event."""

    CONFIG = "config"
    WIRING = "wiring"
    IMPORT = "import"
    STALE_REF = "stale_ref"
    TEST_MARKER = "test_marker"
    ENV_VAR = "env_var"


class EnumFixOutcome(StrEnum):
    """Outcome of an attempted friction fix."""

    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"
    SKIPPED = "skipped"


class ModelFrictionClassification(BaseModel):
    """Classification of a friction aggregate as fixable or requiring escalation."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    surface_key: str
    skill: str
    surface: str
    disposition: EnumFrictionDisposition
    fix_category: EnumFixCategory | None
    escalation_reason: str | None
    description: str
    most_recent_ticket: str | None
    count: int
    severity_score: int


class ModelMicroPlanTask(BaseModel):
    """A single task within a micro-plan for fixing a friction point."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    file_path: str
    action: str


class ModelMicroPlan(BaseModel):
    """A micro-plan (1-3 tasks) for fixing a single friction point."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surface_key: str
    title: str
    tasks: list[ModelMicroPlanTask]
    target_repo: str

    @field_validator("tasks")
    @classmethod
    def validate_task_count(
        cls, v: list[ModelMicroPlanTask]
    ) -> list[ModelMicroPlanTask]:
        if len(v) < 1:
            raise ValueError("Micro-plans require at least 1 task")
        if len(v) > 3:
            raise ValueError("Micro-plans are limited to 3 tasks maximum")
        return v


class ModelFrictionFixResult(BaseModel):
    """Result of an attempted friction fix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surface_key: str
    outcome: EnumFixOutcome
    ticket_id: str | None = None
    pr_number: int | None = None
    verification_passed: bool | None = None
