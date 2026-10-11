# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Operator prompts on the content-capture topic (OMN-20905).

RULING 2026-10-10T22:40:43Z: the operator's decisions and asks are extracted
from the bus, so the Stop capture records which prompts the operator typed.
The transcript entries below are the shapes Claude Code 2.1.295 writes,
measured on 2026-10-10: an operator's prompt carries ``origin.kind`` ``human``;
a lane brief given to ``claude -p`` carries no origin and ``turnOrigin``
``sdk``; scheduled prompts, task notifications and compaction summaries carry
another origin or none.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# The hook library is a script directory, not a package: import it by name once
# it is on the path.
capture_mod = importlib.import_module("hook_content_capture")
health = importlib.import_module("hook_emit_health")
journal = importlib.import_module("hook_emit_journal")

SESSION = "0f0f0f0f-1111-2222-3333-444444444444"
NOW = datetime.now(UTC)


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    health.write_status(
        capture_mod.status_path_for(directory),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("content.captured",),
        ),
    )
    return directory


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)


def _stamp(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _user(
    text: str,
    uid: str,
    *,
    origin: str | None = None,
    turn_origin: str | None = None,
    minutes_ago: float = 1,
    meta: bool = False,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": "user",
        "uuid": uid,
        "promptId": f"prompt-{uid}",
        "timestamp": _stamp(minutes_ago),
        "message": {"role": "user", "content": text},
    }
    if origin is not None:
        entry["origin"] = {"kind": origin}
    if turn_origin is not None:
        entry["turnOrigin"] = turn_origin
    if meta:
        entry["isMeta"] = True
    return entry


def _reply(text: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _transcript(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def _records(journal_dir: Path) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == "content.captured"
    ]


def _operator(journal_dir: Path) -> list[dict[str, Any]]:
    return [
        r
        for r in _records(journal_dir)
        if r["content_kind"] == capture_mod.OPERATOR_PROMPT_KIND
    ]


def _stop(journal_dir: Path, transcript: Path) -> None:
    capture_mod.capture(
        {"session_id": SESSION, "transcript_path": str(transcript)},
        kind="stop",
        journal_dir=journal_dir,
    )


def test_only_the_operator_typed_prompt_is_recorded(jdir: Path, tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path / "s.jsonl",
        [
            _user("You are a headless lane. Do the work.", "a", turn_origin="sdk"),
            _user("Merge-throughput tick", "b", turn_origin="scheduled", meta=True),
            _user(
                "<task-notification>done</task-notification>",
                "c",
                origin="task-notification",
            ),
            _user("This session is being continued", "d", turn_origin="human"),
            _user("Ship the bus consumer and stop the hooks.", "e", origin="human"),
            _reply("On it."),
        ],
    )

    _stop(jdir, transcript)

    records = _operator(jdir)
    assert [r["content"] for r in records] == [
        "Ship the bus consumer and stop the hooks."
    ]
    (record,) = records
    assert record["prompt_id"] == "prompt-e"
    assert record["hook_source"] == "stop"
    assert datetime.fromisoformat(record["said_at"]) <= datetime.now(UTC)
    # The reply is still captured beside it.
    assert [r["content_kind"] for r in _records(jdir)].count("assistant_reply") == 1


def test_a_lane_brief_session_yields_no_operator_prompt(
    jdir: Path, tmp_path: Path
) -> None:
    transcript = _transcript(
        tmp_path / "lane.jsonl",
        [
            _user("Build lane X. Return under 120 words.", "a", turn_origin="sdk"),
            _reply("ok"),
        ],
    )
    _stop(jdir, transcript)
    assert _operator(jdir) == []


def test_each_operator_prompt_is_recorded_once_per_session(
    jdir: Path, tmp_path: Path
) -> None:
    path = tmp_path / "s.jsonl"
    entries = [_user("first ask", "a", origin="human"), _reply("one")]
    _stop(jdir, _transcript(path, entries))
    # A message typed mid-turn never fires UserPromptSubmit; it is in the transcript.
    entries += [_user("and also this", "b", origin="human"), _reply("two")]
    _stop(jdir, _transcript(path, entries))
    _stop(jdir, _transcript(path, entries))

    assert [r["content"] for r in _operator(jdir)] == ["first ask", "and also this"]


def test_the_first_stop_does_not_replay_old_history(jdir: Path, tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path / "s.jsonl",
        [
            _user("said yesterday", "old", origin="human", minutes_ago=24 * 60),
            _user("said just now", "new", origin="human", minutes_ago=2),
            _reply("ok"),
        ],
    )
    _stop(jdir, transcript)
    assert [r["content"] for r in _operator(jdir)] == ["said just now"]


def test_a_subagent_stop_records_no_operator_prompt(jdir: Path, tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path / "s.jsonl",
        [_user("operator words", "a", origin="human"), _reply("ok")],
    )
    capture_mod.capture(
        {"session_id": SESSION, "transcript_path": str(transcript)},
        kind="stop",
        journal_dir=jdir,
        agent_id="agent-1",
    )
    assert _operator(jdir) == []


def test_a_failed_append_records_the_prompt_again_next_stop(
    jdir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _transcript(
        tmp_path / "s.jsonl", [_user("keep this", "a", origin="human"), _reply("ok")]
    )
    real = capture_mod.appender.append_event

    def failing(**kwargs: Any) -> str | None:
        if kwargs["payload"].get("content_kind") == capture_mod.OPERATOR_PROMPT_KIND:
            raise OSError("journal full")
        return real(**kwargs)

    monkeypatch.setattr(capture_mod.appender, "append_event", failing)
    with pytest.raises(OSError):
        _stop(jdir, transcript)
    monkeypatch.setattr(capture_mod.appender, "append_event", real)
    _stop(jdir, transcript)

    assert [r["content"] for r in _operator(jdir)] == ["keep this"]
