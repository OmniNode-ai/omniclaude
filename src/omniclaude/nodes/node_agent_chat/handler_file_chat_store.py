# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""File-based chat store — append-only JSONL persistence for agent chat messages.

Messages are written to ``$ONEX_STATE_DIR/chat/chat.jsonl`` as one JSON line per
message. The store provides append (write) and tail-read (most recent N messages)
operations.

Design decisions:
    - **Append-only JSONL**: Simple, crash-safe (partial writes are discarded on read),
      and human-inspectable via ``tail -f``.
    - **Single file**: All channels in one file. Channel filtering is done at read time.
      This keeps the write path trivial and avoids directory management.
    - **File locking**: Uses ``fcntl.flock`` for safe concurrent appends from multiple
      sessions. Lock is held only during the write (not during serialization).
    - **No rotation**: MVP scope. Future ticket can add log rotation if file grows large.

Related tickets:
    - OMN-3972: Agentic Chat Over Kafka MVP
    - OMN-6509: File-based chat store
"""

from __future__ import annotations

import fcntl
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from omniclaude.nodes.node_agent_chat.models.model_chat_message import (
    ModelAgentChatMessage,
)

logger = logging.getLogger(__name__)

# Default subdirectory under ONEX_STATE_DIR
_CHAT_SUBDIR = "chat"
_CHAT_FILENAME = "chat.jsonl"


def _default_chat_path() -> Path:
    """Resolve the default chat JSONL path via ONEX_STATE_DIR.

    Returns:
        Path to the chat.jsonl file under $ONEX_STATE_DIR/chat/.

    Raises:
        RuntimeError: If ONEX_STATE_DIR is not set.
    """
    # Import here to avoid circular dependency and allow tests to mock
    from omniclaude.hooks.lib.onex_state import ensure_state_dir

    chat_dir = ensure_state_dir(_CHAT_SUBDIR)
    return chat_dir / _CHAT_FILENAME


class HandlerFileChatStore:
    """Append-only JSONL store for agent chat messages.

    Attributes:
        path: Path to the JSONL file. Defaults to $ONEX_STATE_DIR/chat/chat.jsonl.
    """

    __slots__ = ("_path",)

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the file chat store.

        Args:
            path: Explicit path to the JSONL file. If None, uses the default
                  path under $ONEX_STATE_DIR/chat/chat.jsonl.
        """
        self._path = path

    @property
    def path(self) -> Path:
        """Resolved path to the JSONL file (lazy to defer env var lookup)."""
        if self._path is None:
            self._path = _default_chat_path()
        return self._path

    def append(self, message: ModelAgentChatMessage) -> None:
        """Append a single message to the JSONL file.

        Uses file locking (``fcntl.flock``) for safe concurrent writes from
        multiple Claude Code sessions.

        Args:
            message: The chat message to persist.
        """
        line = message.model_dump_json() + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def read_tail(
        self,
        n: int = 50,
        *,
        channel: str | None = None,
        epic_id: str | None = None,
    ) -> list[ModelAgentChatMessage]:
        """Read the most recent N messages, optionally filtered.

        Reads the entire file and returns the last N messages matching the
        optional filters. This is acceptable for MVP (file is small); a future
        ticket can add reverse-read optimization.

        Args:
            n: Maximum number of messages to return (default 50).
            channel: If set, only return messages with this channel value.
            epic_id: If set, only return messages with this epic_id.

        Returns:
            List of messages in chronological order (oldest first within the
            returned window).
        """
        if not self.path.exists():
            return []

        messages: list[ModelAgentChatMessage] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    msg = ModelAgentChatMessage.model_validate_json(stripped)
                except (json.JSONDecodeError, ValidationError):
                    logger.warning(
                        "Skipping malformed chat line %d in %s",
                        line_num,
                        self.path,
                    )
                    continue

                # Apply filters
                if channel is not None and msg.channel.value != channel:
                    continue
                if epic_id is not None and msg.epic_id != epic_id:
                    continue

                messages.append(msg)

        # Return last N
        return messages[-n:] if len(messages) > n else messages

    def message_count(self) -> int:
        """Return the total number of valid messages in the store.

        Returns:
            Count of parseable JSONL lines.
        """
        if not self.path.exists():
            return 0

        count = 0
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    json.loads(stripped)
                    count += 1
                except json.JSONDecodeError:
                    continue
        return count


__all__ = ["HandlerFileChatStore"]
