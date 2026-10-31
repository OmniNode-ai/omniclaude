# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The result HandlerSessionCostEmitter.handle returns (OMN-21742).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSessionCostEmitResult(BaseModel):
    """Whether the daemon accepted the event. Failure is soft, never raised."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    emitted: bool = Field(
        description="True if the event was accepted by the daemon, False otherwise."
    )
