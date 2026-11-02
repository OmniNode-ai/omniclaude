# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Agent Trace and PR Debugging System — trace data models.

ChangeFrame and PR envelope models, and the trace table DDL and row shapes
(TRACE-02). The logic that builds and replays them lives in
``omniclaude.handlers.trace``.
"""

from omniclaude.models.trace.change_frame import (
    ChangeFrame,
    ModelCheckResult,
    OutcomeStatus,
)

__all__ = [
    "ChangeFrame",
    "ModelCheckResult",
    "OutcomeStatus",
]
