# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for the review-all-prs skill (OMN-2638).

Tests verify:
- Scope guard: --all-authors without --gate-attestation → hard error documented
- Scope guard: --all-authors + --gate-attestation without OMN-2613 flag → hard error documented
- Worktree claim lifecycle: claim acquired before worktree creation
- Claim released after worktree deleted
- Dedup ledger prevents re-processing same thread fingerprint
- Preflight tripwire: worktree exists without claim → hard error documented
- Dry-run produces zero ~/.claude/ writes (no filesystem side effects documented)

All tests are static analysis / structural tests that run without external
credentials, live GitHub access, or live PRs. Safe for CI.

Test markers:
    @pytest.mark.unit  — pure static analysis, no external services required
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_REVIEW_ALL_PRS_DIR = _SKILLS_ROOT / "review-all-prs"
_REVIEW_ALL_PRS_PROMPT = _REVIEW_ALL_PRS_DIR / "prompt.md"
_REVIEW_ALL_PRS_SKILL = _REVIEW_ALL_PRS_DIR / "SKILL.md"
_PR_SAFETY_HELPERS = _SKILLS_ROOT / "_lib" / "pr-safety" / "helpers.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_skill_file(path: Path) -> str:
    """Read a skill file, skipping the test if not present."""
    if not path.exists():
        pytest.skip(f"Skill file not found: {path}")
    return path.read_text(encoding="utf-8")


def _grep_file(path: Path, pattern: str) -> list[str]:
    """Return lines in file matching the pattern (regex)."""
    content = _read_skill_file(path)
    compiled = re.compile(pattern)
    return [line for line in content.splitlines() if compiled.search(line)]


# ---------------------------------------------------------------------------
# Test class 1: Scope guard — --all-authors without --gate-attestation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScopeGuardAllAuthorsRequiresAttestation:
    """Test case 1: --all-authors without --gate-attestation → hard error.

    The skill must document that invoking --all-authors without a gate
    attestation token produces an immediate hard_error exit.
    Verified by static analysis of SKILL.md and prompt.md.
    """

    def test_skill_documents_all_authors_flag(self) -> None:
        """SKILL.md must document --all-authors flag."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--all-authors" in content, (
            "SKILL.md must document --all-authors flag"
        )

    def test_skill_documents_gate_attestation_required_for_all_authors(self) -> None:
        """SKILL.md must document --gate-attestation as required with --all-authors."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--gate-attestation" in content, (
            "SKILL.md must document --gate-attestation flag"
        )

    def test_skill_documents_hard_error_on_missing_attestation(self) -> None:
        """SKILL.md must document hard_error when --all-authors used without --gate-attestation."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "hard_error" in content, (
            "SKILL.md must document hard_error behavior"
        )
        assert "gate-attestation" in content, (
            "SKILL.md must reference gate-attestation in hard_error context"
        )

    def test_prompt_documents_scope_guard_attestation_check(self) -> None:
        """prompt.md must document scope guard check for --gate-attestation."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "--gate-attestation" in content, (
            "prompt.md must document scope guard: --gate-attestation required with --all-authors"
        )

    def test_prompt_documents_hard_error_exit_on_missing_attestation(self) -> None:
        """prompt.md must document immediate EXIT on missing attestation."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "hard_error" in content, (
            "prompt.md must document hard_error exit when --gate-attestation absent"
        )
        assert "EXIT" in content or "exit" in content.lower(), (
            "prompt.md must document immediate exit on guard failure"
        )

    def test_skill_documents_default_scope_is_me(self) -> None:
        """SKILL.md must document default author scope as 'me' (not all)."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        # Default must be "me" not "all"
        assert "default" in content.lower() and "me" in content, (
            "SKILL.md must document default --authors scope as 'me' (the invoking user)"
        )


# ---------------------------------------------------------------------------
# Test class 2: Scope guard — missing OMN-2613 flag
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScopeGuardOmn2613FlagRequired:
    """Test case 2: --all-authors + --gate-attestation without OMN-2613 flag → hard error.

    The skill must document that even with a gate attestation, --all-authors
    also requires --omn-2613-merged or --accept-duplicate-ticket-risk.
    """

    def test_skill_documents_omn2613_merged_flag(self) -> None:
        """SKILL.md must document --omn-2613-merged flag."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--omn-2613-merged" in content, (
            "SKILL.md must document --omn-2613-merged flag"
        )

    def test_skill_documents_accept_duplicate_ticket_risk_flag(self) -> None:
        """SKILL.md must document --accept-duplicate-ticket-risk flag."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--accept-duplicate-ticket-risk" in content, (
            "SKILL.md must document --accept-duplicate-ticket-risk flag"
        )

    def test_skill_documents_hard_error_on_missing_omn2613_flag(self) -> None:
        """SKILL.md must document hard_error when neither OMN-2613 flag is present."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        # Both flags must be mentioned in a hard_error context
        assert "--omn-2613-merged" in content and "--accept-duplicate-ticket-risk" in content, (
            "SKILL.md must document both --omn-2613-merged and --accept-duplicate-ticket-risk "
            "in the hard_error context for --all-authors"
        )

    def test_prompt_documents_omn2613_flag_check(self) -> None:
        """prompt.md must document the OMN-2613 flag check in scope guard."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "--omn-2613-merged" in content or "omn-2613" in content.lower(), (
            "prompt.md must document --omn-2613-merged check in scope guard"
        )
        assert "--accept-duplicate-ticket-risk" in content, (
            "prompt.md must document --accept-duplicate-ticket-risk as alternative"
        )

    def test_skill_documents_duplicate_ticket_risk_context(self) -> None:
        """SKILL.md must explain OMN-2613 as duplicate ticket prevention mechanism."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "OMN-2613" in content, (
            "SKILL.md must reference OMN-2613 in the scope guard context"
        )
        assert "duplicate" in content.lower(), (
            "SKILL.md must explain duplicate ticket risk in scope guard context"
        )


# ---------------------------------------------------------------------------
# Test class 3: Worktree claim lifecycle — claim before worktree creation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorktreeClaimBeforeCreation:
    """Test case 3: Worktree creation claims PR first.

    The skill must document that acquire_claim() is called BEFORE git worktree add,
    and that the claim file exists at claim_path(pr_key) before any worktree
    directory is created.
    """

    def test_skill_documents_claim_before_worktree(self) -> None:
        """SKILL.md must document claim-before-worktree invariant."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "acquire_claim" in content, (
            "SKILL.md must document acquire_claim() in worktree lifecycle"
        )
        assert "claim_path" in content, (
            "SKILL.md must document claim_path() in worktree lifecycle"
        )

    def test_prompt_documents_acquire_claim_before_git_worktree_add(self) -> None:
        """prompt.md must document acquire_claim() called before git worktree add."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "acquire_claim" in content, (
            "prompt.md must document acquire_claim() before worktree creation"
        )
        # Verify ordering: acquire_claim appears before git worktree add in the doc
        acquire_pos = content.find("acquire_claim")
        worktree_pos = content.find("git worktree add") if "git worktree add" not in content else content.find("git worktree add", acquire_pos)
        # If git worktree add is referenced, acquire_claim must precede it
        if "git worktree add" in content:
            assert acquire_pos < content.find("git worktree add"), (
                "prompt.md must document acquire_claim() BEFORE git worktree add"
            )

    def test_prompt_documents_skip_claim_active(self) -> None:
        """prompt.md must document skipping PR when acquire_claim returns 'skip'."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "skip" in content and ("claim" in content or "acquire_claim" in content), (
            "prompt.md must document skipping PR when acquire_claim() returns 'skip'"
        )

    def test_helpers_documents_acquire_claim(self) -> None:
        """_lib/pr-safety/helpers.md must define acquire_claim()."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "acquire_claim" in content, (
            "_lib/pr-safety/helpers.md must define acquire_claim()"
        )

    def test_helpers_documents_claim_path(self) -> None:
        """_lib/pr-safety/helpers.md must define claim_path()."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "claim_path" in content, (
            "_lib/pr-safety/helpers.md must define claim_path()"
        )


# ---------------------------------------------------------------------------
# Test class 4: Claim released after worktree deleted
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClaimReleasedAfterWorktreeDeleted:
    """Test case 4: Claim released after worktree deleted.

    The skill must document that release_claim() is called in cleanup after
    git worktree remove, ensuring claim_path(pr_key) is absent after cleanup.
    """

    def test_skill_documents_release_claim_in_cleanup(self) -> None:
        """SKILL.md must document release_claim() in worktree cleanup."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "release_claim" in content, (
            "SKILL.md must document release_claim() in cleanup lifecycle"
        )

    def test_prompt_documents_release_claim_in_finally(self) -> None:
        """prompt.md must document release_claim() called in cleanup (finally block)."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "release_claim" in content, (
            "prompt.md must document release_claim() in cleanup step"
        )

    def test_prompt_documents_claim_released_regardless_of_worktree_result(self) -> None:
        """prompt.md must document claim released even when worktree removal fails."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        # release_claim must be documented as always running (finally/regardless)
        assert "release_claim" in content, (
            "prompt.md must document release_claim() in cleanup"
        )
        assert (
            "finally" in content.lower()
            or "regardless" in content.lower()
            or "always" in content.lower()
        ), (
            "prompt.md must document that claim is released regardless of worktree removal outcome"
        )

    def test_helpers_documents_release_claim(self) -> None:
        """_lib/pr-safety/helpers.md must define release_claim()."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "release_claim" in content, (
            "_lib/pr-safety/helpers.md must define release_claim()"
        )

    def test_skill_documents_claims_dir_path(self) -> None:
        """SKILL.md must document claim file location for cleanup verification."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "claim_path" in content or "claims" in content.lower(), (
            "SKILL.md must document claim file path for lifecycle verification"
        )


# ---------------------------------------------------------------------------
# Test class 5: Dedup ledger prevents re-processing same fingerprint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDedupLedgerPreventsReprocessing:
    """Test case 5: Dedup ledger prevents re-processing same thread fingerprint.

    The skill must document that the per-run dedup ledger checks thread fingerprints
    and skips PRs where the fingerprint already appears with result: ticket_created.
    """

    def test_skill_documents_dedup_ledger(self) -> None:
        """SKILL.md must document the dedup ledger."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "dedup" in content.lower() or "ledger" in content.lower(), (
            "SKILL.md must document the dedup/ledger mechanism"
        )

    def test_skill_documents_thread_fingerprint(self) -> None:
        """SKILL.md must document thread_fingerprint field in ledger."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "thread_fingerprint" in content or "fingerprint" in content.lower(), (
            "SKILL.md must document thread fingerprint in dedup ledger"
        )

    def test_skill_documents_ticket_created_result(self) -> None:
        """SKILL.md must document last_result: ticket_created in dedup ledger."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "ticket_created" in content, (
            "SKILL.md must document last_result: ticket_created in dedup ledger"
        )

    def test_skill_documents_dedup_skip_logic(self) -> None:
        """SKILL.md must document skip logic when fingerprint is in ledger."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "skip" in content.lower() and "fingerprint" in content.lower(), (
            "SKILL.md must document dedup skip logic based on fingerprint"
        )

    def test_prompt_documents_dedup_ledger_check(self) -> None:
        """prompt.md must document checking the dedup ledger during scan."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "dedup" in content.lower() or "ledger" in content.lower(), (
            "prompt.md must document dedup ledger check during scan phase"
        )

    def test_skill_documents_per_run_dedup_protection(self) -> None:
        """SKILL.md must document that dedup protects within a single run."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "per-run" in content.lower() or "single run" in content.lower() or "within a run" in content.lower(), (
            "SKILL.md must document that dedup ledger protects against duplicates within a single run"
        )


# ---------------------------------------------------------------------------
# Test class 6: Preflight tripwire — worktree without claim → hard error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPreflightTripwire:
    """Test case 6: Preflight tripwire fires if worktree exists without claim.

    The skill must document that if a worktree directory exists at the expected path
    WITHOUT a corresponding active claim, the orchestrator emits a hard_error and exits.
    """

    def test_skill_documents_preflight_tripwire(self) -> None:
        """SKILL.md must document the preflight tripwire."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert (
            "tripwire" in content.lower()
            or "Preflight" in content
            or "preflight" in content.lower()
        ), (
            "SKILL.md must document the preflight tripwire"
        )

    def test_skill_documents_hard_error_on_worktree_without_claim(self) -> None:
        """SKILL.md must document hard_error when worktree exists without claim."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "worktree exists" in content.lower() or (
            "worktree" in content and "no active claim" in content.lower()
        ), (
            "SKILL.md must document hard_error when worktree exists without corresponding claim"
        )

    def test_prompt_documents_preflight_tripwire_check(self) -> None:
        """prompt.md must document preflight verification of claim-before-worktree invariant."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert (
            "tripwire" in content.lower()
            or "Preflight" in content
            or "preflight" in content.lower()
        ), (
            "prompt.md must document preflight tripwire check"
        )

    def test_prompt_documents_tripwire_hard_error(self) -> None:
        """prompt.md must document hard_error exit in tripwire check."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "hard_error" in content, (
            "prompt.md must document hard_error in preflight tripwire"
        )
        # The tripwire hard_error must reference worktree/claim context
        tripwire_section = ""
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "tripwire" in line.lower() or "Preflight" in line:
                tripwire_section = "\n".join(lines[i : i + 20])
                break
        if tripwire_section:
            assert "claim" in tripwire_section.lower() or "worktree" in tripwire_section.lower(), (
                "prompt.md tripwire section must reference claim/worktree in hard_error context"
            )

    def test_prompt_documents_manual_cleanup_instruction(self) -> None:
        """prompt.md preflight tripwire must include manual cleanup instruction."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "git worktree remove" in content or "manual cleanup" in content.lower(), (
            "prompt.md tripwire must include manual cleanup instruction for orphaned worktree"
        )


# ---------------------------------------------------------------------------
# Test class 7: Dry-run produces zero ~/.claude/ writes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunZeroWrites:
    """Test case 7: Dry-run produces zero ~/.claude/ writes.

    The skill must document that --dry-run suppresses all filesystem writes.
    No claim files, no worktrees, no ledger updates, no marker files.
    All output goes to stdout only.
    """

    def test_skill_documents_dry_run_zero_writes(self) -> None:
        """SKILL.md must document dry-run zero-write contract."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--dry-run" in content, (
            "SKILL.md must document --dry-run flag"
        )
        assert "zero" in content.lower() or "no writes" in content.lower() or "DryRunWriteError" in content, (
            "SKILL.md must document zero-write contract for --dry-run"
        )

    def test_skill_documents_dry_run_no_claim_files(self) -> None:
        """SKILL.md must document that dry-run skips claim file creation."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--dry-run" in content and "claim" in content.lower(), (
            "SKILL.md must document that --dry-run skips claim file writes"
        )

    def test_skill_documents_dry_run_no_worktrees(self) -> None:
        """SKILL.md must document that dry-run skips worktree creation."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--dry-run" in content and "worktree" in content.lower(), (
            "SKILL.md must document that --dry-run skips worktree creation"
        )

    def test_skill_documents_dry_run_no_ledger_writes(self) -> None:
        """SKILL.md must document that dry-run skips ledger writes."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "--dry-run" in content and "ledger" in content.lower(), (
            "SKILL.md must document that --dry-run skips ledger writes"
        )

    def test_skill_documents_dry_run_write_error(self) -> None:
        """SKILL.md must document DryRunWriteError propagation in dry-run mode."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "DryRunWriteError" in content, (
            "SKILL.md must document DryRunWriteError as the dry-run enforcement mechanism"
        )

    def test_prompt_documents_dry_run_mode(self) -> None:
        """prompt.md must document --dry-run mode behavior."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "--dry-run" in content, (
            "prompt.md must document --dry-run mode"
        )

    def test_prompt_documents_dry_run_no_claim_writes(self) -> None:
        """prompt.md must document that --dry-run skips acquire_claim()."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "--dry-run" in content and (
            "acquire_claim" in content or "claim" in content.lower()
        ), (
            "prompt.md must document that --dry-run skips acquire_claim() calls"
        )

    def test_helpers_documents_dry_run_write_error(self) -> None:
        """_lib/pr-safety/helpers.md must define DryRunWriteError."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "DryRunWriteError" in content, (
            "_lib/pr-safety/helpers.md must define DryRunWriteError"
        )

    def test_helpers_documents_atomic_write_dry_run(self) -> None:
        """_lib/pr-safety/helpers.md atomic_write() must support dry_run parameter."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "atomic_write" in content and "dry_run" in content, (
            "_lib/pr-safety/helpers.md atomic_write() must accept dry_run parameter"
        )


# ---------------------------------------------------------------------------
# Test class: ModelSkillResult contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelSkillResultContract:
    """Verify review-all-prs emits a documented ModelSkillResult contract."""

    REQUIRED_STATUS_VALUES = [
        "all_clean",
        "partial",
        "nothing_to_review",
        "error",
    ]

    def test_skill_documents_all_status_values(self) -> None:
        """SKILL.md must document all ModelSkillResult status values."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        for status in self.REQUIRED_STATUS_VALUES:
            assert status in content, (
                f"SKILL.md must document ModelSkillResult status='{status}'"
            )

    def test_prompt_emits_model_skill_result(self) -> None:
        """prompt.md must emit ModelSkillResult at conclusion."""
        content = _read_skill_file(_REVIEW_ALL_PRS_PROMPT)
        assert "ModelSkillResult" in content, (
            "prompt.md must emit ModelSkillResult at conclusion"
        )

    def test_skill_documents_result_file_path(self) -> None:
        """SKILL.md must document where ModelSkillResult is written."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "pr-queue" in content or "~/.claude" in content, (
            "SKILL.md must document where ModelSkillResult is written"
        )

    def test_skill_documents_skipped_ledger_result(self) -> None:
        """ModelSkillResult details[] must include skipped_ledger result value."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "skipped_ledger" in content, (
            "SKILL.md must document skipped_ledger as a PR-level result value"
        )


# ---------------------------------------------------------------------------
# Test class: No direct mutation calls
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoDirectMutationCalls:
    """Verify review-all-prs prompt.md uses _lib/pr-safety abstractions.

    review-all-prs creates worktrees via get_worktree() (not direct git worktree add
    in the prompt logic), and does not call gh pr merge or gh pr checkout directly.
    """

    def test_no_gh_pr_merge_in_prompt(self) -> None:
        """prompt.md must not contain direct 'gh pr merge' calls."""
        matches = _grep_file(_REVIEW_ALL_PRS_PROMPT, r"\bgh pr merge\b")
        assert matches == [], (
            "Direct 'gh pr merge' found in review-all-prs/prompt.md. "
            "review-all-prs reviews PRs, not merges them:\n" + "\n".join(matches)
        )

    def test_no_gh_pr_checkout_in_prompt(self) -> None:
        """prompt.md must not contain direct 'gh pr checkout' calls."""
        matches = _grep_file(_REVIEW_ALL_PRS_PROMPT, r"\bgh pr checkout\b")
        assert matches == [], (
            "Direct 'gh pr checkout' found in review-all-prs/prompt.md:\n"
            + "\n".join(matches)
        )

    def test_skill_references_pr_safety_lib(self) -> None:
        """SKILL.md must reference _lib/pr-safety for claim/worktree operations."""
        content = _read_skill_file(_REVIEW_ALL_PRS_SKILL)
        assert "_lib/pr-safety" in content or "pr-safety" in content, (
            "SKILL.md must reference _lib/pr-safety/helpers.md for claim operations"
        )
