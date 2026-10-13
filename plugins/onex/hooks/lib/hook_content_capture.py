#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Full-content hook capture: journal the complete prompt, tool call and reply.

OMN-19551, the hook half of OMN-19550. Operator ruling 2026-09-25 (ledger
RULING row 2026-09-25T11:23:30Z): full content is captured through hooks, not
an API proxy, under the redaction contract, local-first.

What this does, per hook call
-----------------------------
* ``--kind prompt`` (UserPromptSubmit): the prompt text.
* ``--kind tool`` (PostToolUse): two items, the tool input and the tool
  result, each keyed by ``tool_use_id``.
* ``--kind stop`` (Stop): the assistant reply of the turn that just ended,
  read from the harness's own ``last_assistant_message`` when it sends one,
  else from ``transcript_path``. Also, from the same transcript, every prompt
  the OPERATOR typed that this session has not yet recorded, one
  ``operator_prompt`` item each (OMN-20905, below).

Operator prompts (OMN-20905)
----------------------------
Operator ruling, RULING row 2026-10-10T22:40:43Z: the operator's decisions and
asks are extracted asynchronously from the bus, not by a capture hook. The bus
must therefore say which prompts the operator typed. The UserPromptSubmit
payload cannot: it carries the same fields for an operator's prompt, a lane
brief given to ``claude -p``, a scheduled prompt and a task notification, and
the prompt's transcript entry, which does say, is written only after the hook
returns (measured 2026-10-10 on Claude Code 2.1.295). At Stop the entries
exist. A user entry is the operator's when its ``origin.kind`` is ``human``
and it is neither meta nor a sidechain; a lane brief (``origin`` absent,
``turnOrigin`` ``sdk``), a scheduled prompt, a task notification and a
compaction summary never are. Each is journalled once per session (a marker
of transcript entry ids beside the turn state), and the first Stop of a
session looks back at most ``OPERATOR_LOOKBACK_SECONDS``, so installing this
never replays a long session's history. A message the operator typed while a
turn was running never fires UserPromptSubmit; it is recorded here too.

Each item is redacted WHOLE by the capture-redaction contract, then split per
the contract's size policy, and every chunk is journalled as one
``content.captured`` record. The drainer publishes the records and the
emit effect's fan-out applies the same contract again to each chunk.

It runs AFTER the bus mirror's own metadata append, in the same backgrounded
subshell, so a content record reads the turn that append just stamped: the
same turn the metadata record carries.

The three refusals, each fail-closed
------------------------------------
Capture journals nothing, and says so in the hook log, when:

1. The operator opted out: ``OMNICLAUDE_CONTENT_CAPTURE`` is ``0``, ``off``,
   ``false`` or ``no``.
2. The local drainer cannot publish the event type. Its status file lists the
   event types its loaded registry declares. A record the drainer cannot
   resolve fails at the journal head every cycle and holds every record behind
   it until it is dead-lettered (the OMN-19074 outage shape), so an absent
   list, or a list without this event type, means NOT capturing.
3. The redaction resolver cannot be loaded. Content never crosses unredacted.

Why the resolver is loaded by file path
---------------------------------------
``import omniclaude.hooks.capture_redaction`` runs the package ``__init__``,
which imports ``omnibase_infra``, ``pydantic`` and ``aiokafka``: 22 s cold,
measured 2026-09-25, on every tool call. That is the OMN-17224 cost. The
resolver itself needs only the standard library and PyYAML, so it is loaded
straight from its file.

Fail-open like every hook on this path: always exits 0, never writes stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_emit_append as appender  # noqa: E402
import hook_emit_health as health  # noqa: E402
import hook_emit_journal as journal  # noqa: E402

#: The semantic event type journalled for one content item or chunk. The
#: emit registry routes it; the topic is read from the contract, never here.
CONTENT_EVENT_TYPE = "content.captured"

#: Opt-out switch. Unset means capture (the ruling); these values turn it off.
OPT_OUT_ENV = "OMNICLAUDE_CONTENT_CAPTURE"
_OFF_VALUES = frozenset({"0", "off", "false", "no"})

#: Tail window read from a transcript to find the last turn. A turn's reply
#: sits at the end of the file; reading a multi-hundred-megabyte transcript
#: whole on every Stop would be the cost this hook must never add.
TRANSCRIPT_TAIL_BYTES = 8 * 1024 * 1024

#: The Stop hook can fire before the harness has flushed the reply to the
#: transcript. Poll briefly; this process is already backgrounded.
TRANSCRIPT_POLL_ATTEMPTS = 6
TRANSCRIPT_POLL_SECONDS = 0.5

#: The content kind of a prompt the operator typed, resolved at Stop.
OPERATOR_PROMPT_KIND = "operator_prompt"

#: The first Stop of a session records operator prompts this recent only.
OPERATOR_LOOKBACK_SECONDS = 3600

#: Transcript entry ids kept in a session's operator marker.
OPERATOR_MARKER_KEEP = 512

_RESOLVER_MODULE_NAME = "omniclaude_capture_redaction_by_path"

#: OMN-20926: the record field carrying the producer's store-then-reference
#: outcome, ``{stored, fallback, reason}``. Declared on the content topic.
STORE_OUTCOME_FIELD = "stored_refs"

#: OMN-20926: omnimarket's captured secret store effect, imported only when a
#: capture actually finds a secret, so a clean capture pays nothing for it.
_STORE_HANDLER_MODULE = (
    "omnimarket.nodes.node_captured_secret_store_effect.handlers."
    "handler_captured_secret_store"
)
_STORE_REQUEST_MODULE = (
    "omnimarket.nodes.node_captured_secret_store_effect.models."
    "model_captured_secret_store_request"
)
#: The effect is not installed in this interpreter yet (an older omnimarket).
WRITER_UNAVAILABLE = "writer_unavailable"
#: Reasons that mean this machine does not take part, so nothing is alarmed.
QUIET_STORE_REFUSALS = frozenset({"not_configured", WRITER_UNAVAILABLE})
_REPLY_MARKER_SUFFIX = ".reply"
_OPERATOR_MARKER_SUFFIX = ".operator"


def _log(message: str) -> None:
    print(f"hook_content_capture: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def capture_enabled_by_operator() -> bool:
    return os.environ.get(OPT_OUT_ENV, "").strip().lower() not in _OFF_VALUES


def drainer_can_publish(status_path: Path) -> bool:
    """True only when the drainer's status names this event type as publishable."""
    status = health.read_status(status_path)
    if status is None or status.publishable_event_types is None:
        return False
    return CONTENT_EVENT_TYPE in status.publishable_event_types


def status_path_for(journal_dir: Path) -> Path:
    """The drainer status beside a journal, resolved the way the drainer does."""
    if journal_dir == health.default_journal_dir():
        return health.default_status_path()
    return journal_dir.parent / health.STATUS_FILENAME


def _resolver_candidates() -> list[Path]:
    candidates = [
        Path(__file__).resolve().parents[4]
        / "src"
        / "omniclaude"
        / "hooks"
        / "capture_redaction.py"
    ]
    # find_spec on a TOP-LEVEL name locates the package without executing it.
    spec = importlib.util.find_spec("omniclaude")
    if spec is not None and spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            candidates.append(Path(location) / "hooks" / "capture_redaction.py")
    return candidates


def load_resolver() -> ModuleType | None:
    """Load the capture-redaction resolver by file path, or return ``None``."""
    loaded = sys.modules.get(_RESOLVER_MODULE_NAME)
    if loaded is not None:
        return loaded
    for candidate in _resolver_candidates():
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location(_RESOLVER_MODULE_NAME, candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        # Registered before exec: dataclasses resolve their module by name.
        sys.modules[_RESOLVER_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 -- try the next candidate
            sys.modules.pop(_RESOLVER_MODULE_NAME, None)
            _log(f"resolver at {candidate.name} did not load: {exc}")
            continue
        return module
    return None


def content_topic(resolver: ModuleType) -> str:
    """The one governed topic that declares a content size policy."""
    contract = resolver.load_contract()
    topics = [t for t, p in contract.topics.items() if p.content_policy is not None]
    if len(topics) != 1:
        raise ValueError(
            f"expected exactly one content topic in the redaction contract, got {topics}"
        )
    return str(topics[0])


# ---------------------------------------------------------------------------
# turning hook input into content items
# ---------------------------------------------------------------------------


def _as_text(value: Any) -> str:
    """Full content as text: a string as itself, anything else as JSON."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _matcher_key(tool_name: str, tool_input: Any) -> Any:
    """What the contract's output classes match on for this tool.

    The command for Bash; the path for a file-reading tool. The output classes
    decide whether the RESULT is hashed from this, so it travels on both the
    input record and the result record.
    """
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Bash":
        return tool_input.get("command")
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def items_for_prompt(hook_input: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = hook_input.get("prompt")
    if not isinstance(prompt, str):
        return []
    return [{"content_kind": "prompt", "content": prompt}]


def items_for_tool(hook_input: dict[str, Any]) -> list[dict[str, Any]]:
    tool_name = hook_input.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return []
    tool_use_id = hook_input.get("tool_use_id")
    tool_input = hook_input.get("tool_input")
    base: dict[str, Any] = {"tool_name": tool_name}
    if isinstance(tool_use_id, str) and tool_use_id:
        base["tool_use_id"] = tool_use_id
    key = _matcher_key(tool_name, tool_input)
    if key is not None:
        base["command"] = key
    items = [{**base, "content_kind": "tool_input", "content": _as_text(tool_input)}]
    if "tool_response" in hook_input:
        items.append(
            {
                **base,
                "content_kind": "tool_response",
                "content": _as_text(hook_input.get("tool_response")),
            }
        )
    return items


def _is_prompt_entry(entry: dict[str, Any]) -> bool:
    """A user entry that is a real prompt, not a tool result or a meta line."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def _assistant_text(entry: dict[str, Any]) -> list[str]:
    if entry.get("type") != "assistant" or entry.get("isSidechain"):
        return []
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [content] if content.strip() else []
    if not isinstance(content, list):
        return []
    return [
        str(block.get("text"))
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
        and block.get("text", "").strip()
    ]


def _tail_lines(transcript: Path, tail_bytes: int) -> list[str]:
    """The transcript's last ``tail_bytes`` as lines; ``[]`` when unreadable."""
    try:
        size = transcript.stat().st_size
        with transcript.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
                handle.readline()  # drop the partial first line
            return handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def last_turn_reply(
    transcript: Path, *, tail_bytes: int = TRANSCRIPT_TAIL_BYTES
) -> str:
    """The assistant text written after the last real prompt, oldest first.

    Reads only the tail of the file. Returns ``""`` when the last turn has no
    reply yet, including when the transcript is absent or unreadable.
    """
    lines = _tail_lines(transcript, tail_bytes)
    collected: list[str] = []
    for raw in reversed(lines):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if _is_prompt_entry(entry):
            break
        collected[:0] = _assistant_text(entry)
    return "\n\n".join(collected)


def items_for_stop(
    hook_input: dict[str, Any],
    *,
    attempts: int = TRANSCRIPT_POLL_ATTEMPTS,
    pause: float = TRANSCRIPT_POLL_SECONDS,
) -> list[dict[str, Any]]:
    direct = hook_input.get("last_assistant_message")
    if isinstance(direct, str) and direct.strip():
        return [{"content_kind": "assistant_reply", "content": direct}]
    raw_path = hook_input.get("transcript_path") or hook_input.get("transcriptPath")
    if not isinstance(raw_path, str) or not raw_path:
        return []
    transcript = Path(raw_path)
    for attempt in range(max(1, attempts)):
        reply = last_turn_reply(transcript)
        if reply:
            return [{"content_kind": "assistant_reply", "content": reply}]
        if attempt + 1 < attempts:
            time.sleep(pause)
    return []


def _reply_already_captured(turn_dir: Path, session_id: str, digest: str) -> bool:
    """Stop can fire more than once for one reply; record each reply once."""
    safe = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    marker = turn_dir / f"{safe}{_REPLY_MARKER_SUFFIX}"
    try:
        if marker.read_text(encoding="utf-8").strip() == digest:
            return True
    except OSError:
        pass
    try:
        turn_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(digest, encoding="utf-8")
    except OSError:
        pass
    return False


def _prompt_text(entry: dict[str, Any]) -> str:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text"))
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


def is_operator_prompt_entry(entry: dict[str, Any]) -> bool:
    """A real prompt whose transcript origin is a human: the operator typed it."""
    if not _is_prompt_entry(entry):
        return False
    origin = entry.get("origin")
    return isinstance(origin, dict) and origin.get("kind") == "human"


def _said_at(entry: dict[str, Any]) -> datetime | None:
    stamp = entry.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else None


def _operator_marker(turn_dir: Path, session_id: str) -> Path:
    safe = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return turn_dir / f"{safe}{_OPERATOR_MARKER_SUFFIX}"


def _read_marker(marker: Path) -> list[str] | None:
    """Entry ids already recorded; ``None`` when this session has no marker yet."""
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return None
    return [line.strip() for line in text.splitlines() if line.strip()]


def operator_prompt_items(
    transcript: Path,
    *,
    turn_dir: Path,
    session_id: str,
    now: datetime,
    tail_bytes: int = TRANSCRIPT_TAIL_BYTES,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Operator prompts not yet recorded for this session, and their entry ids.

    The ids are written to the marker by :func:`record_operator_marker` only
    after the items are journalled, so a failed append records them again on
    the next Stop rather than losing them.
    """
    seen = _read_marker(_operator_marker(turn_dir, session_id))
    floor = now - timedelta(seconds=OPERATOR_LOOKBACK_SECONDS) if seen is None else None
    known = set(seen or ())
    items: list[dict[str, Any]] = []
    ids: list[str] = []
    for raw in _tail_lines(transcript, tail_bytes):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or not is_operator_prompt_entry(entry):
            continue
        entry_id = entry.get("uuid")
        if not isinstance(entry_id, str) or not entry_id or entry_id in known:
            continue
        said_at = _said_at(entry)
        if floor is not None and (said_at is None or said_at < floor):
            continue
        text = _prompt_text(entry)
        if not text.strip():
            continue
        item: dict[str, Any] = {"content_kind": OPERATOR_PROMPT_KIND, "content": text}
        prompt_id = entry.get("promptId")
        if isinstance(prompt_id, str) and prompt_id:
            item["prompt_id"] = prompt_id
        if said_at is not None:
            item["said_at"] = said_at.astimezone(UTC).isoformat()
        items.append(item)
        ids.append(entry_id)
        known.add(entry_id)
    return items, ids


def record_operator_marker(turn_dir: Path, session_id: str, ids: list[str]) -> None:
    """Remember recorded entry ids (the newest ``OPERATOR_MARKER_KEEP``)."""
    marker = _operator_marker(turn_dir, session_id)
    kept = [*(_read_marker(marker) or []), *ids][-OPERATOR_MARKER_KEEP:]
    try:
        turn_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError as exc:
        _log(f"operator marker not written ({exc}); the prompts may be recorded again")


# ---------------------------------------------------------------------------
# the secret store (OMN-20926)
# ---------------------------------------------------------------------------


def onex_home() -> Path:
    """This machine's ``~/.onex``: its private overlay and credential file."""
    return Path("~/.onex").expanduser()


def build_store_handler(home: Path) -> tuple[Any, Any]:
    """omnimarket's captured secret store effect, and its request model.

    Raises ``ImportError`` when this interpreter's omnimarket predates the
    effect; :class:`StoreSink` turns that into ``writer_unavailable``.
    """
    handler_module = importlib.import_module(_STORE_HANDLER_MODULE)
    request_module = importlib.import_module(_STORE_REQUEST_MODULE)
    return (
        handler_module.HandlerCapturedSecretStore(onex_home=home),
        request_module.ModelCapturedSecretStoreRequest,
    )


class StoreSink:
    """The resolver's ``SecretSink``, over the captured secret store effect.

    Called with each secret the scrub finds; returns the reference the effect
    minted, or ``None`` so the span crosses as the marker. ``refusal`` is the
    effect's outcome code for the first failure, which also stops every later
    call in this capture.
    """

    def __init__(self, *, session_id: str) -> None:
        self.session_id = session_id
        self.refusal: str | None = None
        self.detail: str | None = None
        self._handler: Any = None
        self._request: Any = None

    def __call__(self, value: str) -> str | None:
        if self.refusal is not None:
            return None
        if self._handler is None:
            try:
                self._handler, self._request = build_store_handler(onex_home())
            except ImportError as exc:
                self.refusal = WRITER_UNAVAILABLE
                self.detail = type(exc).__name__
                return None
        result = self._handler.handle(
            self._request(
                value=value, session_id=self.session_id, captured_at=datetime.now(UTC)
            )
        )
        if result.reference is None:
            self.refusal = str(result.outcome.value)
            self.detail = result.detail
            return None
        return str(result.reference)


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

_ITEMS = {"prompt": items_for_prompt, "tool": items_for_tool, "stop": items_for_stop}
_HOOK_SOURCE = {
    "prompt": "user_prompt_submit",
    "tool": "post_tool_use",
    "stop": "stop",
}


def capture(
    hook_input: dict[str, Any],
    *,
    kind: str,
    journal_dir: Path,
    correlation_id: str | None = None,
    cwd: str | None = None,
    actor: str | None = None,
    host_turn_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    transcript_path: str | None = None,
    now: datetime | None = None,
) -> int:
    """Journal every content record for one hook call. Returns how many.

    ``now`` anchors the first Stop's operator-prompt lookback; ``main`` passes
    the wall clock.
    """
    if not capture_enabled_by_operator():
        return 0
    if not drainer_can_publish(status_path_for(journal_dir)):
        _log(
            f"skipped: the local drainer does not list {CONTENT_EVENT_TYPE} as "
            "publishable (update its omnimarket and restart it)"
        )
        return 0
    resolver = load_resolver()
    if resolver is None:
        _log("skipped: the capture-redaction resolver could not be loaded")
        return 0
    topic = content_topic(resolver)

    session = session_id or hook_input.get("session_id") or hook_input.get("sessionId")
    if not isinstance(session, str) or not session:
        return 0
    items = _ITEMS[kind](hook_input)
    operator_ids: list[str] = []
    turn_dir = appender.hook_turn_id.turn_dir_for(journal_dir)
    if kind == "stop":
        if items:
            digest = hashlib.sha256(items[0]["content"].encode("utf-8")).hexdigest()
            if _reply_already_captured(turn_dir, session, digest):
                items = []
        raw_transcript = (
            transcript_path
            or hook_input.get("transcript_path")
            or hook_input.get("transcriptPath")
        )
        if not agent_id and isinstance(raw_transcript, str) and raw_transcript:
            operator_items, operator_ids = operator_prompt_items(
                Path(raw_transcript),
                turn_dir=turn_dir,
                session_id=session,
                now=now or datetime.now(UTC),
            )
            items = [*items, *operator_items]

    # OMN-20926: a detected secret is stored in the secret store and a
    # reference replaces it. The writer loads only when a secret is found; a
    # span the store did not take crosses as the marker.
    sink = (
        None
        if resolver.load_contract().reference is None
        else StoreSink(session_id=session)
    )

    written = 0
    fallback = 0
    for item in items:
        record = {"session_id": session, "hook_source": _HOOK_SOURCE[kind], **item}
        chunks = resolver.prepare_content_records(
            record,
            topic=topic,
            content_field="content",
            redaction_field="producer_redaction",
            chunk_index_field="chunk_index",
            chunk_count_field="chunk_count",
            digest_field="content_sha256",
            secret_sink=sink,
            stored_refs_field=STORE_OUTCOME_FIELD,
        )
        outcome = chunks[0].get(STORE_OUTCOME_FIELD) if chunks else None
        if isinstance(outcome, dict):
            fallback += int(outcome.get("fallback") or 0)
        for chunk in chunks:
            appender.append_event(
                # A literal, not CONTENT_EVENT_TYPE, on purpose (OMN-19913):
                # validate_hook_edge_lane.py resolves only literal classes at
                # an emit call, so the constant hid this class from the lane
                # contract and nothing derived from the contract knew it needed
                # a broker grant. tests pin the literal to the constant.
                event_type="content.captured",
                payload=chunk,
                correlation_id=correlation_id or session,
                cwd=cwd,
                actor=actor,
                host_turn_id=host_turn_id,
                agent_id=agent_id,
                transcript_path=transcript_path,
                session_id=session,
                journal_dir=str(journal_dir),
            )
            written += 1
    if sink is not None and fallback and sink.refusal not in QUIET_STORE_REFUSALS:
        _report_store_fallback(
            sink,
            fallback=fallback,
            session=session,
            journal_dir=journal_dir,
            correlation_id=correlation_id,
            cwd=cwd,
            actor=actor,
            host_turn_id=host_turn_id,
            agent_id=agent_id,
            transcript_path=transcript_path,
        )
    if operator_ids:
        record_operator_marker(turn_dir, session, operator_ids)
    return written


def _report_store_fallback(
    sink: StoreSink,
    *,
    fallback: int,
    session: str,
    journal_dir: Path,
    correlation_id: str | None,
    cwd: str | None,
    actor: str | None,
    host_turn_id: str | None,
    agent_id: str | None,
    transcript_path: str | None,
) -> None:
    """Say loudly that secrets crossed as the marker because the store failed.

    The hook log always; a ``hook.health.error`` record too when the local
    drainer can publish one. Reason code and count only: never a value, a
    digest, a store address or a path.
    """
    message = (
        f"captured-secret store fallback: {fallback} secret span(s) crossed as "
        f"the redaction marker, reason={sink.refusal}"
    )
    _log(message + (f" ({sink.detail})" if sink.detail else ""))
    status = health.read_status(status_path_for(journal_dir))
    publishable = None if status is None else status.publishable_event_types
    if publishable is None or "hook.health.error" not in publishable:
        return
    emitted_at = datetime.now(UTC).isoformat()
    appender.append_event(
        # A literal, not a constant (OMN-19913): validate_hook_edge_lane.py
        # resolves only literal classes at an emit call.
        event_type="hook.health.error",
        payload={
            "event_id": str(uuid.uuid4()),
            "hook_name": "hook_content_capture",
            "error_tier": "degraded",
            "error_category": "functional_degradation",
            "error_message": message,
            "session_id": session,
            "fingerprint": hashlib.sha256(
                f"hook_content_capture:secret_store:{sink.refusal}".encode()
            ).hexdigest()[:16],
            "emitted_at": emitted_at,
        },
        correlation_id=correlation_id or session,
        cwd=cwd,
        actor=actor,
        host_turn_id=host_turn_id,
        agent_id=agent_id,
        transcript_path=transcript_path,
        session_id=session,
        journal_dir=str(journal_dir),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Journal full hook content (OMN-19551)."
    )
    parser.add_argument("--kind", required=True, choices=sorted(_ITEMS))
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--actor", default=None)
    parser.add_argument("--turn-id", default=None)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--transcript-path", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--journal-dir", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 0
    try:
        raw = sys.stdin.read()
        parsed = json.loads(raw) if raw.strip() else {}
        hook_input = parsed if isinstance(parsed, dict) else {}
        journal_dir = (
            Path(args.journal_dir)
            if args.journal_dir
            else journal.default_journal_dir()
        )
        count = capture(
            hook_input,
            kind=args.kind,
            journal_dir=journal_dir,
            correlation_id=args.correlation_id or None,
            cwd=args.cwd or None,
            actor=args.actor or None,
            host_turn_id=args.turn_id or None,
            agent_id=args.agent_id or None,
            session_id=args.session_id or None,
            transcript_path=args.transcript_path or None,
            now=datetime.now(UTC),
        )
        if count:
            _log(f"journalled {count} {CONTENT_EVENT_TYPE} record(s) ({args.kind})")
    except Exception as exc:  # noqa: BLE001 -- outermost boundary: report, exit 1
        # Exit 1 so hook_emit_bounded fails loud (OMN-20110).
        print(
            f"hook_content_capture: content NOT journalled: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    journal.emit_done()
    return 0


if __name__ == "__main__":
    sys.exit(main())
