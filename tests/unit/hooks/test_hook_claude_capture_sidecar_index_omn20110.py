# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The capture finds a Workflow agent's sidecar without listing every run (OMN-20110).

Before this change every hook event of a subagent listed every Workflow run
directory of its session (``subagents/workflows/*/``), one ``opendir`` each,
inside the 30 s emit budget: 492 directories per call on the operator session
of 2026-10-01, growing for as long as the session lives. The run id is now
remembered the first time the sidecar is found.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_claude_capture as capture_mod  # noqa: E402
import hook_emit_health as health  # noqa: E402
import hook_emit_journal as journal  # noqa: E402

pytestmark = pytest.mark.unit

_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "hooks" / "claude_hook_capture"
_SESSION = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(capture_mod, "lane_grant_pending", lambda: False)


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
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
    return directory


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "projects" / "-fixture"
    (path / _SESSION / "subagents" / "workflows").mkdir(parents=True)
    return path


def _sidecar_body(phase: str | None = "implementation") -> dict[str, Any]:
    body: dict[str, Any] = {
        "agentType": "workflow-subagent",
        "description": "fixture lane",
        "model": "opus",
        "requestNonInteractive": False,
        "requestShape": "foreground",
        "spawnDepth": 1,
    }
    if phase is not None:
        body["workflowPhase"] = phase
    return body


def _write_sidecar(project: Path, agent_id: str, run_id: str | None) -> Path:
    subagents = project / _SESSION / "subagents"
    target = subagents / "workflows" / run_id if run_id else subagents
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"agent-{agent_id}.meta.json"
    path.write_text(json.dumps(_sidecar_body(None if run_id is None else "build")))
    return path


def _stdin(project: Path, agent_id: str) -> dict[str, Any]:
    stdin: dict[str, Any] = json.loads(
        (_FIXTURES / "stdin" / "PostToolUse.json").read_text(encoding="utf-8")
    )
    stdin["session_id"] = _SESSION
    stdin["transcript_path"] = str(project / f"{_SESSION}.jsonl")
    stdin["agent_id"] = agent_id
    stdin["agent_type"] = "workflow-subagent"
    return stdin


def _lineages(journal_dir: Path) -> list[dict[str, Any]]:
    lineages: list[dict[str, Any]] = []
    for entry in journal.list_pending(journal_dir):
        if entry.record.event_type != capture_mod.HOOK_EVENT_TYPE:
            continue
        lineage = dict(entry.record.payload)["lineage"]
        assert isinstance(lineage, dict)
        lineages.append(lineage)
    return lineages


class _GlobCounter:
    """Counts ``Path.glob`` calls under a ``workflows`` directory."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = 0
        original = Path.glob

        def counting(path: Path, pattern: str, *a: Any, **k: Any) -> Iterator[Path]:
            if path.name == "workflows":
                self.calls += 1
            return original(path, pattern, *a, **k)

        monkeypatch.setattr(Path, "glob", counting)


def _many_runs(project: Path, count: int) -> None:
    workflows = project / _SESSION / "subagents" / "workflows"
    for index in range(count):
        (workflows / f"wf_other-{index:03d}").mkdir()


def test_the_run_is_searched_once_then_read_from_the_index(
    project: Path, jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _many_runs(project, 40)
    _write_sidecar(project, "aworkflow01", "wf_target-001")
    globs = _GlobCounter(monkeypatch)

    for _ in range(5):
        assert (
            capture_mod.capture(_stdin(project, "aworkflow01"), journal_dir=jdir) == 1
        )

    assert globs.calls == 1, "only the first hook call of the agent may search"
    lineages = _lineages(jdir)
    assert len(lineages) == 5
    assert {lin["workflow_run_id"] for lin in lineages} == {"wf_target-001"}
    entry = capture_mod.sidecar_index_dir_for(jdir) / _SESSION / "aworkflow01"
    assert entry.read_text(encoding="utf-8") == "wf_target-001"


def test_a_task_agent_never_reaches_the_workflow_runs(
    project: Path, jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _many_runs(project, 10)
    _write_sidecar(project, "ataskagent1", None)
    globs = _GlobCounter(monkeypatch)

    assert capture_mod.capture(_stdin(project, "ataskagent1"), journal_dir=jdir) == 1

    assert globs.calls == 0
    (lineage,) = _lineages(jdir)
    assert lineage["workflow_run_id"] is None
    assert lineage["agent_type"] == "workflow-subagent"


def test_an_index_entry_naming_no_sidecar_falls_back_to_the_search(
    project: Path, jdir: Path
) -> None:
    _write_sidecar(project, "aworkflow02", "wf_real-002")
    entry = capture_mod.sidecar_index_dir_for(jdir) / _SESSION / "aworkflow02"
    entry.parent.mkdir(parents=True)
    entry.write_text("wf_gone-999")

    assert capture_mod.capture(_stdin(project, "aworkflow02"), journal_dir=jdir) == 1

    (lineage,) = _lineages(jdir)
    assert lineage["workflow_run_id"] == "wf_real-002"
    assert entry.read_text(encoding="utf-8") == "wf_real-002"


def test_an_index_entry_cannot_point_outside_the_session(
    project: Path, jdir: Path
) -> None:
    _write_sidecar(project, "aworkflow03", "wf_real-003")
    entry = capture_mod.sidecar_index_dir_for(jdir) / _SESSION / "aworkflow03"
    entry.parent.mkdir(parents=True)
    entry.write_text("../../../elsewhere")

    assert capture_mod.capture(_stdin(project, "aworkflow03"), journal_dir=jdir) == 1

    (lineage,) = _lineages(jdir)
    assert lineage["workflow_run_id"] == "wf_real-003"


def test_a_miss_prunes_session_indexes_untouched_for_a_week(
    project: Path, jdir: Path
) -> None:
    index = capture_mod.sidecar_index_dir_for(jdir)
    stale = index / "stale-session"
    fresh = index / "fresh-session"
    for directory in (stale, fresh):
        directory.mkdir(parents=True)
        (directory / "aagent").write_text("wf_x")
    old = time.time() - capture_mod.SIDECAR_INDEX_STALE_AFTER_S - 60
    os.utime(stale, (old, old))
    _write_sidecar(project, "aworkflow04", "wf_real-004")

    assert capture_mod.capture(_stdin(project, "aworkflow04"), journal_dir=jdir) == 1

    assert not stale.exists()
    assert (fresh / "aagent").is_file()
    assert (index / _SESSION / "aworkflow04").is_file()
