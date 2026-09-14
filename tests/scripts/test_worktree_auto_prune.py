# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for worktree_auto_prune.py's fact collection [OMN-16901].

The pure predicate itself is covered by
``tests/unit/hooks/lib/test_worktree_prune_policy.py``. These tests cover the
fact-collection half — the parts that decide *what the predicate is told*, where
a bug is just as capable of deleting live work:

* ledger claim-awareness (the OMN-15551 hazard: a lane that re-claimed a closed
  ticket must block the prune),
* stash attribution to a branch (stashes are repo-wide, worktrees are not),
* tracker state mapping (only ``completed``/``canceled`` are terminal).

No network calls, no subprocesses.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumDebrisRemediation,
    EnumPruneBlockReason,
    EnumPruneDisposition,
    EnumTicketLifecycle,
)

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_auto_prune.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worktree_auto_prune", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# =============================================================================
# Ledger claim-awareness
# =============================================================================


class TestParseLedgerClaims:
    def test_terminal_row_without_later_claim_is_closed(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "| 2026-08-01T10:00:00Z | lane-a | OMN-1234 | CLAIM | started |\n"
            "| 2026-08-02T10:00:00Z | lane-a | OMN-1234 | TERMINAL | landed |\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is True
        assert open_claim is None

    def test_claim_after_terminal_reopens_the_ticket(self, tmp_path: Path) -> None:
        """The OMN-15551 hazard: a live lane resumed work on a closed ticket."""
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "| 2026-08-02T10:00:00Z | lane-a | OMN-1234 | TERMINAL | landed |\n"
            "| 2026-08-03T10:00:00Z | lane-b | OMN-1234 | CLAIM | repair lane |\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is True
        assert open_claim is not None
        assert "repair lane" in open_claim

    def test_claim_plus_terminal_on_one_line_resolves_to_terminal(
        self, tmp_path: Path
    ) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "### OMN-1234 — a lane\n\n- **Status:** CLAIM+TERMINAL\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is True
        assert open_claim is None

    def test_section_body_inherits_the_ticket_from_its_heading(
        self, tmp_path: Path
    ) -> None:
        """`- **Status:** IN PROGRESS.` carries no ticket id of its own."""
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "### OMN-1234 — a lane (CLAIM)\n\n"
            "- **Scope:** something\n"
            "- **Status:** IN PROGRESS.\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is False
        assert open_claim is not None

    def test_prose_mentioning_a_ticket_is_not_a_claim(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "Some prose about the claim gate and OMN-1234 being terminal-ish.\n",
            encoding="utf-8",
        )
        assert mod.parse_ledger_claims(ledger) == {}

    def test_missing_ledger_returns_empty_map(self, tmp_path: Path) -> None:
        assert mod.parse_ledger_claims(tmp_path / "absent.md") == {}

    def test_tickets_are_tracked_independently(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "| t1 | lane | OMN-1 | TERMINAL | done |\n"
            "| t2 | lane | OMN-2 | CLAIM | live |\n",
            encoding="utf-8",
        )
        parsed = mod.parse_ledger_claims(ledger)
        assert parsed["OMN-1"] == (True, None)
        assert parsed["OMN-2"][0] is False
        assert parsed["OMN-2"][1] is not None


# =============================================================================
# Stash attribution — stashes are repo-wide, worktrees are not
# =============================================================================


class TestCountAttributedStashes:
    def test_counts_only_stashes_naming_this_branch(self) -> None:
        subjects = [
            "WIP on jonah/omn-1-a: 1234567 msg",
            "On jonah/omn-1-a: manual stash",
            "WIP on jonah/omn-2-b: 89abcde msg",
        ]
        assert mod.count_attributed_stashes(subjects, "jonah/omn-1-a") == 2
        assert mod.count_attributed_stashes(subjects, "jonah/omn-2-b") == 1

    def test_unrelated_branch_has_no_attributed_stash(self) -> None:
        subjects = ["WIP on other/branch: 1234567 msg"]
        assert mod.count_attributed_stashes(subjects, "jonah/omn-1-a") == 0

    def test_detached_head_attributes_nothing(self) -> None:
        assert mod.count_attributed_stashes(["WIP on x: y"], None) == 0

    def test_prefix_collision_does_not_over_attribute(self) -> None:
        """`WIP on feat/a-extended:` must not be attributed to `feat/a`."""
        subjects = ["WIP on feat/a-extended: 1234567 msg"]
        assert mod.count_attributed_stashes(subjects, "feat/a") == 0


# =============================================================================
# Tracker state mapping — only terminal states are terminal
# =============================================================================


class TestStateTypeToLifecycle:
    @pytest.mark.parametrize(
        ("state_type", "expected"),
        [
            ("completed", EnumTicketLifecycle.DONE),
            ("canceled", EnumTicketLifecycle.CANCELED),
            ("started", EnumTicketLifecycle.OPEN),
            ("unstarted", EnumTicketLifecycle.OPEN),
            ("backlog", EnumTicketLifecycle.OPEN),
            ("triage", EnumTicketLifecycle.OPEN),
            ("", EnumTicketLifecycle.OPEN),
        ],
    )
    def test_mapping(self, state_type: str, expected: EnumTicketLifecycle) -> None:
        assert mod._state_type_to_lifecycle(state_type) is expected


# =============================================================================
# Worktree discovery — a linked worktree's .git is a file, a clone's is a dir
# =============================================================================


class TestDiscoverWorktrees:
    def test_finds_linked_worktrees_and_ignores_full_clones(
        self, tmp_path: Path
    ) -> None:
        linked = tmp_path / "OMN-1" / "repo"
        linked.mkdir(parents=True)
        (linked / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")

        nested = tmp_path / "OMN-2" / "sub" / "repo"
        nested.mkdir(parents=True)
        (nested / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")

        clone = tmp_path / "OMN-3" / "repo"
        (clone / ".git").mkdir(parents=True)

        found = mod.discover_worktrees(tmp_path)
        assert linked in found
        assert nested in found
        assert clone not in found


# =============================================================================
# Real-git harness [OMN-16951] — the two defects under test both depend on
# git's actual behavior (stderr content on refusal, `worktree list --porcelain`
# annotations, object-database presence), so these tests run the real binary
# against real throwaway repos rather than mocking subprocess.
# =============================================================================

_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "omn16951",
    "GIT_COMMITTER_NAME": "omn16951",
    "GIT_AUTHOR_EMAIL": "omn16951@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn16951@example.invalid",
}


def _git_ok(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=_GIT_ENV,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc


@pytest.fixture
def canonical_repo(tmp_path: Path) -> Path:
    """A real, throwaway git clone with one committed file under `src/`."""
    canonical = tmp_path / "canonical" / "omnibase_infra"
    canonical.mkdir(parents=True)
    _git_ok(canonical, "init", "-q", "-b", "dev")
    (canonical / "src").mkdir()
    (canonical / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_ok(canonical, "add", "-A")
    _git_ok(canonical, "commit", "-q", "-m", "init")
    return canonical


# =============================================================================
# Defect 1 — refusal observability: stderr must reach the report
# =============================================================================


class TestGitCaptureAndPruneWorktreeStderr:
    def test_git_capture_returns_the_real_stderr_on_a_refusal(
        self, canonical_repo: Path
    ) -> None:
        code, _out, err = mod._git_capture(
            canonical_repo, "worktree", "remove", str(canonical_repo / "nonexistent")
        )
        assert code != 0
        assert err != "", "a real git refusal must not read as empty stderr"

    def test_prune_worktree_records_command_exit_code_and_real_stderr(
        self, tmp_path: Path, canonical_repo: Path
    ) -> None:
        """RED 1: a refused removal must surface stderr text in the report.

        Dirty the worktree so git itself refuses the removal (the second,
        independent safety gate the module's docstring promises), and prove
        the refusal reason actually reaches the ``ModelRemovalAttempt`` —
        never the old flat ``"no output"`` regardless of cause.
        """
        worktree = tmp_path / "omni_worktrees" / "OMN-1" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            canonical_repo, "worktree", "add", "-q", str(worktree), "-b", "wt-branch"
        )
        (worktree / "src" / "uncommitted.py").write_text(
            "DIRTY = True\n", encoding="utf-8"
        )

        decision = mod.ModelWorktreePruneDecision(
            path=str(worktree),
            ticket="OMN-1",
            repo="omnibase_infra",
            branch="wt-branch",
            disposition=EnumPruneDisposition.PRUNE,
            block_reasons=(),
            eligibility_evidence="test",
            safety_evidence="test",
            branch_content_preserved=True,
            dirty_file_count=0,
            commits_ahead=0,
            pr_state=EnumBranchPrState.NONE,
            ledger_open_claim=None,
        )

        attempt = mod.prune_worktree(decision)

        assert attempt.ok is False
        assert attempt.exit_code != 0
        assert attempt.stderr != "", "the refusal reason must not be swallowed"
        assert attempt.stderr != "no output"
        assert "worktree remove" in attempt.command
        assert str(worktree) in attempt.command
        assert worktree.is_dir(), "a refused removal must leave the tree untouched"


# =============================================================================
# OMN-18370 AC-1 / AC-2 — the branch delete goes through a guard-permitted path
#
# The canonical-clone `reference-transaction` guard refuses `refs/heads/*`
# deletion inside a canonical clone, by design. The shipped pruner deleted the
# branch there and lost that race 23 times out of 26 on 2026-09-14. These tests
# install a faithful stand-in for the guard's deny rule in a throwaway clone —
# with a POSITIVE CONTROL proving the stand-in actually refuses — and then
# require the pruner to leave no orphan branch anyway.
# =============================================================================


_GUARD_HOOK = """#!/usr/bin/env bash
# Stand-in for the canonical-clone reference-transaction guard's deny rule:
# refuse deleting a refs/heads/* ref when the invoking work tree is a canonical
# clone. A linked worktree's `.git` is a FILE, so the guard exits 0 there —
# which is the seam the pruner is required to use.
[ "$1" = "prepared" ] || exit 0
top=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -d "$top/.git" ] || exit 0
while read -r old new ref; do
  case "$ref" in
    refs/heads/*)
      if [ "$new" = "0000000000000000000000000000000000000000" ]; then
        echo "ERROR: refused deleting a branch in canonical clone: $ref" >&2
        exit 1
      fi
      ;;
  esac
done
exit 0
"""


@pytest.fixture
def guarded_canonical_repo(canonical_repo: Path, tmp_path: Path) -> Path:
    """`canonical_repo` plus an origin/dev base ref and the branch-delete guard."""
    _git_ok(canonical_repo, "update-ref", "refs/remotes/origin/dev", "HEAD")

    hooks_dir = tmp_path / "canonical-clone-hooks"
    hooks_dir.mkdir()
    hook = hooks_dir / "reference-transaction"
    hook.write_text(_GUARD_HOOK, encoding="utf-8")
    hook.chmod(0o755)
    _git_ok(canonical_repo, "config", "core.hooksPath", str(hooks_dir))
    return canonical_repo


def _decision(
    worktree: Path,
    branch: str | None,
    *,
    branch_content_preserved: bool = True,
    pr_state: EnumBranchPrState = EnumBranchPrState.NONE,
) -> object:
    return mod.ModelWorktreePruneDecision(
        path=str(worktree),
        ticket="OMN-1",
        repo="omnibase_infra",
        branch=branch,
        disposition=EnumPruneDisposition.PRUNE,
        block_reasons=(),
        eligibility_evidence="test",
        safety_evidence="test",
        branch_content_preserved=branch_content_preserved,
        dirty_file_count=0,
        commits_ahead=0,
        pr_state=pr_state,
        ledger_open_claim=None,
    )


def _branch_exists(clone: Path, branch: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(clone), "branch", "--list", branch],
        capture_output=True,
        text=True,
        env=_GIT_ENV,
        check=False,
        timeout=60,
    )
    return bool(proc.stdout.strip())


class TestBranchDeleteThroughAGuardPermittedPath:
    def test_positive_control_the_guard_actually_refuses_a_clone_side_delete(
        self, guarded_canonical_repo: Path
    ) -> None:
        """Without this control, a green AC-1 test proves only that no guard ran."""
        _git_ok(guarded_canonical_repo, "branch", "control-branch")
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(guarded_canonical_repo),
                "branch",
                "-D",
                "control-branch",
            ],
            capture_output=True,
            text=True,
            env=_GIT_ENV,
            check=False,
            timeout=60,
        )
        assert proc.returncode != 0
        assert "refused deleting a branch in canonical clone" in proc.stderr
        assert _branch_exists(guarded_canonical_repo, "control-branch")

    def test_prune_leaves_no_orphan_branch(
        self, guarded_canonical_repo: Path, tmp_path: Path
    ) -> None:
        """AC-1: after a prune, the local branch is gone and the guard refused nothing."""
        worktree = tmp_path / "omni_worktrees" / "OMN-1" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            guarded_canonical_repo,
            "worktree",
            "add",
            "-q",
            str(worktree),
            "-b",
            "wt-merged",
        )

        attempt = mod.prune_worktree(_decision(worktree, "wt-merged"))

        assert attempt.ok is True, attempt.detail
        assert not worktree.exists()
        assert not _branch_exists(guarded_canonical_repo, "wt-merged")
        assert "deleted" in attempt.branch_outcome
        assert "refused deleting a branch" not in attempt.detail

    def test_an_unmerged_branch_is_never_deleted(
        self, guarded_canonical_repo: Path, tmp_path: Path
    ) -> None:
        """AC-2: `git branch -d` is a real second opinion, not a formality.

        The decision is deliberately built as if the policy had approved the
        branch delete. git's own merged-into-HEAD check must still refuse it,
        because HEAD is detached onto the BASE and the branch's commit is not in
        it — and with no merged pull request there is no second proof either.
        """
        worktree = tmp_path / "omni_worktrees" / "OMN-1" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            guarded_canonical_repo,
            "worktree",
            "add",
            "-q",
            str(worktree),
            "-b",
            "wt-unmerged",
        )
        (worktree / "src" / "new.py").write_text("NEW = 1\n", encoding="utf-8")
        _git_ok(worktree, "add", "-A")
        _git_ok(worktree, "commit", "-q", "-m", "unmerged work")

        attempt = mod.prune_worktree(
            _decision(worktree, "wt-unmerged", branch_content_preserved=True)
        )

        assert _branch_exists(guarded_canonical_repo, "wt-unmerged"), (
            "an unmerged branch must survive the prune"
        )
        assert "kept" in attempt.branch_outcome

    def test_a_detached_worktree_reports_no_branch_to_delete(
        self, guarded_canonical_repo: Path, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "omni_worktrees" / "OMN-1" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            guarded_canonical_repo, "worktree", "add", "-q", "--detach", str(worktree)
        )

        attempt = mod.prune_worktree(_decision(worktree, None))

        assert attempt.ok is True, attempt.detail
        assert "no local branch" in attempt.branch_outcome

    def test_a_refused_removal_restores_the_branch_it_deleted(
        self,
        guarded_canonical_repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The branch delete happens BEFORE the removal, so a refusal must undo it."""
        worktree = tmp_path / "omni_worktrees" / "OMN-1" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            guarded_canonical_repo,
            "worktree",
            "add",
            "-q",
            str(worktree),
            "-b",
            "wt-restore",
        )

        real_run = mod._git_run

        def fake_run(cwd: Path, *args: str, timeout: int = 60):  # noqa: ANN202
            if args[:2] == ("worktree", "remove"):
                return mod.ModelGitResult(
                    exit_code=1,
                    stdout="",
                    stderr="fatal: injected refusal",
                    timed_out=False,
                    load_average=None,
                )
            return real_run(cwd, *args, timeout=timeout)

        monkeypatch.setattr(mod, "_git_run", fake_run)
        monkeypatch.setattr(mod, "_git_run_with_load_retry", fake_run)

        attempt = mod.prune_worktree(_decision(worktree, "wt-restore"))

        assert attempt.ok is False
        assert worktree.is_dir()
        assert _branch_exists(guarded_canonical_repo, "wt-restore")
        assert "restored" in attempt.detail


# =============================================================================
# OMN-18370 AC-4 — a removal timeout is a host reading, not a safety finding
# =============================================================================


class TestRemovalTimeoutHandling:
    def test_a_timeout_is_reported_with_the_load_and_never_as_a_refusal(
        self,
        guarded_canonical_repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-4 falsifier: an injected timeout produces a timed_out row with the load."""
        worktree = tmp_path / "omni_worktrees" / "OMN-1" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            guarded_canonical_repo,
            "worktree",
            "add",
            "-q",
            str(worktree),
            "-b",
            "wt-timeout",
        )

        real_run = mod._git_run

        def fake_run(cwd: Path, *args: str, timeout: int = 60):  # noqa: ANN202
            if args[:2] == ("worktree", "remove"):
                return mod.ModelGitResult(
                    exit_code=-1,
                    stdout="",
                    stderr=f"TimeoutExpired after {timeout}s",
                    timed_out=True,
                    load_average=127.4,
                )
            return real_run(cwd, *args, timeout=timeout)

        monkeypatch.setattr(mod, "_git_run", fake_run)
        # The host never calms down, so the retry window expires. Collapse the
        # window rather than sleeping through it.
        monkeypatch.setattr(mod, "LOAD_RETRY_MAX_WAIT_SECONDS", 0)
        monkeypatch.setattr(mod, "host_load_average", lambda: 127.4)

        attempt = mod.prune_worktree(_decision(worktree, "wt-timeout"))

        assert attempt.ok is False
        assert attempt.timed_out is True
        assert attempt.load_average == 127.4
        assert "127.4" in attempt.detail
        assert "Not a safety finding" in attempt.detail
        assert worktree.is_dir(), "a timed-out removal must leave the tree untouched"
        assert _branch_exists(guarded_canonical_repo, "wt-timeout")

    def test_a_timeout_is_retried_once_when_the_load_drops(
        self, canonical_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The retry is conditional on the load actually falling, never immediate."""
        calls: list[int] = []

        def fake_run(cwd: Path, *args: str, timeout: int = 60):  # noqa: ANN202
            calls.append(1)
            if len(calls) == 1:
                return mod.ModelGitResult(
                    exit_code=-1,
                    stdout="",
                    stderr="TimeoutExpired",
                    timed_out=True,
                    load_average=127.4,
                )
            return mod.ModelGitResult(
                exit_code=0, stdout="", stderr="", timed_out=False, load_average=None
            )

        monkeypatch.setattr(mod, "_git_run", fake_run)
        monkeypatch.setattr(mod, "host_load_average", lambda: 1.0)
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

        result = mod._git_run_with_load_retry(canonical_repo, "worktree", "remove", "x")

        assert result.ok is True
        assert len(calls) == 2, "exactly one retry, not a loop"

    def test_no_retry_is_attempted_while_the_load_stays_high(
        self, canonical_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def fake_run(cwd: Path, *args: str, timeout: int = 60):  # noqa: ANN202
            calls.append(1)
            return mod.ModelGitResult(
                exit_code=-1,
                stdout="",
                stderr="TimeoutExpired",
                timed_out=True,
                load_average=200.0,
            )

        monkeypatch.setattr(mod, "_git_run", fake_run)
        monkeypatch.setattr(mod, "host_load_average", lambda: 200.0)
        monkeypatch.setattr(mod, "LOAD_RETRY_MAX_WAIT_SECONDS", 0)

        result = mod._git_run_with_load_retry(canonical_repo, "worktree", "remove", "x")

        assert result.timed_out is True
        assert result.load_average == 200.0
        assert len(calls) == 1, "retrying at load 200 just reproduces the timeout"


# =============================================================================
# OMN-16901 — the verdict is re-verified live immediately before the removal
# =============================================================================


class TestRemovalTimeRevalidation:
    def test_a_row_that_gains_a_claim_between_passes_is_not_removed(
        self,
        guarded_canonical_repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A registry-scale classification pass runs for tens of minutes while peer
        lanes keep working. `git worktree remove` re-checks cleanliness but knows
        nothing about the ledger, so the CLAIM window is closed here or nowhere."""
        root = tmp_path / "omni_worktrees"
        worktree = root / "OMN-1" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            guarded_canonical_repo,
            "worktree",
            "add",
            "-q",
            str(worktree),
            "-b",
            "wt-claimed",
        )
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "| 2026-09-14T10:00:00Z | lane-a | OMN-1 | TERMINAL | landed |\n",
            encoding="utf-8",
        )

        real_collect = mod.collect_facts
        calls: list[int] = []

        def fake_collect(*args: object, **kwargs: object):  # noqa: ANN202
            facts = real_collect(*args, **kwargs)  # type: ignore[arg-type]
            calls.append(1)
            if len(calls) == 1:
                return facts
            # The second call is the removal-time re-verification: a peer lane
            # opened a CLAIM in the meantime.
            return facts.model_copy(
                update={"ledger_open_claim": "2026-09-14T11:00:00Z | a peer lane"}
            )

        monkeypatch.setattr(mod, "collect_facts", fake_collect)
        monkeypatch.setattr(
            mod,
            "prune_worktree",
            lambda _d: pytest.fail("removed a re-claimed worktree"),
        )

        exit_code = mod.main(
            [
                "--worktrees-root",
                str(root),
                "--ledger",
                str(ledger),
                "--execute",
                "--no-fetch",
                "--no-tracker",
                "--no-pr-state",
            ]
        )

        assert exit_code == 0
        assert len(calls) == 2, "the predicate must run again before the removal"
        assert worktree.is_dir()


class TestReportIsPathPortable:
    def test_no_operator_machine_path_survives_into_the_report(
        self, guarded_canonical_repo: Path, tmp_path: Path
    ) -> None:
        """The report is published to a shared repository whose readers cannot
        resolve a path on this machine, and the shared scrub refuses a document
        carrying one. The Removals section embeds a full git command line, not
        just a path column, so a column-only fix left the report unpublishable."""
        root = tmp_path / "omni_worktrees"
        worktree = root / "OMN-2" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            guarded_canonical_repo,
            "worktree",
            "add",
            "-q",
            str(worktree),
            "-b",
            "wt-report",
        )
        ledger = tmp_path / "ledger.md"
        ledger.write_text("", encoding="utf-8")
        report_md = tmp_path / "report.md"

        exit_code = mod.main(
            [
                "--worktrees-root",
                str(root),
                "--ledger",
                str(ledger),
                "--execute",
                "--no-debris",
                "--no-fetch",
                "--no-tracker",
                "--no-pr-state",
                "--report-md",
                str(report_md),
            ]
        )

        assert exit_code == 0
        body = report_md.read_text(encoding="utf-8")
        registry_prefix = str(root.parent).rstrip("/") + "/"
        assert registry_prefix not in body, (
            "the report still carries the operator-machine prefix"
        )
        assert "omni_worktrees/OMN-2/omnibase_infra" in body, (
            "the portable form of the path must survive"
        )


class TestNoDebrisFlag:
    def test_no_debris_skips_the_pass_and_removes_nothing_extra(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The debris pass runs BEFORE any removal and costs two git subprocesses
        per file of every candidate, so one whole-repo candidate can hold an
        --execute run for tens of minutes while approved removals wait behind it.
        Skipping it must report no debris and leave the directory alone — it can
        never widen what is removed."""
        root = tmp_path / "omni_worktrees"
        debris = root / "OMN-9" / "omnibase_infra"
        debris.mkdir(parents=True)
        (debris / "app.py").write_text("x = 1\n", encoding="utf-8")
        ledger = tmp_path / "ledger.md"
        ledger.write_text("", encoding="utf-8")

        exit_code = mod.main(
            [
                "--worktrees-root",
                str(root),
                "--ledger",
                str(ledger),
                "--execute",
                "--no-debris",
                "--no-fetch",
                "--no-tracker",
                "--no-pr-state",
            ]
        )

        assert exit_code == 0
        assert "--no-debris" in capsys.readouterr().out
        assert debris.is_dir()
        assert (debris / "app.py").exists()


# =============================================================================
# Defect 2 — partial-mutation debris: detection + the narrow auto-remove case
# =============================================================================


class TestDiscoverDebrisDirectories:
    def test_finds_a_git_gone_directory_with_content(self, tmp_path: Path) -> None:
        debris = tmp_path / "OMN-1" / "omnibase_infra"
        debris.mkdir(parents=True)
        (debris / "src").mkdir()
        (debris / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")

        found = mod.discover_debris_directories(tmp_path, known_worktrees=set())
        assert debris in found

    def test_excludes_an_empty_leftover_directory(self, tmp_path: Path) -> None:
        empty = tmp_path / "OMN-2" / "omnibase_infra"
        empty.mkdir(parents=True)

        found = mod.discover_debris_directories(tmp_path, known_worktrees=set())
        assert empty not in found

    def test_excludes_a_directory_with_a_valid_git_link(self, tmp_path: Path) -> None:
        valid = tmp_path / "OMN-3" / "omnibase_infra"
        valid.mkdir(parents=True)
        (valid / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        (valid / "src.py").write_text("x = 1\n", encoding="utf-8")

        found = mod.discover_debris_directories(tmp_path, known_worktrees=set())
        assert valid not in found

    def test_excludes_a_directory_already_known_as_a_valid_worktree(
        self, tmp_path: Path
    ) -> None:
        known = tmp_path / "OMN-4" / "omnibase_infra"
        known.mkdir(parents=True)
        (known / "app.py").write_text("x = 1\n", encoding="utf-8")

        found = mod.discover_debris_directories(tmp_path, known_worktrees={known})
        assert known not in found

    def test_excludes_subdirectories_of_a_valid_git_linked_worktree(
        self, tmp_path: Path
    ) -> None:
        """CodeRabbit (OMN-16951 PR review): the `.git` check on Line 172 only
        applies to `child` itself. `root/OMN-5/repo/src` matches the depth-3
        glob, is not itself a known worktree, carries no `.git` of its own,
        and holds a file — every prior filter passed it through. Its parent
        (`root/OMN-5/repo`) does carry `.git`, which must be enough to
        exclude the subdirectory too.
        """
        valid = tmp_path / "OMN-5" / "repo"
        valid.mkdir(parents=True)
        (valid / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        src = valid / "src"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n", encoding="utf-8")

        found = mod.discover_debris_directories(tmp_path, known_worktrees=set())
        assert valid not in found
        assert src not in found

    def test_excludes_subdirectories_of_a_known_worktree(self, tmp_path: Path) -> None:
        """Same shape as above, but the ancestor is excluded via
        `known_worktrees` rather than an on-disk `.git`."""
        known = tmp_path / "OMN-6" / "repo"
        known.mkdir(parents=True)
        src = known / "src"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n", encoding="utf-8")

        found = mod.discover_debris_directories(tmp_path, known_worktrees={known})
        assert src not in found


class TestPartialMutationDebrisIntegration:
    """RED 2, end to end against real git: a `.git`-gone directory must
    classify as `partial_mutation_debris`, and the provably-reachable-content
    case must be the ONLY auto-removable one."""

    def test_git_gone_worktree_with_untouched_content_is_auto_removable(
        self, tmp_path: Path, canonical_repo: Path
    ) -> None:
        root = tmp_path / "omni_worktrees"
        worktree = root / "OMN-16869" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            canonical_repo, "worktree", "add", "-q", str(worktree), "-b", "wt-branch"
        )
        assert mod.discover_worktrees(root) == [worktree]

        # Simulate the partial-mutation debris shape: the linked `.git` file
        # is gone, every tracked file is untouched.
        (worktree / ".git").unlink()
        assert mod.discover_worktrees(root) == []  # invisible to the old path
        debris_candidates = mod.discover_debris_directories(root, set())
        assert worktree in debris_candidates

        owner_lookup: dict[str, tuple[Path, str]] = {}
        for path_str, state in mod.collect_worktree_list_entries(
            canonical_repo
        ).items():
            owner_lookup[path_str] = (canonical_repo, state)
        owner = owner_lookup.get(str(worktree.resolve()))
        assert owner is not None, "git must still carry the administrative record"
        assert "prunable" in owner[1]

        facts = mod.collect_debris_facts(worktree, root, owner_lookup)
        assert facts.file_count > 0
        assert facts.unreachable_files == ()

        decision = mod.classify_partial_mutation_debris(facts)
        assert decision.block_reasons == (EnumPruneBlockReason.PARTIAL_MUTATION_DEBRIS,)
        assert decision.remediation is EnumDebrisRemediation.AUTO_REMOVABLE

    def test_git_gone_worktree_with_a_locally_edited_file_is_triage_only(
        self, tmp_path: Path, canonical_repo: Path
    ) -> None:
        """The provably-reachable-content case must be the ONLY
        auto-removable one — a single edited file must flip it to TRIAGE."""
        root = tmp_path / "omni_worktrees"
        worktree = root / "OMN-16906" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            canonical_repo, "worktree", "add", "-q", str(worktree), "-b", "wt-branch2"
        )
        (worktree / ".git").unlink()
        # Local, uncommitted-and-now-unrecoverable-via-git-status edit: the
        # content no longer matches any blob in the owning clone.
        (worktree / "src" / "app.py").write_text(
            "VALUE = 2  # locally edited\n", encoding="utf-8"
        )

        owner_lookup: dict[str, tuple[Path, str]] = {}
        for path_str, state in mod.collect_worktree_list_entries(
            canonical_repo
        ).items():
            owner_lookup[path_str] = (canonical_repo, state)

        facts = mod.collect_debris_facts(worktree, root, owner_lookup)
        assert facts.unreachable_files != ()

        decision = mod.classify_partial_mutation_debris(facts)
        assert decision.remediation is EnumDebrisRemediation.TRIAGE

    def test_remediate_debris_prunes_and_removes_only_when_auto_removable(
        self, tmp_path: Path, canonical_repo: Path
    ) -> None:
        root = tmp_path / "omni_worktrees"
        worktree = root / "OMN-16891" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            canonical_repo, "worktree", "add", "-q", str(worktree), "-b", "wt-branch3"
        )
        (worktree / ".git").unlink()

        owner_lookup: dict[str, tuple[Path, str]] = {}
        for path_str, state in mod.collect_worktree_list_entries(
            canonical_repo
        ).items():
            owner_lookup[path_str] = (canonical_repo, state)
        facts = mod.collect_debris_facts(worktree, root, owner_lookup)
        decision = mod.classify_partial_mutation_debris(facts)
        assert decision.remediation is EnumDebrisRemediation.AUTO_REMOVABLE

        attempt = mod.remediate_debris(decision, canonical_repo)

        assert attempt.ok is True
        assert not worktree.exists()
        # The administrative record must be gone too (git worktree prune ran).
        remaining = mod.collect_worktree_list_entries(canonical_repo)
        assert str(worktree.resolve()) not in remaining

    def test_remediate_debris_refuses_when_content_changed_after_classification(
        self, tmp_path: Path, canonical_repo: Path
    ) -> None:
        """CodeRabbit (OMN-16951 PR review): reachability is proven once, at
        classification time; `--execute` over a large root can run minutes
        later. A file edited into unreachability during that gap must refuse
        the deletion rather than delete it unchecked."""
        root = tmp_path / "omni_worktrees"
        worktree = root / "OMN-16999" / "omnibase_infra"
        worktree.parent.mkdir(parents=True)
        _git_ok(
            canonical_repo, "worktree", "add", "-q", str(worktree), "-b", "wt-branch4"
        )
        (worktree / ".git").unlink()

        owner_lookup: dict[str, tuple[Path, str]] = {}
        for path_str, state in mod.collect_worktree_list_entries(
            canonical_repo
        ).items():
            owner_lookup[path_str] = (canonical_repo, state)
        facts = mod.collect_debris_facts(worktree, root, owner_lookup)
        decision = mod.classify_partial_mutation_debris(facts)
        assert decision.remediation is EnumDebrisRemediation.AUTO_REMOVABLE

        # The gap: content changes after classification proved it reachable.
        (worktree / "src" / "app.py").write_text(
            "VALUE = 2  # edited after classification\n", encoding="utf-8"
        )

        attempt = mod.remediate_debris(decision, canonical_repo)

        assert attempt.ok is False
        assert worktree.exists()  # never deleted
        assert (worktree / "src" / "app.py").exists()


class TestRenderReportDebrisAccounting:
    """CodeRabbit (OMN-16951 PR review): an AUTO_REMOVABLE debris row is (on
    `--execute`) actually removed, so the "Triage block reasons" table must
    not count it — only the TRIAGE subset belongs there."""

    def test_by_reason_table_excludes_auto_removable_debris(
        self, tmp_path: Path
    ) -> None:
        from omniclaude.hooks.lib.worktree_prune_policy import (
            ModelPartialMutationDebrisDecision,
        )

        auto_removable = ModelPartialMutationDebrisDecision(
            path=str(tmp_path / "OMN-1" / "repo"),
            ticket="OMN-1",
            repo="repo",
            block_reasons=(EnumPruneBlockReason.PARTIAL_MUTATION_DEBRIS,),
            remediation=EnumDebrisRemediation.AUTO_REMOVABLE,
            evidence="every remaining file content-reachable",
        )
        triage_only = ModelPartialMutationDebrisDecision(
            path=str(tmp_path / "OMN-2" / "repo"),
            ticket="OMN-2",
            repo="repo",
            block_reasons=(EnumPruneBlockReason.PARTIAL_MUTATION_DEBRIS,),
            remediation=EnumDebrisRemediation.TRIAGE,
            evidence="one file unreachable",
        )

        report = mod.render_report(
            [],
            root=tmp_path,
            executed=True,
            generated_at="2026-08-29T00:00:00Z",
            removals=[],
            tracker_resolved=0,
            debris_decisions=[auto_removable, triage_only],
        )

        assert "| `partial_mutation_debris` | 1 |" in report
