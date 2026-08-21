# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Typed models for the hook-event spool drain / shipper (OMN-16090).

These models are the PRODUCER half of the gateway seam. The consumer half
lives in omnimarket's ``node_hook_event_capture`` (``ModelHookEventCaptureRequest`` /
``ModelCapturedHookEvent`` in
``omnimarket/src/omnimarket/nodes/node_hook_event_capture/models/model_hook_event_capture_request.py``)
and the gateway's own coarse structural filter lives in
``omninode_infra/docker/onex-api/workflow-contracts.yaml`` under the
``hook-event-capture`` catalog entry. All three must stay field-for-field
matched; the validators here are deliberately the SAME shape as the consumer's
so a malformed batch is caught locally, before a network call, rather than
discovered as a 400 at the gateway.

Spool file format (ground truth, read from source — NOT assumed): one JSON
file per event, written by ``omnibase_infra.cli.receipt_mode._emit_or_spool``
on emit-daemon-socket failure, under
``<ONEX_STATE_DIR>/<SPOOL_DIR_NAME>/{event-type-with-dashes}-{stem}.json``.
Each file is a flat dict: ``{"event_type": str, "payload": dict,
"spooled_at_utc": str, "spool_reason": str}``. This is NOT the same shape as
omnimarket's ``node_emit_daemon`` ``ModelQueuedEvent`` (which has its own,
separately-rooted spool for Kafka-publish durability) — the two are different
spools serving different producers; this module drains the
``omnibase_infra``-written one, which is the one that actually accumulates on
an operator Mac when the emit daemon socket is unavailable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Mirrors omnimarket's ModelCapturedHookEvent.event_sha / batch_sha validators
# exactly (SHA256_HEX) so a malformed hash is caught here, not at the gateway.
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

# Mirrors the consumer's EVENT_TYPE pattern.
EVENT_TYPE_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")

# Mirrors the gateway catalog's `source` pattern
# (workflow-contracts.yaml: "^[a-z0-9][a-z0-9_-]{2,63}$").
SOURCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")

MAX_EVENTS_PER_BATCH = 250
MAX_PAYLOAD_JSON_CHARS = 32768

# Opaque, heterogeneous JSON object type: raw hook-event payload bodies and
# gateway request/response bodies, whose shape genuinely varies per
# event_type / endpoint and is not modeled here. A named alias (rather than a
# repeated inline ``dict[str, Any]``) keeps every downstream annotation a
# simple reference.  # ONEX_EXCLUDE: dict_str_any - opaque JSON payload, shape is not fixed by this producer
JsonObject = dict[str, Any]


class ModelSpoolRecord(BaseModel):
    """One raw spool file as written by ``omnibase_infra`` receipt-mode.

    ``extra="ignore"`` per the repo's event-schema policy (docs/CLAUDE.md
    invariant: event schemas are frozen but tolerant of additive fields) —
    an older or newer spool writer adding a field must not break the drain.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_type: str = Field(min_length=1)
    payload: JsonObject = Field(default_factory=dict)
    spooled_at_utc: str | None = Field(default=None)
    spool_reason: str | None = Field(default=None)


class ModelCapturedHookEvent(BaseModel):
    """One event framed for the ``hook-event-capture`` gateway contract.

    Field set and validators are deliberately identical to the consumer's
    ``ModelCapturedHookEvent`` (omnimarket) — see module docstring.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str = Field(min_length=3, max_length=200)
    event_sha: str
    occurred_at: str = Field(min_length=20, max_length=40)
    payload_json: str = Field(min_length=2, max_length=MAX_PAYLOAD_JSON_CHARS)

    event_id: str | None = Field(default=None, max_length=64)
    correlation_id: str | None = Field(default=None, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)
    spooled_at: str | None = Field(default=None, max_length=40)
    spool_reason: str | None = Field(default=None, max_length=512)

    @field_validator("event_type")
    @classmethod
    def _event_type_shape(cls, value: str) -> str:
        if not EVENT_TYPE_PATTERN.fullmatch(value):
            raise ValueError(
                f"event_type {value!r} is not a dotted lowercase producer type"
            )
        return value

    @field_validator("event_sha")
    @classmethod
    def _sha_shape(cls, value: str) -> str:
        if not SHA256_HEX.fullmatch(value):
            raise ValueError("event_sha must be a lowercase sha256 hex digest")
        return value


class ModelHookEventCaptureBatch(BaseModel):
    """A gateway-submittable batch: ``payload`` of the ``hook-event-capture``
    workflow_type. Field set matches the gateway's passthrough spec exactly
    (``source``, ``batch_sha``, ``events``; ``additionalProperties: false``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=3, max_length=64)
    batch_sha: str
    events: list[ModelCapturedHookEvent] = Field(
        min_length=1, max_length=MAX_EVENTS_PER_BATCH
    )

    @field_validator("source")
    @classmethod
    def _source_shape(cls, value: str) -> str:
        if not SOURCE_PATTERN.fullmatch(value):
            raise ValueError(
                f"source {value!r} does not match {SOURCE_PATTERN.pattern}"
            )
        return value

    @field_validator("batch_sha")
    @classmethod
    def _batch_sha_shape(cls, value: str) -> str:
        if not SHA256_HEX.fullmatch(value):
            raise ValueError("batch_sha must be a lowercase sha256 hex digest")
        return value

    def to_workflow_request(self) -> JsonObject:
        """Render the POST /v1/workflows request body."""
        return {
            "workflow_type": "hook-event-capture",
            "payload": self.model_dump(mode="json"),
        }


class ModelDrainSkip(BaseModel):
    """One spool file that could not be framed — left in the spool, reported."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    reason: str


class ModelDrainBatchResult(BaseModel):
    """Outcome of submitting (and, unless dry-run, confirming) one batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_sha: str
    event_count: int = Field(ge=0)
    confirmed: bool
    status: str
    http_status: int | None = None
    workflow_id: str | None = None
    error: str | None = None
    files_moved: int = Field(ge=0, default=0)


class ModelDrainSummary(BaseModel):
    """Full result of one drain run — the shape returned to callers/tests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dry_run: bool
    files_present: int = Field(ge=0)
    files_considered: int = Field(ge=0)
    unique_events: int = Field(ge=0)
    duplicate_files_collapsed: int = Field(ge=0)
    skipped: list[ModelDrainSkip] = Field(default_factory=list)
    batches: list[ModelDrainBatchResult] = Field(default_factory=list)
    events_shipped: int = Field(ge=0, default=0)
    remaining_in_spool: int = Field(ge=0, default=0)

    @property
    def had_failures(self) -> bool:
        if self.dry_run:
            return False
        return any(not b.confirmed for b in self.batches)


def canonical_sha_input(event_type: str, payload: JsonObject, occurred_at: str) -> str:
    """Canonical JSON rendering hashed for ``event_sha`` (sorted keys, no
    insignificant whitespace, UTF-8) — reproducible across machines and
    Python versions, which the consumer's dedupe on ``(tenant, event_sha)``
    depends on.
    """
    blob = json.dumps(
        {"event_type": event_type, "payload": payload, "occurred_at": occurred_at},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return blob


__all__ = [
    "EVENT_TYPE_PATTERN",
    "MAX_EVENTS_PER_BATCH",
    "MAX_PAYLOAD_JSON_CHARS",
    "SHA256_HEX",
    "SOURCE_PATTERN",
    "JsonObject",
    "ModelCapturedHookEvent",
    "ModelDrainBatchResult",
    "ModelDrainSkip",
    "ModelDrainSummary",
    "ModelHookEventCaptureBatch",
    "ModelSpoolRecord",
    "canonical_sha_input",
]
