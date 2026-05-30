# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behavioral tests for the main-target-guard workflow (OMN-12477).

OMN-12477 removed the ``hotfix/*`` bypass so that ``main`` accepts promotion
PRs only (head ref ``dev``/``promotion/*`` with a ``promotion-receipt: OCC-N``
line). These tests extract the guard's inline shell script and execute it
against synthetic PR contexts to prove:

* a ``dev`` PR with a promotion receipt is still ALLOWED, and
* a ``hotfix/*`` PR to main is now REJECTED (the bypass is gone).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GUARD_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "main-target-guard.yml"


def _load_workflow(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _guard_script() -> str:
    workflow = _load_workflow(GUARD_WORKFLOW_PATH)
    jobs = workflow["jobs"]
    steps = jobs["main-target-guard"]["steps"]
    step = next(s for s in steps if s.get("name") == "Check PR target branch")
    run = step["run"]
    assert isinstance(run, str)
    return run


def _run_guard(
    *, base_ref: str, head_ref: str, pr_body: str
) -> subprocess.CompletedProcess[str]:
    """Run the guard's shell logic with synthetic GitHub Actions env vars."""
    return subprocess.run(
        ["bash", "-c", _guard_script()],
        env={
            "BASE_REF": base_ref,
            "HEAD_REF": head_ref,
            "PR_BODY": pr_body,
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_dev_promotion_with_receipt_is_allowed() -> None:
    result = _run_guard(
        base_ref="main",
        head_ref="dev",
        pr_body="promotion-receipt: OCC-12477",
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_hotfix_pr_to_main_is_rejected() -> None:
    # Even a fully-formed legacy hotfix body (evidence + backmerge) must now fail:
    # the hotfix/* bypass was removed in OMN-12477.
    result = _run_guard(
        base_ref="main",
        head_ref="hotfix/urgent-fix",
        pr_body="hotfix-evidence: OCC-9999\nbackmerge: #1234",
    )
    assert result.returncode == 1, result.stderr + result.stdout


def test_dev_without_receipt_is_rejected() -> None:
    result = _run_guard(
        base_ref="main",
        head_ref="dev",
        pr_body="no receipt here",
    )
    assert result.returncode == 1, result.stderr + result.stdout


def test_non_main_target_is_ignored() -> None:
    result = _run_guard(
        base_ref="dev",
        head_ref="feature/whatever",
        pr_body="",
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_guard_yaml_has_no_hotfix_branch_logic() -> None:
    script = _guard_script()
    assert "hotfix/*" not in script
    assert "hotfix-evidence" not in script
    assert "backmerge" not in script
