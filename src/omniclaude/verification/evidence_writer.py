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
    """Emit an EvidenceWritten event to Kafka. Fail-open: logs on error."""
    try:
        from omniclaude.hooks.handler_event_emitter import HookEventEmitter
        from omniclaude.hooks.topics import TopicBase, build_topic

        topic = build_topic(TopicBase.AUDIT_DISPATCH_VALIDATED)
        emitter = HookEventEmitter()
        emitter.emit_sync(
            topic=topic,
            payload=event.model_dump(mode="json"),
        )
    except (OSError, RuntimeError, ValueError):
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
    ) -> Path:
        """Write self-check evidence to disk and emit Kafka event.

        Returns the path to the written evidence file.
        """
        evidence_dir = self._evidence_dir(result.task_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC)
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
    ) -> Path:
        """Write verifier evidence to disk and emit Kafka event.

        Returns the path to the written evidence file.
        """
        evidence_dir = self._evidence_dir(result.task_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC)
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
