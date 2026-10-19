# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19854: the verifier-floor check also runs from a required CI step, and the caller enforces.

Ruling 2026-10-10T11:04:11Z: the hosted `repo-evidence / dod-verify` context must refuse a
contract whose acceptance criteria are only partly bound. The floor itself, and the pre-commit hook
`call-repo-evidence-gate-verifier-floor` that holds it, are pinned by
`test_repo_evidence_caller_verifier_floor_omn17427.py`. This file pins the two things that module
leaves open: the caller refuses instead of reporting (`shadow: "false"`, repo-owned evidence), and a
`ci.yml` step runs the same module as the hook, so a local and a CI verdict cannot disagree.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CALLER_PATH = REPO_ROOT / ".github" / "workflows" / "call-repo-evidence-gate.yml"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
HOOK_ID = "call-repo-evidence-gate-verifier-floor"
FLOOR_TEST = "tests/ci/test_repo_evidence_caller_verifier_floor_omn17427.py"


def _job(path: Path = CALLER_PATH) -> dict[str, Any]:
    caller = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = caller["jobs"]
    assert "repo-evidence" in jobs, "the caller must declare a repo-evidence job"
    job: dict[str, Any] = jobs["repo-evidence"]
    return job


def _enforcement_refusals(job: dict[str, Any]) -> list[str]:
    """Name every way the caller job stops refusing; empty means it enforces."""
    refusals: list[str] = []
    with_inputs = job.get("with", {})
    if with_inputs.get("shadow") != "false":
        refusals.append(
            "shadow must be 'false': a shadow run reports the verdict without refusing"
        )
    if with_inputs.get("evidence-source") != "caller":
        refusals.append("evidence-source must be 'caller'")
    return refusals


def _hook_module() -> str:
    config = yaml.safe_load(PRECOMMIT_CONFIG.read_text(encoding="utf-8"))
    hooks = [
        hook
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == HOOK_ID
    ]
    assert len(hooks) == 1, f"exactly one pre-commit hook must be declared as {HOOK_ID}"
    modules = [t for t in shlex.split(hooks[0]["entry"]) if t.endswith(".py")]
    assert len(modules) == 1, f"{HOOK_ID} must run exactly one test module"
    return modules[0]


def _ci_run_commands() -> list[str]:
    jobs = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return [
        str(step.get("run", ""))
        for job in jobs.values()
        for step in job.get("steps", [])
    ]


def test_caller_enforces_repo_owned_evidence_not_a_shadow_run() -> None:
    assert _enforcement_refusals(_job()) == []


def test_a_shadow_caller_is_caught(tmp_path: Path) -> None:
    """Negative control: a caller copy that only reports is refused by the same check."""
    text = CALLER_PATH.read_text(encoding="utf-8")
    planted = text.replace('shadow: "false"', 'shadow: "true"')
    assert planted != text
    copy = tmp_path / "call-repo-evidence-gate.yml"
    copy.write_text(planted, encoding="utf-8")
    refusals = _enforcement_refusals(_job(copy))
    assert len(refusals) == 1
    assert "shadow must be 'false'" in refusals[0]


def test_the_required_ci_job_runs_the_module_the_hook_runs() -> None:
    """The hook and the CI step run one module, so a local and a CI verdict cannot disagree."""
    module = _hook_module()
    assert module == FLOOR_TEST, f"{HOOK_ID} must run {FLOOR_TEST}, runs {module}"
    assert any(module in command for command in _ci_run_commands()), (
        f"a ci.yml step must run {module}"
    )


def test_the_ci_step_check_has_a_refusing_case() -> None:
    """Negative control: a module no ci.yml step runs is not found by the same lookup."""
    absent = "tests/ci/test_no_such_floor_module.py"
    assert not any(absent in command for command in _ci_run_commands())
