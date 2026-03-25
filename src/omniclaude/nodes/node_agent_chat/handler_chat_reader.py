# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Chat reader — renders recent chat history as formatted text.

The reader fetches messages from the file store and formats them for
display in the /chat skill output or for injection into agent context
via the SessionStart hook.

Related tickets:
    - OMN-3972: Agentic Chat Over Kafka MVP
    - OMN-6511: Chat reader
"""

from __future__ import annotations

import logging

from omniclaude.nodes.node_agent_chat.handler_file_chat_store import (
    HandlerFileChatStore,
)
from omniclaude.nodes.node_agent_chat.models.model_chat_message import (
    ModelAgentChatMessage,
)

logger = logging.getLogger(__name__)

# Severity → display prefix mapping
_SEVERITY_PREFIX = {
    "INFO": "",
    "WARN": "[WARN] ",
    "ERROR": "[ERROR] ",
    "CRITICAL": "[CRITICAL] ",
}

# Default number of messages to show
DEFAULT_TAIL_COUNT = 20


def format_message(msg: ModelAgentChatMessage) -> str:
    """Format a single chat message for display.

    Format: ``[HH:MM] agent_id (channel): body``
    With severity prefix for WARN/ERROR/CRITICAL.

    Args:
        msg: The chat message to format.

    Returns:
        A single-line formatted string.
    """
    time_str = msg.emitted_at.strftime("%H:%M")
    severity_prefix = _SEVERITY_PREFIX.get(msg.severity.value, "")
    channel_tag = msg.channel.value.lower()

    parts = [f"[{time_str}]"]
    parts.append(f"{msg.agent_id}")
    parts.append(f"({channel_tag}):")
    parts.append(f"{severity_prefix}{msg.body}")

    return " ".join(parts)


def format_messages(messages: list[ModelAgentChatMessage]) -> str:
    """Format a list of messages into a multi-line display string.

    Args:
        messages: List of messages in chronological order.

    Returns:
        Newline-separated formatted messages. Empty string if no messages.
    """
    if not messages:
        return ""
    return "\n".join(format_message(msg) for msg in messages)


class HandlerChatReader:
    """Reads and formats chat history from the file store.

    Attributes:
        store: The underlying file-based chat store.
    """

    __slots__ = ("_store",)

    def __init__(self, store: HandlerFileChatStore | None = None) -> None:
        """Initialize the reader.

        Args:
            store: Explicit file store instance. If None, a default store
                   is created.
        """
        self._store = store or HandlerFileChatStore()

    @property
    def store(self) -> HandlerFileChatStore:
        """The underlying file store."""
        return self._store

    def read_formatted(
        self,
        n: int = DEFAULT_TAIL_COUNT,
        *,
        channel: str | None = None,
        epic_id: str | None = None,
    ) -> str:
        """Read recent messages and return formatted text.

        Args:
            n: Maximum number of messages to return.
            channel: Optional channel filter (e.g., "CI", "EPIC").
            epic_id: Optional epic ID filter.

        Returns:
            Formatted multi-line string of recent messages.
            Empty string if no messages match.
        """
        messages = self._store.read_tail(n=n, channel=channel, epic_id=epic_id)
        return format_messages(messages)

    def read_context_block(
        self,
        n: int = DEFAULT_TAIL_COUNT,
        *,
        channel: str | None = None,
        epic_id: str | None = None,
    ) -> str:
        """Read recent messages formatted as a context injection block.

        Returns a block suitable for injection into agent system prompts
        via the SessionStart hook.

        Args:
            n: Maximum number of messages to include.
            channel: Optional channel filter.
            epic_id: Optional epic ID filter.

        Returns:
            A context block with header, or empty string if no messages.
        """
        formatted = self.read_formatted(n=n, channel=channel, epic_id=epic_id)
        if not formatted:
            return ""

        count = len(formatted.strip().splitlines())
        header = f"## Agent Chat ({count} recent messages)"
        return f"{header}\n{formatted}"


__all__ = ["HandlerChatReader", "format_message", "format_messages"]
