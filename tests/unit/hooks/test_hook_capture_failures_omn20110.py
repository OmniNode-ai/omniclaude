# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Real harness sidecars and a capture that never waits for network delivery."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/onex/hooks/lib"))
capture = import_module("hook_claude_capture")
appender = import_module("hook_emit_append")
journal = import_module("hook_emit_journal")

pytestmark = pytest.mark.unit
FIXTURE = (
    ROOT / "tests/fixtures/hooks/claude_hook_capture/sidecars/agent-current.meta.json"
)


def test_captured_current_sidecar_keeps_known_lineage(tmp_path: Path) -> None:
    """Captured from the current harness: description and both origin fields are absent."""
    contract = capture.load_contract()
    assert contract is not None
    raw = json.loads(FIXTURE.read_text())
    sidecar = contract.ModelSubagentSidecar.model_validate(raw)
    assert sidecar.agent_type == raw["agentType"]
    assert sidecar.model == raw["model"]
    assert sidecar.spawn_depth == raw["spawnDepth"]
    assert sidecar.description is None
    assert sidecar.tool_use_id is None
    assert sidecar.workflow_run_id is None
    subagents = tmp_path / "session" / "subagents"
    subagents.mkdir(parents=True)
    # The run id is caller-owned path metadata, never a sidecar claim.
    (subagents / "agent-current.meta.json").write_text(
        json.dumps(raw | {"workflow_run_id": "untrusted-sidecar-claim"})
    )
    found = capture.read_sidecar(
        contract,
        transcript_path=str(tmp_path / "session.jsonl"),
        session_id="session",
        agent_id="current",
    )
    assert found == sidecar
    event = capture.build_event_payload(
        {
            "hook_event_name": "SubagentStart",
            "session_id": "session",
            "transcript_path": str(tmp_path / "session.jsonl"),
            "agent_id": "current",
            "agent_type": raw["agentType"],
        },
        contract=contract,
        turn_dir=tmp_path / "turns",
        emitted_at=datetime.now(UTC),
        version="2.1.302",
    )
    assert event["lineage"]["agent_model"] == raw["model"]
    assert event["lineage"]["spawn_depth"] == raw["spawnDepth"]
    assert event["lineage"]["parent_tool_use_id"] is None
    assert event["lineage"]["workflow_run_id"] is None


def test_invalid_sidecar_logs_field_and_reason_without_private_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = capture.load_contract()
    subagents = tmp_path / "session" / "subagents"
    subagents.mkdir(parents=True)
    raw = json.loads(FIXTURE.read_text())
    raw["spawnDepth"] = "private-invalid-value"
    (subagents / "agent-invalid.meta.json").write_text(json.dumps(raw))
    assert (
        capture.read_sidecar(
            contract,
            transcript_path=str(tmp_path / "session.jsonl"),
            session_id="session",
            agent_id="invalid",
        )
        is None
    )
    error = capsys.readouterr().err
    assert "spawnDepth" in error and "int_parsing" in error
    assert "private-invalid-value" not in error


def test_append_journals_before_any_bus_emit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> bool:
        pytest.fail("the foreground hook attempted a bus emit")

    monkeypatch.setattr(
        appender, "_landed_on_local_bus", network_forbidden, raising=False
    )
    jdir = tmp_path / "journal"
    appender.append_event(
        event_type="hook.event",
        payload={"session_id": "session"},
        correlation_id="session",
        cwd=None,
        actor="claude",
        host_turn_id="turn",
        agent_id=None,
        transcript_path=None,
        session_id="session",
        journal_dir=str(jdir),
    )
    pending = journal.list_pending(jdir)
    assert len(pending) == 1
    assert pending[0].record.event_type == "hook.event"


@pytest.mark.parametrize(
    "fields",
    [
        {
            "description": "label",
            "toolUseId": "tool",
            "workflowPhase": "build",
            "workflow_run_id": "wf",
        },
        {"description": "label", "workflowPhase": "build"},
        {"description": "label", "toolUseId": "tool", "workflow_run_id": "wf"},
    ],
)
def test_conflicting_sidecar_origins_still_fail(fields: dict[str, object]) -> None:
    raw = json.loads(FIXTURE.read_text()) | fields
    with pytest.raises(ValueError):
        capture.load_contract().ModelSubagentSidecar.model_validate(raw)


def test_stop_wrapper_retains_event_until_drainer_confirms_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hook_lane_overlay: dict[str, str]
) -> None:
    import io
    from typing import cast

    import hook_emit_drainer as drainer
    import hook_emit_health as health

    jdir = tmp_path / "state" / "hook_emit_journal"
    health.write_status(
        jdir.parent / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("hook.event",),
        ),
    )
    stdin = {
        "hook_event_name": "Stop",
        "session_id": "session",
        "last_assistant_message": "reply",
        "stop_hook_active": True,
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin)))
    assert capture.main(["--journal-dir", str(jdir)]) == 0
    (original,) = journal.list_pending(jdir)

    class Emitter:
        delivered = False

        def publish(self, record: journal.JournalRecord) -> bool:
            assert record.event_id == original.record.event_id
            assert record.payload["hook_event_name"] == "Stop"
            return self.delivered

    emitter = Emitter()
    assert drainer.drain_once(jdir, cast("drainer._Emitter", emitter)) == (0, 1, 0)
    assert journal.list_pending(jdir)[0].record.event_id == original.record.event_id
    emitter.delivered = True
    assert drainer.drain_once(jdir, cast("drainer._Emitter", emitter)) == (1, 0, 0)
    assert journal.list_pending(jdir) == []


@pytest.mark.parametrize("write_fails", [False, True])
def test_real_stop_hook_is_silent_on_success_and_logs_append_failure(
    tmp_path: Path, hook_lane_overlay: dict[str, str], write_fails: bool
) -> None:
    import os
    import subprocess

    import hook_emit_health as health

    state = tmp_path / "state"
    state.mkdir()
    health.write_status(
        state / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("hook.event",),
        ),
    )
    jdir = state / "hook_emit_journal"
    if write_fails:
        jdir.write_text("a file blocks the journal directory")
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ | {
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(ROOT / "plugins/onex"),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "OMNICLAUDE_MODE": "full",
        "PLUGIN_PYTHON_BIN": sys.executable,
        "ONEX_STATE_DIR": str(state),
        "ONEX_HOOK_EMIT_JOURNAL_DIR": str(jdir),
        "ONEX_SESSION_INTENT": "normal",
        "ONEX_HOOK_EMIT_BUDGET_S": "5",
        "ONEX_EMIT_ALARM_CMD": "/usr/bin/true",
        "ONEX_EMIT_EPISODE_MARKER": str(tmp_path / "episode"),
    }
    stdin = {
        "hook_event_name": "Stop",
        "session_id": "session",
        "last_assistant_message": "reply",
        "stop_hook_active": True,
    }
    proc = subprocess.run(
        ["bash", str(ROOT / "plugins/onex/hooks/scripts/claude_hook_capture.sh")],
        input=json.dumps(stdin),
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    log = (state / "hooks/logs/hook-claude-hook-capture.log").read_text()
    assert proc.stdout == ""
    if write_fails:
        assert proc.returncode == 1
        assert "NOT journalled" in log and "BLOCKED:" in log
        assert "BLOCKED:" in proc.stderr
    else:
        assert proc.returncode == 0, proc.stderr
        assert proc.stderr == ""
        assert "journalled hook.event Stop" in log
        assert len(journal.list_pending(jdir)) == 1


def test_future_sidecar_keys_are_ignored_as_before() -> None:
    contract = capture.load_contract()
    raw = json.loads(FIXTURE.read_text())
    expected = contract.ModelSubagentSidecar.model_validate(raw)
    raw["futureHarnessField"] = "private-future-value"
    assert contract.ModelSubagentSidecar.model_validate(raw) == expected
    assert "futureHarnessField" not in expected.model_dump()
