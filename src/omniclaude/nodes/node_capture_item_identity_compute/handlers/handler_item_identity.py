# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared item identity, producer sequence and barrier records (OMN-18531, TA.21).

The producer half of TA.21, in omniclaude. Two hooks capture one hook call:
``hook_claude_capture`` journals the lineage event, which names each full
content field only by a reference (``content_record_id``, a uuid5 over the
event id and the field name), and ``hook_content_capture`` journals the content
itself. Until this module the two shared no identity: the content record never
carried the reference's id, and nothing proved a session's earlier records had
reached the projection. This module is what both hooks call so that they do.

Shared item identity
--------------------
``content_record_id(event_id, field)`` is the one function that computes the id.
The lineage mapper calls it for each reference; the content hook calls it for
each record it fulfils. The event id cannot be recomputed by the second hook
(it is a uuid5 over a wall-clock ``emitted_at``), so it is *handed over*:
whichever hook of a pair runs first records the event id it minted under an
item key in the session's item state, and the other adopts it. The key is
``(agent_id, hook_event_name, discriminator)`` where the discriminator is a
value both hooks read from the same stdin (the ``tool_use_id`` of a tool call,
the sha256 of a prompt's text, the sha256 of a reply). Each entry is claimed
once per stream, so two identical prompts have two entries and so two ids.
An entry older than ``ENTRY_TTL_SECONDS`` is never matched: a hook of a pair
that was dropped must not hand its event id to a later, unrelated call.

Producer sequence
-----------------
``next_producer_seq`` issues 1, 2, 3 ... per session and per stream from a
counter file under an exclusive ``fcntl.flock`` (the lock ``hook_turn_id``
already uses and macOS supports). A producer stamps each record it journals
with the number it was issued.

Barrier
-------
``build_barrier_payload`` states, for one stream of one session, the highest
sequence number the producer has issued. The consumer holds the barrier met
when its projection has applied every number from 1 to that high-water.
The lineage stream's barrier also says whether content capture is enabled; when
the operator turned it off, the content stream journals nothing at all.

Where it is loaded from
-----------------------
The hooks load this file BY PATH (``hook_content_capture.load_item_identity``),
not through ``omniclaude.nodes``: importing a package module runs the omniclaude
package ``__init__`` (22 s cold, OMN-17224), a cost no per-tool-call hook can
pay. So the module level here imports the standard library only; the node's
pydantic models are imported inside :meth:`HandlerCaptureItemIdentity.handle`,
which only the runtime calls.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omniclaude.nodes.node_capture_item_identity_compute.models import (
        ModelCaptureItemIdentityRequest,
        ModelCaptureItemIdentityResult,
    )

#: Must equal ``omniclaude.hooks.model_claude_hook_event.HOOK_CAPTURE_NAMESPACE``;
#: re-declared because the package import is the OMN-17224 cost. A test pins it.
HOOK_CAPTURE_NAMESPACE = uuid.UUID("9449178f-fb63-5b0d-b17d-379aafbcfe67")

STREAM_LINEAGE = "lineage"
STREAM_CONTENT = "content"
STREAMS = (STREAM_LINEAGE, STREAM_CONTENT)

#: A barrier record rides the already-registered, already-granted content
#: event type, told apart by ``content_kind``. A new event type would have to be
#: declared in omnimarket's emit registry first (the ``event_registry_drift``
#: gate refuses an omniclaude type the daemon registry does not project), which
#: would make this producer wait on a second repository for no gain: a barrier
#: carries ids, a count and a flag, the same class of data as a chunk's header.
BARRIER_EVENT_TYPE = "content.captured"
BARRIER_CONTENT_KIND = "barrier"
BARRIER_RECORD_TYPE = "barrier"

CONTENT_CAPTURE_ENABLED = "enabled"
CONTENT_CAPTURE_DISABLED = "disabled"

#: The directory, beside the journal, that holds a session's item state.
ITEM_DIRNAME = "hook_items"

#: A hook of a pair waits this long for its partner before its entry is stale
#: (a PreToolUse waits for its call to finish).
ENTRY_TTL_SECONDS = 3600

#: Open entries kept per session; the oldest are dropped past this.
MAX_ENTRIES = 256

#: Content kind (``hook_content_capture``) -> (lineage hook_event_name, lineage
#: field) whose reference the content record fulfils. Only these pairs are
#: full-capture: every other referenced field is metadata-only and outside the
#: completeness check (TA.21). A tool's input is referenced by the PreToolUse
#: event (the PostToolUse and PostToolUseFailure events reference only the
#: result), yet it is the post-call hook that records it, so the content hook
#: adopts the id of the call's PreToolUse event for it.
FULL_CAPTURE_BY_KIND: dict[str, tuple[str, str]] = {
    "prompt": ("UserPromptSubmit", "prompt"),
    "tool_input": ("PreToolUse", "tool_input"),
    "tool_response": ("PostToolUse", "tool_response"),
    "tool_error": ("PostToolUseFailure", "error"),
    "assistant_reply": ("Stop", "last_assistant_message"),
}

#: Lineage hooks whose full-capture references a content record fulfils.
LINEAGE_FULL_CAPTURE_HOOKS = frozenset(h for h, _ in FULL_CAPTURE_BY_KIND.values())

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def content_record_id(event_id: uuid.UUID | str, field: str) -> uuid.UUID:
    """The id of the content record that fulfils ``field`` of event ``event_id``."""
    return uuid.uuid5(HOOK_CAPTURE_NAMESPACE, f"{event_id}|{field}")


def is_full_capture(hook_event_name: str, field: str) -> bool:
    """True when ``field`` of ``hook_event_name`` must resolve to a content record."""
    return (hook_event_name, field) in set(FULL_CAPTURE_BY_KIND.values())


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def item_discriminator(hook_event_name: str, hook_input: Mapping[str, Any]) -> str:
    """The value both hooks of a pair read from the same stdin.

    A tool call is told apart by its ``tool_use_id``; a prompt and a reply have
    no id on stdin, so they are told apart by the sha256 of their text. An input
    that carries neither yields the empty string, and the entry's TTL and its
    once-per-stream claim bound the cost of the weaker key.
    """
    if hook_event_name in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        value = hook_input.get("tool_use_id")
        return value if isinstance(value, str) else ""
    if hook_event_name == "UserPromptSubmit":
        value = hook_input.get("prompt")
        return sha256_text(value) if isinstance(value, str) else ""
    if hook_event_name == "Stop":
        value = hook_input.get("last_assistant_message")
        return sha256_text(value) if isinstance(value, str) else ""
    return ""


def item_dir_for(journal_dir: Path) -> Path:
    """The item-state directory for a journal: a sibling, like the turn counters."""
    return journal_dir.parent / ITEM_DIRNAME


def _state_path(item_dir: Path, session_id: str, suffix: str) -> Path:
    name = session_id if _SAFE_NAME.match(session_id) else ""
    if not name or name in {".", ".."}:
        name = sha256_text(session_id)
    return item_dir / f"{name}.{suffix}"


def _lock_wait_s() -> float:
    try:
        return float(os.environ.get("ONEX_HOOK_LOCK_WAIT_S", "2"))
    except ValueError:
        return 2.0


def _flock_bounded(fd: int, path: Path) -> None:
    """Take an exclusive lock within the lock-wait budget, or raise TimeoutError."""
    wait_s = _lock_wait_s()
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError(f"item state lock {path} busy for {wait_s:g}s")
        time.sleep(0.01)


def _locked_json(path: Path, update: Any) -> Any:
    """Read ``path`` as a JSON object under an exclusive lock, apply ``update``.

    ``update(state)`` mutates the dict in place and returns the call's result;
    the file is rewritten and flushed before the lock is released.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        _flock_bounded(handle.fileno(), path)
        try:
            handle.seek(0)
            raw = handle.read().strip()
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            state: dict[str, Any] = parsed if isinstance(parsed, dict) else {}
            result = update(state)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(state, sort_keys=True))
            # Flushed, not fsynced: the state survives a process death, and an OS
            # crash costs only counters the journal itself would not outlive.
            # An fsync under the lock is the cost that starved eight writers.
            handle.flush()
            return result
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def claim_event_id(
    item_dir: Path,
    *,
    session_id: str,
    agent_id: str | None,
    hook_event_name: str,
    discriminator: str,
    stream: str,
    minted: uuid.UUID,
    now: float | None = None,
) -> uuid.UUID:
    """Return the event id ``stream`` uses for this call, shared with its partner.

    The first hook of the pair to reach here stores ``minted`` and keeps it; the
    other stream adopts the stored id. A stream claims an entry once, so the
    same stream arriving again for the same key opens a new entry.
    """
    if stream not in STREAMS:
        raise ValueError(f"unknown stream {stream!r}")
    other = STREAM_CONTENT if stream == STREAM_LINEAGE else STREAM_LINEAGE
    key = json.dumps([agent_id or "", hook_event_name, discriminator])
    stamp = time.time() if now is None else now

    def update(state: dict[str, Any]) -> uuid.UUID:
        entries: list[dict[str, Any]] = [
            e
            for e in state.get("entries", [])
            if isinstance(e, dict)
            and stamp - float(e.get("at", 0)) <= ENTRY_TTL_SECONDS
        ]
        for entry in entries:
            if entry.get("key") == key and not entry.get(stream):
                entry[stream] = True
                chosen = uuid.UUID(str(entry["event_id"]))
                # Both streams have used it: the entry has done its job.
                if entry.get(other):
                    entries.remove(entry)
                state["entries"] = entries
                return chosen
        entries.append({"key": key, "event_id": str(minted), stream: True, "at": stamp})
        state["entries"] = entries[-MAX_ENTRIES:]
        return minted

    return uuid.UUID(
        str(_locked_json(_state_path(item_dir, session_id, "items"), update))
    )


def next_producer_seq(item_dir: Path, session_id: str, stream: str) -> int:
    """Issue the next sequence number of ``stream`` for the session (1, 2, 3 ...)."""
    if stream not in STREAMS:
        raise ValueError(f"unknown stream {stream!r}")

    def update(state: dict[str, Any]) -> int:
        issued = int(state.get(stream, 0)) + 1
        state[stream] = issued
        return issued

    return int(_locked_json(_state_path(item_dir, session_id, "seq"), update))


def high_water(item_dir: Path, session_id: str, stream: str) -> int:
    """The highest sequence number issued on ``stream`` for the session so far."""
    if stream not in STREAMS:
        raise ValueError(f"unknown stream {stream!r}")

    def update(state: dict[str, Any]) -> int:
        return int(state.get(stream, 0))

    return int(_locked_json(_state_path(item_dir, session_id, "seq"), update))


def build_barrier_payload(
    *,
    session_id: str,
    barrier_id: str,
    stream: str,
    high_water_value: int,
    content_capture_enabled: bool,
    emitted_at: str,
) -> dict[str, Any]:
    """One barrier record: ids, a count and a flag, never content."""
    if stream not in STREAMS:
        raise ValueError(f"unknown stream {stream!r}")
    payload: dict[str, Any] = {
        "content_kind": BARRIER_CONTENT_KIND,
        "record_type": BARRIER_RECORD_TYPE,
        "session_id": session_id,
        "barrier_id": barrier_id,
        "stream": stream,
        "high_water": high_water_value,
        "emitted_at": emitted_at,
    }
    if stream == STREAM_LINEAGE:
        payload["content_capture"] = (
            CONTENT_CAPTURE_ENABLED
            if content_capture_enabled
            else CONTENT_CAPTURE_DISABLED
        )
    return payload


class HandlerCaptureItemIdentity:
    """The node's handler: one request in, one id or number out."""

    def handle(
        self, request: ModelCaptureItemIdentityRequest
    ) -> ModelCaptureItemIdentityResult:
        from omniclaude.nodes.node_capture_item_identity_compute.models import (
            EnumCaptureItemOperation,
            ModelCaptureItemIdentityResult,
        )

        operation = request.operation
        if operation is EnumCaptureItemOperation.CONTENT_RECORD_ID:
            if request.event_id is None or request.field is None:
                raise ValueError("content_record_id needs event_id and field")
            return ModelCaptureItemIdentityResult(
                content_record_id=content_record_id(request.event_id, request.field)
            )
        if request.session_id is None or request.item_dir is None:
            raise ValueError(f"{operation.value} needs session_id and item_dir")
        item_dir = Path(request.item_dir)
        stream = request.stream or ""
        if operation is EnumCaptureItemOperation.CLAIM_EVENT_ID:
            if request.minted_event_id is None or request.hook_event_name is None:
                raise ValueError(
                    "claim_event_id needs minted_event_id and hook_event_name"
                )
            return ModelCaptureItemIdentityResult(
                event_id=claim_event_id(
                    item_dir,
                    session_id=request.session_id,
                    agent_id=request.agent_id,
                    hook_event_name=request.hook_event_name,
                    discriminator=request.discriminator or "",
                    stream=stream,
                    minted=request.minted_event_id,
                )
            )
        if operation is EnumCaptureItemOperation.NEXT_PRODUCER_SEQ:
            return ModelCaptureItemIdentityResult(
                sequence=next_producer_seq(item_dir, request.session_id, stream)
            )
        return ModelCaptureItemIdentityResult(
            sequence=high_water(item_dir, request.session_id, stream)
        )
