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
def test_refuses_missing_upstream(scratch: Scratch) -> None:
    env, clone = scratch.env, scratch.clone
    git(env, clone, "branch", "--unset-upstream")
    proc = scratch.run("omnimarket", "--execute")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "upstream" in (proc.stdout + proc.stderr).lower()
    assert not scratch.evidence_root.exists()


# --- detached HEAD (OMN-17313) ------------------------------------------------
#
# A canonical clone left in detached HEAD by a stray ``git checkout FETCH_HEAD``
# used to be refused here, and that refusal was a dead end: the canonical-clone
# guard denies ``checkout``/``switch`` inside a clone and points the operator at
# THIS script, and pull-all.sh delegates its drift-repair stage here too. The
# live case was $OMNI_HOME/omnimarket sitting detached at an unmerged PR-branch
# commit for two days, which is what served a stale routing contract to both
# BIFROST_CONTRACT_PATH and the clone-HEAD-pinned venv (OMN-6790 / OMN-17193).


def test_detached_head_reattaches_and_converges(scratch: Scratch) -> None:
    env, clone = scratch.env, scratch.clone
    _dirty_like_the_incident(scratch)
    git(env, clone, "checkout", "-q", "--detach")

    proc = scratch.run("omnimarket", "--execute", "--ticket", "OMN-17313")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # HEAD is ATTACHED again -- the sha alone is not the assertion.
    assert git(env, clone, "symbolic-ref", "--short", "HEAD") == "dev"
    assert git(env, clone, "rev-parse", "HEAD") == scratch.upstream_head
    assert git(env, clone, "status", "--porcelain", "--untracked-files=no") == ""

    out = proc.stdout + proc.stderr
    assert "re-attached DETACHED HEAD to dev" in out, out
    assert "derived from HEAD reflog" in out, out

    # The uncommitted work is preserved, exactly as in the attached path.
    evidence = sorted(scratch.evidence_root.glob("omnimarket-*"))[-1]
    manifest = (evidence / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "detached_before=1" in manifest, manifest
    assert "reattach_target_source=derived from HEAD reflog" in manifest, manifest
    assert (evidence / "untracked" / "untracked.txt").read_text(
        encoding="utf-8"
    ) == "untracked draft\n"
    assert "preserved" in (evidence / "full-vs-HEAD.patch").read_text(encoding="utf-8")

    row = scratch.ledger.read_text(encoding="utf-8")
    assert "CONVERGED" in row and "re-attached DETACHED HEAD" in row, row
    assert "OMN-17313" in row, row


def test_detached_only_commits_are_preserved_as_patches(scratch: Scratch) -> None:
    env, clone = scratch.env, scratch.clone
    git(env, clone, "checkout", "-q", "--detach")
    (clone / "orphan.txt").write_text("only on the detached HEAD\n", encoding="utf-8")
    git(env, clone, "add", "-A")
    git(env, clone, "commit", "-q", "-m", "orphan work")
    orphan_sha = git(env, clone, "rev-parse", "HEAD")

    proc = scratch.run("omnimarket", "--execute")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    evidence = sorted(scratch.evidence_root.glob("omnimarket-*"))[-1]
    log = (evidence / "detached-commits.log").read_text(encoding="utf-8")
    assert orphan_sha in log, log
    patches = sorted((evidence / "detached-patches").glob("*.patch"))
    assert patches, "detached-only commit was not preserved as a patch"
    assert "only on the detached HEAD" in patches[-1].read_text(encoding="utf-8")
    manifest = (evidence / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "detached-patches/" in manifest, manifest


def test_detached_head_on_upstream_tip_is_not_already_converged(
    scratch: Scratch,
) -> None:
    """A detached HEAD whose sha equals the upstream tip is still broken.

    Nothing can fast-forward it and every clone-HEAD-pinned consumer stays
    frozen, so the sha-equality early exit must not swallow this case.
    """
    env, clone = scratch.env, scratch.clone
    git(env, clone, "fetch", "-q", "origin")
    git(env, clone, "checkout", "-q", "--detach", scratch.upstream_head)
    assert git(env, clone, "rev-parse", "HEAD") == scratch.upstream_head

    proc = scratch.run("omnimarket", "--execute")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "already converged" not in (proc.stdout + proc.stderr).lower()
    assert git(env, clone, "symbolic-ref", "--short", "HEAD") == "dev"
    assert git(env, clone, "rev-parse", "HEAD") == scratch.upstream_head


def test_detached_head_honours_to_branch_override(scratch: Scratch) -> None:
    env, clone = scratch.env, scratch.clone
    git(env, clone, "branch", "alt", "--track", "origin/dev")
    git(env, clone, "checkout", "-q", "--detach")

    proc = scratch.run("omnimarket", "--execute", "--to-branch", "alt")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert git(env, clone, "symbolic-ref", "--short", "HEAD") == "alt"
    assert git(env, clone, "rev-parse", "HEAD") == scratch.upstream_head
    assert "--to-branch" in (proc.stdout + proc.stderr)


def test_detached_head_refuses_when_target_cannot_be_derived(
    scratch: Scratch,
) -> None:
    """Derivation never guesses: a reflog naming a branch that no longer exists
    is skipped, and with no candidate left the script refuses and names the
    explicit override instead of picking a default."""
    env, clone = scratch.env, scratch.clone
    git(env, clone, "checkout", "-q", "--detach")
    git(env, clone, "branch", "-D", "dev")

    proc = scratch.run("omnimarket", "--execute")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    out = proc.stdout + proc.stderr
    assert "--to-branch" in out, out
    assert not scratch.evidence_root.exists()


def test_to_branch_and_branch_modes_are_mutually_exclusive(
    scratch: Scratch,
) -> None:
    proc = scratch.run("omnimarket", "--branch", "dev", "--to-branch", "dev")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "--to-branch cannot be combined with --branch" in (proc.stdout + proc.stderr)


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


# --- --branch mode (OMN-16500) ------------------------------------------------
#
# The release-synced-main policy rewrites origin/main to the release tag, so a
# canonical clone's local main -- which still holds the pre-rewrite promotion
# commits -- can never fast-forward again. main is a release-pointer branch that
# is never worked on locally, so converging it is always correct, but the move
# must preserve the orphaned commits first and must not touch the checked-out
# branch or the working tree.


def _setup_rewritten_main(scratch: Scratch) -> tuple[str, str]:
    """Model the release-synced-main incident shape.

    Gives the remote a ``main``, gives the clone a local ``main`` tracking it
    with one unique "promotion" commit, then rewrites remote main (force-push)
    to a history that does not contain that commit. Returns
    ``(local_main_sha, rewritten_origin_main_sha)``. The clone is left checked
    out on ``dev`` and does NOT know about the rewrite yet (the script must
    fetch for itself).
    """
    env, clone = scratch.env, scratch.clone
    seed = scratch.remote.parent / "seed"

    # remote main starts at c0; the clone tracks it
    git(env, seed, "push", "-q", "origin", f"{scratch.old_head}:refs/heads/main")
    git(env, clone, "fetch", "-q", "origin")
    git(env, clone, "branch", "-q", "--track", "main", "origin/main")

    # one local promotion commit on main (the orphan-to-be), back to dev after
    git(env, clone, "switch", "-q", "main")
    (clone / "promotion.txt").write_text("promotion artifact\n", encoding="utf-8")
    git(env, clone, "add", "promotion.txt")
    git(env, clone, "commit", "-q", "-m", "promotion commit (will be orphaned)")
    local_main = git(env, clone, "rev-parse", "main")
    git(env, clone, "switch", "-q", "dev")

    # the release rewrites remote main to an unrelated-descendant history
    git(
        env,
        seed,
        "push",
        "-q",
        "-f",
        "origin",
        f"{scratch.upstream_head}:refs/heads/main",
    )
    return local_main, scratch.upstream_head


@pytest.mark.unit
def test_branch_dry_run_is_a_no_op(scratch: Scratch) -> None:
    local_main, target = _setup_rewritten_main(scratch)
    proc = scratch.run("omnimarket", "--branch", "main")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY-RUN" in proc.stdout
    assert "--execute" in proc.stdout
    assert "branch -f" in proc.stdout
    assert git(scratch.env, scratch.clone, "rev-parse", "main") == local_main
    assert not scratch.evidence_root.exists()
    assert scratch.ledger.read_text(encoding="utf-8") == "# ledger\n"


@pytest.mark.unit
def test_branch_execute_converges_without_touching_worktree(
    scratch: Scratch,
) -> None:
    local_main, target = _setup_rewritten_main(scratch)
    env, clone = scratch.env, scratch.clone

    # dirty the checked-out dev tree: --branch must not touch any of it
    (clone / "README.md").write_text("uncommitted dev edit\n", encoding="utf-8")
    (clone / "scratchpad.txt").write_text("untracked\n", encoding="utf-8")
    dev_head = git(env, clone, "rev-parse", "HEAD")

    proc = scratch.run(
        "omnimarket",
        "--branch",
        "main",
        "--execute",
        "--ticket",
        "OMN-16500",
        "--lane",
        "test-lane",
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

    # the branch ref converged; nothing else moved
    assert git(env, clone, "rev-parse", "main") == target
    assert git(env, clone, "rev-parse", "HEAD") == dev_head
    assert git(env, clone, "symbolic-ref", "--short", "HEAD") == "dev"
    assert (clone / "README.md").read_text(encoding="utf-8") == "uncommitted dev edit\n"
    assert (clone / "scratchpad.txt").read_text(encoding="utf-8") == "untracked\n"

    # preservation evidence: the orphaned promotion commit is kept as log+patch
    dirs = list(scratch.evidence_root.iterdir())
    assert len(dirs) == 1
    evidence = dirs[0]
    assert "main" in evidence.name
    ahead_log = (evidence / "ahead-commits.log").read_text(encoding="utf-8")
    assert local_main in ahead_log
    assert "promotion commit (will be orphaned)" in ahead_log
    patches = sorted((evidence / "ahead-patches").glob("*.patch"))
    assert patches, "no per-commit patches preserved for the orphaned commits"
    joined = "".join(p.read_text(encoding="utf-8") for p in patches)
    assert "promotion artifact" in joined
    manifest = (evidence / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "mode=branch" in manifest
    assert f"branch_before={local_main}" in manifest
    assert f"target={target}" in manifest
    assert "branch=main" in manifest
    assert "upstream=origin/main" in manifest
    assert "sha256 " in manifest
    assert "ahead-commits.log" in manifest

    ledger = scratch.ledger.read_text(encoding="utf-8")
    rows = [line for line in ledger.splitlines() if "BRANCH-CONVERGED" in line]
    assert len(rows) == 1, ledger
    row = rows[0]
    assert "| test-lane | OMN-16500 | BRANCH-CONVERGED |" in row
    assert local_main[:7] in row
    assert target[:7] in row
    assert "branch -f" in row
    assert str(evidence) in row


@pytest.mark.unit
def test_branch_already_converged_is_reported_without_evidence(
    scratch: Scratch,
) -> None:
    _setup_rewritten_main(scratch)
    proc = scratch.run("omnimarket", "--branch", "main", "--execute")
    assert proc.returncode == 0, proc.stderr
    proc2 = scratch.run("omnimarket", "--branch", "main", "--execute")
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    assert "already converged" in proc2.stdout.lower()
    # only the first run left evidence
    assert len(list(scratch.evidence_root.iterdir())) == 1


@pytest.mark.unit
def test_branch_refuses_checked_out_branch(scratch: Scratch) -> None:
    _setup_rewritten_main(scratch)
    proc = scratch.run("omnimarket", "--branch", "dev", "--execute")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    combined = (proc.stdout + proc.stderr).lower()
    assert "checked-out" in combined or "checked out" in combined
    assert not scratch.evidence_root.exists()


@pytest.mark.unit
def test_branch_refuses_missing_branch_and_missing_upstream(
    scratch: Scratch,
) -> None:
    env, clone = scratch.env, scratch.clone
    proc = scratch.run("omnimarket", "--branch", "nosuchbranch", "--execute")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "no local branch" in (proc.stdout + proc.stderr).lower()

    git(env, clone, "branch", "-q", "localonly")
    proc = scratch.run("omnimarket", "--branch", "localonly", "--execute")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "upstream" in (proc.stdout + proc.stderr).lower()
    assert not scratch.evidence_root.exists()


@pytest.mark.unit
def test_branch_refuses_clean_untracked_combination(scratch: Scratch) -> None:
    _setup_rewritten_main(scratch)
    proc = scratch.run(
        "omnimarket", "--branch", "main", "--execute", "--clean-untracked"
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "clean-untracked" in (proc.stdout + proc.stderr).lower()
