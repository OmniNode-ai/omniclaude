# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pipeline policy and state models for review iteration tracking."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PipelinePolicy(BaseModel):
    """Controls pipeline behavior: auto-advance gates, iteration limits, and stop conditions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = "1.0"
    auto_advance: bool = True
    auto_commit: bool = True
    auto_push: bool = True
    auto_pr_create: bool = True
    max_review_iterations: int = Field(default=3, ge=1, le=10)
    stop_on_major: bool = True
    stop_on_repeat: bool = True
    stop_on_cross_repo: bool = True
    stop_on_invariant: bool = True


class IssueFingerprint(BaseModel):
    """Unique identity of a review finding, used for deduplication and repeat detection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    rule_id: str
    severity: str

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, v: str) -> str:
        allowed = {"critical", "major", "minor", "nit"}
        if v not in allowed:
            msg = f"severity must be one of {sorted(allowed)}, got {v!r}"
            raise ValueError(msg)
        return v

    def as_tuple(self) -> tuple[str, str, str]:
        """Return (file, rule_id, severity) for stable ordering and comparison."""
        return (self.file, self.rule_id, self.severity)


class PhaseResult(BaseModel):
    """Outcome of a single pipeline phase execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["completed", "blocked", "failed"]
    blocking_issues: int = 0
    nit_count: int = 0
    artifacts: tuple[tuple[str, str], ...] = Field(default_factory=tuple)

    @field_validator("artifacts", mode="before")
    @classmethod
    def _coerce_artifacts(cls, v: dict[str, str] | tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
        if isinstance(v, dict):
            return tuple(sorted(v.items()))
        return v

    reason: str | None = None
    block_kind: (
        Literal[
            "blocked_human_gate",
            "blocked_policy",
            "blocked_review_limit",
            "failed_exception",
        ]
        | None
    ) = None


class IterationRecord(BaseModel):
    """Snapshot of a single review iteration for convergence tracking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iteration: int = Field(ge=1)
    fingerprints: frozenset[IssueFingerprint] = Field(default_factory=frozenset)
    blocking_count: int = 0
    nit_count: int = 0
    has_major: bool = False
