# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A refused call carries the guard that refused it (OMN-18946).

3,939 refused calls in one week carried no guard name: the guard and its reason
lived only in rate-limited ledger FRICTION rows, which are not joined to hook
events. A refused PreToolUse has no PostToolUse to pair with, so the only
evidence of the refusal was its absence. These tests hold the refusal to one
``GuardRefusal`` event per refused call, naming the guard and its reason class,
joined to the call by ``tool_use_id`` and carrying no content.

Planted secrets are built by concatenation and carry ``FAKE``.
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
    make_tool_call_key,
    map_hook_stdin,
)
from omniclaude.nodes.node_hook_refusal_record_effect.handlers import (
    handler_hook_refusal_record as recorder,
)
from omniclaude.nodes.node_hook_refusal_record_effect.models import (
    EnumHookRefusalRecordStatus,
    ModelHookRefusalRecordRequest,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

SESSION = "session-refusal-1"
TOOL_USE = "toolu_refused_1"
GUARD = "pre_tool_use_worktree_guard.sh"
ANTHROPIC_FAKE = "sk-" + "ant-" + "FAKE" + "0" * 28
_NOW = datetime(2026, 10, 14, 5, 0, 0, tzinfo=UTC)


def _refusal_stdin(**over: Any) -> dict[str, Any]:
    stdin: dict[str, Any] = {
        "hook_event_name": "GuardRefusal",
        "session_id": SESSION,
        "prompt_id": "prompt-1",
        "tool_name": "Bash",
        "tool_use_id": TOOL_USE,
        "guard": GUARD,
        "reason_class": "worktree-add-refused",
        "refused_hook_event_name": "PreToolUse",
    }
    stdin.update(over)
    return stdin


def _map(stdin: dict[str, Any]) -> ModelClaudeHookEvent:
    return map_hook_stdin(
        stdin,
        emitted_at=_NOW,
        sidecar=None,
        claude_code_version="2.1.283",
        turn_id="turn-1",
    ).event


# ---------------------------------------------------------------------------
# the event
# ---------------------------------------------------------------------------


def test_the_enum_names_the_refusal_as_a_derived_event_not_a_harness_hook() -> None:
    assert EnumClaudeHookEventName.GUARD_REFUSAL.value == "GuardRefusal"
    assert EnumClaudeHookEventName.GUARD_REFUSAL in EnumClaudeHookEventName.derived()
    assert EnumClaudeHookEventName.PRE_TOOL_USE not in (
        EnumClaudeHookEventName.derived()
    )


def test_a_refusal_event_names_the_guard_and_the_reason_class() -> None:
    event = _map(_refusal_stdin())

    assert event.hook_event_name is EnumClaudeHookEventName.GUARD_REFUSAL
    payload = event.payload.model_dump(mode="json")
    assert payload["guard"] == GUARD
    assert payload["reason_class"] == "worktree-add-refused"
    assert payload["refused_hook_event_name"] == "PreToolUse"
    assert payload["tool_name"] == "Bash"


def test_a_refusal_event_joins_the_refused_call_by_tool_use_id() -> None:
    refusal = _map(_refusal_stdin())
    pre = _map(
        {
            "hook_event_name": "PreToolUse",
            "session_id": SESSION,
            "prompt_id": "prompt-1",
            "tool_name": "Bash",
            "tool_use_id": TOOL_USE,
            "tool_input": {"command": "git worktree add /tmp/x"},
        }
    )

    assert refusal.lineage.tool_use_id == pre.lineage.tool_use_id == TOOL_USE
    pre_payload = pre.payload.model_dump(mode="json")
    assert refusal.lineage.causation_id is not None
    assert str(refusal.lineage.causation_id) == pre_payload["tool_call_key"]
    assert refusal.lineage.causation_id == make_tool_call_key(SESSION, TOOL_USE)


def test_a_refusal_event_carries_no_content_reference() -> None:
    event = _map(_refusal_stdin())

    assert event.content_refs == ()
    assert not any(key.endswith("_ref") for key in event.payload.model_dump())


def test_a_reason_class_rides_raw_cut_to_its_bound() -> None:
    """OMN-19513: no scrub; the label is only cut to its column's bound."""
    event = _map(_refusal_stdin(reason_class=f"bad token {ANTHROPIC_FAKE}"))

    assert event.payload.model_dump()["reason_class"] == f"bad token {ANTHROPIC_FAKE}"


def test_two_guards_refusing_one_call_get_distinct_event_ids() -> None:
    first = _map(_refusal_stdin(guard="guard_a.sh"))
    second = _map(_refusal_stdin(guard="guard_b.sh"))

    assert first.event_id != second.event_id
    assert first.lineage.tool_use_id == second.lineage.tool_use_id


def test_a_refusal_of_a_call_with_no_tool_use_id_has_no_causation() -> None:
    event = _map(_refusal_stdin(tool_use_id=None, tool_name=None))

    assert event.lineage.tool_use_id is None
    assert event.lineage.causation_id is None


# ---------------------------------------------------------------------------
# the producer journals it
# ---------------------------------------------------------------------------


@pytest.fixture
def jdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    health.write_status(
        directory.parent / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("hook.event",),
        ),
    )
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(capture_mod, "lane_grant_pending", lambda: False)
    monkeypatch.setenv("ONEX_HOOK_EMIT_JOURNAL_DIR", str(directory))
    return directory


def _journalled(journal_dir: Path) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == capture_mod.HOOK_EVENT_TYPE
    ]


def test_capture_guard_refusal_journals_one_event_for_the_refused_call(
    jdir: Path,
) -> None:
    refused_stdin = {
        "hook_event_name": "PreToolUse",
        "session_id": SESSION,
        "prompt_id": "prompt-1",
        "tool_name": "Bash",
        "tool_use_id": TOOL_USE,
        "tool_input": {"command": "git worktree add /tmp/x"},
        "transcript_path": f"/restricted/{SESSION}.jsonl",
    }

    written = capture_mod.capture_guard_refusal(
        refused_stdin,
        guard=GUARD,
        reason_class="worktree-add-refused",
        journal_dir=jdir,
    )

    assert written == 1
    (payload,) = _journalled(jdir)
    event = ModelClaudeHookEvent.model_validate(payload)
    assert event.hook_event_name is EnumClaudeHookEventName.GUARD_REFUSAL
    assert payload["session_id"] == SESSION
    assert event.lineage.tool_use_id == TOOL_USE
    dumped = event.payload.model_dump(mode="json")
    assert dumped["guard"] == GUARD
    assert dumped["refused_hook_event_name"] == "PreToolUse"
    # The refused command is content: it does not ride the refusal event.
    assert "git worktree add" not in json.dumps(payload)


def test_capture_guard_refusal_is_off_when_the_drainer_cannot_publish(
    jdir: Path,
) -> None:
    health.write_status(
        jdir.parent / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("tool.executed",),
        ),
    )

    written = capture_mod.capture_guard_refusal(
        {"session_id": SESSION, "tool_use_id": TOOL_USE},
        guard=GUARD,
        reason_class="x",
        journal_dir=jdir,
    )

    assert written == 0
    assert _journalled(jdir) == []


def test_capture_guard_refusal_skips_a_payload_with_no_session(jdir: Path) -> None:
    written = capture_mod.capture_guard_refusal(
        {"tool_use_id": TOOL_USE}, guard=GUARD, reason_class="x", journal_dir=jdir
    )

    assert written == 0


# ---------------------------------------------------------------------------
# the recorder calls it on every refusal, not once per rate-limit window
# ---------------------------------------------------------------------------


@pytest.fixture
def recording(jdir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "registry"))
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ONEX_HOOK_REFUSAL_STATE_DIR", str(tmp_path / "refusals"))
    monkeypatch.setattr(
        recorder, "resolve_lane_fields", lambda *a, **kw: ("lane-x", "env")
    )
    return jdir


def _request(tool_use_id: str, **over: Any) -> ModelHookRefusalRecordRequest:
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": SESSION,
        "tool_name": "Bash",
        "tool_use_id": tool_use_id,
        "tool_input": {"command": "git worktree add /tmp/x"},
    }
    return ModelHookRefusalRecordRequest(
        guard=GUARD,
        reason="worktree-add-refused",
        detail="BLOCKED: worktree path",
        payload=payload,
        print_row=True,
        **over,
    )


def test_every_refusal_is_journalled_even_when_its_ledger_row_is_suppressed(
    recording: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler = recorder.HandlerHookRefusalRecord()
    monkeypatch.setattr(recorder.time, "time", lambda: 10_000.0)

    first = handler.handle(_request("toolu_a"))
    assert first.status is EnumHookRefusalRecordStatus.PRINTED
    # Suppress the key the way a landed first row does.
    recorder._write_state(
        Path(recorder.state_dir()) / f"{first.key}.json",
        last_emitted=10_000.0,
        suppressed=0,
    )
    second = handler.handle(_request("toolu_b"))
    assert second.status is EnumHookRefusalRecordStatus.SUPPRESSED

    events = [ModelClaudeHookEvent.model_validate(p) for p in _journalled(recording)]
    assert [e.lineage.tool_use_id for e in events] == ["toolu_a", "toolu_b"]
    assert {e.payload.model_dump()["guard"] for e in events} == {GUARD}


def test_the_journalled_reason_class_is_the_normalised_token(
    recording: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recorder.time, "time", lambda: 10_000.0)
    request = ModelHookRefusalRecordRequest(
        guard=GUARD,
        reason="Worktree add refused: some/path 12345",
        detail="d",
        payload={"session_id": SESSION, "tool_use_id": "toolu_c"},
        print_row=True,
    )

    recorder.HandlerHookRefusalRecord().handle(request)

    (payload,) = _journalled(recording)
    assert payload["payload"]["reason_class"] == "worktree-add-refused"


def test_a_failed_journal_does_not_change_the_ledger_verdict(
    recording: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("journal unavailable")

    monkeypatch.setattr(capture_mod, "capture_guard_refusal", boom)
    monkeypatch.setattr(recorder.time, "time", lambda: 10_000.0)

    result = recorder.HandlerHookRefusalRecord().handle(_request("toolu_d"))

    assert result.status is EnumHookRefusalRecordStatus.PRINTED
    assert any("refusal event" in message for message in result.messages)
