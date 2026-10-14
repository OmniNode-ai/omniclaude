# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Token use and model per assistant message, read from the transcript (OMN-18946).

No event carried tokens, usage or price, and the model rode 37.5% of events.
Claude Code hands a hook no usage: Stop and SubagentStop name a transcript and
the last reply, PostToolUse a tool response, SessionStart a ``context_tokens``
gauge (the generated stdin fixtures under
``tests/fixtures/hooks/claude_hook_capture/stdin`` show every field). The
transcript is the one place the harness writes usage, as ``message.usage`` and
``message.model`` on each assistant entry.

Three facts about those entries decide this reader (measured on a live
transcript, 2026-10-14):

* One API message becomes several entries, one per content block (thinking,
  text, tool_use), and each repeats the message's whole ``usage``. Summing
  entries multiplies the tokens by the block count. The reader counts a
  ``message.id`` once.
* A subagent's own transcript marks every entry ``isSidechain``. The main
  thread's transcript is read without sidechain entries, so a subagent's tokens
  are counted by its own SubagentStop and never twice.
* A synthetic entry (``model: "<synthetic>"``) is the harness talking, not the
  model, and carries no usage.

A read is a transcript byte offset plus the ids of the last messages counted,
kept in a marker beside the turn counters. A read consumes nothing: the marker
is advanced by ``HandlerTranscriptUsageCommit`` only after the caller
journalled what the read returned, so a disabled capture or a failed append
leaves the usage for the next read instead of losing it. The first read of a
thread with no marker takes at most its last ``first_read_bytes`` and says so
(``partial_window``): a resumed session whose history is hundreds of megabytes
is not parsed on a hook's critical path.

The hook process imports this module, so it uses the standard library and the
node's own models only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from omniclaude.nodes.node_transcript_usage_read_effect.models import (
    ModelTranscriptUsageReadRequest,
    ModelTranscriptUsageReadResult,
    ModelUsageTotals,
)

#: Message ids kept in a marker. A message split across two reads is two
#: entries with one id; this is how the second is recognised.
RECENT_IDS_KEEP = 256

#: The model the harness stamps on entries it wrote itself.
SYNTHETIC_MODEL = "<synthetic>"

MARKER_SUFFIX = ".usage"


def marker_path(state_dir: Path, session_id: str, agent_id: str | None) -> Path:
    """The marker for a session's main thread, or for one of its subagents."""
    identity = f"{session_id}|{agent_id or ''}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return state_dir / f"{digest}{MARKER_SUFFIX}"


def _read_marker(marker: Path) -> tuple[int, list[str]] | None:
    """``(offset, recent ids)``, or ``None`` when this thread has no marker."""
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    offset = data.get("offset")
    ids = data.get("ids")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return None
    recent = [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []
    return offset, recent


def _count(value: object) -> int:
    """A usage field as a non-negative integer; anything else reads as zero."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _message_usage(
    entry: dict[str, object], *, include_sidechain: bool
) -> tuple[str, str, tuple[int, int, int, int]] | None:
    """``(message id, model, (in, out, cache create, cache read))`` or ``None``."""
    if entry.get("type") != "assistant":
        return None
    if entry.get("isSidechain") and not include_sidechain:
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    model = message.get("model")
    usage = message.get("usage")
    if not isinstance(model, str) or not model or model == SYNTHETIC_MODEL:
        return None
    if not isinstance(usage, dict):
        return None
    identity = message.get("id") or entry.get("uuid")
    if not isinstance(identity, str) or not identity:
        return None
    return (
        identity,
        model,
        (
            _count(usage.get("input_tokens")),
            _count(usage.get("output_tokens")),
            _count(usage.get("cache_creation_input_tokens")),
            _count(usage.get("cache_read_input_tokens")),
        ),
    )


def _window(
    transcript: Path, *, start: int, skip_partial_first_line: bool
) -> tuple[bytes, int] | None:
    """The complete lines from ``start`` to the end, and the offset after them.

    A last line with no newline yet is the harness mid-write: it is left for
    the next read, not parsed half-written.
    """
    try:
        with transcript.open("rb") as handle:
            if skip_partial_first_line and start > 0:
                handle.seek(start - 1)
                if handle.read(1) != b"\n":
                    handle.readline()
                    start = handle.tell()
            else:
                handle.seek(start)
            data = handle.read()
    except OSError:
        return None
    end = data.rfind(b"\n")
    if end < 0:
        return b"", start
    return data[: end + 1], start + end + 1


class HandlerTranscriptUsageRead:
    """Read the usage of messages not yet counted for one session thread."""

    def handle(
        self, request: ModelTranscriptUsageReadRequest
    ) -> ModelTranscriptUsageReadResult:
        transcript = Path(request.transcript_path)
        marker = marker_path(
            Path(request.state_dir), request.session_id, request.agent_id
        )
        prior = _read_marker(marker)
        offset, recent = prior if prior is not None else (0, [])
        nothing = ModelTranscriptUsageReadResult(
            marker_path=str(marker), next_offset=offset, seen_ids=tuple(recent)
        )
        try:
            size = transcript.stat().st_size
        except OSError:
            return nothing
        partial = False
        if prior is None:
            start = max(0, size - request.first_read_bytes)
            partial = start > 0
        else:
            # A transcript that shrank was rewritten: read it from its start.
            start = offset if offset <= size else 0
        window = _window(transcript, start=start, skip_partial_first_line=prior is None)
        if window is None:
            return nothing
        data, next_offset = window

        counted = set(recent)
        messages: dict[str, tuple[str, tuple[int, int, int, int]]] = {}
        for raw in data.decode("utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            found = _message_usage(entry, include_sidechain=request.include_sidechain)
            if found is None:
                continue
            identity, model, numbers = found
            if identity in counted:
                continue
            held = messages.get(identity)
            # The blocks of one streamed message can disagree while it is
            # written; its final usage is the largest output count.
            if held is None or numbers[1] >= held[1][1]:
                messages[identity] = (model, numbers)

        per_model: dict[str, list[int]] = {}
        for model, numbers in messages.values():
            row = per_model.setdefault(model, [0, 0, 0, 0, 0])
            row[0] += 1
            for index, value in enumerate(numbers):
                row[index + 1] += value
        totals = tuple(
            ModelUsageTotals(
                model=model,
                message_count=row[0],
                input_tokens=row[1],
                output_tokens=row[2],
                cache_creation_input_tokens=row[3],
                cache_read_input_tokens=row[4],
            )
            for model, row in sorted(per_model.items())
        )
        return ModelTranscriptUsageReadResult(
            totals=totals,
            partial_window=partial,
            marker_path=str(marker),
            next_offset=next_offset,
            seen_ids=tuple([*recent, *messages][-RECENT_IDS_KEEP:]),
        )


__all__ = [
    "MARKER_SUFFIX",
    "RECENT_IDS_KEEP",
    "SYNTHETIC_MODEL",
    "HandlerTranscriptUsageRead",
    "marker_path",
]
