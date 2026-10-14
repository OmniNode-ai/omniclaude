# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Token use and model per assistant message reach the hook events (OMN-18946).

No hook's stdin carries usage: Stop and SubagentStop name a transcript and the
last reply, PostToolUse a tool response, SessionStart a ``context_tokens``
gauge. The transcript is the one place Claude Code writes usage, once per API
message, repeated on every content block of that message. These tests hold the
reader to: count a message once, count it once across Stop events, attribute it
to the model that ran it, and say when it read only a tail.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

import hook_claude_capture as capture_mod
import hook_emit_health as health
import hook_emit_journal as journal

from omniclaude.hooks.model_claude_hook_event import (
    EnumClaudeHookEventName,
    ModelClaudeHookEvent,
    map_hook_stdin,
)
from omniclaude.nodes.node_transcript_usage_read_effect.handlers.handler_transcript_usage_commit import (
    HandlerTranscriptUsageCommit,
)
from omniclaude.nodes.node_transcript_usage_read_effect.handlers.handler_transcript_usage_read import (
    HandlerTranscriptUsageRead,
)
from omniclaude.nodes.node_transcript_usage_read_effect.models import (
    ModelTranscriptUsageCommitRequest,
    ModelTranscriptUsageReadRequest,
    ModelTranscriptUsageReadResult,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

SESSION = "session-usage-1"
SONNET = "model-alpha"
OPUS = "model-beta"
_NOW = datetime(2026, 10, 14, 5, 0, 0, tzinfo=UTC)


def _entry(
    message_id: str,
    model: str,
    *,
    inp: int,
    out: int,
    cache_create: int = 0,
    cache_read: int = 0,
    sidechain: bool = False,
    block: str = "text",
    uuid: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "uuid": uuid or f"{message_id}-{block}",
        "timestamp": "2026-10-14T04:00:00.000Z",
        "message": {
            "id": message_id,
            "model": model,
            "role": "assistant",
            "content": [{"type": block}],
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_creation_input_tokens": cache_create,
                "cache_read_input_tokens": cache_read,
            },
        },
    }


def _write(path: Path, entries: list[dict[str, Any]], *, append: bool = False) -> None:
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def _collect(
    transcript: Path, state: Path, *, agent_id: str | None = None, **kw: Any
) -> ModelTranscriptUsageReadResult:
    return HandlerTranscriptUsageRead().handle(
        ModelTranscriptUsageReadRequest(
            transcript_path=str(transcript),
            state_dir=str(state),
            session_id=SESSION,
            agent_id=agent_id,
            **kw,
        )
    )


def _commit(read: ModelTranscriptUsageReadResult) -> None:
    result = HandlerTranscriptUsageCommit().handle(
        ModelTranscriptUsageCommitRequest(
            marker_path=read.marker_path,
            next_offset=read.next_offset,
            seen_ids=read.seen_ids,
        )
    )
    assert result.committed


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    return tmp_path / f"{SESSION}.jsonl"


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "turns"


# ---------------------------------------------------------------------------
# reading the transcript
# ---------------------------------------------------------------------------


def test_the_blocks_of_one_api_message_count_once(
    transcript: Path, state: Path
) -> None:
    _write(
        transcript,
        [
            _entry(
                "msg_1",
                SONNET,
                inp=2,
                out=563,
                cache_create=59749,
                cache_read=10564,
                block="thinking",
            ),
            _entry(
                "msg_1",
                SONNET,
                inp=2,
                out=563,
                cache_create=59749,
                cache_read=10564,
                block="text",
            ),
            _entry(
                "msg_1",
                SONNET,
                inp=2,
                out=563,
                cache_create=59749,
                cache_read=10564,
                block="tool_use",
            ),
        ],
    )

    read = _collect(transcript, state)

    (totals,) = read.totals
    assert totals.model == SONNET
    assert totals.message_count == 1
    assert totals.input_tokens == 2
    assert totals.output_tokens == 563
    assert totals.cache_creation_input_tokens == 59749
    assert totals.cache_read_input_tokens == 10564


def test_each_model_gets_its_own_totals(transcript: Path, state: Path) -> None:
    _write(
        transcript,
        [
            _entry("msg_1", SONNET, inp=10, out=100),
            _entry("msg_2", OPUS, inp=20, out=200),
            _entry("msg_3", SONNET, inp=30, out=300),
        ],
    )

    by_model = {t.model: t for t in _collect(transcript, state).totals}

    assert set(by_model) == {SONNET, OPUS}
    assert (by_model[SONNET].message_count, by_model[SONNET].output_tokens) == (2, 400)
    assert (by_model[SONNET].input_tokens) == 40
    assert (by_model[OPUS].message_count, by_model[OPUS].output_tokens) == (1, 200)


def test_a_streamed_message_counts_its_largest_usage(
    transcript: Path, state: Path
) -> None:
    _write(
        transcript,
        [
            _entry("msg_1", SONNET, inp=2, out=5, block="thinking"),
            _entry("msg_1", SONNET, inp=2, out=90, block="text"),
        ],
    )

    (totals,) = _collect(transcript, state).totals

    assert totals.output_tokens == 90


def test_messages_already_counted_are_not_counted_again(
    transcript: Path, state: Path
) -> None:
    _write(transcript, [_entry("msg_1", SONNET, inp=1, out=10)])
    first = _collect(transcript, state)
    _commit(first)

    again = _collect(transcript, state)
    assert again.totals == ()

    _write(transcript, [_entry("msg_2", SONNET, inp=2, out=20)], append=True)
    (totals,) = _collect(transcript, state).totals
    assert (totals.message_count, totals.output_tokens) == (1, 20)


def test_nothing_is_consumed_until_the_read_is_committed(
    transcript: Path, state: Path
) -> None:
    _write(transcript, [_entry("msg_1", SONNET, inp=1, out=10)])

    _collect(transcript, state)  # never committed: the event was not journalled
    (totals,) = _collect(transcript, state).totals

    assert totals.output_tokens == 10


def test_a_message_split_across_two_reads_is_counted_once(
    transcript: Path, state: Path
) -> None:
    _write(transcript, [_entry("msg_1", SONNET, inp=1, out=10, block="thinking")])
    _commit(_collect(transcript, state))
    # The harness flushed the rest of the same message after the first Stop.
    _write(
        transcript,
        [_entry("msg_1", SONNET, inp=1, out=10, block="text")],
        append=True,
    )

    assert _collect(transcript, state).totals == ()


def test_a_half_written_last_line_waits_for_the_next_read(
    transcript: Path, state: Path
) -> None:
    whole = json.dumps(_entry("msg_1", SONNET, inp=1, out=10))
    partial = json.dumps(_entry("msg_2", SONNET, inp=2, out=20))
    transcript.write_text(whole + "\n" + partial[: len(partial) // 2], encoding="utf-8")

    first = _collect(transcript, state)
    _commit(first)
    assert [t.message_count for t in first.totals] == [1]

    transcript.write_text(whole + "\n" + partial + "\n", encoding="utf-8")
    (second,) = _collect(transcript, state).totals
    assert (second.message_count, second.output_tokens) == (1, 20)


def test_sidechain_entries_are_not_the_main_threads_use(
    transcript: Path, state: Path
) -> None:
    _write(
        transcript,
        [
            _entry("msg_1", SONNET, inp=1, out=10),
            _entry("msg_side", OPUS, inp=9, out=900, sidechain=True),
        ],
    )

    (totals,) = _collect(transcript, state).totals

    assert totals.model == SONNET


def test_a_subagents_own_transcript_is_all_sidechain_and_all_counted(
    transcript: Path, state: Path
) -> None:
    _write(
        transcript,
        [_entry("msg_a", OPUS, inp=5, out=50, sidechain=True)],
    )

    (totals,) = _collect(
        transcript, state, agent_id="agent-1", include_sidechain=True
    ).totals

    assert (totals.model, totals.output_tokens) == (OPUS, 50)


def test_synthetic_and_usage_free_entries_are_skipped(
    transcript: Path, state: Path
) -> None:
    no_usage = _entry("msg_n", SONNET, inp=0, out=0)
    del no_usage["message"]["usage"]
    transcript.write_text(
        "\n".join(
            [
                json.dumps(_entry("msg_s", "<synthetic>", inp=0, out=0)),
                json.dumps(no_usage),
                json.dumps({"type": "user", "message": {"content": "hi"}}),
                "{not json",
                json.dumps(_entry("msg_1", SONNET, inp=1, out=10)),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (totals,) = _collect(transcript, state).totals

    assert (totals.model, totals.message_count) == (SONNET, 1)


def test_a_non_numeric_usage_field_reads_as_zero(transcript: Path, state: Path) -> None:
    entry = _entry("msg_1", SONNET, inp=1, out=10)
    entry["message"]["usage"]["output_tokens"] = "lots"
    entry["message"]["usage"]["input_tokens"] = True
    _write(transcript, [entry])

    (totals,) = _collect(transcript, state).totals

    assert (totals.input_tokens, totals.output_tokens) == (0, 0)


def test_a_first_read_of_a_long_transcript_takes_the_tail_and_says_so(
    transcript: Path, state: Path
) -> None:
    _write(
        transcript,
        [_entry(f"msg_{n}", SONNET, inp=1, out=10) for n in range(200)],
    )

    read = _collect(transcript, state, first_read_bytes=2048)

    assert read.partial_window is True
    (totals,) = read.totals
    assert 0 < totals.message_count < 200


def test_a_short_transcript_is_read_whole_and_is_not_partial(
    transcript: Path, state: Path
) -> None:
    _write(transcript, [_entry("msg_1", SONNET, inp=1, out=10)])

    assert _collect(transcript, state).partial_window is False


def test_a_missing_transcript_reads_as_nothing(tmp_path: Path, state: Path) -> None:
    read = _collect(tmp_path / "absent.jsonl", state)

    assert read.totals == ()


def test_a_main_thread_and_a_subagent_keep_separate_markers(
    transcript: Path, state: Path, tmp_path: Path
) -> None:
    _write(transcript, [_entry("msg_1", SONNET, inp=1, out=10)])
    _commit(_collect(transcript, state))

    sub = tmp_path / "agent-1.jsonl"
    _write(sub, [_entry("msg_1", SONNET, inp=1, out=10, sidechain=True)])
    (totals,) = _collect(sub, state, agent_id="agent-1", include_sidechain=True).totals

    assert totals.message_count == 1


# ---------------------------------------------------------------------------
# the event
# ---------------------------------------------------------------------------


def _usage_stdin(**over: Any) -> dict[str, Any]:
    stdin: dict[str, Any] = {
        "hook_event_name": "AssistantUsage",
        "session_id": SESSION,
        "prompt_id": "prompt-1",
        "model": SONNET,
        "message_count": 2,
        "input_tokens": 12,
        "output_tokens": 345,
        "cache_creation_input_tokens": 6,
        "cache_read_input_tokens": 78,
        "usage_source_hook": "Stop",
        "partial_window": False,
    }
    stdin.update(over)
    return stdin


def _map(stdin: dict[str, Any]) -> ModelClaudeHookEvent:
    from omniclaude.hooks.model_claude_hook_event import ModelContentScrubResult

    return map_hook_stdin(
        stdin,
        emitted_at=_NOW,
        sidecar=None,
        claude_code_version="2.1.283",
        turn_id="turn-1",
        content_scrubber=lambda v: ModelContentScrubResult(
            value=v, redaction_state="clean", matched_pattern_names=()
        ),
    ).event


def test_the_usage_event_states_model_and_token_counts() -> None:
    event = _map(_usage_stdin())

    assert event.hook_event_name is EnumClaudeHookEventName.ASSISTANT_USAGE
    assert EnumClaudeHookEventName.ASSISTANT_USAGE in EnumClaudeHookEventName.derived()
    payload = event.payload.model_dump(mode="json")
    assert payload["model"] == SONNET
    assert payload["message_count"] == 2
    assert payload["input_tokens"] == 12
    assert payload["output_tokens"] == 345
    assert payload["cache_creation_input_tokens"] == 6
    assert payload["cache_read_input_tokens"] == 78
    assert payload["usage_source_hook"] == "Stop"
    assert payload["partial_window"] is False
    assert event.content_refs == ()


def test_two_models_in_one_stop_get_distinct_event_ids() -> None:
    assert (
        _map(_usage_stdin(model=SONNET)).event_id
        != _map(_usage_stdin(model=OPUS)).event_id
    )


def test_a_negative_count_is_refused() -> None:
    from omniclaude.hooks.model_claude_hook_event import InvalidHookInputError

    with pytest.raises(InvalidHookInputError):
        _map(_usage_stdin(output_tokens=-1))


# ---------------------------------------------------------------------------
# the producer journals it
# ---------------------------------------------------------------------------


@pytest.fixture
def jdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    _status(directory, ("hook.event",))
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(capture_mod, "lane_grant_pending", lambda: False)
    return directory


def _status(journal_dir: Path, types: tuple[str, ...]) -> None:
    health.write_status(
        journal_dir.parent / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=types,
        ),
    )


def _usage_events(journal_dir: Path) -> list[ModelClaudeHookEvent]:
    return [
        ModelClaudeHookEvent.model_validate(dict(entry.record.payload))
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == capture_mod.HOOK_EVENT_TYPE
        and entry.record.payload["hook_event_name"] == "AssistantUsage"
    ]


def test_stop_journals_one_usage_event_per_model(jdir: Path, transcript: Path) -> None:
    _write(
        transcript,
        [
            _entry("msg_1", SONNET, inp=10, out=100, cache_read=1000),
            _entry("msg_2", OPUS, inp=20, out=200),
            _entry("msg_3", SONNET, inp=30, out=300, cache_read=3000),
        ],
    )

    written = capture_mod.capture_assistant_usage(
        {
            "hook_event_name": "Stop",
            "session_id": SESSION,
            "prompt_id": "prompt-1",
            "transcript_path": str(transcript),
        },
        journal_dir=jdir,
    )

    assert written == 2
    events = _usage_events(jdir)
    by_model = {e.payload.model_dump()["model"]: e.payload.model_dump() for e in events}
    assert by_model[SONNET]["output_tokens"] == 400
    assert by_model[SONNET]["cache_read_input_tokens"] == 4000
    assert by_model[SONNET]["message_count"] == 2
    assert by_model[SONNET]["usage_source_hook"] == "Stop"
    assert by_model[OPUS]["output_tokens"] == 200
    assert all(e.lineage.agent_id is None for e in events)


def test_a_session_total_is_the_sum_of_its_stop_events(
    jdir: Path, transcript: Path
) -> None:
    stop = {
        "hook_event_name": "Stop",
        "session_id": SESSION,
        "transcript_path": str(transcript),
    }
    _write(transcript, [_entry("msg_1", SONNET, inp=10, out=100)])
    capture_mod.capture_assistant_usage(stop, journal_dir=jdir)
    _write(transcript, [_entry("msg_2", SONNET, inp=20, out=200)], append=True)
    capture_mod.capture_assistant_usage(stop, journal_dir=jdir)
    # A Stop that fires again for the same turn adds nothing.
    assert capture_mod.capture_assistant_usage(stop, journal_dir=jdir) == 0

    events = _usage_events(jdir)
    total_in = sum(e.payload.model_dump()["input_tokens"] for e in events)
    total_out = sum(e.payload.model_dump()["output_tokens"] for e in events)
    assert (total_in, total_out) == (30, 300)


def test_a_subagent_stop_reads_the_agents_own_transcript(
    jdir: Path, transcript: Path, tmp_path: Path
) -> None:
    sub = tmp_path / "agent-abc.jsonl"
    _write(sub, [_entry("msg_a", OPUS, inp=5, out=50, sidechain=True)])

    written = capture_mod.capture_assistant_usage(
        {
            "hook_event_name": "SubagentStop",
            "session_id": SESSION,
            "agent_id": "agent-abc",
            "agent_type": "general-purpose",
            "transcript_path": str(transcript),
            "agent_transcript_path": str(sub),
        },
        journal_dir=jdir,
    )

    assert written == 1
    (event,) = _usage_events(jdir)
    assert event.lineage.agent_id == "agent-abc"
    dumped = event.payload.model_dump()
    assert (dumped["model"], dumped["output_tokens"]) == (OPUS, 50)
    assert dumped["usage_source_hook"] == "SubagentStop"


def test_usage_not_journalled_is_counted_by_the_next_stop(
    jdir: Path, transcript: Path
) -> None:
    stop = {
        "hook_event_name": "Stop",
        "session_id": SESSION,
        "transcript_path": str(transcript),
    }
    _write(transcript, [_entry("msg_1", SONNET, inp=10, out=100)])
    _status(jdir, ("tool.executed",))  # the drainer cannot publish hook.event
    assert capture_mod.capture_assistant_usage(stop, journal_dir=jdir) == 0

    _status(jdir, ("hook.event",))
    assert capture_mod.capture_assistant_usage(stop, journal_dir=jdir) == 1
    (event,) = _usage_events(jdir)
    assert event.payload.model_dump()["output_tokens"] == 100


@pytest.mark.parametrize("hook", ["PreToolUse", "PostToolUse", "UserPromptSubmit"])
def test_only_a_stop_class_hook_reads_usage(
    jdir: Path, transcript: Path, hook: str
) -> None:
    _write(transcript, [_entry("msg_1", SONNET, inp=10, out=100)])

    assert (
        capture_mod.capture_assistant_usage(
            {
                "hook_event_name": hook,
                "session_id": SESSION,
                "transcript_path": str(transcript),
            },
            journal_dir=jdir,
        )
        == 0
    )


def test_a_stop_with_no_readable_transcript_journals_nothing_and_does_not_raise(
    jdir: Path, tmp_path: Path
) -> None:
    assert (
        capture_mod.capture_assistant_usage(
            {
                "hook_event_name": "Stop",
                "session_id": SESSION,
                "transcript_path": str(tmp_path / "gone.jsonl"),
            },
            journal_dir=jdir,
        )
        == 0
    )
