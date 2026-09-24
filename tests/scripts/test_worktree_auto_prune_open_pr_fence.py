# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The classifier's opt-in open-pull-request fence, end to end [OMN-19399].

The unattended morning prune runs under a standing consent whose OUT OF SCOPE
list names "any worktree whose branch has an OPEN pull request". On
2026-09-24 the lane executing the first such removal found three open-PR
worktrees the pushed-at-HEAD limb would have removed and fenced them by hand in
its ledger claim. `--hold-open-pr` is that fence as a flag the unattended runner
passes every morning, so no lane has to find them first.

Real throwaway git repos (a bare origin, a canonical clone, one clean worktree
at origin/dev) so the row is PRUNE-eligible on every other fact. The only stub
is the GitHub listing, which no unit test can perform for real.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from omniclaude.hooks.lib.worktree_prune_policy import EnumBranchPrState

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_auto_prune.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "worktree_auto_prune_open_pr", _MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()

_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "omn19399",
    "GIT_COMMITTER_NAME": "omn19399",
    "GIT_AUTHOR_EMAIL": "omn19399@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn19399@example.invalid",
}

BRANCH = "lane/omn-5151-in-review"
CONTROL_BRANCH = "lane/omn-0001-control-merged"


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


@pytest.fixture
def clean_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """One clean worktree at origin/dev: limb (a), no claim. Prunable today."""
    origin = tmp_path / "origin.git"
    _git_ok(tmp_path, "init", "-q", "--bare", "-b", "dev", str(origin))
    canonical = tmp_path / "canonical" / "omnibase_infra"
    canonical.parent.mkdir(parents=True)
    _git_ok(tmp_path, "clone", "-q", str(origin), str(canonical))
    (canonical / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_ok(canonical, "add", "-A")
    _git_ok(canonical, "commit", "-q", "-m", "init")
    _git_ok(canonical, "push", "-q", "origin", "HEAD:dev")
    _git_ok(canonical, "fetch", "-q", "origin")

    root = tmp_path / "omni_worktrees"
    worktree = root / "OMN-5151" / "omnibase_infra"
    worktree.parent.mkdir(parents=True)
    _git_ok(
        canonical, "worktree", "add", "-q", str(worktree), "-b", BRANCH, "origin/dev"
    )

    ledger = tmp_path / "ledger.md"
    ledger.write_text("", encoding="utf-8")
    return root, ledger


@pytest.fixture(autouse=True)
def stub_pr_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """A NON-EMPTY state map, so the row's state reads as observed, not UNKNOWN."""
    monkeypatch.setattr(
        mod,
        "collect_branch_pr_states",
        lambda _c: {CONTROL_BRANCH: (EnumBranchPrState.MERGED, "0" * 40)},
    )


def _row(root: Path, ledger: Path, tmp_path: Path, *extra: str) -> dict[str, object]:
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
        "--report-json",
        str(report),
        *extra,
    ]
    assert mod.main(argv) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    rows = [d for d in payload["decisions"] if d["branch"] == BRANCH]
    assert len(rows) == 1
    return rows[0]


def test_without_the_flag_the_clean_row_is_prunable(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control: the fixture really is a removal without the fence."""
    monkeypatch.setattr(mod, "collect_open_pr_branches", lambda _c: frozenset({BRANCH}))
    row = _row(*clean_worktree, tmp_path)
    assert row["disposition"] == "prune"


def test_the_flag_holds_a_row_whose_branch_has_an_open_pr(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mod, "collect_open_pr_branches", lambda _c: frozenset({BRANCH}))
    row = _row(*clean_worktree, tmp_path, "--hold-open-pr")
    assert row["disposition"] == "triage"
    assert "open_pr_fence" in row["block_reasons"]


def test_the_flag_holds_every_row_when_the_open_listing_fails(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mod, "collect_open_pr_branches", lambda _c: None)
    row = _row(*clean_worktree, tmp_path, "--hold-open-pr")
    assert row["disposition"] == "triage"
    assert "open_pr_fence" in row["block_reasons"]


def test_the_flag_releases_a_row_the_open_listing_does_not_name(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mod, "collect_open_pr_branches", lambda _c: frozenset({"someone/else"})
    )
    row = _row(*clean_worktree, tmp_path, "--hold-open-pr")
    assert row["disposition"] == "prune"


def test_a_truncated_open_listing_is_not_a_resolved_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A listing that came back AT its limit may have dropped the branch."""

    class _Done:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            [{"headRefName": f"b{i}"} for i in range(mod.GH_OPEN_PR_LIMIT)]
        )

    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k: _Done())
    assert mod.collect_open_pr_branches(tmp_path) is None


def test_a_failed_open_listing_is_none_never_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _Failed:
        returncode = 1
        stderr = "API rate limit exceeded"
        stdout = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k: _Failed())
    assert mod.collect_open_pr_branches(tmp_path) is None


def test_a_pr_opened_during_the_scan_is_caught_at_removal_time(
    clean_worktree: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The removal pass re-reads the open listing fresh, per the revalidation
    contract: a row judged with no open PR and opened for review before its
    removal is skipped, never removed."""
    answers = iter([frozenset(), frozenset({BRANCH})])
    monkeypatch.setattr(mod, "collect_open_pr_branches", lambda _c: next(answers))
    root, ledger = clean_worktree
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
        "--hold-open-pr",
        "--execute",
        "--report-json",
        str(report),
    ]
    assert mod.main(argv) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["prune_count"] == 1
    assert payload["revalidation_refusal_count"] == 1
    assert payload["accounting"]["removed"] == 0
    assert (root / "OMN-5151" / "omnibase_infra").is_dir()
