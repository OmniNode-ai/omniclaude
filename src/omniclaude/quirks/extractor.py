# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""QuirkSignalExtractor -- ONEX Effect Node for hook integration.

Wires omniclaude pre/post tool hook events into the Quirks Detector registry
and persists every emitted ``QuirkSignal`` to the database and Kafka.

Design constraints (OMN-2556):
    - Non-blocking: hook events must not be held waiting on detector execution.
      All detection work is dispatched to an ``asyncio.Queue`` background worker.
    - Graceful degradation: if Kafka is unavailable, signals are still persisted
      to DB; a warning is logged but no exception is raised.
    - No thread pool: background tasks use ``asyncio.Queue``, not threads.

Node type: Effect  (external I/O -- DB + Kafka)
Node name: NodeQuirkSignalExtractorEffect

Related:
    - OMN-2533: QuirkSignal / QuirkFinding models + DB schema
    - OMN-2539: Tier 0 detector registry
    - OMN-2548: Tier 1 AST-based detectors
    - OMN-2556: This ticket -- hook integration and signal aggregation
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from omniclaude.hooks.topics import TopicBase
from omniclaude.lib.kafka_publisher_base import (
    create_event_envelope,
    publish_to_kafka,
)
from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.registry import get_all_detectors
from omniclaude.quirks.models import QuirkSignal

logger = logging.getLogger(__name__)

# Quirk signal Kafka topic (ONEX canonical format, OMN-1537)
_SIGNAL_TOPIC = TopicBase.QUIRK_SIGNAL_DETECTED

# Maximum number of pending detection jobs before the queue backpressure kicks
# in (drops the event and logs a warning rather than growing unbounded).
_QUEUE_MAX_SIZE = 256

# Type alias for the injectable publish hook used in unit tests.
_PublishHook = Callable[[dict[str, Any], str, str], Coroutine[Any, Any, bool]]


class NodeQuirkSignalExtractorEffect:
    """ONEX Effect Node that extracts quirk signals from hook events.

    On each hook event the extractor:
    1. Enqueues the ``DetectionContext`` for background processing (non-blocking).
    2. The background worker runs all registered detectors.
    3. Each emitted ``QuirkSignal`` is persisted to the ``quirk_signals`` table.
    4. Each signal is also published to Kafka (best-effort; DB write is authoritative).

    Usage::

        extractor = NodeQuirkSignalExtractorEffect()
        await extractor.start()

        # On each hook event:
        await extractor.on_hook_event(context)

        # Graceful shutdown:
        await extractor.stop()

    The node logs its own execution as an ONEX action event for observability.
    """

    def __init__(
        self,
        db_session_factory: Any | None = None,
        publish_hook: _PublishHook | None = None,
    ) -> None:
        """Initialise the extractor.

        Args:
            db_session_factory: Callable that returns an async SQLAlchemy session
                context manager (``async_sessionmaker`` or similar).  When
                ``None``, DB persistence is skipped (useful in unit tests).
            publish_hook: Async callable ``(envelope, topic, partition_key) -> bool``
                used to publish events.  Defaults to ``kafka_publisher_base.publish_to_kafka``.
                Inject a mock in unit tests to verify publishing without Kafka.
        """
        self._db_session_factory = db_session_factory
        self._publish_hook: _PublishHook = publish_hook or _default_publish
        self._queue: asyncio.Queue[DetectionContext] = asyncio.Queue(
            maxsize=_QUEUE_MAX_SIZE
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._run_id = str(uuid4())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background detection worker."""
        if self._worker_task is not None and not self._worker_task.done():
            logger.debug("NodeQuirkSignalExtractorEffect: worker already running")
            return
        self._worker_task = asyncio.create_task(
            self._detection_worker(), name="quirk-signal-extractor-worker"
        )
        logger.info("NodeQuirkSignalExtractorEffect started (run_id=%s)", self._run_id)

    async def stop(self) -> None:
        """Drain the queue and stop the background worker gracefully."""
        # Signal worker to stop by sending a sentinel None.
        # Use put_nowait to avoid blocking if queue is full.
        try:
            self._queue.put_nowait(None)  # type: ignore[arg-type]
        except asyncio.QueueFull:
            pass

        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "NodeQuirkSignalExtractorEffect: worker did not stop within 5s; cancelling"
                )
                self._worker_task.cancel()
        logger.info("NodeQuirkSignalExtractorEffect stopped (run_id=%s)", self._run_id)

    # ------------------------------------------------------------------
    # Hook entry point
    # ------------------------------------------------------------------

    async def on_hook_event(self, context: DetectionContext) -> None:
        """Enqueue a hook event for background detection (non-blocking).

        This method returns immediately.  If the queue is full the event is
        dropped with a warning (backpressure protection).

        Args:
            context: Detection input bundle built from the hook event payload.
        """
        try:
            self._queue.put_nowait(context)
        except asyncio.QueueFull:
            logger.warning(
                "NodeQuirkSignalExtractorEffect: queue full, dropping hook event "
                "(session_id=%s)",
                context.session_id,
            )

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    async def _detection_worker(self) -> None:
        """Background coroutine that drains the detection queue."""
        logger.debug("NodeQuirkSignalExtractorEffect: worker started")
        while True:
            item: DetectionContext | None = await self._queue.get()
            if item is None:
                # Sentinel received -- stop the worker.
                break
            try:
                await self._process_context(item)
            except Exception:
                logger.exception(
                    "NodeQuirkSignalExtractorEffect: unhandled error processing "
                    "context (session_id=%s)",
                    item.session_id,
                )
            finally:
                self._queue.task_done()
        logger.debug("NodeQuirkSignalExtractorEffect: worker stopped")

    async def _process_context(self, context: DetectionContext) -> None:
        """Run all detectors against a context and persist the results."""
        started_at = datetime.now(tz=UTC)
        detectors = get_all_detectors()
        all_signals: list[QuirkSignal] = []

        for detector in detectors:
            try:
                signals = detector.detect(context)
                all_signals.extend(signals)
            except Exception:
                detector_name = type(detector).__name__
                logger.exception(
                    "NodeQuirkSignalExtractorEffect: detector %s raised an "
                    "exception (session_id=%s)",
                    detector_name,
                    context.session_id,
                )

        duration_ms = int((datetime.now(tz=UTC) - started_at).total_seconds() * 1000)
        logger.debug(
            "NodeQuirkSignalExtractorEffect: detected %d signal(s) in %dms "
            "(session_id=%s)",
            len(all_signals),
            duration_ms,
            context.session_id,
        )

        # Log own execution as ONEX action event for observability.
        self._log_action_event(context.session_id, len(all_signals), duration_ms)

        for signal in all_signals:
            await self._persist_signal(signal)
            await self._publish_signal(signal)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_signal(self, signal: QuirkSignal) -> None:
        """Persist a signal to the quirk_signals table (if DB configured)."""
        if self._db_session_factory is None:
            logger.debug(
                "NodeQuirkSignalExtractorEffect: no DB session factory, skipping persist"
            )
            return

        try:
            # sqlalchemy is an optional runtime dependency; import lazily so that
            # unit tests and callers without SQLAlchemy installed are unaffected.
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                ast_span_json = (
                    list(signal.ast_span) if signal.ast_span is not None else None
                )
                await session.execute(
                    sa_text(_INSERT_QUIRK_SIGNAL_SQL_STR),
                    {
                        "id": str(signal.quirk_id),
                        "quirk_type": signal.quirk_type.value,
                        "session_id": signal.session_id,
                        "confidence": float(signal.confidence),
                        "evidence": signal.evidence,
                        "stage": signal.stage.value,
                        "detected_at": signal.detected_at,
                        "extraction_method": signal.extraction_method,
                        "file_path": signal.file_path,
                        "diff_hunk": signal.diff_hunk,
                        "ast_span": ast_span_json,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "NodeQuirkSignalExtractorEffect: failed to persist signal "
                "(quirk_id=%s)",
                signal.quirk_id,
            )

    # ------------------------------------------------------------------
    # Kafka publishing
    # ------------------------------------------------------------------

    async def _publish_signal(self, signal: QuirkSignal) -> None:
        """Publish a signal to Kafka (best-effort; logs warning on failure)."""
        try:
            envelope = create_event_envelope(
                event_type_value=_SIGNAL_TOPIC.value,
                payload=_signal_to_payload(signal),
                correlation_id=signal.session_id,
                schema_ref="registry://onex/omniclaude/quirk-signal-detected/v1",
            )
            published = await self._publish_hook(
                envelope, _SIGNAL_TOPIC.value, signal.session_id
            )
            if not published:
                logger.warning(
                    "NodeQuirkSignalExtractorEffect: Kafka unavailable, signal "
                    "not published (quirk_id=%s) -- DB write is authoritative",
                    signal.quirk_id,
                )
        except Exception:
            logger.warning(
                "NodeQuirkSignalExtractorEffect: failed to publish signal to Kafka "
                "(quirk_id=%s) -- DB write is authoritative",
                signal.quirk_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def _log_action_event(
        self, session_id: str, signal_count: int, duration_ms: int
    ) -> None:
        """Log own execution as an ONEX action event (best-effort, sync)."""
        logger.info(
            "quirk_signal_extractor.executed session_id=%s signals=%d duration_ms=%d",
            session_id,
            signal_count,
            duration_ms,
        )


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

# Raw SQL string -- wrapping in sqlalchemy.text() is deferred to _persist_signal
# so that sqlalchemy is not a hard import dependency (it may not be installed).
_INSERT_QUIRK_SIGNAL_SQL_STR = """
    INSERT INTO quirk_signals
        (id, quirk_type, session_id, confidence, evidence, stage,
         detected_at, extraction_method, file_path, diff_hunk, ast_span)
    VALUES
        (:id, :quirk_type, :session_id, :confidence, :evidence::jsonb,
         :stage, :detected_at, :extraction_method, :file_path,
         :diff_hunk, :ast_span::jsonb)
    ON CONFLICT (id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _default_publish(
    envelope: dict[str, Any], topic: str, partition_key: str
) -> bool:
    """Default publish implementation using the shared kafka_publisher_base."""
    return await publish_to_kafka(topic, envelope, partition_key)


def _signal_to_payload(signal: QuirkSignal) -> dict[str, Any]:
    """Convert a QuirkSignal to a Kafka event payload dict."""
    return {
        "quirk_id": str(signal.quirk_id),
        "quirk_type": signal.quirk_type.value,
        "session_id": signal.session_id,
        "confidence": signal.confidence,
        "evidence": signal.evidence,
        "stage": signal.stage.value,
        "detected_at": signal.detected_at.isoformat(),
        "extraction_method": signal.extraction_method,
        "diff_hunk": signal.diff_hunk,
        "file_path": signal.file_path,
        "ast_span": list(signal.ast_span) if signal.ast_span is not None else None,
    }


__all__ = ["NodeQuirkSignalExtractorEffect"]
