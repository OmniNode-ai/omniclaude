# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Scope tests for ``.github/workflows/ban-hardcoded-runner-ip.yml`` (OMN-17993).

The reusable gate forbids the literal lab runner address. Until OMN-17993 it
scanned ``.github/workflows/**`` only. omnibase_compat — a repository that
ships this very workflow — carried that exact literal as a fixture value under
``tests/``, and the gate reported green over it. Every repository that
inherited the workflow had the same blind spot.

These tests execute the workflow's own shell body against throwaway
repositories, so the assertion is on behaviour rather than on the YAML reading
as though it were right. ``test_pre_omn17993_scope_would_have_missed_it`` is
the positive control: the old scan expression, run against the same fixture,
finds nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ban-hardcoded-runner-ip.yml"

# The banned literal, planted deliberately. This module is a positive-control
# corpus for the gate under test.
BANNED = "192.168.86.201"  # onex-allow-internal-ip  # public-skill-ok: control fixture


def _scan_step_script() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["ban-hardcoded-runner-ip"]["steps"]
    for step in steps:
        if "Reject hardcoded runner IP literals" in step.get("name", ""):
            return step["run"]
    raise AssertionError("scan step not found in ban-hardcoded-runner-ip.yml")


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return repo


def _run_scan(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _scan_step_script()],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "EVENT_NAME": "push"},
        check=False,
    )


@pytest.mark.unit
def test_tests_tree_violation_is_now_rejected(tmp_path: Path) -> None:
    """The omnibase_compat CRITICAL shape: the banned literal as a test fixture.

    RED against the pre-OMN-17993 workflow, which never looked at tests/.
    """
    repo = _make_repo(
        tmp_path,
        {
            ".github/workflows/ci.yml": "name: ci\n",
            "tests/unit/contracts/test_profile.py": f'BROKER = "{BANNED}:19092"\n',
        },
    )
    result = _run_scan(repo)
    assert result.returncode == 1, result.stdout
    assert "tests/unit/contracts/test_profile.py" in result.stdout


@pytest.mark.unit
def test_pre_omn17993_scope_would_have_missed_it(tmp_path: Path) -> None:
    """Positive control: the pre-OMN-17993 scan expression finds nothing in the
    same tree, which is why the literal survived in a repo shipping this gate."""
    repo = _make_repo(
        tmp_path,
        {
            ".github/workflows/ci.yml": "name: ci\n",
            "tests/unit/contracts/test_profile.py": f'BROKER = "{BANNED}:19092"\n',
        },
    )
    old_scan = subprocess.run(
        [
            "bash",
            "-c",
            "find .github/workflows -name '*.yml' -o -name '*.yaml' 2>/dev/null "
            "| xargs grep -l '192\\.168\\.86\\.201' 2>/dev/null || true",  # public-skill-ok: positive-control fixture for the detector under test
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert old_scan.stdout.strip() == ""


@pytest.mark.unit
def test_workflow_file_violation_is_still_rejected(tmp_path: Path) -> None:
    """The original scope is not lost by the widening."""
    repo = _make_repo(
        tmp_path, {".github/workflows/ci.yml": f"    runs-on: [{BANNED}]\n"}
    )
    result = _run_scan(repo)
    assert result.returncode == 1, result.stdout
    assert ".github/workflows/ci.yml" in result.stdout


@pytest.mark.unit
def test_annotated_line_still_passes(tmp_path: Path) -> None:
    """The documented annotation escape is unchanged by the widening."""
    repo = _make_repo(
        tmp_path,
        {
            ".github/workflows/ci.yml": "name: ci\n",
            "tests/unit/test_doc.py": f"# see {BANNED}  # onex-allow-internal-ip\n",
        },
    )
    result = _run_scan(repo)
    assert result.returncode == 0, result.stdout


@pytest.mark.unit
def test_clean_tree_passes(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        {
            ".github/workflows/ci.yml": "name: ci\n",
            "tests/unit/test_ok.py": 'BROKER = "broker.invalid:19092"\n',
        },
    )
    result = _run_scan(repo)
    assert result.returncode == 0, result.stdout


@pytest.mark.unit
def test_pull_request_path_filter_includes_tests() -> None:
    """A widened scanner behind a paths: filter that still excludes tests/
    would never be triggered by the change that introduces the violation."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    paths = doc[True]["pull_request"]["paths"]  # YAML 1.1 parses `on:` as True
    assert "tests/**" in paths
    assert ".github/workflows/**" in paths
