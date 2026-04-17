# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Dispatch-scoped state record (OMN-9084).

Persisted at dispatch time to ``$ONEX_STATE_DIR/dispatches/<agent-id>.yaml``
so that downstream hooks (Tasks 6, 9, 11 in OMN-9083) can reason about
allowedTools, tool-call history, and consecutive-failure counters scoped to
a single subagent dispatch.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ModelDispatchRecord(BaseModel):
    """Per-dispatch metadata snapshot keyed by ``agent_id``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(..., min_length=1, max_length=128)
    dispatched_at: datetime
    dispatcher: str = Field(..., min_length=1)
    ticket: str = Field(..., pattern=r"^OMN-\d+$")
    allowed_tools: list[str] = Field(default_factory=list)
    prompt_digest: str = Field(..., min_length=1)
    parent_session_id: str = Field(..., min_length=1)
