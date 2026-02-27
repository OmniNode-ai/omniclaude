# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Handler for file-based agent inbox delivery (STANDALONE tier).

Implements ProtocolAgentInbox using the filesystem as the message store.
Messages are written atomically (write to temp file, then rename) to
prevent partial reads by concurrent agents.

Directory Layout:
    ~/.claude/agent-inboxes/
        {agent_id}/
            {timestamp}_{message_id}.json     # directed messages
        _broadcast/
            {epic_id}/
                {timestamp}_{message_id}.json  # broadcast messages

Atomic Write Strategy:
    1. Write JSON to a temp file in the same directory (.tmp suffix)
    2. os.replace() atomically renames temp -> final path
    3. Readers only see complete files (no partial JSON)

GC Strategy:
    Walk all agent inbox directories, remove files older than TTL.

.. versionadded:: 1.0.0
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from omniclaude.nodes.node_agent_inbox_effect.models import (
    ModelInboxDeliveryResult,
    ModelInboxMessage,
    ModelMessageTrace,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default inbox root directory.
DEFAULT_INBOX_ROOT: str = os.path.expanduser("~/.claude/agent-inboxes")

#: Subdirectory for broadcast messages.
BROADCAST_DIR: str = "_broadcast"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class HandlerStandaloneInbox:
    """File-based agent inbox handler (STANDALONE tier).

    Implements ``ProtocolAgentInbox`` using the filesystem for message
    delivery with atomic writes and timestamp-ordered reading.

    Args:
        inbox_root: Root directory for agent inboxes. Defaults to
            ``~/.claude/agent-inboxes``.

    Example::

        handler = HandlerStandaloneInbox()
        result = await handler.send_message(message)
        messages = await handler.receive_messages("worker-omniclaude")
    """

    def __init__(self, inbox_root: str | None = None) -> None:
        self._inbox_root = Path(inbox_root or DEFAULT_INBOX_ROOT)

    # -- ProtocolAgentInbox interface ----------------------------------------

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing."""
        return "standalone"

    async def send_message(
        self,
        message: ModelInboxMessage,
    ) -> ModelInboxDeliveryResult:
        """Deliver a message to the file-based inbox.

        Uses atomic writes: write to temp file, then os.replace() to final path.

        Args:
            message: The inbox message envelope to deliver.

        Returns:
            ModelInboxDeliveryResult with standalone delivery status.
        """
        start = time.monotonic()

        try:
            file_path = self._write_message(message)
            elapsed_ms = (time.monotonic() - start) * 1000.0

            return ModelInboxDeliveryResult(
                success=True,
                message_id=message.message_id,
                delivery_tier="standalone",
                kafka_delivered=False,
                standalone_delivered=True,
                topic=None,
                file_path=str(file_path),
                error=None,
                duration_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.debug("Standalone inbox delivery failed: %s", error_msg)

            return ModelInboxDeliveryResult(
                success=False,
                message_id=message.message_id,
                delivery_tier="none",
                kafka_delivered=False,
                standalone_delivered=False,
                topic=None,
                file_path=None,
                error=error_msg[:1000],
                duration_ms=elapsed_ms,
            )

    async def receive_messages(
        self,
        agent_id: str,
        since: datetime | None = None,
    ) -> list[ModelInboxMessage]:
        """Read pending messages from an agent's file-based inbox.

        Messages are returned in timestamp order (oldest first).

        Args:
            agent_id: The agent whose inbox to read.
            since: Only return messages emitted after this timestamp.

        Returns:
            List of ModelInboxMessage in timestamp order.
        """
        inbox_dir = self._inbox_root / agent_id
        if not inbox_dir.is_dir():
            return []

        messages: list[ModelInboxMessage] = []
        for json_file in sorted(inbox_dir.glob("*.json")):
            try:
                raw = json.loads(json_file.read_text(encoding="utf-8"))
                msg = _parse_message(raw)
                if since is not None and msg.emitted_at <= since:
                    continue
                messages.append(msg)
            except Exception:
                logger.debug("Skipping unreadable inbox file: %s", json_file)
                continue

        return messages

    async def gc_inbox(
        self,
        ttl_hours: int = 24,
    ) -> int:
        """Remove expired message files from all agent inboxes.

        Args:
            ttl_hours: Messages older than this many hours are removed.

        Returns:
            Number of files removed.
        """
        if not self._inbox_root.is_dir():
            return 0

        cutoff = time.time() - (ttl_hours * 3600)
        removed = 0

        for agent_dir in self._inbox_root.iterdir():
            if not agent_dir.is_dir():
                continue
            for json_file in agent_dir.glob("*.json"):
                try:
                    if json_file.stat().st_mtime < cutoff:
                        json_file.unlink()
                        removed += 1
                except OSError:
                    continue

            # Also check broadcast subdirectories
            if agent_dir.name == BROADCAST_DIR:
                for epic_dir in agent_dir.iterdir():
                    if not epic_dir.is_dir():
                        continue
                    for json_file in epic_dir.glob("*.json"):
                        try:
                            if json_file.stat().st_mtime < cutoff:
                                json_file.unlink()
                                removed += 1
                        except OSError:
                            continue

        logger.debug("GC removed %d expired inbox files", removed)
        return removed

    # -- Internal helpers ----------------------------------------------------

    def _write_message(self, message: ModelInboxMessage) -> Path:
        """Write a message to the inbox using atomic rename.

        Args:
            message: The message to write.

        Returns:
            Path to the written file.
        """
        if message.target_agent_id is not None:
            inbox_dir = self._inbox_root / message.target_agent_id
        elif message.target_epic_id is not None:
            inbox_dir = self._inbox_root / BROADCAST_DIR / message.target_epic_id
        else:
            raise ValueError("Message must have target_agent_id or target_epic_id")

        inbox_dir.mkdir(parents=True, exist_ok=True)

        timestamp = message.emitted_at.strftime("%Y%m%dT%H%M%S%f")
        filename = f"{timestamp}_{message.message_id}.json"
        final_path = inbox_dir / filename

        # Serialize to JSON
        payload = _serialize_message(message)

        # Atomic write: temp file + rename
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            dir=str(inbox_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            Path(tmp_path).replace(final_path)
        except Exception:
            # Clean up temp file on failure
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            raise

        return final_path


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_message(message: ModelInboxMessage) -> dict[str, object]:
    """Serialize a ModelInboxMessage to a JSON-safe dictionary.

    Args:
        message: The message to serialize.

    Returns:
        Dictionary suitable for json.dump().
    """
    return {
        "schema_version": message.schema_version,
        "message_id": str(message.message_id),
        "emitted_at": message.emitted_at.isoformat(),
        "trace": {
            "correlation_id": str(message.trace.correlation_id),
            "run_id": message.trace.run_id,
        },
        "type": message.type,
        "source_agent_id": message.source_agent_id,
        "target_agent_id": message.target_agent_id,
        "target_epic_id": message.target_epic_id,
        "payload": message.payload,
    }


def _extract_payload(raw: dict[str, object]) -> dict[str, Any]:
    """Extract the payload dict from raw data, defaulting to empty dict."""
    val = raw.get("payload")
    if isinstance(val, dict):
        return val
    return {}


def _parse_message(raw: dict[str, object]) -> ModelInboxMessage:
    """Parse a raw JSON dictionary into a ModelInboxMessage.

    Args:
        raw: Dictionary loaded from a JSON inbox file.

    Returns:
        Parsed ModelInboxMessage.
    """
    trace_raw = raw.get("trace", {})
    assert isinstance(trace_raw, dict)  # noqa: S101

    trace = ModelMessageTrace(
        correlation_id=UUID(str(trace_raw["correlation_id"])),
        run_id=str(trace_raw["run_id"]),
    )

    return ModelInboxMessage(
        schema_version=str(raw.get("schema_version", "1")),
        message_id=UUID(str(raw["message_id"])),
        emitted_at=datetime.fromisoformat(str(raw["emitted_at"])),
        trace=trace,
        type=str(raw["type"]),  # type: ignore[arg-type]
        source_agent_id=str(raw["source_agent_id"]),
        target_agent_id=str(raw["target_agent_id"])
        if raw.get("target_agent_id")
        else None,
        target_epic_id=str(raw["target_epic_id"])
        if raw.get("target_epic_id")
        else None,
        payload=_extract_payload(raw),
    )


__all__ = [
    "BROADCAST_DIR",
    "DEFAULT_INBOX_ROOT",
    "HandlerStandaloneInbox",
]
