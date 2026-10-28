# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the detect-secrets baseline guard (OMN-15068, OMN-18521).

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

The OMN-18521 block at the bottom covers the third constraint on this file:
the committed baseline must carry no position and no timestamp, so unrelated
pull requests stop conflicting on it. Those tests pin the normalization AND
pin that it did not weaken either earlier fix -- a planted new finding still
blocks, and the merge test carries its own RED positive control so a green
result cannot come from a test that merges everything.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "detect_secrets_guard.py"


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run git with the inherited location overrides scrubbed (OMN-14891).

    Every git call in this module goes through here. A fixture that shells out
    to git while pytest is itself running under one of this repo's git hooks
    inherits GIT_DIR / GIT_WORK_TREE from that hook, and those override BOTH
    `cwd` and `-C` -- so the fixture's command silently retargets the real
    worktree instead of its tmp_path repo.
    """
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(os.environ),
    )


def _load_module():
    spec = importlib.util.spec_from_file_location("detect_secrets_guard", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_repo(tmp_path: Path, baseline: dict[str, Any] | None) -> Path:
    """Create a git repo at tmp_path, optionally with a committed baseline."""
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "test@test.local", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    if baseline is not None:
        (tmp_path / ".secrets.baseline").write_text(json.dumps(baseline, indent=2))
        _git("add", ".secrets.baseline", cwd=tmp_path)
        _git("commit", "-q", "-m", "seed baseline", cwd=tmp_path)
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
    staged = _staged_files(repo)
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
    staged = _staged_files(repo)
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
    staged = _staged_files(repo)
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
    staged = _staged_files(repo)
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
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@test.local", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / ".secrets.baseline").write_text("{not valid json")
    _git("add", ".secrets.baseline", cwd=repo)
    _git("commit", "-q", "-m", "corrupt seed", cwd=repo)
    monkeypatch.chdir(repo)

    with patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"):
        assert mod.main() == 1


def test_no_prior_commit_treats_baseline_as_empty(mod, tmp_path, monkeypatch):
    """First-ever commit (no HEAD yet): the guard must not crash, and must
    treat every finding as new (so it still requires explicit audit)."""
    repo = tmp_path
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@test.local", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / ".secrets.baseline").write_text(json.dumps({"results": {}}))
    monkeypatch.chdir(repo)

    new_baseline = {
        "results": {"app/leaked.py": [_finding("11223344" * 5, line=1)]},
    }
    exit_code = _run_guard_with_scan_result(mod, repo, new_baseline)

    assert exit_code == 1  # unaudited finding, no prior HEAD -> still blocked


# ===========================================================================
# OMN-18521: the committed baseline carries no position and no timestamp, so
# unrelated pull requests stop conflicting on it.
#
# The defect: `detect-secrets scan` writes a top-level `generated_at` and a
# per-finding `line_number`. Every commit that grew a file above a tracked
# finding rewrote that entry and every commit rewrote the timestamp, so every
# pull request carried a baseline hunk and every pair of concurrent pull
# requests conflicted. 60 of the last 60 commits touching the baseline were
# pure position/timestamp churn; 0 changed a finding.
# ===========================================================================


def _staged_files(repo: Path) -> str:
    return _git("diff", "--cached", "--name-only", cwd=repo).stdout


def test_normalize_strips_position_and_timestamp(mod):
    """AC5, at the unit: both bookkeeping fields are removed."""
    baseline = {
        "version": "1.5.0",
        "generated_at": "2026-09-17T21:30:14Z",
        "results": {
            "app/a.py": [_finding("aa" * 20, line=7)],
            "app/b.py": [_finding("bb" * 20, line=91), _finding("cc" * 20, line=92)],
        },
    }

    normalized = mod.normalize_baseline(baseline)
    rendered = mod.serialize_baseline(normalized)

    assert "generated_at" not in normalized
    assert "line_number" not in rendered
    assert "generated_at" not in rendered
    # Everything that is not bookkeeping survives.
    assert normalized["version"] == "1.5.0"
    assert set(normalized["results"]) == {"app/a.py", "app/b.py"}


def test_normalize_preserves_identity_and_audit_markers(mod):
    """OMN-15068's guarantee: normalization must not touch any field the
    audited-vs-unaudited classification reads."""
    known = "cafebabe" * 5
    baseline = {
        "generated_at": "2026-09-17T21:30:14Z",
        "results": {
            "app/known.py": [
                _finding(known, line=5, is_secret=False),
                _finding("dd" * 20, line=6, is_secret=True),
            ]
        },
    }
    keys_before = mod.result_keys(baseline)

    normalized = mod.normalize_baseline(baseline)

    assert mod.result_keys(normalized) == keys_before
    entries = {f["hashed_secret"]: f for f in normalized["results"]["app/known.py"]}
    assert entries[known]["is_secret"] is False
    assert entries["dd" * 20]["is_secret"] is True
    for entry in entries.values():
        assert entry["type"] == "AWS Access Key"
        assert entry["is_verified"] is False


def test_normalize_is_order_canonical(mod):
    """Two scans that emit the same findings in a different order must render
    identically -- otherwise a re-ordering scanner reintroduces the diff the
    position strip removed."""
    a = {
        "results": {"f.py": [_finding("11" * 20, line=3), _finding("22" * 20, line=9)]}
    }
    b = {
        "results": {"f.py": [_finding("22" * 20, line=9), _finding("11" * 20, line=3)]}
    }

    assert mod.serialize_baseline(mod.normalize_baseline(a)) == mod.serialize_baseline(
        mod.normalize_baseline(b)
    )


def test_shifted_positions_serialize_byte_identically(mod):
    """AC2's core property, stated directly: the only difference between these
    two scan outputs is where the findings sit and when the scan ran, which is
    exactly the `omniclaude#2205` shape (four entries, all shifted +59)."""
    before = {
        "generated_at": "2026-09-16T20:18:34Z",
        "results": {
            "app/x.py": [_finding("ab" * 20, line=229), _finding("cd" * 20, line=230)],
            "app/y.py": [_finding("ef" * 20, line=272), _finding("01" * 20, line=280)],
        },
    }
    after = {
        "generated_at": "2026-09-16T21:12:50Z",
        "results": {
            "app/x.py": [_finding("ab" * 20, line=288), _finding("cd" * 20, line=289)],
            "app/y.py": [_finding("ef" * 20, line=331), _finding("01" * 20, line=339)],
        },
    }

    assert mod.serialize_baseline(
        mod.normalize_baseline(before)
    ) == mod.serialize_baseline(mod.normalize_baseline(after))


def test_staged_baseline_carries_no_position_or_timestamp(mod, tmp_path, monkeypatch):
    """End to end through main(): what the hook stages is the normalized form,
    whatever `detect-secrets scan` wrote."""
    known = "cafebabe" * 5
    repo = _init_repo(
        tmp_path,
        baseline={"results": {"app/known.py": [_finding(known, line=5)]}},
    )
    monkeypatch.chdir(repo)

    # What the scan emits: same finding, moved, plus a fresh timestamp.
    scan_output = {
        "version": "1.5.0",
        "generated_at": "2026-09-17T21:30:14Z",
        "results": {"app/known.py": [_finding(known, line=64)]},
    }

    assert _run_guard_with_scan_result(mod, repo, scan_output) == 0

    on_disk = (repo / ".secrets.baseline").read_text()
    assert "line_number" not in on_disk
    assert "generated_at" not in on_disk
    assert ".secrets.baseline" in _staged_files(repo)
    # The finding itself is still there -- this is a normalization, not a purge.
    assert known in on_disk


def test_blocking_path_does_not_normalize_or_stage(mod, tmp_path, monkeypatch):
    """AC3 + AC6: the security path is byte-for-byte the OMN-15068 behaviour.
    A new unaudited finding blocks, nothing is staged, and the guard does not
    rewrite the file on its way out -- normalization is reachable only after
    the classification has already passed."""
    repo = _init_repo(tmp_path, baseline={"results": {}})
    monkeypatch.chdir(repo)

    scan_output = {
        "generated_at": "2026-09-17T21:30:14Z",
        "results": {"app/leaked.py": [_finding("deadbeef" * 5, line=3)]},
    }

    assert _run_guard_with_scan_result(mod, repo, scan_output) == 1

    assert ".secrets.baseline" not in _staged_files(repo)
    # Untouched by the guard: still exactly what the scan wrote.
    assert json.loads((repo / ".secrets.baseline").read_text()) == scan_output


def test_normalized_write_failure_fails_closed(mod, tmp_path, monkeypatch):
    """AC6: a normalizing step that cannot write must refuse the commit, not
    fall back to staging whatever happens to be on disk."""
    known = "cafebabe" * 5
    repo = _init_repo(
        tmp_path,
        baseline={"results": {"app/known.py": [_finding(known, line=5)]}},
    )
    monkeypatch.chdir(repo)
    scan_output = {"results": {"app/known.py": [_finding(known, line=64)]}}

    real_write = Path.write_text
    # The first baseline write is the mocked scan writing its own output; the
    # second is the guard writing the normalized form, which is the one under
    # test.
    writes: list[str] = []

    def exploding_write(self, *args, **kwargs):
        if self.name == ".secrets.baseline":
            writes.append(self.name)
            if len(writes) > 1:
                raise OSError("disk full")
        return real_write(self, *args, **kwargs)

    with patch.object(Path, "write_text", exploding_write):
        exit_code = _run_guard_with_scan_result(mod, repo, scan_output)

    assert exit_code == 1
    assert ".secrets.baseline" not in _staged_files(repo)


# ---------------------------------------------------------------------------
# AC2, against real git: two branches whose only baseline change is a position
# shift must merge cleanly. The positive control immediately below reproduces
# the pre-change conflict, so a green result here cannot come from a test that
# merges everything.
# ---------------------------------------------------------------------------


def _merge_two_shifting_branches(
    repo: Path, *, normalize
) -> subprocess.CompletedProcess:
    """Base -> two branches, each regenerating the baseline with its own
    positions and timestamp, then merge the second into the first.

    `normalize` is the function the "hook" applies before committing.
    """
    known_x, known_y = "ab" * 20, "cd" * 20
    base = {
        "version": "1.5.0",
        "generated_at": "2026-09-16T20:00:00Z",
        "results": {
            "app/x.py": [_finding(known_x, line=229)],
            "app/y.py": [_finding(known_y, line=272)],
        },
    }
    baseline_path = repo / ".secrets.baseline"
    baseline_path.write_text(normalize(json.loads(json.dumps(base))))
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    _git("branch", "feature-a", cwd=repo)
    _git("branch", "feature-b", cwd=repo)

    def branch_commit(name: str, source: str, shift: int, stamp: str) -> None:
        _git("checkout", "-q", name, cwd=repo)
        (repo / source).parent.mkdir(parents=True, exist_ok=True)
        (repo / source).write_text("# padding\n" * shift)
        scanned = json.loads(json.dumps(base))
        scanned["generated_at"] = stamp
        for findings in scanned["results"].values():
            for finding in findings:
                finding["line_number"] += shift
        baseline_path.write_text(normalize(scanned))
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", name, cwd=repo)

    # Two unrelated changes, each shifting every tracked finding by its own
    # amount -- the omniclaude#2205 shape, twice, concurrently.
    branch_commit("feature-a", "app/a_new.py", 59, "2026-09-16T21:12:50Z")
    branch_commit("feature-b", "app/b_new.py", 12, "2026-09-16T21:40:03Z")

    _git("checkout", "-q", "feature-a", cwd=repo)
    return _git("merge", "--no-edit", "feature-b", cwd=repo, check=False)


def test_two_branches_shifting_positions_merge_cleanly(mod, tmp_path):
    """GREEN (AC2): with the hook normalizing, neither branch produces a
    baseline hunk at all, so the merge is clean."""
    repo = _init_repo(tmp_path, baseline=None)

    result = _merge_two_shifting_branches(
        repo,
        normalize=lambda b: mod.serialize_baseline(mod.normalize_baseline(b)),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    conflicts = _git("ls-files", "-u", cwd=repo).stdout
    assert conflicts == ""
    merged = (repo / ".secrets.baseline").read_text()
    assert "line_number" not in merged
    assert "generated_at" not in merged
    # Both branches' unrelated files survived the merge.
    assert (repo / "app/a_new.py").exists() and (repo / "app/b_new.py").exists()


def test_two_branches_shifting_positions_conflict_without_normalization(mod, tmp_path):
    """RED positive control: the same two branches, with the pre-OMN-18521
    behaviour of committing whatever the scan wrote, DO conflict on the
    baseline. Without this, a merge test that always passes would look like a
    fix. If this test ever goes green, the one above has stopped proving
    anything."""
    repo = _init_repo(tmp_path, baseline=None)

    result = _merge_two_shifting_branches(
        repo,
        normalize=lambda b: json.dumps(b, indent=2) + "\n",
    )

    assert result.returncode != 0
    assert ".secrets.baseline" in result.stdout + result.stderr
    conflicts = _git("ls-files", "-u", cwd=repo).stdout
    assert ".secrets.baseline" in conflicts


def test_committed_repo_baseline_is_normalized(mod):
    """AC5 as a standing CI assertion, against this repository's own committed
    baseline rather than a fixture. Before OMN-18521 it carried 36
    `line_number` fields and one `generated_at`."""
    committed = _SCRIPT.resolve().parents[1] / ".secrets.baseline"
    text = committed.read_text()

    assert "line_number" not in text
    assert "generated_at" not in text
    # And it is in the canonical form this module produces, so a hand edit or a
    # bare `detect-secrets scan >` redirect is caught here rather than in a
    # conflict two pull requests later.
    parsed = json.loads(text)
    assert text == mod.serialize_baseline(mod.normalize_baseline(parsed))


# ---------------------------------------------------------------------------
# OMN-17427: a commit rescans its staged files, not the whole tracked set
# ---------------------------------------------------------------------------


def _track(repo: Path, *names: str) -> None:
    for name in names:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    _git("add", *names, cwd=repo)
    _git("commit", "-q", "-m", "track files", cwd=repo)


def _run_guard_recording_scan(
    mod, repo: Path, argv: list[str], scan_result: dict
) -> tuple[int, list[str]]:
    """Run mod.main(argv) with the scan mocked the way detect-secrets behaves
    when it is given files: it writes ONLY their findings and returns the command
    it was asked to run."""
    real_run = subprocess.run
    seen: list[str] = []

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "detect-secrets":
            seen.extend(cmd)
            (repo / ".secrets.baseline").write_text(json.dumps(scan_result, indent=2))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        return mod.main(argv), seen


def test_staged_files_are_the_only_files_rescanned(mod, tmp_path, monkeypatch):
    known = _finding("aa" * 20, line=1, is_secret=False)
    repo = _init_repo(tmp_path, baseline={"results": {"app/old.py": [known]}})
    _track(repo, "app/old.py", "app/new.py", "app/other.py")
    monkeypatch.chdir(repo)

    code, cmd = _run_guard_recording_scan(mod, repo, ["app/new.py"], {"results": {}})

    assert code == 0
    assert cmd[cmd.index("--") + 1 :] == ["app/new.py"]
    # The file nobody touched keeps its entry although the scan did not return it.
    written = json.loads((repo / ".secrets.baseline").read_text())
    assert [f["hashed_secret"] for f in written["results"]["app/old.py"]] == [
        known["hashed_secret"]
    ]
    assert ".secrets.baseline" in _staged_files(repo)


def test_new_unaudited_finding_in_a_staged_file_still_blocks(
    mod, tmp_path, monkeypatch
):
    known = _finding("aa" * 20, line=1, is_secret=False)
    repo = _init_repo(tmp_path, baseline={"results": {"app/old.py": [known]}})
    _track(repo, "app/old.py", "app/new.py")
    monkeypatch.chdir(repo)

    leaked = {"results": {"app/new.py": [_finding("deadbeef" * 5, line=2)]}}
    code, _ = _run_guard_recording_scan(mod, repo, ["app/new.py"], leaked)

    assert code == 1
    assert ".secrets.baseline" not in _staged_files(repo)
    # A blocked commit leaves the whole tree's findings behind, not only the
    # staged file's, so `detect-secrets audit` still has the full baseline.
    left = json.loads((repo / ".secrets.baseline").read_text())
    assert set(left["results"]) == {"app/old.py", "app/new.py"}


def test_a_finding_that_left_a_staged_file_leaves_the_baseline(
    mod, tmp_path, monkeypatch
):
    repo = _init_repo(
        tmp_path,
        baseline={"results": {"app/a.py": [_finding("aa" * 20, 1, is_secret=False)]}},
    )
    _track(repo, "app/a.py", "app/b.py")
    monkeypatch.chdir(repo)

    code, _ = _run_guard_recording_scan(mod, repo, ["app/a.py"], {"results": {}})

    assert code == 0
    assert json.loads((repo / ".secrets.baseline").read_text())["results"] == {}


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="no-staged-files"),
        pytest.param(["app/a.py", "app/b.py"], id="every-tracked-file"),
        pytest.param(["app/a.py", "scripts/detect_secrets_guard.py"], id="guard-edit"),
        pytest.param(["app/a.py", ".pre-commit-config.yaml"], id="hook-wiring-edit"),
    ],
)
def test_whole_tree_rescan_cases_pass_no_files_to_the_scan(
    mod, tmp_path, monkeypatch, argv
):
    repo = _init_repo(tmp_path, baseline={"results": {}})
    _track(
        repo,
        "app/a.py",
        "app/b.py",
        "scripts/detect_secrets_guard.py",
        ".pre-commit-config.yaml",
    )
    # `every-tracked-file` means the whole tracked set, whatever it holds.
    if argv == ["app/a.py", "app/b.py"]:
        argv = sorted(
            _git("ls-files", cwd=repo).stdout.split(),
        )
    monkeypatch.chdir(repo)

    code, cmd = _run_guard_recording_scan(mod, repo, argv, {"results": {}})

    assert code == 0
    assert "--" not in cmd


def test_merge_keeps_only_tracked_unexcluded_untouched_entries(mod):
    entry = _finding("aa" * 20, 1, is_secret=False)
    prior = {
        "results": {
            "kept.py": [entry],
            "rescanned.py": [entry],
            "deleted.py": [entry],
            "tests/excluded.py": [entry],
        }
    }
    scanned = {"results": {"rescanned.py": [_finding("bb" * 20, 4)]}}

    merged = mod.merge_incremental_results(
        prior,
        scanned,
        files={"rescanned.py"},
        tracked={"kept.py", "rescanned.py", "tests/excluded.py"},
    )

    assert set(merged) == {"kept.py", "rescanned.py"}
    assert merged["rescanned.py"] == scanned["results"]["rescanned.py"]
    assert merged["kept.py"] == [entry]


# ---------------------------------------------------------------------------
# T2.6 (OMN-21433): the pre-commit hook runs `--check`, which never writes
# ---------------------------------------------------------------------------


def _run_check_with_scan_result(
    mod, repo: Path, new_baseline: dict, argv: list[str] | None = None
) -> int:
    """Run `main(["--check", ...])` with the scan mocked.

    Unlike `_run_guard_with_scan_result`, the fake writes where the command's
    `--baseline` argument points, because check mode must scan a scratch copy
    and not the committed file.
    """
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "detect-secrets":
            target = Path(cmd[cmd.index("--baseline") + 1])
            target.write_text(json.dumps(new_baseline, indent=2))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        return mod.main(["--check", *(argv or [])])


def _seed_current_baseline(mod, repo: Path, results: dict) -> str:
    """Commit a baseline already in canonical form; return its text."""
    text = mod.serialize_baseline(mod.normalize_baseline({"results": results}))
    (repo / ".secrets.baseline").write_text(text)
    _git("add", ".secrets.baseline", cwd=repo)
    _git("commit", "-q", "-m", "seed canonical baseline", cwd=repo)
    return text


def test_check_refuses_stale_baseline_and_leaves_it_untouched(
    mod, tmp_path, monkeypatch, capsys
):
    """A baseline that is not what a scan would write is refused, not refreshed."""
    known = "cafebabe" * 5
    repo = _init_repo(tmp_path, baseline=None)
    monkeypatch.chdir(repo)
    committed = _seed_current_baseline(
        mod, repo, {"app/known.py": [_finding(known, line=5)]}
    )
    (repo / ".secrets.baseline").write_text(committed)  # byte-identical start

    # The scan now also finds a human-audited false positive that the file lacks.
    scanned = {
        "results": {
            "app/known.py": [_finding(known, line=42)],
            "app/reviewed.py": [_finding("00112233" * 5, line=7, is_secret=False)],
        }
    }
    exit_code = _run_check_with_scan_result(mod, repo, scanned)

    assert exit_code == 1
    assert "stale" in capsys.readouterr().err
    assert (repo / ".secrets.baseline").read_text() == committed
    assert ".secrets.baseline" not in _staged_files(repo)


def test_check_accepts_current_baseline_without_writing_or_staging(
    mod, tmp_path, monkeypatch
):
    """Positive control: a line shift only, baseline already canonical, passes."""
    known = "cafebabe" * 5
    repo = _init_repo(tmp_path, baseline=None)
    monkeypatch.chdir(repo)
    committed = _seed_current_baseline(
        mod, repo, {"app/known.py": [_finding(known, line=5)]}
    )

    scanned = {"results": {"app/known.py": [_finding(known, line=99)]}}
    exit_code = _run_check_with_scan_result(mod, repo, scanned)

    assert exit_code == 0
    assert (repo / ".secrets.baseline").read_text() == committed
    assert _staged_files(repo) == ""


def test_check_still_blocks_a_new_unaudited_finding(mod, tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, baseline=None)
    monkeypatch.chdir(repo)
    committed = _seed_current_baseline(mod, repo, {})

    scanned = {"results": {"app/leaked.py": [_finding("deadbeef" * 5, line=3)]}}
    exit_code = _run_check_with_scan_result(mod, repo, scanned)

    assert exit_code == 1
    assert (repo / ".secrets.baseline").read_text() == committed
    assert _staged_files(repo) == ""


def test_check_flag_is_not_taken_for_a_file_name(mod, tmp_path, monkeypatch):
    """`--check` selects the mode; it is never a path handed to the scan."""
    repo = _init_repo(tmp_path, baseline=None)
    monkeypatch.chdir(repo)
    _seed_current_baseline(mod, repo, {})
    seen: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "detect-secrets":
            seen.append(list(cmd))
            target = Path(cmd[cmd.index("--baseline") + 1])
            target.write_text(json.dumps({"results": {}}))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/detect-secrets"),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        assert mod.main(["--check", "app/a.py"]) == 0

    assert seen and "--check" not in seen[0]
    assert Path(seen[0][seen[0].index("--baseline") + 1]) != Path(".secrets.baseline")


def test_check_refuses_a_baseline_with_crlf_line_endings(mod, tmp_path, monkeypatch):
    """The comparison is on bytes: a CRLF copy is not the canonical file."""
    known = "cafebabe" * 5
    repo = _init_repo(tmp_path, baseline=None)
    monkeypatch.chdir(repo)
    committed = _seed_current_baseline(
        mod, repo, {"app/known.py": [_finding(known, line=5)]}
    )
    crlf = committed.replace("\n", "\r\n").encode("utf-8")
    (repo / ".secrets.baseline").write_bytes(crlf)

    scanned = {"results": {"app/known.py": [_finding(known, line=5)]}}
    assert _run_check_with_scan_result(mod, repo, scanned) == 1
    assert (repo / ".secrets.baseline").read_bytes() == crlf
