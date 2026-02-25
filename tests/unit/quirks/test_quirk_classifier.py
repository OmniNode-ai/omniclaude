# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for NodeQuirkClassifierCompute.

Tests cover:
- No finding returned when count < threshold
- Finding returned when count >= 3 AND mean_confidence >= 0.7
- policy_recommendation mapping (observe / warn / block)
- 24-hour sliding window pruning
- Concurrent calls are safe (asyncio.Lock)
- Graceful degradation when Kafka unavailable

Related: OMN-2556
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from omniclaude.quirks.classifier import (
    NodeQuirkClassifierCompute,
    _policy_recommendation,
)
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.models import QuirkSignal

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_signal(
    quirk_type: QuirkType = QuirkType.STUB_CODE,
    session_id: str = "test-session",
    confidence: float = 0.9,
    detected_at: datetime | None = None,
) -> QuirkSignal:
    return QuirkSignal(
        quirk_id=uuid4(),
        quirk_type=quirk_type,
        session_id=session_id,
        confidence=confidence,
        evidence=["evidence text"],
        stage=QuirkStage.WARN,
        detected_at=detected_at or datetime.now(tz=UTC),
        extraction_method="regex",
    )


def _make_classifier(
    operator_block_approved: bool = False,
    publish_result: bool = True,
) -> NodeQuirkClassifierCompute:
    return NodeQuirkClassifierCompute(
        db_session_factory=None,
        publish_hook=AsyncMock(return_value=publish_result),
        operator_block_approved=operator_block_approved,
    )


# ---------------------------------------------------------------------------
# Tests: policy_recommendation helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_policy_recommendation_observe() -> None:
    assert _policy_recommendation(3) == "observe"
    assert _policy_recommendation(9) == "observe"


@pytest.mark.unit
def test_policy_recommendation_warn() -> None:
    assert _policy_recommendation(10) == "warn"
    assert _policy_recommendation(29) == "warn"


@pytest.mark.unit
def test_policy_recommendation_block_requires_approval() -> None:
    # Without operator approval, 30+ signals stay at warn.
    assert _policy_recommendation(30, operator_block_approved=False) == "warn"


@pytest.mark.unit
def test_policy_recommendation_block_with_approval() -> None:
    assert _policy_recommendation(30, operator_block_approved=True) == "block"
    assert _policy_recommendation(100, operator_block_approved=True) == "block"


# ---------------------------------------------------------------------------
# Tests: NodeQuirkClassifierCompute.process_signal
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_finding_below_count_threshold() -> None:
    """Fewer than 3 signals should not produce a finding."""
    classifier = _make_classifier()
    for _ in range(2):
        result = await classifier.process_signal(_make_signal())
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_finding_below_confidence_threshold() -> None:
    """3 signals with mean confidence < 0.7 should not produce a finding."""
    classifier = _make_classifier()
    result = None
    for _ in range(3):
        result = await classifier.process_signal(
            _make_signal(confidence=0.5)  # mean = 0.5 < 0.7
        )
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finding_at_threshold() -> None:
    """Exactly 3 signals with confidence >= 0.7 should produce a finding."""
    classifier = _make_classifier()
    result = None
    for _ in range(3):
        result = await classifier.process_signal(_make_signal(confidence=0.8))
    assert result is not None
    assert result.policy_recommendation == "observe"
    assert result.quirk_type == QuirkType.STUB_CODE
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finding_warn_at_10_signals() -> None:
    """10 signals should yield warn recommendation."""
    classifier = _make_classifier()
    result = None
    for _ in range(10):
        result = await classifier.process_signal(_make_signal(confidence=0.9))
    assert result is not None
    assert result.policy_recommendation == "warn"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finding_block_at_30_signals_with_approval() -> None:
    """30 signals with operator approval should yield block."""
    classifier = _make_classifier(operator_block_approved=True)
    result = None
    for _ in range(30):
        result = await classifier.process_signal(_make_signal(confidence=0.9))
    assert result is not None
    assert result.policy_recommendation == "block"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finding_only_within_session_id_scope() -> None:
    """Signals from different session IDs do not aggregate together."""
    classifier = _make_classifier()
    for _ in range(3):
        await classifier.process_signal(
            _make_signal(session_id="session-a", confidence=0.9)
        )

    # Different session — should start fresh, no finding for 1 signal.
    result = await classifier.process_signal(
        _make_signal(session_id="session-b", confidence=0.9)
    )
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finding_only_within_quirk_type_scope() -> None:
    """Signals of different QuirkTypes are aggregated separately."""
    classifier = _make_classifier()
    for _ in range(3):
        await classifier.process_signal(
            _make_signal(quirk_type=QuirkType.STUB_CODE, confidence=0.9)
        )

    # Different quirk type — fresh window.
    result = await classifier.process_signal(
        _make_signal(quirk_type=QuirkType.NO_TESTS, confidence=0.9)
    )
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_old_signals_pruned_outside_window() -> None:
    """Signals older than 24h are pruned before evaluation."""
    classifier = _make_classifier()
    old_time = datetime.now(tz=UTC) - timedelta(hours=25)
    for _ in range(3):
        await classifier.process_signal(
            _make_signal(confidence=0.9, detected_at=old_time)
        )

    # Add a fresh signal — old ones should have been pruned, so count=1.
    result = await classifier.process_signal(_make_signal(confidence=0.9))
    assert result is None  # Only 1 valid signal after pruning.


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finding_has_fix_guidance() -> None:
    """Produced findings include non-empty fix_guidance."""
    classifier = _make_classifier()
    result = None
    for _ in range(3):
        result = await classifier.process_signal(_make_signal(confidence=0.9))
    assert result is not None
    assert len(result.fix_guidance) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_unavailable_does_not_raise() -> None:
    """Kafka failure during finding emission should not propagate."""
    classifier = _make_classifier(publish_result=False)
    result = None
    for _ in range(3):
        result = await classifier.process_signal(_make_signal(confidence=0.9))
    # Allow background task (asyncio.create_task) to run.
    await asyncio.sleep(0.05)
    # No exception raised — test passes.


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_process_signal_is_safe() -> None:
    """Concurrent process_signal calls should not corrupt window state."""
    classifier = _make_classifier()

    async def feed(n: int) -> None:
        for _ in range(n):
            await classifier.process_signal(_make_signal(confidence=0.9))

    await asyncio.gather(feed(5), feed(5))
    # Window count should be 10 (5+5); mean_confidence = 0.9 → warn.
    key = (QuirkType.STUB_CODE.value, "test-session")
    entry = classifier._windows[key]
    assert entry.count == 10
    assert entry.mean_confidence == pytest.approx(0.9)
