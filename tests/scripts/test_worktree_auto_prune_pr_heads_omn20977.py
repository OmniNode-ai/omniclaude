# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The pruner's pull-request state comes from ``onex scm pr-heads`` (OMN-20977).

Lanes may no longer call ``gh pr list``, so the merged-PR limb read nothing and
the tools deleted nothing. ``onex scm pr-heads OWNER/REPO --source local``
(omnimarket PR #3776) answers every PR's number, head oid, state and merge
commit from the PR watcher state and the canonical clone alone, and this file
holds worktree_auto_prune.py's consumer contract for it:

* ``collect_branch_pr_states`` maps a MERGED row's head branch to
  ``(MERGED, head_oid)`` — the policy separately requires that oid to be the
  worktree's HEAD — and an OPEN row's branch to ``NOT_MERGED``;
* ``collect_open_pr_branches`` (the OMN-19399 fence) reads OPEN rows only
  behind a fresh watcher tick, and holds (``None``) on any failure: pr-heads
  downgrades OPEN rows to UNMERGED once the watcher state is stale, which must
  never read as "no open pull request";
* end to end, an OPEN pull request's worktree and a worktree with uncommitted
  changes are never removed, and a merged one is.

The fixture is a recording of the real command against the omniclaude
canonical clone on 2026-10-13, trimmed to the newest rows plus two older ones
chosen for their shape (a MERGED row that still names its head branch, and an
UNMERGED row); every row and the envelope are verbatim. Most MERGED rows carry ``head_ref: null`` — the branch is gone
after the merge — which is why the head oid, not the branch name, is the
primary key of the merged decision.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from omniclaude.hooks.lib.worktree_prune_policy import EnumBranchPrState

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_auto_prune.py"
)
_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "pr_heads_omniclaude_omn20977.json"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "worktree_auto_prune_pr_heads", _MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()

_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "omn20977",
    "GIT_COMMITTER_NAME": "omn20977",
    "GIT_AUTHOR_EMAIL": "omn20977@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn20977@example.invalid",
}


def _git_ok(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=scrub_git_location_env(_GIT_ENV),
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _recorded() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _recorded_rows() -> list[dict[str, Any]]:
    return _recorded()["result"]["prs"]


def _variant(**changes: object) -> dict[str, Any]:
    answer = _recorded()
    answer.update(changes)
    return answer


def _with_rows(rows: list[dict[str, object]], **changes: object) -> dict[str, Any]:
    answer = _variant(**changes)
    result = dict(answer["result"])
    result["prs"] = rows
    answer["result"] = result
    return answer


def _row(number: int, state: str, head_ref: str | None, oid: str) -> dict[str, object]:
    return {
        "number": number,
        "state": state,
        "head_oid": oid,
        "head_ref": head_ref,
        "base_ref": "dev",
        "merge_commit_sha": "d" * 40 if state == "MERGED" else None,
        "merged_at": None,
    }


A = "a" * 40
B = "b" * 40
MERGED_WITH_BRANCH = next(
    row for row in _recorded_rows() if row["state"] == "MERGED" and row.get("head_ref")
)


# ------------------------------------------------ collect_branch_pr_states
@pytest.mark.unit
def test_branch_states_map_merged_rows_by_head_branch() -> None:
    """A MERGED row names its head branch MERGED at its head oid; a row whose
    branch is gone (head_ref null) maps nothing by name; a branch the clone
    cannot classify (UNMERGED) is absent, exactly as the gh listing left it."""
    states = mod.collect_branch_pr_states_from_answer(_recorded())
    ref = MERGED_WITH_BRANCH["head_ref"]
    assert states[ref] == (
        EnumBranchPrState.MERGED,
        MERGED_WITH_BRANCH["head_oid"],
    )
    gone = [
        row
        for row in _recorded_rows()
        if row["state"] == "MERGED" and not row.get("head_ref")
    ]
    assert gone, "the recording must hold merged rows whose branch is gone"
    assert all(not row.get("head_ref") for row in gone)
    unmerged = next(row for row in _recorded_rows() if row["state"] == "UNMERGED")
    assert unmerged["head_ref"] not in states


def test_open_then_merged_precedence_is_preserved() -> None:
    """A branch reused after its merge reads MERGED at the merged head oid —
    the oid, not the state, then decides limb (b). Same order as the gh calls."""
    rows = [
        _row(10, "OPEN", "reused/branch", B),
        _row(9, "MERGED", "reused/branch", A),
    ]
    states = mod.collect_branch_pr_states_from_answer(_with_rows(rows))
    assert states["reused/branch"] == (EnumBranchPrState.MERGED, A)


def test_an_open_row_maps_not_merged() -> None:
    rows = [_row(11, "OPEN", "lane/omn-20977-open", A)]
    states = mod.collect_branch_pr_states_from_answer(
        _with_rows(rows, watcher_tick=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    )
    assert states["lane/omn-20977-open"] == (EnumBranchPrState.NOT_MERGED, None)


def test_a_failed_pr_heads_answer_is_an_empty_map() -> None:
    assert mod.collect_branch_pr_states_from_answer(None) == {}


# ---------------------------------------------- collect_open_pr_branches
def _fence_answer(tick: str | None, rows: list[dict[str, object]]) -> dict[str, Any]:
    return _with_rows(rows, watcher_tick=tick)


def test_the_fence_reads_open_rows_behind_a_fresh_tick() -> None:
    tick = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        _row(31, "OPEN", "lane/omn-20977-open", A),
        _row(30, "MERGED", "lane/omn-20977-done", B),
        _row(29, "UNMERGED", "lane/omn-20977-unknown", A),
    ]
    open_branches = mod.collect_open_pr_branches_from_answer(_fence_answer(tick, rows))
    assert open_branches == frozenset({"lane/omn-20977-open"})


def test_the_fence_holds_when_the_watcher_tick_is_stale() -> None:
    """Nine minutes old: pr-heads has already downgraded every OPEN row to
    UNMERGED, so the open set would silently miss real open pull requests."""
    stale = (datetime.now(UTC) - timedelta(minutes=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [_row(31, "OPEN", "lane/omn-20977-open", A)]
    assert mod.collect_open_pr_branches_from_answer(_fence_answer(stale, rows)) is None


def test_the_fence_holds_without_a_watcher_tick() -> None:
    """The raw recording carries watcher_tick null: no OPEN row can exist."""
    rows = [_row(31, "OPEN", "lane/omn-20977-open", A)]
    assert mod.collect_open_pr_branches_from_answer(_fence_answer(None, rows)) is None


def test_the_fence_holds_a_truncated_answer() -> None:
    tick = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    answer = _fence_answer(tick, [_row(31, "OPEN", "lane/omn-20977-open", A)])
    answer["result"]["truncated"] = True
    assert mod.collect_open_pr_branches_from_answer(answer) is None


def test_the_fence_holds_when_pr_heads_cannot_answer() -> None:
    assert mod.collect_open_pr_branches_from_answer(None) is None


# --------------------------------------------------------- the onex command
def test_the_onex_command_resolves_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEX_SCM_CLI", "/stub/onex --flag")
    assert mod.resolve_onex_command() == ["/stub/onex", "--flag"]


def test_the_onex_command_defaults_to_the_internal_venv_then_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONEX_SCM_CLI", raising=False)
    monkeypatch.delenv("OMNIBASE_INTERNAL_HOME", raising=False)
    assert mod.resolve_onex_command() == ["onex"]


# --------------------------------------------------- end to end (real git)
@pytest.fixture
def clean_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """One clean worktree at origin/dev, on branch OMN-20977-BRANCH."""
    origin = tmp_path / "origin.git"
    _git_ok(tmp_path, "init", "-q", "--bare", "-b", "dev", str(origin))
    canonical = tmp_path / "canonical" / "omniclaude"
    canonical.parent.mkdir(parents=True)
    _git_ok(tmp_path, "clone", "-q", str(origin), str(canonical))
    (canonical / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_ok(canonical, "add", "-A")
    _git_ok(canonical, "commit", "-q", "-m", "init")
    _git_ok(canonical, "push", "-q", "origin", "HEAD:dev")
    _git_ok(canonical, "fetch", "-q", "origin")

    root = tmp_path / "omni_worktrees"
    worktree = root / "OMN-20977" / "omniclaude"
    worktree.parent.mkdir(parents=True)
    _git_ok(
        canonical,
        "worktree",
        "add",
        "-q",
        str(worktree),
        "-b",
        "lane/omn-20977-merged",
        "origin/dev",
    )
    ledger = tmp_path / "ledger.md"
    ledger.write_text("", encoding="utf-8")
    return root, ledger


def _run_main(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, object] | None,
    *extra: str,
) -> tuple[dict[str, object], Path]:
    root, ledger = clean_worktree
    worktree = root / "OMN-20977" / "omniclaude"
    monkeypatch.setattr(mod, "run_pr_heads", lambda _canonical: answer)
    report = tmp_path / "report.json"
    argv = [
        "--worktrees-root",
        str(root),
        "--ledger",
        str(ledger),
        "--no-fetch",
        "--no-tracker",
        "--no-debris",
        "--no-checkpoint",
        "--no-registration-prune",
        "--report-json",
        str(report),
        *extra,
    ]
    assert mod.main(argv) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    rows = [d for d in payload["decisions"] if d["branch"] == "lane/omn-20977-merged"]
    assert len(rows) == 1
    return rows[0], worktree


def _merged_answer(head_oid: str) -> dict[str, object]:
    tick = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        _row(41, "MERGED", "lane/omn-20977-merged", head_oid),
        _row(40, "OPEN", "someone/else", B),
    ]
    return _with_rows(rows, watcher_tick=tick)


def test_a_merged_pr_worktree_is_pruned_from_pr_heads(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ledger = clean_worktree
    worktree = root / "OMN-20977" / "omniclaude"
    answer = _merged_answer(_git_ok(worktree, "rev-parse", "HEAD"))
    row, removed = _run_main(clean_worktree, tmp_path, monkeypatch, answer, "--execute")
    assert row["disposition"] == "prune"
    assert not removed.exists()


def test_an_open_pr_worktree_is_never_removed(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OMN-19399 fence over pr-heads: an OPEN row names the branch, and
    --execute still removes nothing."""
    tick = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [_row(42, "OPEN", "lane/omn-20977-merged", A)]
    answer = _with_rows(rows, watcher_tick=tick)
    row, kept = _run_main(
        clean_worktree, tmp_path, monkeypatch, answer, "--hold-open-pr", "--execute"
    )
    assert row["disposition"] == "triage"
    assert "open_pr_fence" in row["block_reasons"]
    assert kept.is_dir()


def test_a_worktree_with_uncommitted_changes_is_never_removed(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a MERGED row at the exact HEAD cannot authorize removing a tree
    with uncommitted changes."""
    root, _ledger = clean_worktree
    worktree = root / "OMN-20977" / "omniclaude"
    (worktree / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    answer = _merged_answer(_git_ok(worktree, "rev-parse", "HEAD"))
    row, kept = _run_main(clean_worktree, tmp_path, monkeypatch, answer, "--execute")
    assert row["disposition"] == "triage"
    assert "dirty_tree" in row["block_reasons"]
    assert kept.is_dir()
