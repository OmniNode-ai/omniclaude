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

The publish transport never raises and uses only the standard library.
Contractor admission reads the existing lane and YAML declarations before
transport or capture writes. Models remain ``NamedTuple`` values so loading
this handler does not import the publisher stack.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple
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
    payload: dict[str, object]
    correlation_id: str | None
    journal_dir: Path


class ModelHookBusPublishResult(NamedTuple):
    outcome: EnumHookBusPublishOutcome
    event_id: str
    detail: str = ""


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: contract must be a JSON object")
    return loaded


def _text(contract: Mapping[str, object], key: str) -> str:
    """A string field of the contract; TypeError when it is not one."""
    value = contract[key]
    if not isinstance(value, str):
        raise TypeError(f"contract {key} must be a string, got {type(value).__name__}")
    return value


def _count(contract: Mapping[str, object], key: str) -> int:
    """An integer field of the contract; TypeError when it is not one."""
    value = contract[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"contract {key} must be an integer, got {type(value).__name__}"
        )
    return value


def build_body(
    request: ModelHookBusPublishRequest,
    contract: Mapping[str, object],
    *,
    event_id: str,
    fired_at: str,
) -> bytes:
    """The proxy request body: one record whose value is the runtime envelope."""
    payload = {**request.payload, _text(contract, "fire_time_key"): fired_at}
    correlation_id = request.correlation_id or event_id
    envelope = {
        "envelope_id": str(uuid.uuid4()),
        "envelope_timestamp": fired_at,
        "event_type": contract["command_topic"],
        "source_tool": contract["source_tool"],
        "payload": {
            "event_type": request.event_type,
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
    contract: Mapping[str, object],
    *,
    event_id: str,
    fired_at: str,
    size: int,
) -> str:
    held = request.journal_dir / _text(contract, "quarantine_dirname")
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


def _post(base: str, contract: Mapping[str, object], body: bytes) -> str | None:
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
        url.hostname, url.port, timeout=_count(contract, "timeout_ms") / 1000
    )
    try:
        connection.request(
            "POST",
            f"{url.path.rstrip('/')}/topics/{contract['command_topic']}",
            body=body,
            headers={"Content-Type": _text(contract, "content_type")},
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
    contract: Mapping[str, object] | None = None,
    event_id: str | None = None,
    fired_at: str | None = None,
) -> ModelHookBusPublishResult:
    """Publish one event. A replay passes the journal record's id and fire time."""
    event_id = event_id or str(uuid.uuid4())
    outcome = EnumHookBusPublishOutcome
    try:
        contract = load_contract() if contract is None else contract
        env = os.environ if environ is None else environ
        base = env.get(_text(contract, "url_env"), "").strip().rstrip("/")
        if not base:
            return ModelHookBusPublishResult(outcome.NO_LOCAL_BUS, event_id)
        fired_at = fired_at or datetime.now(UTC).isoformat()
        body = build_body(request, contract, event_id=event_id, fired_at=fired_at)
        if len(body) > _count(contract, "max_record_bytes"):
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


def replay_journal(
    journal_dir: Path,
    *,
    environ: Mapping[str, str] | None = None,
    contract: Mapping[str, object] | None = None,
    limit: int | None = None,
    pause_s: float = 0.0,
) -> dict[str, int]:
    """Publish a host's existing journal through the local bus, oldest first.

    The retirement step for the hook-emit drainer (OMN-19513). Each record keeps
    the instant its hook fired (its event id names its quarantine file only). A record leaves the journal
    only once it is on the bus or quarantined as too large; the first record the
    bus does not take stops the replay with that record and every one behind it
    still journalled, so a broker outage loses nothing and reorders nothing.
    ``pause_s`` paces the replay so it does not raise the host's load.
    """
    contract = load_contract() if contract is None else contract
    contract = {**contract, "timeout_ms": contract["replay_timeout_ms"]}
    counts = {"published": 0, "quarantined": 0, "unreadable": 0, "left": 0}
    pending = sorted(journal_dir.glob("[0-9]*.json"))
    for index, path in enumerate(pending):
        if limit is not None and index >= limit:
            counts["left"] += len(pending) - index
            break
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            request = ModelHookBusPublishRequest(
                event_type=record["event_type"],
                payload=dict(record["payload"]),
                correlation_id=record.get("correlation_id"),
                journal_dir=journal_dir,
            )
        except (OSError, ValueError, KeyError, TypeError):
            counts["unreadable"] += 1
            continue
        result = handle(
            request,
            environ=environ,
            contract=contract,
            event_id=record.get("event_id"),
            fired_at=record.get("queued_at"),
        )
        if result.outcome not in (
            EnumHookBusPublishOutcome.PUBLISHED,
            EnumHookBusPublishOutcome.QUARANTINED,
        ):
            counts["left"] += len(pending) - index
            break
        path.unlink(missing_ok=True)
        counts[str(result.outcome)] += 1
        if pause_s:
            time.sleep(pause_s)
    return counts


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=replay_journal.__doc__)
    parser.add_argument("--replay-journal", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pause-s", type=float, default=0.05)
    args = parser.parse_args()
    counts = replay_journal(args.replay_journal, limit=args.limit, pause_s=args.pause_s)
    sys.stdout.write(json.dumps(counts) + "\n")


def developer_event_suppressed(event_type: str) -> bool:
    """Apply the declared developer admission policy before capture or transport.

    Reads the facts (lanes, each lane's declared people, the developer's lane store) and hands
    them to omnimarket's ``node_developer_lane_admission_compute``. A refusal drops, never blocks.
    """
    import importlib

    import yaml

    # The edge lane module ships in the plugin tree, not in this package, so it
    # is resolved by name at call time.
    lane = importlib.import_module("hook_edge_lane")

    path = Path(str(lane.__file__)).parent.parent / "contracts/hook_edge_lane.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    policy = raw.get("developer_event_policy", {})
    if not isinstance(policy, dict):
        raise lane.HookEdgeLaneError("developer event policy must be a mapping")
    excluded = policy.get("excluded_event_classes", [])
    if not isinstance(excluded, list):
        raise lane.HookEdgeLaneError("developer excluded classes must be a list")
    if not set(excluded) <= set(raw["governed_event_classes"]):
        raise lane.HookEdgeLaneError("developer policy names ungoverned event classes")
    template = str(policy.get("bound_lane_principal_declaration"))
    paths = {
        name: policy.get("principal_declaration")
        if name == raw["lane"]
        else template.replace("{lane}", name)
        for name in raw["known_lanes"]
    }
    if not all(
        isinstance(rel, str)
        and rel.strip()
        and not Path(rel).is_absolute()
        and ".." not in Path(rel).parts
        for rel in paths.values()
    ):
        raise lane.HookEdgeLaneError("principal declarations must be relative paths")

    def _yaml(file: Path | None) -> object:
        try:  # Unreadable is malformed ({}), never absent and never a traceback.
            return file and yaml.safe_load(file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # A YAML exception can include a source excerpt containing a value.
            return {}

    env = lane.read_operator_env_file(lane.operator_env_file_path())
    lanes = {}
    for name, entry in raw["known_lanes"].items():
        found = _yaml(lane._onex_state().workspace_config_file(paths[name]))
        source = entry.get("sasl_credential_source")
        prefix = entry.get("sasl_env_prefix") or ""
        lanes[name] = {
            "credential_source": source,
            "env_principal": env.get(f"{prefix}{lane.ENV_SASL_USERNAME}")
            if source == lane.CREDENTIAL_SOURCE_OPERATOR_ENV_FILE
            else None,
            "declaration": found if isinstance(found, dict) or found is None else {},
        }
    store = _yaml(lane.onex_home_path() / lane.LANE_STORE_CONFIG_FILE)
    # The handler of omnimarket's admission node: stdlib-only, so loaded by file path.
    node_name = "node_developer_lane_admission_compute"
    node = importlib.import_module("hook_content_capture").load_node_handler(
        node_name, node_name, "handler_developer_lane_admission.py"
    )
    request = {
        "declared_lane": raw["lane"],
        "barred_lanes": policy.get("collaborator_barred_lanes", []),
        "lane_store": store if isinstance(store, dict) else None,
        "lanes": lanes,
    }
    missing = {"refusal": "admission-node-missing", "detail": f"no {node_name}"}
    decision = node.admit(request) if node else missing
    if decision["refusal"] is None:
        return event_type in excluded and bool(
            decision["verdict"] == getattr(node, "VERDICT_COLLABORATOR", None)
        )
    notice = policy.get("refusal_notice") or {}
    if event_type == notice.get("event_class"):
        fix = notice["remedies"].get(decision["refusal"], notice["default_remedy"])
        text = str(notice["message"]).format(fix=fix, **decision)
        out = os.environ.get("ONEX_HOOK_NOTICE_FILE") or "/dev/stdout"  # hook relays it
        with contextlib.suppress(OSError), open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"systemMessage": text}) + "\n")
    return True
