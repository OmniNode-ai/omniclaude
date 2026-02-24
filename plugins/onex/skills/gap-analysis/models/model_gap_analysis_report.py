# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""ModelGapAnalysisReport — aggregated output of a gap-analysis run."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .model_gap_finding import ModelGapFinding


class ModelGapAnalysisReport(BaseModel):
    """Aggregated report of all gap findings from one gap-analysis run."""

    model_schema_version: str = "1.0"

    # Run metadata
    run_id: str
    epic_id: str | None = None
    repos_in_scope: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    rejected_repos: list[str] = Field(
        default_factory=list,
        description="Repos removed after canonicalization (unknown/aliased)",
    )

    # Status for epics with no usable repo evidence
    status: str | None = None
    blocked_reason: str | None = None

    # Findings
    findings: list[ModelGapFinding] = Field(
        default_factory=list,
        description="DETERMINISTIC findings at or above severity threshold",
    )
    best_effort_findings: list[ModelGapFinding] = Field(
        default_factory=list,
        description="BEST_EFFORT findings (severity capped at WARNING)",
    )

    # Skipped probes (no findings emitted)
    skipped_probes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of {probe, reason} dicts for SKIP-confidence probes",
    )

    # Suppression info
    expired_suppressions_warned: list[str] = Field(
        default_factory=list,
        description="Fingerprints of expired suppressions that were NOT applied",
    )

    # Ticket management
    tickets_created: list[str] = Field(default_factory=list)
    tickets_commented: list[str] = Field(
        default_factory=list,
        description="Existing ticket IDs that received a dedup comment",
    )

    class Config:
        frozen = True
        extra = "ignore"
        from_attributes = True
