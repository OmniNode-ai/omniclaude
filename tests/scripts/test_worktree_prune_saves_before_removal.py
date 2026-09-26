# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Every omniclaude worktree-removal path saves before it removes (OMN-19539).

Operator ruling 2026-09-25 (ledger RULING 2026-09-25T15:29:22Z, item 2): every
worktree-removal path saves the worktree's binary diff and untracked files under
``$OMNI_HOME/.onex_state`` before removing it, and refuses to remove when the
save fails. These tests drive the two morning-prune removal paths
against throwaway registries under ``tmp_path``
(``prune-worktrees.sh`` is covered in ``test_prune_worktrees_disposable_state.py``):

* ``worktree_auto_prune.prune_worktree`` (the morning prune's removal),
* ``worktree_auto_prune.remediate_debris`` (its ``.git``-gone debris pass),

Each has a positive control: a clean, pushed worktree is still removed.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tarfile
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumPruneDisposition,
)

pytestmark = pytest.mark.unit

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prune = _load("worktree_auto_prune")


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables that override ``-C`` (OMN-18434)."""
    scrubbed = dict(env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        scrubbed.pop(key, None)
    return scrubbed


_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "omn19539",
    "GIT_COMMITTER_NAME": "omn19539",
    "GIT_AUTHOR_EMAIL": "omn19539@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn19539@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=scrub_git_location_env(_GIT_ENV),
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Scratch OMNI_HOME: a bare origin, a clone pushed to it, an omni_worktrees root."""
    registry_root = tmp_path / "registry_root"
    origin = tmp_path / "origin.git"
    clone = registry_root / "omnibase_infra"
    registry_root.mkdir()
    _git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    (clone / ".gitignore").write_text(".env\n.venv/\n", encoding="utf-8")
    (clone / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "init")
    _git(clone, "push", "-q", "origin", "HEAD:dev")
    monkeypatch.setenv("OMNI_HOME", str(registry_root))
    return registry_root


def _worktree(registry: Path, ticket: str, branch: str) -> Path:
    worktree = registry / "omni_worktrees" / ticket / "omnibase_infra"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(
        registry / "omnibase_infra",
        "worktree",
        "add",
        "-q",
        str(worktree),
        "-b",
        branch,
        "origin/dev",
    )
    return worktree


def _decision(worktree: Path, branch: str) -> object:
    return prune.ModelWorktreePruneDecision(
        path=str(worktree),
        ticket=worktree.parent.name,
        repo="omnibase_infra",
        branch=branch,
        disposition=EnumPruneDisposition.PRUNE,
        block_reasons=(),
        eligibility_evidence="test",
        safety_evidence="test",
        branch_content_preserved=True,
        dirty_file_count=0,
        commits_ahead=0,
        pr_state=EnumBranchPrState.MERGED,
        ledger_open_claim=None,
    )


def _snapshots(registry: Path) -> list[Path]:
    root = registry / ".onex_state" / "worktree-removal-snapshots"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _archived(snapshot_dir: Path) -> set[str]:
    with tarfile.open(snapshot_dir / "untracked.tar.gz", "r:gz") as tar:
        return set(tar.getnames())


def _branch_exists(clone: Path, branch: str) -> bool:
    return bool(_git(clone, "branch", "--list", branch).strip())


class TestMorningPruneRemoval:
    def test_positive_control_clean_pushed_worktree_is_still_removed(
        self, registry: Path
    ) -> None:
        worktree = _worktree(registry, "OMN-1", "wt-clean")

        attempt = prune.prune_worktree(_decision(worktree, "wt-clean"))

        assert attempt.ok is True, attempt.detail
        assert not worktree.exists()
        assert attempt.snapshot and Path(attempt.snapshot).is_dir()
        assert [Path(attempt.snapshot)] == _snapshots(registry)

    def test_an_ignored_env_file_is_saved_before_the_removal_deletes_it(
        self, registry: Path
    ) -> None:
        """RED on the pre-image: plain `git worktree remove` deletes ignored files."""
        worktree = _worktree(registry, "OMN-2", "wt-env")
        (worktree / ".env").write_text("TOKEN=not-a-real-secret\n", encoding="utf-8")
        (worktree / ".venv").mkdir()
        (worktree / ".venv" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")

        attempt = prune.prune_worktree(_decision(worktree, "wt-env"))

        assert attempt.ok is True, attempt.detail
        assert not worktree.exists()
        (saved,) = _snapshots(registry)
        assert _archived(saved) == {".env"}

    def test_a_failed_save_removes_nothing_and_keeps_the_branch(
        self, registry: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worktree = _worktree(registry, "OMN-3", "wt-keep")
        (worktree / ".env").write_text("TOKEN=x\n", encoding="utf-8")
        monkeypatch.delenv("OMNI_HOME")

        attempt = prune.prune_worktree(_decision(worktree, "wt-keep"))

        assert attempt.ok is False
        assert "snapshot" in attempt.detail
        assert worktree.is_dir() and (worktree / ".env").is_file()
        assert _branch_exists(registry / "omnibase_infra", "wt-keep")
        assert _git(worktree, "symbolic-ref", "--short", "HEAD").strip() == "wt-keep"


class TestMorningPruneDebris:
    def _debris(self, registry: Path, ticket: str) -> tuple[Path, object]:
        root = registry / "omni_worktrees"
        clone = registry / "omnibase_infra"
        worktree = _worktree(registry, ticket, f"wt-{ticket.lower()}")
        (worktree / ".git").unlink()
        owners = {
            path: (clone, state)
            for path, state in prune.collect_worktree_list_entries(clone).items()
        }
        decision = prune.classify_partial_mutation_debris(
            prune.collect_debris_facts(worktree, root, owners)
        )
        return worktree, decision

    def test_positive_control_reachable_debris_is_saved_then_removed(
        self, registry: Path
    ) -> None:
        """The debris pass already refuses any file not reachable as a blob
        (a .env included); what it removes is saved first all the same."""
        worktree, decision = self._debris(registry, "OMN-4")

        attempt = prune.remediate_debris(decision, registry / "omnibase_infra")

        assert attempt.ok is True, attempt.detail
        assert not worktree.exists()
        (saved,) = _snapshots(registry)
        assert attempt.snapshot == str(saved)
        assert _archived(saved) == {".gitignore", "app.py"}

    def test_debris_is_kept_when_the_save_fails(
        self, registry: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worktree, decision = self._debris(registry, "OMN-5")
        monkeypatch.delenv("OMNI_HOME")

        attempt = prune.remediate_debris(decision, registry / "omnibase_infra")

        assert attempt.ok is False
        assert "snapshot" in attempt.detail
        assert worktree.is_dir()
