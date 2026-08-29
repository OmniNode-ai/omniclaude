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
            dirty_file_count=0,
            commits_ahead=0,
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
