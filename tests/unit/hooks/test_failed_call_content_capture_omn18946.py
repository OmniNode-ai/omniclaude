# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A failed tool call's content reaches session_content (OMN-18946).

Content was stored for completed calls only: ``--kind tool`` runs from the
PostToolUse mirror, and a call that fails fires PostToolUseFailure, which no
content capture listened to. Measured on the lab: 0 of 7,544 failed Bash calls
carried command or error text. These tests hold the failure path to the same
redaction as the completed one.

Every planted value is built by concatenation and holds ``FAKE``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

import hook_claude_capture as claude_capture
import hook_content_capture as capture_mod
import hook_emit_health as health
import hook_emit_journal as journal

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

SESSION = "0f0f0f0f-1111-2222-3333-444444444444"
GITHUB_FAKE = "gh" + "p_" + "FAKE" + "a1b2" * 9
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "hooks" / "claude_hook_capture"


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
            publishable_event_types=("content.captured", "hook.event"),
        ),
    )
    return directory


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.delenv(claude_capture.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(claude_capture, "lane_grant_pending", lambda: False)


def _records(journal_dir: Path) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == "content.captured"
    ]


def _failure_stdin(**over: Any) -> dict[str, Any]:
    stdin: dict[str, Any] = json.loads(
        (_FIXTURES / "stdin" / "PostToolUseFailure.json").read_text(encoding="utf-8")
    )
    stdin.update(over)
    return stdin


def test_a_failed_call_stores_its_input_and_error_text(jdir: Path) -> None:
    written = capture_mod.capture(
        _failure_stdin(
            session_id=SESSION,
            tool_use_id="toolu_fail_1",
            tool_input={"command": "git push origin dev"},
            error="Exit code 1\nremote: permission denied",
        ),
        kind="tool_failure",
        journal_dir=jdir,
    )

    assert written == 2
    by_kind = {r["content_kind"]: r for r in _records(jdir)}
    assert set(by_kind) == {"tool_input", "tool_error"}
    assert "git push origin dev" in by_kind["tool_input"]["content"]
    assert by_kind["tool_error"]["content"] == "Exit code 1\nremote: permission denied"
    for record in by_kind.values():
        assert record["tool_use_id"] == "toolu_fail_1"
        assert record["tool_name"] == "Bash"
        assert record["session_id"] == SESSION
        assert record["hook_source"] == "post_tool_use_failure"
        assert record["command"] == "git push origin dev"


def test_a_failed_call_is_captured_raw_like_a_completed_one(jdir: Path) -> None:
    """OMN-19513: no producer redaction on a failed call either."""
    capture_mod.capture(
        _failure_stdin(
            session_id=SESSION,
            tool_input={"command": f"curl -H 'Authorization: token {GITHUB_FAKE}' x"},
            error=f"Exit code 22\nrejected token {GITHUB_FAKE}",
        ),
        kind="tool_failure",
        journal_dir=jdir,
    )

    records = _records(jdir)
    assert len(records) == 2
    by_kind = {r["content_kind"]: r for r in records}
    assert GITHUB_FAKE in by_kind["tool_input"]["content"]
    assert (
        by_kind["tool_error"]["content"]
        == f"Exit code 22\nrejected token {GITHUB_FAKE}"
    )
    assert not any("producer_redaction" in r for r in records)


def test_a_failed_call_without_an_error_text_stores_the_input_only(
    jdir: Path,
) -> None:
    stdin = _failure_stdin(session_id=SESSION)
    del stdin["error"]

    written = capture_mod.capture(stdin, kind="tool_failure", journal_dir=jdir)

    assert written == 1
    assert {r["content_kind"] for r in _records(jdir)} == {"tool_input"}


def test_the_failure_hook_runs_the_content_capture_beside_the_metadata_one(
    jdir: Path,
) -> None:
    """PostToolUseFailure is already registered for claude_hook_capture.sh."""
    stdin = _failure_stdin(
        session_id=SESSION,
        tool_use_id="toolu_fail_2",
        tool_input={"command": "false"},
        error="Exit code 1",
    )

    claude_capture.capture_failure_content(stdin, journal_dir=jdir)

    assert {r["content_kind"] for r in _records(jdir)} == {"tool_input", "tool_error"}


def test_only_a_failure_hook_triggers_the_failure_content_capture(
    jdir: Path,
) -> None:
    stdin = _failure_stdin(session_id=SESSION)
    stdin["hook_event_name"] = "PostToolUse"

    assert claude_capture.capture_failure_content(stdin, journal_dir=jdir) == 0
    assert _records(jdir) == []


def test_the_opt_out_switch_stops_the_failure_content_capture(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(capture_mod.OPT_OUT_ENV, "off")

    assert (
        claude_capture.capture_failure_content(
            _failure_stdin(session_id=SESSION), journal_dir=jdir
        )
        == 0
    )
    assert _records(jdir) == []
