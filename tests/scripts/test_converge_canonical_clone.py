# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behavioural tests for ``scripts/converge-canonical-clone.sh`` (OMN-16496, G4).

The script is the ONE sanctioned way to bring a dirty canonical clone under
``$OMNI_HOME`` back to its upstream. These tests build a real bare remote plus
a real clone under a scratch ``$OMNI_HOME``, dirty the clone the way the
2026-08-24 omnimarket forensics found it (a plumbing ref move that manufactures
phantom staged diffs, plus a genuine unstaged edit and an untracked file), and
drive the script as a subprocess.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "converge-canonical-clone.sh"


def _git_env(home: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and k not in {"HOME", "OMNI_HOME"}
    }
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    return env


def git(env: dict[str, str], cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


@dataclass(frozen=True)
class Scratch:
    home: Path
    omni_home: Path
    remote: Path
    clone: Path
    ledger: Path
    env: dict[str, str]
    old_head: str
    upstream_head: str

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**self.env, "OMNI_HOME": str(self.omni_home)}
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=self.home,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    @property
    def evidence_root(self) -> Path:
        return self.omni_home / ".onex_state" / "canonical-clone-converge"


@pytest.fixture
def scratch(tmp_path: Path) -> Scratch:
    home = tmp_path / "home"
    omni_home = home / "omni_home"
    (omni_home / "docs" / "tracking").mkdir(parents=True)
    (omni_home / "omni_worktrees").mkdir()
    ledger = omni_home / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
    ledger.write_text("# ledger\n", encoding="utf-8")
    env = _git_env(home)
    (home / "gitconfig").write_text("[init]\n\tdefaultBranch = dev\n", encoding="utf-8")

    remote = tmp_path / "remote.git"
    git(env, tmp_path, "init", "--bare", "-b", "dev", str(remote))

    seed = tmp_path / "seed"
    git(env, tmp_path, "clone", "-q", str(remote), str(seed))
    (seed / "README.md").write_text("v0\n", encoding="utf-8")
    (seed / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(env, seed, "add", "-A")
    git(env, seed, "commit", "-q", "-m", "c0")
    git(env, seed, "push", "-q", "-u", "origin", "dev")

    clone = omni_home / "omnimarket"
    git(env, tmp_path, "clone", "-q", str(remote), str(clone))
    old_head = git(env, clone, "rev-parse", "HEAD")

    # upstream moves on: c1 + c2 land on origin/dev after the canonical clone last synced
    (seed / "README.md").write_text("v1\n", encoding="utf-8")
    git(env, seed, "commit", "-q", "-am", "c1")
    (seed / "later.txt").write_text("c2\n", encoding="utf-8")
    git(env, seed, "add", "-A")
    git(env, seed, "commit", "-q", "-m", "c2")
    git(env, seed, "push", "-q", "origin", "dev")
    upstream_head = git(env, seed, "rev-parse", "HEAD")

    return Scratch(
        home=home,
        omni_home=omni_home,
        remote=remote,
        clone=clone,
        ledger=ledger,
        env=env,
        old_head=old_head,
        upstream_head=upstream_head,
    )


def _dirty_like_the_incident(scratch: Scratch) -> str:
    """Reproduce the forensic shape: HEAD moved by plumbing, index left behind,
    plus one genuine unstaged edit and one untracked file."""
    env = scratch.env
    clone = scratch.clone
    # a local commit the ref move will "unwind" (index keeps its tree => phantom staged diff)
    (clone / "tracked.txt").write_text("local-commit\n", encoding="utf-8")
    git(env, clone, "commit", "-q", "-am", "local c1'")
    local_commit = git(env, clone, "rev-parse", "HEAD")
    git(env, clone, "update-ref", "refs/heads/dev", scratch.old_head)
    # genuine uncommitted content that must be preserved, never lost
    (clone / "README.md").write_text(
        "draft edit that must be preserved\n", encoding="utf-8"
    )
    (clone / "untracked.txt").write_text("untracked draft\n", encoding="utf-8")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "M  tracked.txt" in status, status  # phantom staged
    assert " M README.md" in status, status  # real unstaged
    assert "?? untracked.txt" in status, status
    return local_commit


@pytest.mark.unit
def test_dry_run_is_a_no_op(scratch: Scratch) -> None:
    _dirty_like_the_incident(scratch)
    before_status = git(scratch.env, scratch.clone, "status", "--porcelain")
    proc = scratch.run("omnimarket")
    assert proc.returncode == 0, proc.stderr
    assert "DRY-RUN" in proc.stdout
    assert "--execute" in proc.stdout
    assert git(scratch.env, scratch.clone, "rev-parse", "HEAD") == scratch.old_head
    assert git(scratch.env, scratch.clone, "status", "--porcelain") == before_status
    assert not scratch.evidence_root.exists()
    assert scratch.ledger.read_text(encoding="utf-8") == "# ledger\n"


@pytest.mark.unit
def test_execute_converges_and_preserves(scratch: Scratch) -> None:
    _dirty_like_the_incident(scratch)
    proc = scratch.run(
        "omnimarket", "--execute", "--ticket", "OMN-16496", "--lane", "test-lane"
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

    env, clone = scratch.env, scratch.clone
    assert git(env, clone, "rev-parse", "HEAD") == scratch.upstream_head
    assert git(env, clone, "rev-parse", "@{u}") == scratch.upstream_head
    assert git(env, clone, "symbolic-ref", "--short", "HEAD") == "dev"
    assert git(env, clone, "status", "--porcelain", "--untracked-files=no") == ""
    # untracked content is kept unless --clean-untracked is passed
    assert (clone / "untracked.txt").read_text(encoding="utf-8") == "untracked draft\n"
    assert (clone / "README.md").read_text(encoding="utf-8") == "v1\n"
    assert (clone / "later.txt").is_file()

    dirs = list(scratch.evidence_root.iterdir())
    assert len(dirs) == 1
    evidence = dirs[0]
    assert evidence.name.startswith("omnimarket-")
    full_patch = (evidence / "full-vs-HEAD.patch").read_text(encoding="utf-8")
    assert "draft edit that must be preserved" in full_patch
    unstaged = (evidence / "unstaged.patch").read_text(encoding="utf-8")
    assert "draft edit that must be preserved" in unstaged
    staged = (evidence / "staged.patch").read_text(encoding="utf-8")
    assert "local-commit" in staged
    status_txt = (evidence / "status.txt").read_text(encoding="utf-8")
    assert "?? untracked.txt" in status_txt
    assert (evidence / "untracked" / "untracked.txt").read_text(
        encoding="utf-8"
    ) == "untracked draft\n"
    manifest = (evidence / "MANIFEST.txt").read_text(encoding="utf-8")
    assert f"head_before={scratch.old_head}" in manifest
    assert f"target={scratch.upstream_head}" in manifest
    assert "branch=dev" in manifest
    assert "upstream=origin/dev" in manifest
    assert "sha256 " in manifest
    assert "full-vs-HEAD.patch" in manifest
    reflog = (evidence / "reflog.txt").read_text(encoding="utf-8")
    assert scratch.old_head[:7] in reflog

    ledger = scratch.ledger.read_text(encoding="utf-8")
    rows = [line for line in ledger.splitlines() if "CONVERGED" in line]
    assert len(rows) == 1, ledger
    row = rows[0]
    assert "| test-lane | OMN-16496 | CONVERGED |" in row
    assert scratch.old_head[:7] in row
    assert scratch.upstream_head[:7] in row
    assert str(evidence) in row
    assert "converge-canonical-clone.sh" in row


@pytest.mark.unit
def test_execute_with_clean_untracked(scratch: Scratch) -> None:
    _dirty_like_the_incident(scratch)
    proc = scratch.run("omnimarket", "--execute", "--clean-untracked")
    assert proc.returncode == 0, proc.stderr
    assert not (scratch.clone / "untracked.txt").exists()
    assert git(scratch.env, scratch.clone, "status", "--porcelain") == ""
    evidence = next(scratch.evidence_root.iterdir())
    assert (evidence / "untracked" / "untracked.txt").is_file()


@pytest.mark.unit
def test_already_converged_clone_is_reported_without_evidence(scratch: Scratch) -> None:
    git(scratch.env, scratch.clone, "pull", "-q", "--ff-only")
    proc = scratch.run("omnimarket", "--execute")
    assert proc.returncode == 0, proc.stderr
    assert "already converged" in proc.stdout.lower()
    assert not scratch.evidence_root.exists()
    assert "CONVERGED" not in scratch.ledger.read_text(encoding="utf-8")


@pytest.mark.unit
def test_accepts_absolute_path_and_dot(scratch: Scratch) -> None:
    _dirty_like_the_incident(scratch)
    proc = scratch.run(str(scratch.clone), "--execute")
    assert proc.returncode == 0, proc.stderr
    assert git(scratch.env, scratch.clone, "rev-parse", "HEAD") == scratch.upstream_head


@pytest.mark.unit
def test_refuses_worktree_non_clone_and_outside_paths(scratch: Scratch) -> None:
    env = scratch.env
    wt = scratch.omni_home / "omni_worktrees" / "OMN-1" / "omnimarket"
    git(env, scratch.clone, "worktree", "add", "-q", str(wt), "-b", "scratch")
    (wt / "README.md").write_text("wt edit\n", encoding="utf-8")

    for target in (
        str(wt),
        "omni_worktrees",
        str(scratch.omni_home / "docs"),
        str(scratch.home),
        "nope",
    ):
        proc = scratch.run(target, "--execute")
        assert proc.returncode == 2, (target, proc.stdout, proc.stderr)
        assert "refus" in (proc.stdout + proc.stderr).lower(), target
    assert (wt / "README.md").read_text(encoding="utf-8") == "wt edit\n"
    assert not scratch.evidence_root.exists()
    assert "CONVERGED" not in scratch.ledger.read_text(encoding="utf-8")


@pytest.mark.unit
def test_refuses_detached_head_and_missing_upstream(scratch: Scratch) -> None:
    env, clone = scratch.env, scratch.clone
    git(env, clone, "checkout", "-q", "--detach")
    proc = scratch.run("omnimarket", "--execute")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "detached" in (proc.stdout + proc.stderr).lower()

    git(env, clone, "checkout", "-q", "dev")
    git(env, clone, "branch", "--unset-upstream")
    proc = scratch.run("omnimarket", "--execute")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "upstream" in (proc.stdout + proc.stderr).lower()
    assert not scratch.evidence_root.exists()


@pytest.mark.unit
def test_requires_omni_home(scratch: Scratch) -> None:
    env = {k: v for k, v in scratch.env.items() if k != "OMNI_HOME"}
    proc = subprocess.run(
        ["bash", str(SCRIPT), "omnimarket"],
        cwd=scratch.home,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "OMNI_HOME" in proc.stderr


@pytest.mark.unit
def test_script_carries_no_machine_specific_paths() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for needle in ("/Users" + "/", "/Volumes" + "/"):
        assert needle not in text
    assert "set -euo pipefail" in text
    assert os.access(SCRIPT, os.X_OK)
