# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A Claude Code hook record carries a turn id that is unique per session turn (OMN-19517).

The defect, measured on the lab dev-lane broker at 2026-09-25T01:37:40Z: all of the
last 20,000 ``tool-executed`` records carried ONE turn_id,
``sha256:74234e98...``, across 31 distinct sessions, and 187 prompt-submitted
sessions carried the same value. That value is ``sha256("null")``. Claude Code's
hook input has no turn identifier, so the appender journalled ``turn_id: null``,
and the capture redaction's fail-closed default (``capture_hashed``) turned
every null into the same digest. A grouping key that is identical for every
session groups nothing.

What each test pins
-------------------
* AC1 -- a prompt-submitted record opens a new turn for its session, and the
  tool-executed records after it carry that turn; turns differ across prompts
  and across sessions, and concurrent prompts never allocate the same turn.
* AC2 -- a host-supplied turn id (Codex) is kept verbatim, and the two session
  lifecycle events keep a null turn id, as the envelope contract says.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LIB = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
_SCRIPTS = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"
sys.path.insert(0, str(_LIB))

import hook_emit_append  # noqa: E402
import hook_emit_journal as journal  # noqa: E402

_SESSION_A = "9787a4a3-ec49-4819-8bdc-5044efb94550"
_SESSION_B = "33f32a16-bfe1-4711-8017-8d15163575ce"
_NULL_DIGEST = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"


def _append(
    journal_dir: Path,
    event_type: str,
    session_id: str,
    *,
    turn_id: str | None = None,
    actor: str | None = None,
) -> None:
    argv = [
        "--event-type",
        event_type,
        "--payload",
        json.dumps({"session_id": session_id}),
        "--correlation-id",
        session_id,
        "--session-id",
        session_id,
        "--journal-dir",
        str(journal_dir),
    ]
    if turn_id is not None:
        argv += ["--turn-id", turn_id]
    if actor is not None:
        argv += ["--actor", actor]
    assert hook_emit_append.main(argv) == 0


def _turn_ids(journal_dir: Path) -> list[Any]:
    """Turn ids of every journalled record, in append order."""
    return [e.record.payload.get("turn_id") for e in journal.list_pending(journal_dir)]


def test_a_prompt_opens_a_turn_and_the_tool_calls_after_it_carry_that_turn(
    tmp_path: Path,
) -> None:
    j = tmp_path / "hook_emit_journal"
    for event in (
        "prompt.submitted",
        "tool.executed",
        "tool.executed",
        "prompt.submitted",
        "tool.executed",
    ):
        _append(j, event, _SESSION_A)

    ids = _turn_ids(j)
    assert all(isinstance(i, str) and i for i in ids), (
        f"a Claude Code prompt or tool record must carry a turn id, got {ids}"
    )
    first, second = ids[0], ids[3]
    assert ids[:3] == [first, first, first], "a tool call belongs to its prompt's turn"
    assert ids[3:] == [second, second], "a new prompt opens a new turn"
    assert first != second, "two prompts in one session must be two turns"


def test_two_sessions_never_share_a_turn_id(tmp_path: Path) -> None:
    j = tmp_path / "hook_emit_journal"
    for session in (_SESSION_A, _SESSION_B):
        _append(j, "prompt.submitted", session)
        _append(j, "tool.executed", session)

    entries = journal.list_pending(j)
    by_session: dict[str, set[Any]] = {}
    for e in entries:
        by_session.setdefault(e.record.payload["session_id"], set()).add(
            e.record.payload.get("turn_id")
        )
    assert by_session[_SESSION_A].isdisjoint(by_session[_SESSION_B]), (
        f"a turn id shared across sessions is the defect itself: {by_session}"
    )
    assert None not in by_session[_SESSION_A] | by_session[_SESSION_B]


def test_a_tool_call_before_any_observed_prompt_still_gets_a_session_scoped_turn(
    tmp_path: Path,
) -> None:
    """A session resumed after the hook was installed has not been seen to prompt.

    Its tool calls still get a turn that is scoped to the session, never null
    (which the redaction would collapse into the shared digest).
    """
    j = tmp_path / "hook_emit_journal"
    _append(j, "tool.executed", _SESSION_A)
    _append(j, "tool.executed", _SESSION_B)
    _append(j, "prompt.submitted", _SESSION_A)

    before_a, before_b, after_a = _turn_ids(j)
    assert before_a and before_b and after_a
    assert before_a != before_b
    assert after_a != before_a, "the first observed prompt opens a new turn"


def test_a_host_supplied_turn_id_is_kept_verbatim(tmp_path: Path) -> None:
    j = tmp_path / "hook_emit_journal"
    host_turn = "01a0b512-0898-7df0-9d16-5fe4e9fd1f0f"
    _append(j, "prompt.submitted", _SESSION_A, turn_id=host_turn, actor="codex")
    _append(j, "tool.executed", _SESSION_A, turn_id=host_turn, actor="codex")
    assert _turn_ids(j) == [host_turn, host_turn]


@pytest.mark.parametrize("event", ["session.started", "session.ended"])
def test_session_lifecycle_records_keep_a_null_turn_id(
    event: str, tmp_path: Path
) -> None:
    j = tmp_path / "hook_emit_journal"
    _append(j, "prompt.submitted", _SESSION_A)
    _append(j, event, _SESSION_A)
    assert _turn_ids(j)[1] is None, "a session event is not a turn"


def _prompt_in_child(journal_dir: str) -> None:
    _append(Path(journal_dir), "prompt.submitted", _SESSION_A)


def test_concurrent_prompts_in_one_session_never_allocate_the_same_turn(
    tmp_path: Path,
) -> None:
    """The appender is forked and disowned per hook, so allocations can overlap."""
    j = tmp_path / "hook_emit_journal"
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_prompt_in_child, args=(str(j),)) for _ in range(8)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    ids = _turn_ids(j)
    assert len(ids) == 8
    assert len(set(ids)) == 8, f"two concurrent prompts shared a turn: {ids}"


def test_the_minted_turn_id_never_hashes_to_the_null_digest(tmp_path: Path) -> None:
    """The measured symptom, stated directly against the redaction's hash."""
    import hashlib

    j = tmp_path / "hook_emit_journal"
    _append(j, "prompt.submitted", _SESSION_A)
    _append(j, "tool.executed", _SESSION_A)
    for turn_id in _turn_ids(j):
        canonical = json.dumps(turn_id, sort_keys=True, separators=(",", ":"))
        digest = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        assert digest != _NULL_DIGEST


def _run_hook(script: str, payload: dict[str, Any], state_dir: Path) -> None:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(_REPO_ROOT)
    env["OMNICLAUDE_MODE"] = "full"
    env["ONEX_STATE_DIR"] = str(state_dir)
    env["ONEX_HOOK_EMIT_JOURNAL_DIR"] = str(state_dir / "hook_emit_journal")
    env["PLUGIN_PYTHON_BIN"] = sys.executable
    env.pop("ONEX_HOOK_ACTOR", None)
    result = subprocess.run(
        ["bash", str(_SCRIPTS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def _wait_for_records(journal_dir: Path, count: int) -> list[journal.JournalEntry]:
    deadline = time.monotonic() + 15.0
    entries: list[journal.JournalEntry] = []
    while time.monotonic() < deadline:
        if journal_dir.is_dir():
            entries = journal.list_pending(journal_dir)
            if len(entries) >= count:
                return entries
        time.sleep(0.05)
    return entries


def test_the_shipped_claude_hooks_carry_one_turn_from_prompt_to_tool_call(
    tmp_path: Path,
) -> None:
    """End to end through the real bus-mirror scripts with Claude-shaped input."""
    state = tmp_path / "onex_state"
    j = state / "hook_emit_journal"
    base = {"session_id": _SESSION_A, "cwd": str(_REPO_ROOT)}
    _run_hook(
        "user_prompt_submit_bus_mirror.sh",
        {**base, "hook_event_name": "UserPromptSubmit", "prompt": "hi"},
        state,
    )
    # The appender is backgrounded; the prompt must land before the tool call,
    # as it does in a real session where the model answers in between.
    assert len(_wait_for_records(j, 1)) == 1
    _run_hook(
        "post_tool_use_bus_mirror.sh",
        {
            **base,
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "duration_ms": 5,
            "tool_response": {"interrupted": False},
        },
        state,
    )
    entries = _wait_for_records(j, 2)
    assert len(entries) == 2
    prompt_turn = entries[0].record.payload.get("turn_id")
    tool_turn = entries[1].record.payload.get("turn_id")
    assert prompt_turn, "the Claude prompt record must carry a turn id"
    assert tool_turn == prompt_turn
