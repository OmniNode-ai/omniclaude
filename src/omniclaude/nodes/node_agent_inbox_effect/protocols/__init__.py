# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeAgentInboxEffect node.

This package defines the protocol interface for agent inbox backends.

Exported:
    ProtocolAgentInbox: Runtime-checkable protocol for inbox backends

Operation Mapping (from node contract io_operations):
    - send_message operation -> ProtocolAgentInbox.send_message()
    - receive_messages operation -> ProtocolAgentInbox.receive_messages()
    - gc_inbox operation -> ProtocolAgentInbox.gc_inbox()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Implement send_message for inter-agent message delivery
    3. Implement receive_messages for inbox reading
    4. Implement gc_inbox for expired message cleanup
"""

from .protocol_agent_inbox import ProtocolAgentInbox

__all__ = [
    "ProtocolAgentInbox",
]
