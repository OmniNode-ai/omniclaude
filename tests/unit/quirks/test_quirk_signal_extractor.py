# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for NodeQuirkSignalExtractorEffect.

Tests cover:
- Queue enqueue / non-blocking contract
- Detector dispatch and signal collection
- Kafka publish called per signal (mock)
- Graceful degradation when Kafka is unavailable
- Queue backpressure (drop + warn when queue full)

Related: OMN-2556
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.extractor import NodeQuirkSignalExtractorEffect
from omniclaude.quirks.models import QuirkSignal

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_signal(session_id: str = "test-session") -> QuirkSignal:
    return QuirkSignal(
        quirk_type=QuirkType.STUB_CODE,
        session_id=session_id,
        confidence=0.9,
        evidence=["NotImplementedError found"],
        stage=QuirkStage.WARN,
        detected_at=datetime.now(tz=UTC),
        extraction_method="regex",
    )


def _make_context(session_id: str = "test-session") -> DetectionContext:
    return DetectionContext(
        session_id=session_id,
        diff="+    raise NotImplementedError\n",
    )


def _make_extractor(
    mock_signals: list[QuirkSignal] | None = None,
) -> NodeQuirkSignalExtractorEffect:
    """Create an extractor with a mocked detector registry and no-op Kafka."""
    extractor = NodeQuirkSignalExtractorEffect(
        db_session_factory=None,  # skip DB
        producer_manager=MagicMock(),
    )
    # Patch producer.publish to always succeed
    extractor._producer.publish = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    return extractor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_and_stop_lifecycle() -> None:
    """Extractor starts and stops cleanly."""
    extractor = _make_extractor()
    await extractor.start()
    assert extractor._worker_task is not None
    assert not extractor._worker_task.done()
    await extractor.stop()
    assert extractor._worker_task.done()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_hook_event_is_non_blocking() -> None:
    """on_hook_event returns immediately without blocking."""
    extractor = _make_extractor()
    await extractor.start()
    ctx = _make_context()
    # Should return immediately.
    await extractor.on_hook_event(ctx)
    await extractor.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_full_drops_event(caplog: pytest.LogCaptureFixture) -> None:
    """When the queue is full the event is dropped and a warning is logged."""
    extractor = NodeQuirkSignalExtractorEffect(
        db_session_factory=None,
        producer_manager=MagicMock(),
    )
    # Manually fill the queue to capacity.
    for _ in range(extractor._queue.maxsize):
        extractor._queue.put_nowait(_make_context())

    ctx = _make_context(session_id="overflow-session")
    import logging

    with caplog.at_level(logging.WARNING, logger="omniclaude.quirks.extractor"):
        await extractor.on_hook_event(ctx)

    assert any("queue full" in record.message.lower() for record in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_signals_published_to_kafka() -> None:
    """Each detected signal triggers a Kafka publish call."""
    signal = _make_signal()
    extractor = _make_extractor()

    with patch(
        "omniclaude.quirks.extractor.get_all_detectors",
        return_value=[_FakeDetector([signal])],
    ):
        await extractor.start()
        await extractor.on_hook_event(_make_context())
        # Allow the background worker to process.
        await asyncio.sleep(0.05)
        await extractor.stop()

    extractor._producer.publish.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_signals_no_kafka_call() -> None:
    """When detectors emit no signals, Kafka is not called."""
    extractor = _make_extractor()

    with patch(
        "omniclaude.quirks.extractor.get_all_detectors",
        return_value=[_FakeDetector([])],
    ):
        await extractor.start()
        await extractor.on_hook_event(_make_context())
        await asyncio.sleep(0.05)
        await extractor.stop()

    extractor._producer.publish.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_unavailable_does_not_raise() -> None:
    """If Kafka publish fails, the extractor does not raise (graceful degradation)."""
    signal = _make_signal()
    extractor = _make_extractor()
    extractor._producer.publish = AsyncMock(return_value=False)  # type: ignore[attr-defined]

    with patch(
        "omniclaude.quirks.extractor.get_all_detectors",
        return_value=[_FakeDetector([signal])],
    ):
        await extractor.start()
        await extractor.on_hook_event(_make_context())
        await asyncio.sleep(0.05)
        await extractor.stop()
    # No exception raised — test passes if we reach here.


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detector_exception_is_isolated() -> None:
    """An exception in one detector does not prevent others from running."""
    signal = _make_signal()
    extractor = _make_extractor()

    with patch(
        "omniclaude.quirks.extractor.get_all_detectors",
        return_value=[_FaultyDetector(), _FakeDetector([signal])],
    ):
        await extractor.start()
        await extractor.on_hook_event(_make_context())
        await asyncio.sleep(0.05)
        await extractor.stop()

    # Second detector's signal should still have been published.
    extractor._producer.publish.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_double_start_is_idempotent() -> None:
    """Calling start() twice should not spawn a second worker."""
    extractor = _make_extractor()
    await extractor.start()
    first_task = extractor._worker_task
    await extractor.start()
    assert extractor._worker_task is first_task
    await extractor.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDetector:
    """Detector stub that returns a fixed list of signals."""

    def __init__(self, signals: list[QuirkSignal]) -> None:
        self._signals = signals

    def detect(self, context: DetectionContext) -> list[QuirkSignal]:
        return list(self._signals)


class _FaultyDetector:
    """Detector stub that always raises."""

    def detect(self, context: DetectionContext) -> list[QuirkSignal]:
        raise RuntimeError("intentional detector failure")
