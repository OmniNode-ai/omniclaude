"""Bounded Event Queue with Disk Spool for Embedded Event Publisher.

Ported from omnibase_infra.runtime.emit_daemon.queue (OMN-1944).

Queue Behavior:
    1. Events are first added to the in-memory queue
    2. When memory queue is full, events overflow to disk spool
    3. When disk spool is full (by message count or bytes), oldest events are dropped
    4. Dequeue prioritizes memory queue, then disk spool (FIFO ordering)

Disk Spool Format:
    - Directory: ~/.claude/event-spool/ (configurable)
    - Files: {timestamp}_{event_id}.json (one event per file)
    - Sorted by filename for FIFO ordering

Concurrency: coroutine-safe using asyncio.Lock (not thread-safe).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

from omnibase_core.types import JsonType  # noqa: TC002 - runtime use by Pydantic
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class ModelQueuedEvent(BaseModel):
    """An event waiting to be published."""

    model_config = ConfigDict(
        strict=False,
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    event_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    payload: JsonType = Field(...)
    partition_key: str | None = Field(default=None)
    queued_at: datetime = Field(...)

    @field_validator("queued_at", mode="before")
    @classmethod
    def ensure_utc_aware(cls, v: object) -> object:
        if not isinstance(v, datetime):
            return v
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        if v.utcoffset() == timedelta(0):
            if v.tzinfo is not UTC:
                return v.replace(tzinfo=UTC)
            return v
        return v.astimezone(UTC)


class BoundedEventQueue:
    """Bounded in-memory queue with disk spool overflow."""

    def __init__(
        self,
        max_memory_queue: int = 100,
        max_spool_messages: int = 1000,
        max_spool_bytes: int = 10_485_760,  # 10 MB
        spool_dir: Path | None = None,
    ) -> None:
        self._max_memory_queue = max_memory_queue
        self._max_spool_messages = max_spool_messages
        self._max_spool_bytes = max_spool_bytes
        self._spool_dir = spool_dir or (Path.home() / ".claude" / "event-spool")

        self._memory_queue: deque[ModelQueuedEvent] = deque()
        self._spool_files: list[Path] = []
        self._spool_bytes: int = 0
        self._lock = asyncio.Lock()

        self._ensure_spool_dir()

    def _ensure_spool_dir(self) -> None:
        try:
            self._spool_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(
                f"Failed to create spool directory {self._spool_dir}: {e}. "
                "Disk spool will be unavailable."
            )

    async def enqueue(self, event: ModelQueuedEvent) -> bool:
        async with self._lock:
            if len(self._memory_queue) < self._max_memory_queue:
                self._memory_queue.append(event)
                logger.debug(
                    f"Event {event.event_id} queued in memory "
                    f"(memory: {len(self._memory_queue)}/{self._max_memory_queue})"
                )
                return True

            if self._max_spool_messages == 0 or self._max_spool_bytes == 0:
                logger.warning(
                    f"Dropping event {event.event_id}: memory queue full "
                    f"({len(self._memory_queue)}/{self._max_memory_queue}) "
                    "and spooling is disabled"
                )
                return False

            return await self._spool_event(event)

    async def _spool_event(self, event: ModelQueuedEvent) -> bool:
        """Spool an event to disk. Caller must hold self._lock."""
        if self._max_spool_messages == 0 or self._max_spool_bytes == 0:
            return False

        try:
            event_json = event.model_dump_json()
            event_bytes = len(event_json.encode("utf-8"))
        except Exception:
            logger.exception("Failed to serialize event %s", event.event_id)
            return False

        while (
            len(self._spool_files) >= self._max_spool_messages
            or self._spool_bytes + event_bytes > self._max_spool_bytes
        ) and self._spool_files:
            await self._drop_oldest_spool()

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        filename = f"{timestamp}_{event.event_id}.json"
        filepath = self._spool_dir / filename

        try:
            filepath.write_text(event_json, encoding="utf-8")
            self._spool_files.append(filepath)
            self._spool_bytes += event_bytes
            logger.debug(
                f"Event {event.event_id} spooled to disk "
                f"(spool: {len(self._spool_files)}/{self._max_spool_messages}, "
                f"bytes: {self._spool_bytes}/{self._max_spool_bytes})"
            )
            return True
        except OSError:
            logger.exception("Failed to write spool file %s", filepath)
            return False

    async def _drop_oldest_spool(self) -> None:
        """Drop the oldest spooled event. Caller must hold self._lock."""
        if not self._spool_files:
            return

        oldest = self._spool_files.pop(0)
        try:
            file_size = oldest.stat().st_size
            oldest.unlink()
            self._spool_bytes -= file_size
            event_id = (
                oldest.stem.split("_", 1)[1] if "_" in oldest.stem else oldest.stem
            )
            logger.warning(
                f"Dropping oldest spooled event {event_id} due to spool overflow"
            )
        except OSError:
            logger.exception("Failed to delete oldest spool file %s", oldest)
            self._spool_bytes = max(0, self._spool_bytes)

    async def dequeue(self) -> ModelQueuedEvent | None:
        async with self._lock:
            if self._memory_queue:
                event = self._memory_queue.popleft()
                logger.debug(
                    f"Dequeued event {event.event_id} from memory "
                    f"(remaining: {len(self._memory_queue)})"
                )
                return event

            if self._spool_files:
                return await self._dequeue_from_spool()

            return None

    async def _dequeue_from_spool(self) -> ModelQueuedEvent | None:
        """Dequeue next event from disk spool. Caller must hold self._lock."""
        if not self._spool_files:
            return None

        filepath = self._spool_files.pop(0)
        try:
            content = filepath.read_text(encoding="utf-8")
            event = ModelQueuedEvent.model_validate_json(content)
            # Use stat().st_size for consistency with load_spool()
            try:
                file_size = filepath.stat().st_size
            except OSError:
                file_size = len(content.encode("utf-8"))
            self._spool_bytes = max(0, self._spool_bytes - file_size)
        except OSError:
            logger.exception("Failed to read spool file %s", filepath)
            return None
        except Exception:
            logger.exception("Failed to parse spool file %s", filepath)
            # Decrement spool bytes to maintain accurate accounting — file was
            # already popped from _spool_files and its size was counted during load_spool.
            # Note: content may be unbound if read_text() raised a non-OSError
            # (e.g. UnicodeDecodeError), so fall back to 0 if stat also fails.
            try:
                file_size = filepath.stat().st_size
            except OSError:
                try:
                    file_size = len(content.encode("utf-8"))
                except NameError:
                    file_size = 0
            self._spool_bytes = max(0, self._spool_bytes - file_size)
            try:
                filepath.unlink()
            except OSError:
                pass
            return None

        try:
            filepath.unlink()
        except OSError:
            logger.warning(
                "Failed to delete spool file %s after successful dequeue",
                filepath,
            )

        logger.debug(
            f"Dequeued event {event.event_id} from spool "
            f"(remaining spool: {len(self._spool_files)})"
        )
        return event

    def memory_size(self) -> int:
        return len(self._memory_queue)

    def spool_size(self) -> int:
        return len(self._spool_files)

    def total_size(self) -> int:
        return self.memory_size() + self.spool_size()

    async def drain_to_spool(self) -> int:
        async with self._lock:
            if self._max_spool_messages == 0 or self._max_spool_bytes == 0:
                memory_count = len(self._memory_queue)
                if memory_count > 0:
                    logger.warning(
                        f"Spooling disabled. {memory_count} events in memory will be lost."
                    )
                return 0

            count = 0
            while self._memory_queue:
                event = self._memory_queue.popleft()
                if await self._spool_event(event):
                    count += 1
                else:
                    logger.error(f"Failed to spool event {event.event_id} during drain")
            logger.info(f"Drained {count} events from memory to spool")
            return count

    async def load_spool(self) -> int:
        async with self._lock:
            self._spool_files.clear()
            self._spool_bytes = 0

            if not self._spool_dir.exists():
                return 0

            try:
                files = sorted(self._spool_dir.glob("*.json"))
                for filepath in files:
                    try:
                        file_size = filepath.stat().st_size
                        self._spool_files.append(filepath)
                        self._spool_bytes += file_size
                    except OSError as e:
                        logger.warning(f"Failed to stat spool file {filepath}: {e}")

                count = len(self._spool_files)
                if count > 0:
                    logger.info(
                        f"Loaded {count} events from spool ({self._spool_bytes} bytes)"
                    )
                return count
            except OSError:
                logger.exception("Failed to scan spool directory")
                return 0


__all__: list[str] = ["BoundedEventQueue", "ModelQueuedEvent"]
