"""Tests for omniclaude.publisher.event_queue."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from omniclaude.publisher.event_queue import BoundedEventQueue, ModelQueuedEvent


def _make_event(
    event_id: str = "test-001", event_type: str = "test.event"
) -> ModelQueuedEvent:
    return ModelQueuedEvent(
        event_id=event_id,
        event_type=event_type,
        topic="test-topic",
        payload={"key": "value"},
        queued_at=datetime.now(UTC),
    )


class TestModelQueuedEvent:
    def test_basic_creation(self) -> None:
        event = _make_event()
        assert event.event_id == "test-001"

    def test_frozen(self) -> None:
        event = _make_event()
        with pytest.raises(Exception):
            event.event_id = "mutated"  # type: ignore[misc]

    def test_naive_datetime_gets_utc(self) -> None:
        event = ModelQueuedEvent(
            event_id="tz-test",
            event_type="test",
            topic="test-topic",
            payload={},
            queued_at=datetime(2025, 1, 1, 12, 0, 0),  # naive
        )
        assert event.queued_at.tzinfo is UTC

    def test_json_roundtrip(self) -> None:
        event = _make_event()
        json_str = event.model_dump_json()
        restored = ModelQueuedEvent.model_validate_json(json_str)
        assert restored.event_id == event.event_id
        assert restored.event_type == event.event_type


class TestBoundedEventQueue:
    @pytest.fixture
    def spool_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "spool"
        d.mkdir()
        return d

    @pytest.fixture
    def queue(self, spool_dir: Path) -> BoundedEventQueue:
        return BoundedEventQueue(
            max_memory_queue=3,
            max_spool_messages=5,
            max_spool_bytes=10_000,
            spool_dir=spool_dir,
        )

    @pytest.mark.asyncio
    async def test_enqueue_dequeue_fifo(self, queue: BoundedEventQueue) -> None:
        e1 = _make_event("e1")
        e2 = _make_event("e2")
        await queue.enqueue(e1)
        await queue.enqueue(e2)

        out1 = await queue.dequeue()
        out2 = await queue.dequeue()
        assert out1 is not None and out1.event_id == "e1"
        assert out2 is not None and out2.event_id == "e2"

    @pytest.mark.asyncio
    async def test_dequeue_empty_returns_none(self, queue: BoundedEventQueue) -> None:
        assert await queue.dequeue() is None

    @pytest.mark.asyncio
    async def test_memory_overflow_spools_to_disk(
        self, queue: BoundedEventQueue, spool_dir: Path
    ) -> None:
        # Fill memory queue (max 3)
        for i in range(3):
            assert await queue.enqueue(_make_event(f"mem-{i}"))

        # This should overflow to spool
        assert await queue.enqueue(_make_event("spool-0"))
        assert queue.memory_size() == 3
        assert queue.spool_size() == 1

        spool_files = list(spool_dir.glob("*.json"))
        assert len(spool_files) == 1

    @pytest.mark.asyncio
    async def test_dequeue_prioritizes_memory(self, queue: BoundedEventQueue) -> None:
        for i in range(3):
            await queue.enqueue(_make_event(f"mem-{i}"))
        await queue.enqueue(_make_event("spool-0"))

        # First 3 should come from memory
        for i in range(3):
            event = await queue.dequeue()
            assert event is not None and event.event_id == f"mem-{i}"

        # Next should come from spool
        event = await queue.dequeue()
        assert event is not None and event.event_id == "spool-0"

    @pytest.mark.asyncio
    async def test_spool_overflow_drops_oldest(self, spool_dir: Path) -> None:
        queue = BoundedEventQueue(
            max_memory_queue=1,
            max_spool_messages=2,
            max_spool_bytes=100_000,
            spool_dir=spool_dir,
        )

        await queue.enqueue(_make_event("mem"))
        await queue.enqueue(_make_event("spool-1"))
        await queue.enqueue(_make_event("spool-2"))
        # This should drop spool-1 (oldest) and add spool-3
        await queue.enqueue(_make_event("spool-3"))

        assert queue.spool_size() == 2
        # Dequeue memory first
        e = await queue.dequeue()
        assert e is not None and e.event_id == "mem"
        # Then spool (spool-1 was dropped, spool-2 and spool-3 remain)
        e = await queue.dequeue()
        assert e is not None and e.event_id == "spool-2"
        e = await queue.dequeue()
        assert e is not None and e.event_id == "spool-3"

    @pytest.mark.asyncio
    async def test_drain_to_spool(
        self, queue: BoundedEventQueue, spool_dir: Path
    ) -> None:
        for i in range(3):
            await queue.enqueue(_make_event(f"drain-{i}"))

        assert queue.memory_size() == 3
        count = await queue.drain_to_spool()
        assert count == 3
        assert queue.memory_size() == 0
        assert queue.spool_size() == 3

        spool_files = list(spool_dir.glob("*.json"))
        assert len(spool_files) == 3

    @pytest.mark.asyncio
    async def test_load_spool_on_startup(self, spool_dir: Path) -> None:
        # Write a spool file manually
        event = _make_event("pre-existing")
        filepath = spool_dir / "20250101120000000000_pre-existing.json"
        filepath.write_text(event.model_dump_json(), encoding="utf-8")

        queue = BoundedEventQueue(
            max_memory_queue=10,
            spool_dir=spool_dir,
        )
        count = await queue.load_spool()
        assert count == 1
        assert queue.spool_size() == 1

        # Dequeue the loaded event
        e = await queue.dequeue()
        assert e is not None and e.event_id == "pre-existing"

    @pytest.mark.asyncio
    async def test_spooling_disabled(self, spool_dir: Path) -> None:
        queue = BoundedEventQueue(
            max_memory_queue=1,
            max_spool_messages=0,
            max_spool_bytes=0,
            spool_dir=spool_dir,
        )
        assert await queue.enqueue(_make_event("ok"))
        # Second event should be dropped (memory full, spool disabled)
        assert not await queue.enqueue(_make_event("dropped"))

    @pytest.mark.asyncio
    async def test_total_size(self, queue: BoundedEventQueue) -> None:
        assert queue.total_size() == 0
        await queue.enqueue(_make_event("e1"))
        assert queue.total_size() == 1
        for i in range(3):
            await queue.enqueue(_make_event(f"extra-{i}"))
        # 3 in memory + 1 in spool = 4
        assert queue.total_size() == 4

    @pytest.mark.asyncio
    async def test_drain_with_spooling_disabled(self, spool_dir: Path) -> None:
        queue = BoundedEventQueue(
            max_memory_queue=5,
            max_spool_messages=0,
            max_spool_bytes=0,
            spool_dir=spool_dir,
        )
        await queue.enqueue(_make_event("e1"))
        count = await queue.drain_to_spool()
        assert count == 0  # Can't drain when spooling disabled
