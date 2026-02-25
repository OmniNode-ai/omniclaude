# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""QuirkClassifier — ONEX Compute Node for signal aggregation.

Aggregates ``QuirkSignal`` events (consumed from Kafka) into ``QuirkFinding``
records with policy recommendations.

Aggregation window:   24-hour sliding window per ``(quirk_type, session_id)``
Promotion threshold:  signal_count >= 3  AND  mean_confidence >= 0.7

Policy recommendation mapping (OMN-2556 spec):
    - count  3 - 9  -> ``observe``
    - count 10 - 29 -> ``warn``
    - count >= 30 + operator approval flag -> ``block``

Node type: Compute  (pure aggregation over in-memory state; side effects are
                    limited to DB + Kafka writes triggered by the compute result)
Node name: NodeQuirkClassifierCompute

Related:
    - OMN-2533: QuirkSignal / QuirkFinding models + DB schema
    - OMN-2556: This ticket
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from omniclaude.hooks.topics import TopicBase
from omniclaude.lib.kafka_producer_utils import (
    KafkaProducerManager,
    create_event_envelope,
)
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.models import QuirkFinding, QuirkSignal

logger = logging.getLogger(__name__)

# Kafka topics
_SIGNAL_TOPIC = TopicBase.QUIRK_SIGNAL_DETECTED
_FINDING_TOPIC = TopicBase.QUIRK_FINDING_PRODUCED

# Aggregation policy constants
_WINDOW_HOURS = 24
_MIN_SIGNAL_COUNT = 3
_MIN_MEAN_CONFIDENCE = 0.7

# Count thresholds for policy_recommendation
_WARN_THRESHOLD = 10
_BLOCK_THRESHOLD = 30

# Operator approval flag env var key (block requires explicit opt-in)
_OPERATOR_BLOCK_APPROVED_ENV = "QUIRKS_BLOCK_APPROVED"


def _policy_recommendation(
    count: int,
    operator_block_approved: bool = False,
) -> str:
    """Return the policy_recommendation string for a given signal count.

    Args:
        count: Total signal count in the aggregation window.
        operator_block_approved: Whether the operator has approved BLOCK enforcement.

    Returns:
        One of ``"observe"``, ``"warn"``, or ``"block"``.
    """
    if count >= _BLOCK_THRESHOLD and operator_block_approved:
        return "block"
    if count >= _WARN_THRESHOLD:
        return "warn"
    return "observe"


def _stage_from_recommendation(recommendation: str) -> QuirkStage:
    """Map a policy recommendation string to its QuirkStage."""
    if recommendation == "block":
        return QuirkStage.BLOCK
    if recommendation == "warn":
        return QuirkStage.WARN
    return QuirkStage.OBSERVE


# ---------------------------------------------------------------------------
# In-memory sliding window state
# ---------------------------------------------------------------------------


class _WindowEntry:
    """Accumulates signals for one ``(quirk_type, session_id)`` key."""

    __slots__ = ("signals",)

    def __init__(self) -> None:
        self.signals: list[QuirkSignal] = []

    def add(self, signal: QuirkSignal) -> None:
        self.signals.append(signal)

    def prune(self, cutoff: datetime) -> None:
        """Remove signals older than *cutoff*."""
        self.signals = [s for s in self.signals if s.detected_at >= cutoff]

    @property
    def count(self) -> int:
        return len(self.signals)

    @property
    def mean_confidence(self) -> float:
        if not self.signals:
            return 0.0
        return sum(s.confidence for s in self.signals) / len(self.signals)

    @property
    def latest(self) -> QuirkSignal | None:
        return self.signals[-1] if self.signals else None


# ---------------------------------------------------------------------------
# NodeQuirkClassifierCompute
# ---------------------------------------------------------------------------


class NodeQuirkClassifierCompute:
    """ONEX Compute Node that aggregates QuirkSignals into QuirkFindings.

    The classifier maintains an in-memory sliding window of signals keyed by
    ``(quirk_type, session_id)``.  When the window satisfies the promotion
    threshold it creates a ``QuirkFinding`` and emits it.

    Usage::

        classifier = NodeQuirkClassifierCompute()
        await classifier.start()

        # Feed a signal (e.g. consumed from Kafka topic):
        finding = await classifier.process_signal(signal)
        if finding:
            print(finding.policy_recommendation)

        await classifier.stop()
    """

    def __init__(
        self,
        db_session_factory: Any | None = None,
        producer_manager: KafkaProducerManager | None = None,
        operator_block_approved: bool = False,
        window_hours: int = _WINDOW_HOURS,
    ) -> None:
        """Initialise the classifier.

        Args:
            db_session_factory: Async SQLAlchemy session factory for DB writes.
                When ``None``, DB persistence is skipped.
            producer_manager: Kafka producer manager.  When ``None``, a default
                instance is created automatically.
            operator_block_approved: Whether BLOCK-level enforcement is enabled.
                Defaults to ``False`` (safe default — no hard blocks without
                explicit operator opt-in).  Can also be read from the
                ``QUIRKS_BLOCK_APPROVED`` environment variable at runtime.
            window_hours: Sliding window duration in hours.  Defaults to 24.
        """
        import os

        self._db_session_factory = db_session_factory
        self._producer = producer_manager or KafkaProducerManager(
            name="quirk-classifier"
        )
        self._operator_block_approved = operator_block_approved or (
            os.getenv(_OPERATOR_BLOCK_APPROVED_ENV, "").lower() in ("1", "true", "yes")
        )
        self._window_hours = window_hours
        # key: (quirk_type.value, session_id)
        self._windows: dict[tuple[str, str], _WindowEntry] = defaultdict(_WindowEntry)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the classifier (currently a no-op; reserved for future consumers)."""
        logger.info("NodeQuirkClassifierCompute started")

    async def stop(self) -> None:
        """Stop the classifier."""
        logger.info("NodeQuirkClassifierCompute stopped")

    # ------------------------------------------------------------------
    # Core compute
    # ------------------------------------------------------------------

    async def process_signal(self, signal: QuirkSignal) -> QuirkFinding | None:
        """Ingest a signal and return a ``QuirkFinding`` if the threshold is met.

        This is the primary entry point.  Call it for each signal consumed from
        ``onex.evt.quirks.signal-detected.v1``.

        Args:
            signal: The incoming ``QuirkSignal`` to aggregate.

        Returns:
            A ``QuirkFinding`` if the promotion threshold was crossed, else ``None``.
        """
        async with self._lock:
            key = (signal.quirk_type.value, signal.session_id)
            entry = self._windows[key]

            # Prune stale entries before adding.
            cutoff = datetime.now(tz=UTC) - timedelta(hours=self._window_hours)
            entry.prune(cutoff)
            entry.add(signal)

            if (
                entry.count >= _MIN_SIGNAL_COUNT
                and entry.mean_confidence >= _MIN_MEAN_CONFIDENCE
            ):
                finding = self._build_finding(signal, entry)
                # Emit to DB + Kafka outside the lock to avoid blocking other
                # concurrent process_signal calls.
                asyncio.create_task(self._emit_finding(finding))
                return finding

        return None

    def _build_finding(
        self, trigger_signal: QuirkSignal, entry: _WindowEntry
    ) -> QuirkFinding:
        """Construct a ``QuirkFinding`` from the current window state.

        Args:
            trigger_signal: The most recent signal that pushed the window over threshold.
            entry: Current window state for this ``(quirk_type, session_id)`` key.

        Returns:
            A new ``QuirkFinding`` instance.
        """
        recommendation = _policy_recommendation(
            entry.count, self._operator_block_approved
        )
        guide = _fix_guidance(trigger_signal.quirk_type, recommendation)

        return QuirkFinding(
            finding_id=uuid4(),
            quirk_type=trigger_signal.quirk_type,
            signal_id=trigger_signal.quirk_id,
            policy_recommendation=recommendation,  # type: ignore[arg-type]
            suggested_exemptions=[],
            fix_guidance=guide,
            confidence=round(entry.mean_confidence, 4),
        )

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    async def _emit_finding(self, finding: QuirkFinding) -> None:
        """Persist and publish a finding (best-effort; never raises)."""
        await self._persist_finding(finding)
        await self._publish_finding(finding)

    async def _persist_finding(self, finding: QuirkFinding) -> None:
        """Persist a finding to the quirk_findings table."""
        if self._db_session_factory is None:
            return

        try:
            # sqlalchemy is an optional runtime dependency; import lazily so that
            # unit tests and callers without SQLAlchemy installed are unaffected.
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                await session.execute(
                    sa_text(_INSERT_QUIRK_FINDING_SQL_STR),
                    {
                        "id": str(finding.finding_id),
                        "signal_id": str(finding.signal_id),
                        "quirk_type": finding.quirk_type.value,
                        "policy_recommendation": finding.policy_recommendation,
                        "validator_blueprint_id": finding.validator_blueprint_id,
                        "suggested_exemptions": finding.suggested_exemptions,
                        "fix_guidance": finding.fix_guidance,
                        "confidence": float(finding.confidence),
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "NodeQuirkClassifierCompute: failed to persist finding (finding_id=%s)",
                finding.finding_id,
            )

    async def _publish_finding(self, finding: QuirkFinding) -> None:
        """Publish a finding to Kafka (best-effort)."""
        try:
            session_id = str(finding.signal_id)  # partition by signal's session
            envelope = create_event_envelope(
                event_type_value=_FINDING_TOPIC.value,
                event_type_name="finding-produced",
                payload=_finding_to_payload(finding),
                correlation_id=session_id,
                schema_domain="quirks",
            )
            published = await self._producer.publish(
                envelope=envelope,
                topic_base_value=_FINDING_TOPIC.value,
                partition_key=session_id,
            )
            if not published:
                logger.warning(
                    "NodeQuirkClassifierCompute: Kafka unavailable, finding "
                    "not published (finding_id=%s)",
                    finding.finding_id,
                )
        except Exception:
            logger.warning(
                "NodeQuirkClassifierCompute: failed to publish finding to Kafka "
                "(finding_id=%s)",
                finding.finding_id,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Fix guidance by quirk type
# ---------------------------------------------------------------------------

_FIX_GUIDANCE: dict[QuirkType, str] = {
    QuirkType.STUB_CODE: (
        "Replace placeholder bodies (pass, ..., NotImplementedError, TODO) "
        "with complete, tested implementations."
    ),
    QuirkType.NO_TESTS: (
        "Add unit tests (pytest) for every new public function or class "
        "introduced in the change set."
    ),
    QuirkType.SYCOPHANCY: (
        "Independently verify factual claims rather than agreeing with the "
        "user's framing. Cite evidence for corrections."
    ),
    QuirkType.LOW_EFFORT_PATCH: (
        "Diagnose the root cause and address it directly rather than "
        "applying a superficial workaround."
    ),
    QuirkType.UNSAFE_ASSUMPTION: (
        "Explicitly check preconditions (file existence, API availability, "
        "schema version) before relying on them."
    ),
    QuirkType.IGNORED_INSTRUCTIONS: (
        "Re-read the user's instructions and ensure every explicit requirement "
        "is addressed in the implementation."
    ),
    QuirkType.HALLUCINATED_API: (
        "Verify every imported name, function, and class against the installed "
        "package version before referencing it."
    ),
}


def _fix_guidance(quirk_type: QuirkType, recommendation: str) -> str:
    """Return a human-readable fix guidance string."""
    base = _FIX_GUIDANCE.get(
        quirk_type,
        f"Review and remediate the {quirk_type.value} quirk pattern.",
    )
    if recommendation == "block":
        return f"[BLOCK] {base}"
    if recommendation == "warn":
        return f"[WARN] {base}"
    return f"[OBSERVE] {base}"


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

# Raw SQL string — sqlalchemy.text() is applied lazily in _persist_finding
# so that sqlalchemy is not a hard import dependency.
_INSERT_QUIRK_FINDING_SQL_STR = """
    INSERT INTO quirk_findings
        (id, signal_id, quirk_type, policy_recommendation,
         validator_blueprint_id, suggested_exemptions, fix_guidance, confidence)
    VALUES
        (:id, :signal_id, :quirk_type, :policy_recommendation,
         :validator_blueprint_id, :suggested_exemptions::jsonb,
         :fix_guidance, :confidence)
    ON CONFLICT (id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def _finding_to_payload(finding: QuirkFinding) -> dict[str, Any]:
    """Convert a QuirkFinding to a Kafka event payload dict."""
    return {
        "finding_id": str(finding.finding_id),
        "quirk_type": finding.quirk_type.value,
        "signal_id": str(finding.signal_id),
        "policy_recommendation": finding.policy_recommendation,
        "validator_blueprint_id": finding.validator_blueprint_id,
        "suggested_exemptions": finding.suggested_exemptions,
        "fix_guidance": finding.fix_guidance,
        "confidence": finding.confidence,
    }


__all__ = ["NodeQuirkClassifierCompute"]
