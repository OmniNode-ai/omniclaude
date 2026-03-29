# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pydantic models for the coverage sweep feature."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumCoverageGapPriority(StrEnum):
    """Priority level for a coverage gap."""

    ZERO_COVERAGE = "zero_coverage"
    BELOW_TARGET = "below_target"
    RECENTLY_CHANGED = "recently_changed"


class ModelCoverageGap(BaseModel):
    """A single module with insufficient test coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(description="Repository name (e.g. omniclaude)")
    module_path: str = Field(
        description="Module path relative to repo root (e.g. src/omniclaude/coverage/scanner.py)"
    )
    coverage_pct: float = Field(
        ge=0.0, le=100.0, description="Current line coverage percentage"
    )
    total_statements: int = Field(ge=0, description="Total executable statements")
    covered_statements: int = Field(ge=0, description="Statements covered by tests")
    missing_statements: int = Field(ge=0, description="Statements not covered by tests")
    priority: EnumCoverageGapPriority = Field(description="Gap priority classification")
    recently_changed: bool = Field(
        default=False,
        description="Whether the module was modified recently (last 14 days) without new tests",
    )


class ModelCoverageScanResult(BaseModel):
    """Result of scanning one repo for coverage gaps."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(description="Repository name")
    repo_path: str = Field(description="Absolute path to repo root")
    total_modules: int = Field(ge=0, description="Total modules found")
    modules_below_target: int = Field(ge=0, description="Modules below coverage target")
    modules_zero_coverage: int = Field(ge=0, description="Modules with 0% coverage")
    repo_average_pct: float = Field(
        ge=0.0, le=100.0, description="Repo-wide average coverage"
    )
    target_pct: float = Field(
        ge=0.0, le=100.0, description="Coverage target for this repo"
    )
    gaps: list[ModelCoverageGap] = Field(
        default_factory=list, description="Identified coverage gaps"
    )
    scan_error: str | None = Field(
        default=None, description="Error message if scan failed"
    )


class ModelCoverageTicketRequest(BaseModel):
    """Request to create a Linear ticket for a coverage gap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(description="Ticket title")
    description: str = Field(description="Ticket description with requirements and DoD")
    repo: str = Field(description="Target repository")
    priority: int = Field(
        ge=0,
        le=4,
        description="Linear priority (0=none, 1=urgent, 2=high, 3=medium, 4=low)",
    )
    labels: list[str] = Field(
        default_factory=list, description="Linear labels to apply"
    )
    gap: ModelCoverageGap = Field(description="The coverage gap this ticket addresses")


class ModelCoverageSweepReport(BaseModel):
    """Full report from a coverage sweep across all repos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scans: list[ModelCoverageScanResult] = Field(default_factory=list)
    total_gaps: int = Field(ge=0, default=0)
    tickets_created: int = Field(ge=0, default=0)
    tickets_skipped_dedup: int = Field(ge=0, default=0)
    errors: list[str] = Field(default_factory=list)


class ModelCoverageCache(BaseModel):
    """Cached coverage scan result with TTL tracking."""

    model_config = ConfigDict(extra="forbid")

    repo: str = Field(description="Repository name")
    scanned_at_unix: float = Field(
        description="Unix timestamp of when scan was performed"
    )
    result: ModelCoverageScanResult = Field(description="Cached scan result")
    cache_path: str = Field(default="", description="Path to cache file on disk")

    def is_expired(self, ttl_seconds: float = 3600.0) -> bool:
        """Check if cache entry has expired."""
        import time

        return (time.time() - self.scanned_at_unix) > ttl_seconds
