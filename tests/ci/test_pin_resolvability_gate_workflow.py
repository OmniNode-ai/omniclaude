# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The pre-merge PyPI pin-resolvability gate is wired, and wired to the release's own check (OMN-19655).

The release workflow refuses to publish a wheel whose declared dependencies do
not co-resolve from the published index, but it runs after the merge. Twice
(omnimarket#2819 on 2026-09-24, omnimarket#2896 on 2026-09-25) a floor raise no
published sibling could satisfy merged green and then failed every release.

These tests hold the pre-merge twin to four properties, each of which a
plausible edit would silently break:

* it is minted on every pull request (no ``paths:`` filter, no job-level
  ``if:``), so it can be made required without wedging unrelated pull requests;
* it judges whenever ``pyproject.toml`` or ``uv.lock`` changes, and nightly;
* it builds the wheel before judging it;
* it runs the very script the release workflow runs, so the two verdicts are
  one implementation and cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_GATE = _WORKFLOWS / "pin-resolvability-gate.yml"
_SCRIPT = "scripts/ci/verify_pypi_pin_resolvability.py"
_RELEASE_WORKFLOWS = ("release.yml", "release-on-merge.yml")


def _load(path: Path) -> dict[Any, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} is not a mapping"
    return loaded


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    raw = workflow.get("on", workflow.get(True))
    assert isinstance(raw, dict), "the gate declares its triggers as a mapping"
    return raw


def _steps() -> list[dict[str, Any]]:
    jobs = _load(_GATE)["jobs"]
    assert len(jobs) == 1, "one job, one context"
    (job,) = jobs.values()
    assert "if" not in job, "a job-level if: leaves the context unminted"
    steps = job["steps"]
    assert isinstance(steps, list)
    return steps


@pytest.mark.unit
def test_gate_is_minted_on_every_pull_request_and_runs_nightly() -> None:
    triggers = _triggers(_load(_GATE))
    assert "pull_request" in triggers
    pull_request = triggers["pull_request"] or {}
    assert "paths" not in pull_request, "a paths filter makes a required context vanish"
    assert "branches" not in pull_request
    assert triggers.get("schedule"), "nightly: the index moves"
    assert "workflow_dispatch" in triggers


@pytest.mark.unit
def test_gate_judges_every_change_to_the_declared_dependencies() -> None:
    scope = next(s for s in _steps() if s.get("id") == "scope")
    body = scope["run"]
    pattern = re.search(r"grep -Eq \\\s*'([^']+)'", body)
    assert pattern is not None, "the scope step names its paths in one regex"
    regex = re.compile(pattern.group(1))
    for path in (
        "pyproject.toml",
        "uv.lock",
        _SCRIPT,
        ".github/workflows/pin-resolvability-gate.yml",
    ):
        assert regex.search(path), f"a change to {path} must be judged"
    for path in ("src/pkg/module.py", "README.md", "docs/pyproject.toml.md"):
        assert not regex.search(path), f"{path} cannot change what resolves"
    assert "HEAD^1 HEAD" in body, "the change is measured against the base tip"


@pytest.mark.unit
def test_gate_builds_the_wheel_then_runs_the_release_script() -> None:
    runs = [str(s.get("run", "")) for s in _steps()]
    build = next(i for i, r in enumerate(runs) if "uv build --wheel" in r)
    verify = next(i for i, r in enumerate(runs) if _SCRIPT in r)
    assert build < verify, "the wheel must exist before it is judged"
    judged = [s for s in _steps() if _SCRIPT in str(s.get("run", ""))]
    assert all(s.get("if") == "steps.scope.outputs.applies == 'true'" for s in judged)


def _publishes(step: dict[str, Any]) -> bool:
    run = str(step.get("run", ""))
    uses = str(step.get("uses", ""))
    return (
        "uv publish" in run
        or "publish_with_retry" in run
        or "gh-action-pypi-publish" in uses
    )


@pytest.mark.unit
def test_gate_and_release_run_one_implementation() -> None:
    assert (_REPO_ROOT / _SCRIPT).is_file(), "the release's check is vendored here"
    releases = [p for p in (_WORKFLOWS / n for n in _RELEASE_WORKFLOWS) if p.is_file()]
    assert releases, "a publishing repo has a release workflow"
    for release in releases:
        publishing_jobs = [
            job["steps"]
            for job in _load(release)["jobs"].values()
            if any(_publishes(step) for step in job.get("steps", []))
        ]
        assert publishing_jobs, f"{release.name} has a publishing job"
        for steps in publishing_jobs:
            runs = [str(step.get("run", "")) for step in steps]
            verify = [i for i, run in enumerate(runs) if f"python3 {_SCRIPT}" in run]
            publish = [i for i, step in enumerate(steps) if _publishes(step)]
            assert verify, f"{release.name} must run the same check before publishing"
            assert verify[0] < publish[0], (
                f"{release.name} must judge resolvability before it publishes"
            )
