# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read back real non-atomic git removals [OMN-18826 AC1/AC3/AC4]."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumPruneDisposition,
)

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
SESSION_END = ROOT / "plugins/onex/hooks/scripts/session-end.sh"
SNAPSHOT_HELPER = SCRIPTS / "worktree_removal_snapshot.py"
CHMOD = pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses chmod permissions")


def _load_pruner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "worktree_auto_prune_omn18826", SCRIPTS / "worktree_auto_prune.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prune = _load_pruner()


@pytest.fixture
def readback() -> ModuleType:
    return importlib.import_module("worktree_removal_snapshot")


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables that override ``-C`` (OMN-18434)."""
    return {key: value for key, value in env.items() if key not in _GIT_LOCATION}


_GIT_LOCATION = frozenset(
    (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
    )
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=scrub_git_location_env(os.environ),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _git_ok(cwd: Path, *args: str) -> str:
    proc = _git(cwd, *args)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Git's hook environment overrides -C; never let a scratch test touch it.
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "omn18826")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "omn18826@example.invalid")
    registry = tmp_path / "registry"
    clone = registry / "omnibase_infra"
    clone.mkdir(parents=True)
    _git_ok(tmp_path, "init", "-q", "--bare", "-b", "dev", str(tmp_path / "origin.git"))
    _git_ok(clone, "init", "-q", "-b", "dev")
    (clone / "locked").mkdir()
    (clone / "locked/keep.txt").write_text("survivor\n", encoding="utf-8")
    (clone / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_ok(clone, "add", "-A")
    _git_ok(clone, "commit", "-q", "-m", "init")
    _git_ok(clone, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git_ok(clone, "push", "-qu", "origin", "dev")
    monkeypatch.setenv("OMNI_HOME", str(registry))
    monkeypatch.delenv("ONEX_WORKTREES_ROOT", raising=False)
    return registry


def _worktree(registry: Path, ticket: str = "OMN-1") -> Path:
    worktree = registry / "omni_worktrees" / ticket / "omnibase_infra"
    _git_ok(
        registry / "omnibase_infra",
        "worktree",
        "add",
        "-q",
        "-b",
        f"wt-{ticket}",
        str(worktree),
        "origin/dev",
    )
    return worktree


@pytest.fixture
def locked_worktree(registry: Path) -> Iterator[Path]:
    worktree = _worktree(registry)
    locked = worktree / "locked"
    locked.chmod(0o500)
    try:
        yield worktree
    finally:
        if locked.exists():
            locked.chmod(0o700)


def _decision(worktree: Path) -> object:
    return prune.ModelWorktreePruneDecision(
        path=str(worktree),
        ticket=worktree.parent.name,
        repo="omnibase_infra",
        branch=f"wt-{worktree.parent.name}",
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


@CHMOD
def test_real_partial_removal(
    readback: ModuleType, registry: Path, locked_worktree: Path
) -> None:
    admin = readback.read_gitdir_pointer(locked_worktree)
    assert admin and admin.is_dir()
    proc = _git(registry / "omnibase_infra", "worktree", "remove", str(locked_worktree))
    assert proc.returncode != 0 and "failed to delete" in proc.stderr
    assert not admin.exists() and locked_worktree.exists()
    result = readback.classify_failed_removal(locked_worktree, admin)
    assert result.classification == "partially_removed"
    assert result.survivors >= 1
    assert result.detail == (
        f"partially_removed: admin dir {admin} deleted, {result.survivors} files remain; "
        "destroyed, unrecoverable in place"
    )
    with pytest.raises(FrozenInstanceError):
        result.detail = "changed"


def test_deletable_control(readback: ModuleType, registry: Path) -> None:
    worktree = _worktree(registry)
    admin = readback.read_gitdir_pointer(worktree)
    _git_ok(registry / "omnibase_infra", "worktree", "remove", str(worktree))
    result = readback.classify_failed_removal(worktree, admin)
    assert (result.classification, result.survivors, result.detail) == (
        "removed",
        0,
        "removed",
    )


def test_half_removed_scan_and_clean_control(
    readback: ModuleType, registry: Path
) -> None:
    healthy = _worktree(registry)
    assert readback.is_half_removed(healthy) is False
    assert readback.find_half_removed_worktrees([healthy]) == []
    broken = _worktree(registry, "OMN-2")
    admin = readback.read_gitdir_pointer(broken)
    shutil.rmtree(admin)
    assert readback.is_half_removed(broken) is True
    assert readback.find_half_removed_worktrees([healthy, broken]) == [broken]


def test_pointer_parsing_and_survivors(readback: ModuleType, tmp_path: Path) -> None:
    worktree = tmp_path / "tree"
    worktree.mkdir()
    pointer = worktree / ".git"
    assert readback.read_gitdir_pointer(worktree) is None
    pointer.mkdir()
    assert readback.read_gitdir_pointer(worktree) is None
    pointer.rmdir()
    for malformed in ("", "gitdir:", "gitdir: \n", "other: target\ngitdir: target"):
        pointer.write_text(malformed, encoding="utf-8")
        assert readback.read_gitdir_pointer(worktree) is None
        assert not readback.is_half_removed(worktree)
    pointer.write_text("gitdir: ../admin\nignored\n", encoding="utf-8")
    assert readback.read_gitdir_pointer(worktree) == tmp_path / "admin"
    (worktree / "regular").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "excluded").write_text("x", encoding="utf-8")
    (worktree / "symlink-dir").symlink_to(outside, target_is_directory=True)
    (worktree / "symlink-file").symlink_to(outside / "excluded")
    assert readback.classify_failed_removal(worktree, tmp_path / "admin").survivors == 2
    assert readback.classify_failed_removal(worktree, None).classification == "refused"
    (tmp_path / "admin").mkdir()
    result = readback.classify_failed_removal(worktree, tmp_path / "admin")
    assert result.classification == "refused"
    assert result.detail == f"refused: admin dir {tmp_path / 'admin'} intact"


@CHMOD
def test_survivors_tolerate_unreadable_directories(
    readback: ModuleType, tmp_path: Path
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "file").touch()
    locked.chmod(0)
    try:
        assert readback.classify_failed_removal(tmp_path, None).survivors == 0
    finally:
        locked.chmod(0o700)


@CHMOD
def test_pruner_records_partial_removal_and_recovery(
    registry: Path,
    locked_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = _git_ok(locked_worktree, "rev-parse", "HEAD")
    restore = Mock(
        side_effect=AssertionError("cannot restore through a missing admin dir")
    )
    monkeypatch.setattr(prune, "restore_branch", restore)
    attempt = prune.prune_worktree(_decision(locked_worktree))
    assert attempt.partially_removed is True
    assert not attempt.ok and not attempt.timed_out and attempt.exit_code != 0
    assert "partially_removed" in attempt.detail
    assert "failed to delete" in attempt.stderr
    assert attempt.head_oid == head
    assert (
        f"reconstruct from head {head}; snapshot {attempt.snapshot}" in attempt.detail
    )
    saved = Path(attempt.snapshot)
    assert saved.is_dir()
    manifest = (saved / "MANIFEST.txt").read_text(encoding="utf-8")
    assert str(locked_worktree) in manifest and head in manifest
    restore.assert_not_called()
    report = prune.render_report(
        [],
        root=registry / "omni_worktrees",
        executed=True,
        generated_at="test",
        removals=[attempt],
        tracker_resolved=0,
    )
    assert "| partially_removed |" in report


def test_pruner_refusal_and_success_controls(registry: Path) -> None:
    worktree = _worktree(registry)
    head = _git_ok(worktree, "rev-parse", "HEAD")
    untracked = worktree / "untracked"
    untracked.write_text("must refuse", encoding="utf-8")
    attempt = prune.prune_worktree(_decision(worktree))
    assert not attempt.partially_removed and not attempt.ok
    assert attempt.detail.startswith("git worktree remove refused")
    assert attempt.head_oid == head
    assert (worktree / ".git").exists()
    assert _git_ok(worktree, "symbolic-ref", "--short", "HEAD") == "wt-OMN-1"
    untracked.unlink()
    attempt = prune.prune_worktree(_decision(worktree))
    assert attempt.ok and not attempt.partially_removed
    assert attempt.head_oid == head


@pytest.mark.parametrize("no_debris", [True, False])
def test_main_reports_half_removed_without_classifying(
    readback: ModuleType,
    registry: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_debris: bool,
) -> None:
    healthy = _worktree(registry)
    broken = _worktree(registry, "OMN-2")
    admin = readback.read_gitdir_pointer(broken)
    shutil.rmtree(admin)
    ledger = registry / "ledger.md"
    ledger.write_text("", encoding="utf-8")
    report_md, report_json = registry / "report.md", registry / "report.json"
    collect = prune.collect_facts

    def collect_healthy(worktree: Path, *args: object, **kwargs: object) -> object:
        assert worktree == healthy, "half-removed trees must never reach git probes"
        return collect(worktree, *args, **kwargs)

    monkeypatch.setattr(prune, "collect_facts", collect_healthy)
    assert (
        prune.main(
            [
                "--worktrees-root",
                str(registry / "omni_worktrees"),
                "--ledger",
                str(ledger),
                "--no-tracker",
                "--no-pr-state",
                "--no-fetch",
                "--no-checkpoint",
                "--report-md",
                str(report_md),
                "--report-json",
                str(report_json),
                *(["--no-debris"] if no_debris else []),
            ]
        )
        == 0
    )
    data = json.loads(report_json.read_text(encoding="utf-8"))
    assert data["half_removed_count"] == 1
    assert data["half_removed"] == [{"path": str(broken), "gitdir": str(admin)}]
    assert [row["path"] for row in data["decisions"]] == [str(healthy)]
    assert data["scanned"] == 2
    assert data["accounting"]["worktrees_before"] == 2
    assert data["accounting"]["worktrees_after_expected"] == 2
    markdown = report_md.read_text(encoding="utf-8")
    assert "## Half-removed worktrees (1)" in markdown
    # Reports strip the registry prefix from every path for publication.
    portable_path = broken.relative_to(registry)
    portable_admin = admin.relative_to(registry)
    assert (
        f"- `{portable_path}` — partially_removed: .git points at a missing admin dir "
        f"({portable_admin})" in markdown
    )
    assert (
        "Half-removed worktrees: 1 (.git points at a missing admin dir; reported, never removed)"
        in capsys.readouterr().out
    )
    assert broken.exists() and healthy.exists()


def test_report_empty_half_removed_section(registry: Path) -> None:
    report = prune.render_report(
        [],
        root=registry / "omni_worktrees",
        executed=False,
        generated_at="test",
        removals=[],
        tracker_resolved=0,
    )
    assert "## Half-removed worktrees (0)\n\nNone." in report


def _session_end_function(tmp: Path) -> Path:
    """The removal function exactly as session-end.sh defines it."""
    source = SESSION_END.read_text(encoding="utf-8")
    start = source.index("_wt_remove_with_readback() {")
    end = source.index("\n}\n", start) + 3
    snippet = tmp / "wt_remove_with_readback.sh"
    snippet.write_text(source[start:end], encoding="utf-8")
    return snippet


def _shell_remove(
    registry: Path, worktree: Path, snapshot_helper: Path = SNAPSHOT_HELPER
) -> tuple[int, str]:
    log_file = registry / "removal.log"
    proc = subprocess.run(
        [
            "bash",
            "-c",
            """
set -euo pipefail
source "$1"
LOG_FILE=$2
PYTHON_CMD=$3
_wt_snapshot_helper=$4
log() { printf '%s\\n' "$*" >> "$LOG_FILE"; }
rc=0
_wt_remove_with_readback "$5" "$6" || rc=$?
exit "$rc"
""",
            "test",
            str(_session_end_function(registry)),
            str(log_file),
            sys.executable,
            str(snapshot_helper),
            str(registry / "omnibase_infra"),
            str(worktree),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.stderr == "", proc.stderr
    return proc.returncode, log_file.read_text(
        encoding="utf-8"
    ) if log_file.exists() else ""


@CHMOD
def test_session_end_partial_removal(registry: Path, locked_worktree: Path) -> None:
    rc, log = _shell_remove(registry, locked_worktree)
    assert rc == 1
    stale = next(line for line in log.splitlines() if line.startswith("STALE:"))
    assert "failed to delete" in stale
    assert re.search(r"exit [1-9]\d*", stale)
    assert f"PARTIALLY_REMOVED: {locked_worktree} - partially_removed:" in log
    assert "(snapshot saved before removal)" in log


def test_session_end_deletable_control(registry: Path) -> None:
    worktree = _worktree(registry)
    rc, _ = _shell_remove(registry, worktree)
    assert rc == 0 and not worktree.exists()


def test_session_end_calls_extracted_removal() -> None:
    source = SESSION_END.read_text(encoding="utf-8")
    assert 'if _wt_remove_with_readback "$_wt_parent_repo" "$_wt_dir"' in source
    assert "git worktree remove failed (see log)" not in source
    # The save runs inside the same function, before the removal [OMN-19539].
    start = source.index("_wt_remove_with_readback() {")
    assert (
        start
        < source.index('"$PYTHON_CMD" "$_wt_snapshot_helper"', start)
        < source.index('git -C "$_wt_parent_repo" worktree remove', start)
    )


def test_session_end_missing_snapshot_helper_keeps_tree(registry: Path) -> None:
    worktree = _worktree(registry)
    rc, log = _shell_remove(registry, worktree, registry / "no-such-helper.py")
    assert rc == 2 and worktree.exists()
    assert "snapshot helper missing, nothing is removed unsaved" in log


@CHMOD
def test_session_end_partial_removal_left_a_snapshot(
    registry: Path, locked_worktree: Path
) -> None:
    head = _git_ok(locked_worktree, "rev-parse", "HEAD")
    rc, _ = _shell_remove(registry, locked_worktree)
    assert rc == 1
    manifests = list((registry / ".onex_state").rglob("MANIFEST.txt"))
    assert manifests, "no pre-removal snapshot was written"
    manifest = manifests[0].read_text(encoding="utf-8")
    assert f"worktree={locked_worktree}" in manifest
    assert f"head={head}" in manifest
