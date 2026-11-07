# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22946: a fresh pull request event starts no reviewer job on a lab runner.

Rebuild plan section 8, R3 (RULING 2026-11-05T20:27:56Z): the reviewer triggers
were removed instead of moved, so no reviewer job reaches a lab runner when a
head updates. This check keeps it that way. For every event that a pull request
raises, it reads the repository's workflow files and lists each job that

  * belongs to a reviewer workflow (its file, workflow name, job id or job name
    says so),
  * would start on that event for a pull request into a real landing branch
    (the trigger names the event, its branch filter reaches the branch, the job
    ``if`` is not the literal false), and
  * runs on a runner that is not provably GitHub-hosted.

The two cases that matter are named: ``fresh_event_no_lab_job`` reads the live
workflow files, ``planted_trigger`` plants a reviewer trigger into a copy of the
repository's own reviewer workflow and into a minimal one, and requires the
scan to name it.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"

# Events a pull request raises, directly or through a follow-on workflow.
PULL_REQUEST_EVENTS = (
    "pull_request",
    "pull_request_target",
    "pull_request_review",
    "pull_request_review_comment",
    "issue_comment",
    "workflow_run",
    "merge_group",
)
# Events whose branch filter names the pull request's base branch.
BASE_FILTERED_EVENTS = frozenset({"pull_request", "pull_request_target", "merge_group"})
LANDING_BRANCHES = ("dev", "main")
REVIEWER_NAME = re.compile(r"review", re.IGNORECASE)
HOSTED_LABEL = re.compile(r"^(ubuntu|macos|windows)-(latest|[0-9]+(\.[0-9]+)*)(-arm)?$")
REVIEWER_WORKFLOW = "hostile-reviewer.yml"


@dataclass(frozen=True)
class LabJob:
    workflow: str
    job: str
    event: str
    branch: str
    runs_on: str


def _triggers(data: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key ``on`` as the boolean True.
    raw = data.get("on", data.get(True))
    if raw is None:
        return {}
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return {str(item): None for item in raw}
    return {str(key): value for key, value in raw.items()}


def _branch_reached(spec: Any, branch: str) -> bool:
    if not isinstance(spec, dict):
        return True
    names = spec.get("branches")
    ignored = spec.get("branches-ignore")
    if names is not None and not any(fnmatch.fnmatchcase(branch, p) for p in names):
        return False
    return not (
        ignored is not None and any(fnmatch.fnmatchcase(branch, p) for p in ignored)
    )


def _never_runs(condition: Any) -> bool:
    if condition is False:
        return True
    text = re.sub(r"^\$\{\{|\}\}$", "", str(condition).strip()).strip()
    return text.lower() == "false"


def _runs_on_hosted(runs_on: Any) -> bool:
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    return all(
        isinstance(label, str) and HOSTED_LABEL.match(label) is not None
        for label in labels
    )


def _is_reviewer(
    stem: str, data: dict[Any, Any], job_id: str, job: dict[Any, Any]
) -> bool:
    names = (stem, str(data.get("name", "")), job_id, str(job.get("name", "")))
    return any(REVIEWER_NAME.search(name) for name in names)


def lab_reviewer_jobs(workflows: Path, event: str, branch: str) -> list[LabJob]:
    """Reviewer jobs that start on ``event`` for a pull request into ``branch``
    and do not run on a provably hosted runner."""
    found: list[LabJob] = []
    for path in sorted(workflows.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            continue
        triggers = _triggers(data)
        if event not in triggers:
            continue
        if event in BASE_FILTERED_EVENTS and not _branch_reached(
            triggers[event], branch
        ):
            continue
        for job_id, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict) or not _is_reviewer(
                path.stem, data, str(job_id), job
            ):
                continue
            if "if" in job and _never_runs(job["if"]):
                continue
            runs_on = job.get("runs-on")
            if _runs_on_hosted(runs_on):
                continue
            found.append(LabJob(path.name, str(job_id), event, branch, str(runs_on)))
    return found


def _plant(source: Path, target: Path) -> None:
    """Copy ``source`` into ``target`` with a pull_request trigger on every branch."""
    data = yaml.safe_load(source.read_text())
    data.pop("on", None)
    data.pop(True, None)
    data["on"] = {"pull_request": {"types": ["opened", "synchronize"]}}
    target.write_text(yaml.safe_dump(data, sort_keys=False))


@pytest.mark.parametrize("branch", LANDING_BRANCHES)
@pytest.mark.parametrize("event", PULL_REQUEST_EVENTS)
def test_fresh_event_no_lab_job(event: str, branch: str) -> None:
    assert WORKFLOWS.is_dir(), WORKFLOWS
    assert lab_reviewer_jobs(WORKFLOWS, event, branch) == []


def test_fresh_event_no_lab_job_reads_reviewer_workflows() -> None:
    """Positive control: the scan sees this repository's reviewer workflow."""
    stems = {p.name for p in WORKFLOWS.glob("*.y*ml")}
    assert REVIEWER_WORKFLOW in stems
    data = yaml.safe_load((WORKFLOWS / REVIEWER_WORKFLOW).read_text())
    assert any(
        _is_reviewer(Path(REVIEWER_WORKFLOW).stem, data, str(job_id), job)
        for job_id, job in data["jobs"].items()
    )


def test_planted_trigger_on_the_repository_reviewer_fails(tmp_path: Path) -> None:
    _plant(WORKFLOWS / REVIEWER_WORKFLOW, tmp_path / REVIEWER_WORKFLOW)
    for branch in LANDING_BRANCHES:
        planted = lab_reviewer_jobs(tmp_path, "pull_request", branch)
        assert planted, f"a planted pull_request trigger on {branch} was not named"
        assert {job.workflow for job in planted} == {REVIEWER_WORKFLOW}


@pytest.mark.parametrize("event", PULL_REQUEST_EVENTS)
def test_planted_trigger_on_every_event_fails(tmp_path: Path, event: str) -> None:
    (tmp_path / "planted-reviewer.yml").write_text(
        yaml.safe_dump(
            {
                "name": "Planted Reviewer",
                "on": {event: None},
                "jobs": {
                    "review": {
                        "runs-on": ["self-hosted", "omnibase-ci"],
                        "steps": [{"run": "true"}],
                    }
                },
            },
            sort_keys=False,
        )
    )
    assert lab_reviewer_jobs(tmp_path, event, "dev")


def test_planted_trigger_controls_are_not_flagged(tmp_path: Path) -> None:
    """Negative controls: a hosted runner, a dead job and a branch no pull request targets."""
    base = {"name": "Planted Reviewer", "on": {"pull_request": None}}
    cases = {
        "hosted.yml": {
            **base,
            "jobs": {"review": {"runs-on": "ubuntu-latest", "steps": []}},
        },
        "dead.yml": {
            **base,
            "jobs": {
                "review": {
                    "if": "${{ false }}",
                    "runs-on": ["self-hosted"],
                    "steps": [],
                }
            },
        },
        "other-branch.yml": {
            "name": "Planted Reviewer",
            "on": {"pull_request": {"branches": ["review-stopped"]}},
            "jobs": {"review": {"runs-on": ["self-hosted"], "steps": []}},
        },
    }
    for name, workflow in cases.items():
        (tmp_path / name).write_text(yaml.safe_dump(workflow, sort_keys=False))
    for branch in LANDING_BRANCHES:
        assert lab_reviewer_jobs(tmp_path, "pull_request", branch) == []
