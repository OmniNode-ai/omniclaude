# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The request HandlerSessionCostEmitter.handle takes (OMN-21742).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ModelSessionCostEmitRequest(BaseModel):
    """One SessionEnd payload to turn into an llm.cost.completed event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_end_payload: dict[str, object] = Field(
        description="Raw Claude Code SessionEnd JSON object."
    )
    env: dict[str, str] | None = Field(
        default=None, description="Environment variables. Defaults to os.environ."
    )
    session_id: str | None = Field(
        default=None, description="Extracted from the payload when absent."
    )
    correlation_id: str | None = Field(
        default=None, description="Correlation id for distributed tracing."
    )
    accumulator_dir: Path = Field(
        description="Directory holding omniclaude-session-*.json accumulators.",
    )
    plugin_root: str | None = Field(
        default=None,
        description="Plugin root for emit_client_wrapper; falls back to CLAUDE_PLUGIN_ROOT.",
    )
