# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the CI-side detect-secrets target-branch diff (OMN-15072).

RED-first proof for the finding: the `detect-secrets` CI job in `ci.yml`
diffed the PR's regenerated `.secrets.baseline` against a `.bak` copy taken
from the SAME checked-out commit, so a secret arriving in the same commit as
its own baseline-laundering entry produced a zero-delta, passing scan. These
tests exercise `scripts/detect_secrets_ci_diff.py` against a real temp git
repo with an actual `target` ref/branch, so the `git show <ref>:.secrets.baseline`
comparison is real -- proving the fixed logic diffs against a ref the PR
branch cannot rewrite in its own commit, unlike the old same-commit `.bak`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_SCRIPT = _SCRIPTS_DIR / "detect_secrets_ci_diff.py"


def _load_module():
    # scripts/detect_secrets_ci_diff.py does `from detect_secrets_guard import
    # ...`, so scripts/ must be importable for that to resolve.
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("detect_secrets_ci_diff", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


def _init_repo_with_target_branch(tmp_path: Path, target_baseline: dict | None) -> Path:
    """Create a repo with a `target` branch holding `target_baseline` (or no
    baseline at all if None), then check out a `pr` branch off it so the
    working tree's `.secrets.baseline` can be freely rewritten to simulate
    the PR's regenerated baseline without touching `target`."""
    repo = tmp_path
    _run_git(["init", "-q"], repo)
    _run_git(["config", "user.email", "test@test.local"], repo)
    _run_git(["config", "user.name", "Test"], repo)

    if target_baseline is not None:
        (repo / ".secrets.baseline").write_text(json.dumps(target_baseline, indent=2))
        _run_git(["add", ".secrets.baseline"], repo)
    else:
        (repo / "README.md").write_text("no baseline on target\n")
        _run_git(["add", "README.md"], repo)
    _run_git(["commit", "-q", "-m", "target state"], repo)
    _run_git(["branch", "target"], repo)
    _run_git(["checkout", "-q", "-b", "pr"], repo)
    return repo


def _finding(hashed_secret: str, line: int, is_secret: bool | None = None) -> dict:
    entry: dict[str, Any] = {
        "type": "AWS Access Key",
        "hashed_secret": hashed_secret,
        "is_verified": False,
        "line_number": line,
    }
    if is_secret is not None:
        entry["is_secret"] = is_secret
    return entry


def _write_pr_baseline(repo: Path, baseline: dict) -> None:
    (repo / ".secrets.baseline").write_text(json.dumps(baseline, indent=2))


@pytest.fixture
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# RED: a secret + its own unaudited baseline entry arriving in the SAME
# commit (i.e. absent from the target branch) is caught by --target-ref,
# proving this closes the old same-commit-.bak blind spot.
# ---------------------------------------------------------------------------


def test_new_unaudited_finding_not_on_target_blocks(mod, tmp_path, monkeypatch):
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)
    _write_pr_baseline(
        repo,
        {"results": {"app/leaked_aws.py": [_finding("deadbeef" * 5, line=3)]}},
    )

    exit_code = mod.main(["--target-ref", "target"])

    assert exit_code == 1


def test_same_commit_self_diff_would_have_missed_it(mod, tmp_path, monkeypatch):
    """Negative control: reproduces the OLD job's same-commit `.bak` compare
    (fallback mode against a snapshot taken from the SAME working tree state
    as the PR baseline) to prove that comparison alone is blind to a secret
    laundered into the baseline before the snapshot is even taken."""
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)

    laundered = {"results": {"app/leaked_aws.py": [_finding("deadbeef" * 5, line=3)]}}
    # Old job order: cp .secrets.baseline .secrets.baseline.bak BEFORE the
    # secret+laundered-entry commit is scanned -- but the laundering already
    # happened upstream of CI (the vulnerable pre-commit hook), so both the
    # working baseline and the "backup" already contain the same entry.
    _write_pr_baseline(repo, laundered)
    (repo / ".secrets.baseline.bak").write_text(json.dumps(laundered, indent=2))

    exit_code = mod.main(["--fallback-baseline", ".secrets.baseline.bak"])

    assert exit_code == 0  # confirms the old same-commit shape is blind


# ---------------------------------------------------------------------------
# GREEN paths
# ---------------------------------------------------------------------------


def test_new_audited_finding_not_on_target_passes(mod, tmp_path, monkeypatch):
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)
    _write_pr_baseline(
        repo,
        {
            "results": {
                "app/reviewed.py": [_finding("00112233" * 5, line=7, is_secret=False)]
            }
        },
    )

    assert mod.main(["--target-ref", "target"]) == 0


def test_entry_already_on_target_passes_even_if_unaudited(mod, tmp_path, monkeypatch):
    known_hash = "cafebabe" * 5
    repo = _init_repo_with_target_branch(
        tmp_path,
        target_baseline={"results": {"app/known.py": [_finding(known_hash, line=5)]}},
    )
    monkeypatch.chdir(repo)
    # Line-number churn only, same identity as target -- allowed.
    _write_pr_baseline(
        repo, {"results": {"app/known.py": [_finding(known_hash, line=42)]}}
    )

    assert mod.main(["--target-ref", "target"]) == 0


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


def test_missing_pr_baseline_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)
    (repo / ".secrets.baseline").unlink()

    assert mod.main(["--target-ref", "target"]) == 1


def test_corrupt_pr_baseline_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)
    (repo / ".secrets.baseline").write_text("{not valid json")

    assert mod.main(["--target-ref", "target"]) == 1


def test_unresolvable_target_ref_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)
    _write_pr_baseline(repo, {"results": {}})

    assert mod.main(["--target-ref", "origin/does-not-exist"]) == 1


def test_missing_baseline_on_target_ref_fails_closed(mod, tmp_path, monkeypatch):
    """Unlike the pre-commit guard's own HEAD convenience, a CI job that
    cannot see ANY baseline on the target branch must fail closed, not treat
    it as empty -- per OMN-15072's explicit requirement."""
    repo = _init_repo_with_target_branch(tmp_path, target_baseline=None)
    monkeypatch.chdir(repo)
    _write_pr_baseline(repo, {"results": {}})

    assert mod.main(["--target-ref", "target"]) == 1


def test_missing_fallback_baseline_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)
    _write_pr_baseline(repo, {"results": {}})

    assert mod.main(["--fallback-baseline", ".secrets.baseline.bak"]) == 1


def test_requires_exactly_one_selector(mod, tmp_path, monkeypatch):
    repo = _init_repo_with_target_branch(tmp_path, target_baseline={"results": {}})
    monkeypatch.chdir(repo)

    with pytest.raises(SystemExit):
        mod.main([])

    with pytest.raises(SystemExit):
        mod.main(["--target-ref", "target", "--fallback-baseline", "x"])
