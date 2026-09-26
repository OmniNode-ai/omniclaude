# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pin whole-tree CI coverage for staged-scoped pre-commit hooks (OMN-19612)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

from scripts.ci.check_workflow_expression_contexts import check_workflow
from scripts.ci.ci_summary_gate import GATE_JOBS, SOFT_ALLOWLIST, STRICT_SUCCESS_JOBS

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"
JOB_ID = "precommit-suite"
JOB_NAME = "Pre-commit Suite (OMN-19612)"


def _load_yaml(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} did not parse to a mapping"
    return loaded


def _workflow() -> dict:
    return _load_yaml(CI_WORKFLOW)


def _job() -> dict:
    jobs = _workflow()["jobs"]
    assert JOB_ID in jobs, f"ci.yml has no `{JOB_ID}` job"
    return jobs[JOB_ID]


def _staged_scoped_hook_ids() -> set[str]:
    """Derive explicit filename-filtered hooks from the live configuration."""
    config = _load_yaml(PRECOMMIT_CONFIG)
    return {
        str(hook["id"])
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("pass_filenames") is True and bool(hook.get("files"))
    }


def test_every_staged_scoped_hook_has_a_whole_tree_counterpart() -> None:
    staged_scoped = _staged_scoped_hook_ids()
    assert staged_scoped, "expected at least one explicitly staged-scoped hook"

    commands = "\n".join(str(step.get("run", "")) for step in _job()["steps"])
    assert "SKIP=" not in commands
    for hook_id in staged_scoped:
        assert "pre-commit run --all-files" in commands, (
            f"{hook_id} has no whole-tree pre-commit counterpart"
        )


def _run_step() -> dict:
    steps = [
        step
        for step in _job()["steps"]
        if "pre-commit run --all-files" in str(step.get("run", ""))
    ]
    assert len(steps) == 1, "expected exactly one whole-tree pre-commit step"
    return steps[0]


def _locked_dev_dependencies() -> set[str]:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dev = pyproject.get("dependency-groups", {}).get("dev", [])
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    locked = {str(package.get("name")) for package in lock["package"]}
    return {Requirement(req).name for req in dev if isinstance(req, str)} & locked


def test_pre_commit_is_installable_in_the_whole_tree_step() -> None:
    """The run step must be able to spawn pre-commit (the round-3 red).

    Either pre-commit is a locked dev dependency, or the step layers an
    exact-pinned pre-commit over the project venv with ``uv run --with``.
    """
    run = str(_run_step()["run"])
    pinned_tool = re.search(
        r"uv run\b[^\n]*--with\s+['\"]?pre-commit==\d+\.\d+\.\d+", run
    )
    assert pinned_tool or "pre-commit" in _locked_dev_dependencies(), (
        "pre-commit is neither a locked dev dependency nor an exact-pinned "
        "`uv run --with` tool in the whole-tree step: it cannot be spawned"
    )


def test_whole_tree_job_installs_the_dev_group() -> None:
    steps = _job()["steps"]
    install_index = next(
        index
        for index, step in enumerate(steps)
        if "uv sync" in str(step.get("run", ""))
        and "--group dev" in str(step.get("run", ""))
    )
    run_index = next(
        index
        for index, step in enumerate(steps)
        if "pre-commit run --all-files" in str(step.get("run", ""))
    )
    assert install_index < run_index


def test_whole_tree_job_runs_this_pin_itself() -> None:
    test_path = Path(__file__).relative_to(REPO_ROOT).as_posix()
    matching_steps = [
        step for step in _job()["steps"] if test_path in str(step.get("run", ""))
    ]
    assert matching_steps, f"no step runs {test_path}"
    for step in matching_steps:
        assert "if" not in step


def test_whole_tree_job_is_unconditional_and_fail_closed() -> None:
    job = _job()
    assert "if" not in job
    assert "needs" not in job
    assert "continue-on-error" not in job
    for step in job["steps"]:
        assert "if" not in step, f"conditional step: {step.get('name')}"
        assert "continue-on-error" not in step, f"advisory step: {step.get('name')}"


def test_whole_tree_job_is_required_by_ci_summary() -> None:
    assert JOB_NAME in GATE_JOBS
    assert JOB_NAME in STRICT_SUCCESS_JOBS
    assert JOB_NAME not in SOFT_ALLOWLIST


def test_workflow_has_no_pull_request_path_filter() -> None:
    workflow = _workflow()
    triggers = workflow[True] if True in workflow else workflow["on"]
    pull_request = triggers.get("pull_request") or {}
    assert "paths" not in pull_request
    assert "paths-ignore" not in pull_request
    required_types = {"opened", "synchronize", "reopened"}
    assert "types" not in pull_request or required_types <= set(pull_request["types"])


def test_ci_workflow_uses_only_contexts_available_at_each_key() -> None:
    assert check_workflow(CI_WORKFLOW) == []
