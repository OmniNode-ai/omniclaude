# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Land one hook event on the host's local bus (OMN-19513).

WHY THIS EXISTS. The hook-emit journal and its drainer exist only because the
old publish path imported the whole infra stack, about 31 s per event
(OMN-17224). The operator's 2026-08-29 relay ruling names the right path:
the hook publishes to the LOCAL bus, a runtime node does the enrichment and
fan-out, and ``node_bus_forwarder_effect`` relays onward. Every lab host
already runs that node: its runtime-effects container consumes
``onex.cmd.omnimarket.event-emit.v1`` with ``node_event_emit_effect``, the
handler the drainer called in-process. So the hook needs no new consumer, only
a way onto the bus that costs nothing to import.

HOW. One HTTP POST to the host's Redpanda HTTP proxy, with ``http.client``, a
short timeout, carrying the emit request inside the envelope the runtime's
auto-wiring materialises. Everything is read from
``src/omniclaude/contracts/hook_local_bus.json``.

Outcomes, and what the caller does with each:

* ``PUBLISHED``: the proxy acked the record. Nothing is journalled.
* ``NO_LOCAL_BUS``: the host declares no proxy. The caller journals.
* ``UNREACHABLE``: refused, timed out, or a record error. The caller journals.
* ``QUARANTINED``: the request is over the contract's byte limit. The proxy
  does not refuse such a record, it holds the request open, so retrying it
  can never succeed: it is moved to the journal's quarantine directory with
  its reason beside it and is never sent, never retried.

This handler never raises: capture must not fail or block the hook. Stdlib
only, like every module on the hook fast path; plain ``NamedTuple`` models
instead of Pydantic for the same reason (``test_handler_imports_nothing_heavy``).
"""

from __future__ import annotations

import http.client
import json
import os
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "hook_local_bus.json"
)


class EnumHookBusPublishOutcome(StrEnum):
    PUBLISHED = "published"
    NO_LOCAL_BUS = "no_local_bus"
    UNREACHABLE = "unreachable"
    QUARANTINED = "quarantined"


class ModelHookBusPublishRequest(NamedTuple):
    """One hook event, already stamped with lane, actor and turn."""

    event_type: str
    payload: dict[str, Any]
    correlation_id: str | None
    journal_dir: Path


class ModelHookBusPublishResult(NamedTuple):
    outcome: EnumHookBusPublishOutcome
    event_id: str
    detail: str = ""


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: contract must be a JSON object")
    return loaded


def build_body(
    request: ModelHookBusPublishRequest,
    contract: Mapping[str, Any],
    *,
    event_id: str,
    fired_at: str,
) -> bytes:
    """The proxy request body: one record whose value is the runtime envelope."""
    payload = {**request.payload, contract["fire_time_key"]: fired_at}
    correlation_id = request.correlation_id or event_id
    envelope = {
        "envelope_id": str(uuid.uuid4()),
        "envelope_timestamp": fired_at,
        "event_type": contract["command_topic"],
        "source_tool": contract["source_tool"],
        "payload": {
            "event_type": request.event_type,
            "event_id": event_id,
            "correlation_id": correlation_id,
            "payload": payload,
        },
    }
    session = request.payload.get("session_id")
    key = session if isinstance(session, str) and session else correlation_id
    records = {"records": [{"key": key, "value": envelope}]}
    return json.dumps(records, default=str, separators=(",", ":")).encode("utf-8")


def _quarantine(
    request: ModelHookBusPublishRequest,
    contract: Mapping[str, Any],
    *,
    event_id: str,
    fired_at: str,
    size: int,
) -> str:
    held = request.journal_dir / contract["quarantine_dirname"]
    held.mkdir(parents=True, exist_ok=True)
    target = held / f"{event_id}.json"
    tmp = held / f".{event_id}.json.tmp"
    stored = {
        "record": {
            "event_id": event_id,
            "event_type": request.event_type,
            "correlation_id": request.correlation_id,
            "queued_at": fired_at,
            "payload": request.payload,
        },
        "reason": {
            "reason_code": "payload_too_large",
            "request_bytes": size,
            "limit_bytes": contract["max_record_bytes"],
            "detail": contract["max_record_bytes_reason"],
            "quarantined_at": datetime.now(UTC).isoformat(),
        },
    }
    tmp.write_text(json.dumps(stored, default=str, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return str(target)


def _record_error(answer: bytes) -> str | None:
    """The proxy's per-record error, or None when the record was acked."""
    parsed = json.loads(answer)
    offsets = parsed.get("offsets") if isinstance(parsed, dict) else None
    if not isinstance(offsets, list) or len(offsets) != 1:
        return f"unexpected proxy answer: {answer[:200]!r}"
    code = offsets[0].get("error_code") if isinstance(offsets[0], dict) else None
    return None if code in (None, 0) else f"proxy record error_code={code}"


def _post(base: str, contract: Mapping[str, Any], body: bytes) -> str | None:
    """POST one record to the proxy; the record error, or None when acked."""
    url = urlsplit(base)
    if url.scheme not in ("http", "https") or not url.hostname:
        raise ValueError(f"local bus URL must be http(s)://host:port, got {base!r}")
    connection_cls = (
        http.client.HTTPSConnection
        if url.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_cls(
        url.hostname, url.port, timeout=contract["timeout_ms"] / 1000
    )
    try:
        connection.request(
            "POST",
            f"{url.path.rstrip('/')}/topics/{contract['command_topic']}",
            body=body,
            headers={"Content-Type": contract["content_type"]},
        )
        answer = connection.getresponse()
        data = answer.read()
    finally:
        connection.close()
    if answer.status != 200:
        return f"proxy HTTP {answer.status}: {data[:200]!r}"
    return _record_error(data)


def handle(
    request: ModelHookBusPublishRequest,
    *,
    environ: Mapping[str, str] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> ModelHookBusPublishResult:
    event_id = str(uuid.uuid4())
    outcome = EnumHookBusPublishOutcome
    try:
        contract = load_contract() if contract is None else contract
        env = os.environ if environ is None else environ
        base = env.get(contract["url_env"], "").strip().rstrip("/")
        if not base:
            return ModelHookBusPublishResult(outcome.NO_LOCAL_BUS, event_id)
        fired_at = datetime.now(UTC).isoformat()
        body = build_body(request, contract, event_id=event_id, fired_at=fired_at)
        if len(body) > contract["max_record_bytes"]:
            where = _quarantine(
                request, contract, event_id=event_id, fired_at=fired_at, size=len(body)
            )
            return ModelHookBusPublishResult(outcome.QUARANTINED, event_id, where)
        started = time.monotonic()
        error = _post(base, contract, body)
        if error is not None:
            return ModelHookBusPublishResult(outcome.UNREACHABLE, event_id, error)
        took = f"{(time.monotonic() - started) * 1000:.0f}ms"
        return ModelHookBusPublishResult(outcome.PUBLISHED, event_id, took)
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as exc:
        # Capture never fails the hook: every way the contract read, the
        # quarantine write or the request can fail reports UNREACHABLE.
        detail = f"{type(exc).__name__}: {exc}"
        return ModelHookBusPublishResult(outcome.UNREACHABLE, event_id, detail)


def landed(request: ModelHookBusPublishRequest) -> bool:
    """True when the caller must NOT journal: published, or quarantined as too large."""
    return handle(request).outcome in (
        EnumHookBusPublishOutcome.PUBLISHED,
        EnumHookBusPublishOutcome.QUARANTINED,
    )
