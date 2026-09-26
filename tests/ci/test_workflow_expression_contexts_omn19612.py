# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for GitHub Actions expression-context availability (OMN-19612)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.check_workflow_expression_contexts import (
    check_workflow,
    check_workflows,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _write_workflow(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "workflow.yml"
    path.write_text(body, encoding="utf-8")
    return path


def test_real_workflow_tree_has_no_unavailable_contexts() -> None:
    paths = sorted({*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")})
    assert paths
    assert check_workflows(paths) == []


def test_runner_context_in_job_env_is_one_exact_finding(tmp_path: Path) -> None:
    path = _write_workflow(
        tmp_path,
        """\
name: red
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      CACHE_ROOT: ${{ runner.temp }}/cache
    steps:
      - run: echo red
""",
    )

    findings = check_workflow(path)

    assert len(findings) == 1
    assert findings[0].render() == (
        f'{path.as_posix()}: jobs.build.env: context "runner" is not allowed here '
        "(allowed: github, needs, strategy, matrix, vars, secrets, inputs)"
    )


def test_runner_context_at_step_level_is_allowed(tmp_path: Path) -> None:
    path = _write_workflow(
        tmp_path,
        """\
name: green
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - env:
          CACHE_ROOT: ${{ runner.temp }}/cache
        run: echo green
""",
    )

    assert check_workflow(path) == []


def test_secrets_context_in_job_if_is_rejected(tmp_path: Path) -> None:
    path = _write_workflow(
        tmp_path,
        """\
name: red-secrets
on: push
jobs:
  build:
    if: ${{ secrets.RUN_BUILD == 'yes' }}
    runs-on: ubuntu-latest
    steps:
      - run: echo red
""",
    )

    findings = check_workflow(path)

    assert len(findings) == 1
    assert findings[0].context == "secrets"
    assert findings[0].key_path == "jobs.build.if"


def test_undelimited_job_if_is_checked_as_an_expression(tmp_path: Path) -> None:
    path = _write_workflow(
        tmp_path,
        """\
name: red-bare-if
on: push
jobs:
  build:
    if: secrets.RUN_BUILD == 'yes' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - run: echo red
""",
    )

    findings = check_workflow(path)

    assert [(f.key_path, f.context) for f in findings] == [("jobs.build.if", "secrets")]
