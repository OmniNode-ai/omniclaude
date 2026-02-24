# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeClaudeCodeSessionEffect node.

This package defines the protocol interface for Claude Code session backends.

Exported:
    ProtocolClaudeCodeSession: Runtime-checkable protocol for session backends

Operation Mapping (from node contract io_operations):
    - session_start operation -> ProtocolClaudeCodeSession.session_start()
    - session_query operation -> ProtocolClaudeCodeSession.session_query()
    - session_end operation -> ProtocolClaudeCodeSession.session_end()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Return ModelSkillResult envelopes for all operations
"""

from .protocol_claude_code_session import ProtocolClaudeCodeSession

__all__ = [
    "ProtocolClaudeCodeSession",
]
