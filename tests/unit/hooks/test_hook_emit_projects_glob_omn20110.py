# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A workflow agent's hook emit never globs every project directory (OMN-20110).

Measured 2026-09-30 on the operator Mac: the PreToolUse capture blocked tool
calls nine times between 12:52 and 12:55Z by missing its 30 s budget. The
single largest phase of a workflow-subagent capture was lane attribution:
``hook_lane_attribution._sidecar_candidates`` fell through to a glob of
``~/.claude/projects/*/<session>/subagents/<agent>.meta.json`` over 1,478
project directories, 0.4 to 0.7 s per call at 24 concurrent captures (the
contract load was 0.37 s), and it ran on every hook event of every workflow
agent. It could never answer: a Workflow agent's sidecar lives under
``<session>/subagents/workflows/<run id>/``, which that pattern does not
match, and a session id names exactly one session directory, which the
transcript path already locates.

The glob is the documented fallback for a payload with NO transcript path.
With a transcript path the answer is unchanged and the glob no longer runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
_HOOKS_LIB = Path(__file__).parents[3] / "plugins/onex/hooks/lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

import hook_lane_attribution as la  # noqa: E402

_SESSION = "11111111-2222-3333-4444-555555555555"
_AGENT = "a0123456789abcdef"


@pytest.fixture(autouse=True)
def _no_declared_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test run inside a dispatched lane inherits its ``ONEX_LANE``."""
    monkeypatch.delenv("ONEX_LANE", raising=False)


def _count_globs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    globbed: list[str] = []
    real_glob = Path.glob

    def counting_glob(self: Path, pattern: str, *a: object, **k: object):  # type: ignore[no-untyped-def]
        globbed.append(pattern)
        return real_glob(self, pattern, *a, **k)

    monkeypatch.setattr(Path, "glob", counting_glob)
    return globbed


def _workflow_layout(projects: Path) -> Path:
    """The live layout of a Workflow agent: its sidecar sits under a run id."""
    run = projects / "proj" / _SESSION / "subagents" / "workflows" / "wf_0001"
    run.mkdir(parents=True)
    (run / f"agent-{_AGENT}.meta.json").write_text(
        json.dumps({"agentType": "workflow"}), encoding="utf-8"
    )
    # Unrelated project directories, as on the operator Mac.
    for i in range(50):
        (projects / f"other-{i}").mkdir()
    return projects / "proj" / f"{_SESSION}.jsonl"


def test_a_workflow_agent_with_a_transcript_path_never_globs_the_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = tmp_path / "projects"
    transcript = _workflow_layout(projects)
    monkeypatch.setenv(la.CLAUDE_PROJECTS_ENV, str(projects))
    globbed = _count_globs(monkeypatch)

    assert la.sidecar_lane_name(str(transcript), _SESSION, _AGENT) == ""

    assert globbed == [], f"projects glob ran on the hook path: {globbed}"


def test_the_answer_with_a_transcript_path_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The glob could not have answered: the workflow sidecar is not on its pattern."""
    projects = tmp_path / "projects"
    transcript = _workflow_layout(projects)
    monkeypatch.setenv(la.CLAUDE_PROJECTS_ENV, str(projects))

    assert list(projects.glob(f"*/{_SESSION}/subagents/agent-{_AGENT}.meta.json")) == []
    assert la.resolve_lane(
        None, transcript_path=str(transcript), session_id=_SESSION, agent_id=_AGENT
    ) == ("", la.LANE_SOURCE_UNRESOLVED, "")


def test_without_a_transcript_path_the_glob_is_still_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = tmp_path / "projects"
    subagents = projects / "proj" / _SESSION / "subagents"
    subagents.mkdir(parents=True)
    (subagents / f"agent-{_AGENT}.meta.json").write_text(
        json.dumps({"name": "lane-x"}), encoding="utf-8"
    )
    monkeypatch.setenv(la.CLAUDE_PROJECTS_ENV, str(projects))
    globbed = _count_globs(monkeypatch)

    assert la.sidecar_lane_name(None, _SESSION, _AGENT) == "lane-x"
    assert len(globbed) == 1
