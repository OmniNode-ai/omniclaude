# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Evidence dual-write: disk (authoritative) + Kafka (fail-open).

Writes verification evidence to `.onex_state/evidence/task-{id}/` on disk
and emits an EvidenceWritten Kafka event. Disk is authoritative in Phase A;
Kafka emission is best-effort (fail-open).

Every evidence file carries a timestamp and contract fingerprint.
Re-verification emits a fresh Kafka event — stale evidence is never
silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ModelCheckResult(BaseModel):
    """Result of a single mechanical check."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    criterion: str
    status: str = Field(description="PASS | FAIL")
    output: str = ""


class ModelSelfCheckResult(BaseModel):
    """Result of self-check (A) verification."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    task_id: str
    passed: bool
    checks: list[ModelCheckResult] = Field(default_factory=list)
    contract_fingerprint: str = ""


class ModelVerifierCheckResult(BaseModel):
    """Result of verifier (B) independent verification."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    task_id: str
    passed: bool
    findings: list[str] = Field(default_factory=list)
    contract_fingerprint: str = ""


class ModelEvidenceWrittenEvent(BaseModel):
    """Kafka event emitted on every evidence write."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    task_id: str
    session_id: str = ""
    correlation_id: str = ""
    evidence_type: str = Field(description="self_check | verifier")
    evidence_path: str
    passed: bool
    contract_fingerprint: str = ""
    emitted_at: datetime


def emit_event(event: ModelEvidenceWrittenEvent) -> None:
    """Emit an EvidenceWritten event via the canonical emit-effect node.

    Import failures are loud (error-level log): a broken emitter dependency
    must never regress to a silently-swallowed debug log (OMN-15968 — this
    is what OMN-13213's D1 repoint left undone). Runtime emission failures
    (unregistered event type, spool/publish errors) stay fail-open at
    warning, matching this writer's dual-write posture: disk is
    authoritative, Kafka is best-effort.
    """
    try:
        from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (  # noqa: I001
            HandlerEventEmitEffect,
        )
        from omnimarket.nodes.node_event_emit_effect.models.model_emit_request import (
            ModelEmitRequest,
        )
    except ImportError:
        logger.error(
            "node_event_emit_effect import failed; evidence event for "
            "task %s not emitted",
            event.task_id,
            exc_info=True,
        )
        return

    try:
        HandlerEventEmitEffect().handle(
            ModelEmitRequest(
                # NO explicit `topic` override (OMN-18627). This call site used
                # to pass `topic=build_topic(TopicBase.EVIDENCE_WRITTEN)` while
                # borrowing this registered class's durability tier, on the
                # reasoning that `evidence.written` was the "correct" topic and
                # `team.evidence.written` merely the nearest registration.
                #
                # Both halves of that were wrong, and the cost was measured.
                # `onex.evt.omniclaude.evidence-written.v1` was never
                # provisioned on the lab dev-lane broker and carried no WRITE
                # grant for the hook-edge principal, because nothing derived
                # from a contract can provision a topic no contract declares --
                # an override is invisible to a class-keyed scan by
                # construction. And the override was not routing "around" this
                # class: `ModelEvidenceWrittenEvent` carries exactly the
                # `session_id` + `task_id` this registration requires and keys
                # on, so the registry's own fan-out was always the right
                # destination. From 2026-09-17T20:43Z the resulting denial sat
                # at the head of the emit spool, and because `_drain_backlog`
                # stops at the first failure to preserve ordering, it held 126
                # records of four AUTHORIZED classes behind eight of these --
                # about nine seconds of authorization ladder per journal record,
                # against an arrival rate that would have reached the journal's
                # drop-oldest bound in roughly 45 hours.
                #
                # Resolving through the class is what makes this emission
                # governable: `team.evidence.written` is declared in
                # `governed_event_classes`, the gate scans this directory, and
                # the topic comes from the one registry that owns it.
                event_type="team.evidence.written",
                payload=event.model_dump(mode="json"),
                correlation_id=event.correlation_id or None,
            )
        )
    except (
        RuntimeError,
        ValueError,
        AttributeError,
        TypeError,
        OSError,
        KeyError,
    ):
        # KeyError: node_event_emit_effect's default publish-adapter
        # resolution (ModelKafkaEventBusConfig) reads KAFKA_BOOTSTRAP_SERVERS
        # via a bare os.environ[...] with no default (OMN-16167 -- a missing
        # bootstrap target is a loud construction failure by design, not a
        # silent spool-only fallback). A unit-test / dev environment with no
        # Kafka target configured must still hit this writer's own fail-open
        # contract (disk is authoritative, Kafka is best-effort) rather than
        # propagate that construction failure uncaught.
        logger.warning(
            "Failed to emit EvidenceWritten event for task %s (fail-open)",
            event.task_id,
            exc_info=True,
        )


def _compute_fingerprint(data: str) -> str:
    """SHA-256 fingerprint of evidence content for identity."""
    return hashlib.sha256(data.encode()).hexdigest()[:16]


class EvidenceWriter:
    """Writes verification evidence to disk and emits Kafka events.

    Disk writes are authoritative (Phase A). Kafka emission is fail-open.
    """

    def __init__(self, state_dir: str) -> None:
        self._state_dir = Path(state_dir)

    def _evidence_dir(self, task_id: str) -> Path:
        return self._state_dir / "evidence" / task_id

    def write_self_check(
        self,
        result: ModelSelfCheckResult,
        *,
        session_id: str = "",
        correlation_id: str = "",
        recorded_at: datetime | None = None,
    ) -> Path:
        """Write self-check evidence to disk and emit Kafka event.

        Args:
            result: The self-check verification result.
            session_id: Session identifier for tracing.
            correlation_id: Correlation identifier for tracing.
            recorded_at: Explicit timestamp for deterministic testing.
                Defaults to now(UTC) if not provided.

        Returns the path to the written evidence file.
        """
        evidence_dir = self._evidence_dir(result.task_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        now = recorded_at or datetime.now(UTC)
        payload = {
            "task_id": result.task_id,
            "evidence_type": "self_check",
            "passed": result.passed,
            "checks": [c.model_dump() for c in result.checks],
            "contract_fingerprint": result.contract_fingerprint,
            "timestamp": now.isoformat(),
            "content_fingerprint": _compute_fingerprint(
                json.dumps(
                    [c.model_dump() for c in result.checks], sort_keys=True, default=str
                )
            ),
        }

        evidence_path = evidence_dir / "self-check.yaml"
        evidence_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

        emit_event(
            ModelEvidenceWrittenEvent(
                task_id=result.task_id,
                session_id=session_id,
                correlation_id=correlation_id,
                evidence_type="self_check",
                evidence_path=str(evidence_path),
                passed=result.passed,
                contract_fingerprint=result.contract_fingerprint,
                emitted_at=now,
            )
        )

        return evidence_path

    def write_verifier_check(
        self,
        result: ModelVerifierCheckResult,
        *,
        session_id: str = "",
        correlation_id: str = "",
        recorded_at: datetime | None = None,
    ) -> Path:
        """Write verifier evidence to disk and emit Kafka event.

        Args:
            result: The verifier verification result.
            session_id: Session identifier for tracing.
            correlation_id: Correlation identifier for tracing.
            recorded_at: Explicit timestamp for deterministic testing.
                Defaults to now(UTC) if not provided.

        Returns the path to the written evidence file.
        """
        evidence_dir = self._evidence_dir(result.task_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        now = recorded_at or datetime.now(UTC)
        payload = {
            "task_id": result.task_id,
            "evidence_type": "verifier",
            "passed": result.passed,
            "findings": result.findings,
            "contract_fingerprint": result.contract_fingerprint,
            "timestamp": now.isoformat(),
            "content_fingerprint": _compute_fingerprint(
                json.dumps(result.findings, sort_keys=True, default=str)
            ),
        }

        evidence_path = evidence_dir / "verifier-check.yaml"
        evidence_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

        emit_event(
            ModelEvidenceWrittenEvent(
                task_id=result.task_id,
                session_id=session_id,
                correlation_id=correlation_id,
                evidence_type="verifier",
                evidence_path=str(evidence_path),
                passed=result.passed,
                contract_fingerprint=result.contract_fingerprint,
                emitted_at=now,
            )
        )

        return evidence_path
