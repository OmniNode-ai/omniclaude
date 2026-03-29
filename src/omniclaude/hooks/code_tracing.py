# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Mandatory code tracing for pre-implementation verification (OMN-6819).

Provides a model and formatter for code trace requirements that agents must
complete before writing any implementation code. This prevents the pattern
where agents propose fixes without understanding existing code paths.

The code trace section is injected into skill prompts (ticket-work,
ticket-pipeline) at the spec-to-implementation transition. Agents must
read and trace relevant code paths before editing files.

Environment variables:
    OMNICLAUDE_CODE_TRACING_ENABLED: Enable/disable (default: true)
    OMNICLAUDE_CODE_TRACING_MIN_FILES: Min files to trace (default: 2)
"""

from __future__ import annotations

import logging
import os
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class EnumTraceStatus(str, Enum):
    """Status of a code trace requirement."""

    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ModelCodeTraceRequirement(BaseModel):
    """A single code trace requirement.

    Represents a file or code path that must be read and understood
    before implementation begins.

    Attributes:
        file_path: Path to the file that must be traced.
        reason: Why this file needs to be traced.
        trace_points: Specific functions/classes/lines to examine.
        status: Whether this trace has been completed.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    file_path: str = Field(description="Path to the file to trace")
    reason: str = Field(description="Why this file must be traced")
    trace_points: list[str] = Field(
        default_factory=list,
        description="Specific functions/classes/lines to examine",
    )
    status: EnumTraceStatus = Field(
        default=EnumTraceStatus.PENDING,
        description="Trace completion status",
    )


class ModelCodeTraceConfig(BaseModel):
    """Configuration for mandatory code tracing.

    Attributes:
        enabled: Whether code tracing is enabled.
        min_files: Minimum number of files that must be traced.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(default=True, description="Enable code tracing")
    min_files: int = Field(
        default=2,
        ge=0,
        le=20,
        description="Minimum files to trace before implementation",
    )

    @classmethod
    def from_env(cls) -> ModelCodeTraceConfig:
        """Load config from environment variables."""
        enabled_str = os.getenv(
            "OMNICLAUDE_CODE_TRACING_ENABLED",
            "true",  # ONEX_FLAG_EXEMPT: migration
        )
        enabled = enabled_str.lower() in ("true", "1", "yes")

        min_files_str = os.getenv("OMNICLAUDE_CODE_TRACING_MIN_FILES", "2")
        try:
            min_files = int(min_files_str)
        except ValueError:
            min_files = 2

        return cls(enabled=enabled, min_files=min_files)


class ModelCodeTraceBlock(BaseModel):
    """A collection of code trace requirements for a ticket.

    Attributes:
        ticket_id: The ticket these traces belong to.
        requirements: List of trace requirements.
        all_completed: Whether all requirements have been completed.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    ticket_id: str = Field(description="Ticket ID")
    requirements: list[ModelCodeTraceRequirement] = Field(
        default_factory=list,
        description="Trace requirements",
    )

    @property
    def all_completed(self) -> bool:
        """Check if all trace requirements are completed or skipped."""
        return all(
            r.status in (EnumTraceStatus.COMPLETED, EnumTraceStatus.SKIPPED)
            for r in self.requirements
        )

    @property
    def pending_count(self) -> int:
        """Count of pending trace requirements."""
        return sum(1 for r in self.requirements if r.status == EnumTraceStatus.PENDING)


def build_trace_requirements(
    relevant_files: list[str],
    ticket_id: str,
    ticket_title: str = "",
) -> ModelCodeTraceBlock:
    """Build trace requirements from relevant files discovered during research.

    Args:
        relevant_files: Files identified during the research phase.
        ticket_id: The ticket being worked on.
        ticket_title: Title of the ticket for context.

    Returns:
        A ModelCodeTraceBlock with requirements for each relevant file.
    """
    requirements: list[ModelCodeTraceRequirement] = []
    for file_path in relevant_files:
        requirements.append(
            ModelCodeTraceRequirement(
                file_path=file_path,
                reason=f"Identified as relevant during research for {ticket_id}",
                trace_points=[],
            )
        )

    return ModelCodeTraceBlock(
        ticket_id=ticket_id,
        requirements=requirements,
    )


def format_trace_prompt_section(
    trace_block: ModelCodeTraceBlock,
    config: ModelCodeTraceConfig | None = None,
) -> str:
    """Format the code trace section for injection into a skill prompt.

    This produces a markdown block that instructs the agent to read and
    understand specific files before implementing any changes.

    Args:
        trace_block: The trace requirements.
        config: Optional config override.

    Returns:
        Markdown string with the code trace instructions.
        Empty string if tracing is disabled or no requirements.
    """
    if config is None:
        config = ModelCodeTraceConfig.from_env()

    if not config.enabled:
        return ""

    if not trace_block.requirements:
        return ""

    lines: list[str] = [
        "## Mandatory Code Tracing",
        "",
        "**BEFORE writing any implementation code**, you MUST read and understand "
        "the following files. This is not optional. Proposing changes without "
        "understanding existing code paths leads to regressions and broken "
        "integrations.",
        "",
        "### Required Traces",
        "",
    ]

    for i, req in enumerate(trace_block.requirements, 1):
        status_marker = (
            "[x]"
            if req.status in (EnumTraceStatus.COMPLETED, EnumTraceStatus.SKIPPED)
            else "[ ]"
        )
        lines.append(f"{i}. {status_marker} `{req.file_path}`")
        lines.append(f"   - Reason: {req.reason}")
        if req.trace_points:
            lines.append("   - Trace points:")
            for tp in req.trace_points:
                lines.append(f"     - `{tp}`")

    lines.extend(
        [
            "",
            "### Verification",
            "",
            f"You must trace at least {config.min_files} files before proceeding. "
            "For each file:",
            "1. Read the file using the Read tool",
            "2. Identify the relevant functions, classes, and data flow",
            "3. Note any constraints, patterns, or conventions used",
            "4. Only then proceed to implementation",
            "",
            "**If you skip this step and propose changes based on assumptions, "
            "the review will catch it and send you back.**",
        ]
    )

    return "\n".join(lines)


__all__ = [
    "EnumTraceStatus",
    "ModelCodeTraceBlock",
    "ModelCodeTraceConfig",
    "ModelCodeTraceRequirement",
    "build_trace_requirements",
    "format_trace_prompt_section",
]
