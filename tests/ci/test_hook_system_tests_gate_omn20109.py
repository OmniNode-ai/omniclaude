# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20109: the hook system suite is a merge gate, not an option.

On 2026-09-29 about 10,000 hung hook processes exhausted the operator Mac's
per-user process limit. The hook tests that existed exercised handlers with the
process boundary mocked away, so nothing ran the real entrypoints under
concurrency, over a broken emit path, or against a cost budget. The suite in
``tests/hooks_system`` does. Detection that is not wired as a gate gets ignored
(rule 5), so these tests pin the wiring: the CI job exists and cannot be skipped,
the umbrella waits for it and accepts nothing but success, and a change to the
hook tree runs it before the commit lands.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.ci_summary_gate import GATE_JOBS, STRICT_SUCCESS_JOBS  # noqa: E402

JOB_ID = "hook-system-tests"
JOB_NAME = "Hook System Tests (OMN-20109)"

pytestmark = pytest.mark.unit


def _job() -> dict[str, object]:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    return workflow["jobs"][JOB_ID]


def test_the_job_exists_under_its_registered_name() -> None:
    assert _job()["name"] == JOB_NAME


def test_the_job_cannot_be_skipped() -> None:
    """No ``needs`` and ``if: always()``: a skipped job renders no check run, which
    the umbrella would read as absent rather than as a refusal."""
    job = _job()
    assert "needs" not in job, "a failed dependency would skip this gate silently"
    assert job.get("if") == "always()"


def test_the_job_runs_the_whole_suite_and_no_less() -> None:
    steps = _job()["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert "pytest tests/hooks_system" in commands
    assert "--deselect" not in commands and "-k " not in commands, (
        "the gate may not run a subset of the suite"
    )


def test_the_job_fails_loudly_when_its_tools_are_missing() -> None:
    """The suite counts real processes with ps and drives the real hooks, which use
    jq. A runner without them must fail the job, not skip tests."""
    steps = _job()["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert "jq" in commands and "ps" in commands and "exit 1" in commands


def test_the_umbrella_waits_for_it_and_accepts_only_success() -> None:
    assert JOB_NAME in GATE_JOBS
    assert JOB_NAME in STRICT_SUCCESS_JOBS


def test_a_hook_tree_change_runs_it_before_the_commit() -> None:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    hooks = {h["id"]: h for repo in config["repos"] for h in repo["hooks"]}
    hook = hooks["hook-system-tests"]
    files = hook["files"]
    for path in (
        "plugins/onex/hooks/scripts/common.sh",
        "plugins/onex/hooks/lib/hook_emit_append.py",
        "tests/hooks_system/test_hook_concurrency.py",
        "scripts/hook_process_canary.py",
    ):
        import re

        assert re.search(files, path), f"{path} does not trigger the hook system suite"
    assert hook["pass_filenames"] is False
    assert "pytest" in hook["entry"] or "hook_system_tests" in hook["entry"]
