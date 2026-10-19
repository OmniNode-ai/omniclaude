# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-19854: required CI runs the caller-floor check already used by the hook."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_FLOOR_TEST = "tests/ci/test_repo_evidence_caller_verifier_floor_omn17427.py"


def test_required_ci_job_runs_the_caller_floor_check() -> None:
    workflow = yaml.safe_load(
        (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["refusal-surface"]
    assert "if" not in job
    assert job.get("continue-on-error", False) is False
    commands = [
        step for step in job["steps"] if _FLOOR_TEST in str(step.get("run", ""))
    ]
    assert len(commands) == 1, "required CI must run the caller-floor test once"
    step = commands[0]
    assert "if" not in step
    assert step.get("continue-on-error", False) is False
    assert shlex.split(step["run"]) == [
        "uv",
        "run",
        "pytest",
        _FLOOR_TEST,
        "-q",
        "-p",
        "no:randomly",
        "--no-cov",
    ]
