# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Append-only routing decision recorder for cost/quality tuning.

Records every routing decision to `.onex_state/routing/decisions.ndjson` and
emits a Kafka event (fail-open). Each record captures the intended dispatch
surface, the executed surface (may differ on fallback), model, rationale,
and reroute reason — rich enough for post-hoc cost/quality analysis.

OMN-7035
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1.0.0"
_DECISIONS_SUBPATH = "routing/decisions.ndjson"


class ModelRoutingDecision(BaseModel):
    """A single routing decision record."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    task_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: str = _SCHEMA_VERSION
    intended_surface: str
    executed_surface: str
    agent_model: str
    rationale: str
    fallback: str | None = None
    reroute_reason: str | None = None


class RoutingRecorder:
    """Records routing decisions to append-only NDJSON and emits Kafka events.

    Args:
        state_dir: Root directory for state files. Defaults to
            ``$ONEX_STATE_DIR`` or ``.onex_state`` in the current directory.
    """

    def __init__(self, state_dir: str | None = None) -> None:
        self._state_dir = Path(state_dir or os.getenv("ONEX_STATE_DIR", ".onex_state"))
        self._decisions_path = self._state_dir / _DECISIONS_SUBPATH

    def record(
        self,
        *,
        task_id: str,
        dispatch_surface: str,
        agent_model: str,
        rationale: str,
        fallback: str | None = None,
        executed_surface: str | None = None,
        reroute_reason: str | None = None,
    ) -> ModelRoutingDecision:
        """Record a routing decision to disk and emit a Kafka event.

        Args:
            task_id: The task being routed.
            dispatch_surface: Intended dispatch surface.
            agent_model: Model selected for execution.
            rationale: Why this surface/model was chosen.
            fallback: Fallback surface if primary fails (None if none).
            executed_surface: Actual surface used (defaults to dispatch_surface).
            reroute_reason: Why a reroute occurred (None if no fallback triggered).

        Returns:
            The recorded decision model.
        """
        decision = ModelRoutingDecision(
            task_id=task_id,
            intended_surface=dispatch_surface,
            executed_surface=executed_surface or dispatch_surface,
            agent_model=agent_model,
            rationale=rationale,
            fallback=fallback,
            reroute_reason=reroute_reason,
        )

        self._append_to_disk(decision)
        self._emit_kafka_event(decision)

        return decision

    def read_all(self) -> list[ModelRoutingDecision]:
        """Read all recorded routing decisions from the NDJSON file.

        Returns:
            List of decision models in chronological order.
        """
        if not self._decisions_path.exists():
            return []

        decisions: list[ModelRoutingDecision] = []
        for line in self._decisions_path.read_text().splitlines():
            stripped = line.strip()
            if stripped:
                decisions.append(ModelRoutingDecision.model_validate_json(stripped))
        return decisions

    def _append_to_disk(self, decision: ModelRoutingDecision) -> None:
        """Append decision as a single NDJSON line (never overwrite)."""
        self._decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with self._decisions_path.open("a") as f:
            f.write(decision.model_dump_json() + "\n")

    def _emit_kafka_event(self, decision: ModelRoutingDecision) -> None:
        """Emit routing decision as Kafka event. Fail-open: errors are logged."""
        try:
            from omniclaude.publisher.emit_client import EmitClient

            socket_path = os.getenv("OMNICLAUDE_EMIT_SOCKET", "")
            if not socket_path:
                logger.debug("No emit socket configured, skipping Kafka emission")
                return

            client = EmitClient(socket_path=socket_path)
            client.emit(
                event_type="routing.decision.recorded",
                payload=decision.model_dump(),
            )
        except (OSError, ImportError, KeyError, ValueError, TypeError):
            logger.debug("Kafka emission failed (fail-open)", exc_info=True)
