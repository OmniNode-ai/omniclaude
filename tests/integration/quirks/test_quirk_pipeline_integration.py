# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Integration tests for the QuirkSignal → QuirkFinding pipeline.

These tests exercise the full path from hook event injection through detector
dispatch, signal emission, and classifier aggregation.  They do NOT require a
live database or Kafka broker — persistence and publishing are mocked.

Test scenarios:
1. Inject a fake hook event → verify signal produced and Kafka publish called.
2. Inject 10 signals → verify QuirkFinding produced with ``warn`` recommendation.
3. Graceful degradation: Kafka down → signals still written to mock DB.

Related: OMN-2556
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from omniclaude.quirks.classifier import NodeQuirkClassifierCompute
from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.extractor import NodeQuirkSignalExtractorEffect
from omniclaude.quirks.models import QuirkSignal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_code_diff() -> str:
    """Minimal diff containing a NotImplementedError stub."""
    return (
        "diff --git a/src/foo/bar.py b/src/foo/bar.py\n"
        "--- a/src/foo/bar.py\n"
        "+++ b/src/foo/bar.py\n"
        "@@ -1,3 +1,5 @@\n"
        "+def compute():\n"
        "+    raise NotImplementedError\n"
    )


def _make_signal(
    session_id: str = "integration-session",
    confidence: float = 0.9,
) -> QuirkSignal:
    return QuirkSignal(
        quirk_id=uuid4(),
        quirk_type=QuirkType.STUB_CODE,
        session_id=session_id,
        confidence=confidence,
        evidence=["NotImplementedError found"],
        stage=QuirkStage.WARN,
        detected_at=datetime.now(tz=UTC),
        extraction_method="regex",
    )


# ---------------------------------------------------------------------------
# Scenario 1: hook event → signal → Kafka publish
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hook_event_produces_signal_and_publishes_to_kafka() -> None:
    """Injecting a fake hook event produces a QuirkSignal and publishes to Kafka."""
    published_signals: list[dict[str, Any]] = []

    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock(
        side_effect=lambda envelope, topic_base_value, partition_key: (
            published_signals.append(envelope) or True
        )
    )

    extractor = NodeQuirkSignalExtractorEffect(
        db_session_factory=None,
        producer_manager=mock_producer,
    )

    ctx = DetectionContext(
        session_id="integration-session",
        diff=_stub_code_diff(),
    )

    await extractor.start()
    await extractor.on_hook_event(ctx)
    # Allow background worker to drain.
    await asyncio.sleep(0.1)
    await extractor.stop()

    assert len(published_signals) >= 1, "Expected at least one signal to be published"
    payload = published_signals[0].get("payload", {})
    assert payload.get("quirk_type") == QuirkType.STUB_CODE.value
    assert payload.get("session_id") == "integration-session"
    assert float(payload.get("confidence", 0)) >= 0.7


# ---------------------------------------------------------------------------
# Scenario 2: 10 signals → QuirkFinding with ``warn``
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ten_signals_produce_warn_finding() -> None:
    """Injecting 10 high-confidence signals into the classifier yields a warn finding."""
    classifier = NodeQuirkClassifierCompute(
        db_session_factory=None,
        producer_manager=MagicMock(),
        operator_block_approved=False,
    )
    classifier._producer.publish = AsyncMock(return_value=True)  # type: ignore[attr-defined]

    await classifier.start()

    finding = None
    for _ in range(10):
        finding = await classifier.process_signal(_make_signal(confidence=0.9))

    await asyncio.sleep(0.05)
    await classifier.stop()

    assert finding is not None, "Expected a QuirkFinding after 10 signals"
    assert finding.policy_recommendation == "warn"
    assert finding.quirk_type == QuirkType.STUB_CODE
    assert finding.confidence >= 0.7
    assert "WARN" in finding.fix_guidance or "warn" in finding.fix_guidance.lower()


# ---------------------------------------------------------------------------
# Scenario 3: Kafka down → signals still processed (DB write is authoritative)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kafka_down_signals_still_processed() -> None:
    """When Kafka is unavailable, signals are still processed by the extractor."""
    processed_signals: list[QuirkSignal] = []
    calls: list[str] = []

    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock(return_value=False)  # Kafka unavailable

    extractor = NodeQuirkSignalExtractorEffect(
        db_session_factory=None,  # no DB in this test
        producer_manager=mock_producer,
    )

    original_process = extractor._process_context

    async def _spy_process(context: DetectionContext) -> None:
        calls.append(context.session_id)
        await original_process(context)

    extractor._process_context = _spy_process  # type: ignore[method-assign]

    ctx = DetectionContext(
        session_id="kafka-down-session",
        diff=_stub_code_diff(),
    )

    await extractor.start()
    await extractor.on_hook_event(ctx)
    await asyncio.sleep(0.1)
    await extractor.stop()

    # Context was still processed (detection ran, even though Kafka publish failed).
    assert "kafka-down-session" in calls, (
        "Expected context to be processed despite Kafka being down"
    )
    # Kafka publish was attempted but returned False (no exception).
    mock_producer.publish.assert_awaited()


# ---------------------------------------------------------------------------
# Scenario 4: End-to-end extractor → classifier wiring
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_extractor_to_classifier_end_to_end() -> None:
    """Full pipeline: hook event → extractor detects → classifier aggregates → finding."""
    # Wire extractor and classifier together via a shared signal channel.
    signals_received: list[QuirkSignal] = []

    mock_producer_ext = MagicMock()
    mock_producer_clf = MagicMock()
    mock_producer_clf.publish = AsyncMock(return_value=True)

    classifier = NodeQuirkClassifierCompute(
        db_session_factory=None,
        producer_manager=mock_producer_clf,
    )
    await classifier.start()

    # Hook the extractor's publish to forward signals to the classifier.
    async def _forward_to_classifier(
        envelope: dict[str, Any],
        topic_base_value: str,
        partition_key: str,
    ) -> bool:
        # Re-build a QuirkSignal from the payload and feed to classifier.
        payload = envelope.get("payload", {})
        sig = QuirkSignal(
            quirk_type=QuirkType(payload["quirk_type"]),
            session_id=payload["session_id"],
            confidence=float(payload["confidence"]),
            evidence=payload["evidence"],
            stage=QuirkStage(payload["stage"]),
            detected_at=datetime.fromisoformat(payload["detected_at"]),
            extraction_method=payload["extraction_method"],
            diff_hunk=payload.get("diff_hunk"),
            file_path=payload.get("file_path"),
        )
        signals_received.append(sig)
        await classifier.process_signal(sig)
        return True

    mock_producer_ext.publish = AsyncMock(side_effect=_forward_to_classifier)

    extractor = NodeQuirkSignalExtractorEffect(
        db_session_factory=None,
        producer_manager=mock_producer_ext,
    )

    await extractor.start()

    # Inject 3 hook events with stub code diffs.
    for _ in range(3):
        ctx = DetectionContext(
            session_id="e2e-session",
            diff=_stub_code_diff(),
        )
        await extractor.on_hook_event(ctx)

    await asyncio.sleep(0.2)  # allow all background tasks to run
    await extractor.stop()
    await classifier.stop()

    # At least 3 signals should have been routed through the classifier.
    assert len(signals_received) >= 3

    # The classifier's window for this session should have produced a finding.
    key = (QuirkType.STUB_CODE.value, "e2e-session")
    entry = classifier._windows[key]
    assert entry.count >= 3
    assert entry.mean_confidence >= 0.7
