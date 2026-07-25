# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the detect-secrets baseline guard (OMN-15068).

Recurrence guard for the RED-first finding: the old `detect-secrets-update`
pre-commit hook unconditionally ran `detect-secrets scan --baseline
.secrets.baseline ... && git add .secrets.baseline` and always exited 0,
silently absorbing brand new, unaudited secret findings into the baseline on
every commit. A synthetic AWS key pair committed cleanly under that hook body
with nothing blocking. These tests exercise `scripts/detect_secrets_guard.py`
against a real temp git repo (so the `git show HEAD:.secrets.baseline`
comparison is real) with the `detect-secrets scan` subprocess call mocked
(the guard's own comparison/audit logic is what's under test, not the
detect-secrets tool itself).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "detect_secrets_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("detect_secrets_guard", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_repo(tmp_path: Path, baseline: dict[str, Any] | None) -> Path:
    """Create a git repo at tmp_path, optionally with a committed baseline."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    if baseline is not None:
        (tmp_path / ".secrets.baseline").write_text(json.dumps(baseline, indent=2))
        subprocess.run(["git", "add", ".secrets.baseline"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "seed baseline"], cwd=tmp_path, check=True
        )
    return tmp_path


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


def _run_guard_with_scan_result(mod, repo: Path, new_baseline: dict) -> int:
    """Run mod.main() with the `detect-secrets scan` subprocess call mocked to
    write `new_baseline` to .secrets.baseline and return success, while real
    `git` subprocess calls pass through untouched."""
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "detect-secrets":
            (repo / ".secrets.baseline").write_text(json.dumps(new_baseline, indent=2))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        return mod.main()


@pytest.fixture
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# RED: a genuinely new, unaudited finding BLOCKS the commit
# ---------------------------------------------------------------------------


def test_new_unaudited_finding_blocks(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline={"results": {}})
    monkeypatch.chdir(repo)

    new_baseline = {
        "results": {
            "app/leaked_aws.py": [_finding("deadbeef" * 5, line=3)],
        }
    }

    exit_code = _run_guard_with_scan_result(mod, repo, new_baseline)

    assert exit_code == 1
    # The baseline must NOT have been staged -- `git add` never ran for it.
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".secrets.baseline" not in staged


# ---------------------------------------------------------------------------
# GREEN: line-number-only churn on an already-known finding passes
# ---------------------------------------------------------------------------


def test_line_number_churn_only_passes(mod, tmp_path, monkeypatch):
    known_hash = "cafebabe" * 5
    repo = _init_repo(
        tmp_path,
        baseline={"results": {"app/known.py": [_finding(known_hash, line=5)]}},
    )
    monkeypatch.chdir(repo)

    # Same (file, hashed_secret) identity, only the line number moved.
    new_baseline = {
        "results": {"app/known.py": [_finding(known_hash, line=42)]},
    }

    exit_code = _run_guard_with_scan_result(mod, repo, new_baseline)

    assert exit_code == 0
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".secrets.baseline" in staged


# ---------------------------------------------------------------------------
# GREEN: an explicitly audited new finding passes
# ---------------------------------------------------------------------------


def test_explicitly_audited_new_finding_passes(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline={"results": {}})
    monkeypatch.chdir(repo)

    new_baseline = {
        "results": {
            "app/reviewed.py": [
                _finding("00112233" * 5, line=7, is_secret=False),  # human-reviewed FP
            ],
        }
    }

    exit_code = _run_guard_with_scan_result(mod, repo, new_baseline)

    assert exit_code == 0
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".secrets.baseline" in staged


# ---------------------------------------------------------------------------
# RED: a finding audited as a CONFIRMED real secret (is_secret: true) still
# blocks -- `detect-secrets audit` sets True for "yes, this is real" and
# False for "false positive"; only False is an accept signal.
# ---------------------------------------------------------------------------


def test_audited_as_confirmed_real_secret_still_blocks(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline={"results": {}})
    monkeypatch.chdir(repo)

    new_baseline = {
        "results": {
            "app/leaked_aws.py": [
                _finding(
                    "deadbeef" * 5, line=3, is_secret=True
                ),  # human-confirmed REAL
            ],
        }
    }

    exit_code = _run_guard_with_scan_result(mod, repo, new_baseline)

    assert exit_code == 1
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".secrets.baseline" not in staged


# ---------------------------------------------------------------------------
# Fail-closed: missing tool, scan error, unreadable/corrupt baseline
# ---------------------------------------------------------------------------


def test_missing_tool_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline={"results": {}})
    monkeypatch.chdir(repo)

    with patch.object(mod.shutil, "which", return_value=None):
        assert mod.main() == 1


def test_missing_baseline_file_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline=None)
    monkeypatch.chdir(repo)
    # No .secrets.baseline written at all.

    with patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"):
        assert mod.main() == 1


def test_scan_nonzero_exit_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline={"results": {}})
    monkeypatch.chdir(repo)
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "detect-secrets":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
        return real_run(cmd, *args, **kwargs)

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        assert mod.main() == 1


def test_corrupt_regenerated_baseline_fails_closed(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline={"results": {}})
    monkeypatch.chdir(repo)
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "detect-secrets":
            (repo / ".secrets.baseline").write_text("{not valid json")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        assert mod.main() == 1


def test_corrupt_committed_baseline_fails_closed(mod, tmp_path, monkeypatch):
    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".secrets.baseline").write_text("{not valid json")
    subprocess.run(["git", "add", ".secrets.baseline"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "corrupt seed"], cwd=repo, check=True)
    monkeypatch.chdir(repo)

    with patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"):
        assert mod.main() == 1


def test_no_prior_commit_treats_baseline_as_empty(mod, tmp_path, monkeypatch):
    """First-ever commit (no HEAD yet): the guard must not crash, and must
    treat every finding as new (so it still requires explicit audit)."""
    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".secrets.baseline").write_text(json.dumps({"results": {}}))
    monkeypatch.chdir(repo)

    new_baseline = {
        "results": {"app/leaked.py": [_finding("11223344" * 5, line=1)]},
    }
    exit_code = _run_guard_with_scan_result(mod, repo, new_baseline)

    assert exit_code == 1  # unaudited finding, no prior HEAD -> still blocked
