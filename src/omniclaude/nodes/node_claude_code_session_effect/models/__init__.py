# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Models for the NodeClaudeCodeSessionEffect node.

This package contains Pydantic models for Claude Code session management:

- ModelClaudeCodeSessionRequest: Input model for session operation requests

Output model is ModelSkillResult from omniclaude.nodes.shared.models.

Model Ownership:
    These models are PRIVATE to omniclaude.
"""

from .model_claude_code_session_request import (
    ClaudeCodeSessionOperation,
    ModelClaudeCodeSessionRequest,
)

__all__ = [
    "ClaudeCodeSessionOperation",
    "ModelClaudeCodeSessionRequest",
]
