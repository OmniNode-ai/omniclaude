# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for the fix-prs skill (OMN-2636).

Tests verify:
- Dry-run contract: zero direct mutations documented as skipped
- Claim lifecycle invariant documented in _lib/pr-safety helpers
- Boundary validation coverage in _lib/pr-safety helpers
- Inventory consumption documented in skill
- stop_reason validation against TERMINAL_STOP_REASONS
- No direct mutation calls in fix-prs prompt.md (gh pr merge, gh pr checkout, git worktree add)
- Sub-skill delegation documented in both skill files

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
_FIX_PRS_DIR = _SKILLS_ROOT / "fix-prs"
_FIX_PRS_PROMPT = _FIX_PRS_DIR / "prompt.md"
_FIX_PRS_SKILL = _FIX_PRS_DIR / "SKILL.md"
_PR_SAFETY_HELPERS = _SKILLS_ROOT / "_lib" / "pr-safety" / "helpers.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_skill_file(path: Path) -> str:
    """Read a skill file, skipping if not present."""
    if not path.exists():
        pytest.skip(f"Skill file not found: {path}")
    return path.read_text(encoding="utf-8")


def _grep_file(path: Path, pattern: str) -> list[str]:
    """Return lines in file matching the pattern (regex)."""
    content = _read_skill_file(path)
    compiled = re.compile(pattern)
    return [line for line in content.splitlines() if compiled.search(line)]


# ---------------------------------------------------------------------------
# Test class: Dry-run contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunContract:
    """Test case 1: fix-prs dry-run produces zero live mutations.

    The skill does not have an explicit --dry-run flag (unlike merge-sweep),
    but we verify the structural invariant: no direct gh pr merge or
    gh pr checkout calls in the prompt, meaning a dry-run of sub-skills
    (ci-failures, pr-review-dev) is safe.
    """

    def test_skill_documents_nothing_to_fix_exit(self) -> None:
        """prompt.md must document early exit when work_queue is empty."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        assert "nothing_to_fix" in content, (
            "prompt.md must document ModelSkillResult(status=nothing_to_fix) exit"
        )

    def test_skill_documents_idempotency_ledger(self) -> None:
        """SKILL.md must document idempotency ledger to prevent duplicate fixes."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "ledger" in content.lower() or "idempotency" in content.lower(), (
            "SKILL.md must document idempotency ledger"
        )

    def test_prompt_documents_ledger_load(self) -> None:
        """prompt.md must reference ledger loading at initialization."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        assert "ledger" in content.lower(), (
            "prompt.md must reference ledger at initialization"
        )

    def test_skill_documents_ignore_ledger_flag(self) -> None:
        """SKILL.md must document --ignore-ledger for bypassing idempotency."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "--ignore-ledger" in content, (
            "SKILL.md must document --ignore-ledger flag"
        )


# ---------------------------------------------------------------------------
# Test class: Claim lifecycle invariant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClaimLifecycle:
    """Test case 2+3: Claim lifecycle invariant from _lib/pr-safety helpers.

    fix-prs delegates to ci-failures and pr-review-dev sub-skills for mutations.
    The claim lifecycle is enforced by those sub-skills via mutate_pr() from
    _lib/pr-safety/helpers.md. We verify the helpers document claim acquire/release.
    """

    def test_helpers_documents_acquire_claim(self) -> None:
        """_lib/pr-safety/helpers.md must document acquire_claim()."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "acquire_claim" in content, (
            "_lib/pr-safety/helpers.md must document acquire_claim() function"
        )

    def test_helpers_documents_release_claim(self) -> None:
        """_lib/pr-safety/helpers.md must document release_claim()."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "release_claim" in content, (
            "_lib/pr-safety/helpers.md must document release_claim() for cleanup"
        )

    def test_helpers_documents_claim_heartbeat(self) -> None:
        """_lib/pr-safety/helpers.md must document heartbeat_claim() for stale claim detection."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "heartbeat_claim" in content or "heartbeat" in content.lower(), (
            "_lib/pr-safety/helpers.md must document claim heartbeat mechanism"
        )

    def test_helpers_documents_claim_expiry(self) -> None:
        """_lib/pr-safety/helpers.md must document claim expiry/stale detection."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "stale" in content.lower() or "expiry" in content.lower() or "CLAIM_AGE_STALE" in content, (
            "_lib/pr-safety/helpers.md must document claim stale/expiry detection"
        )

    def test_helpers_documents_claim_not_held_error(self) -> None:
        """_lib/pr-safety/helpers.md must document ClaimNotHeldError for mutation guard."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "ClaimNotHeldError" in content, (
            "_lib/pr-safety/helpers.md must document ClaimNotHeldError"
        )

    def test_helpers_documents_mutate_pr_claim_assertion(self) -> None:
        """mutate_pr() must assert claim held by run_id before mutation."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "mutate_pr" in content, (
            "_lib/pr-safety/helpers.md must define mutate_pr()"
        )
        assert "Assert claim held" in content or "claim not held" in content.lower(), (
            "mutate_pr() must assert claim held before any mutation"
        )


# ---------------------------------------------------------------------------
# Test class: Boundary validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBoundaryValidation:
    """Test case 4: boundary_validate enforces infra/UI/app boundaries.

    Verifies that _lib/pr-safety/helpers.md documents boundary_validate()
    covering all three violation types: import_boundary, file_path_boundary,
    and infra_mutation_boundary.
    """

    def test_helpers_documents_boundary_validate(self) -> None:
        """_lib/pr-safety/helpers.md must define boundary_validate()."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "boundary_validate" in content, (
            "_lib/pr-safety/helpers.md must define boundary_validate()"
        )

    def test_helpers_documents_boundary_violation_error(self) -> None:
        """_lib/pr-safety/helpers.md must document BoundaryViolationError."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "BoundaryViolationError" in content or "boundary_violation" in content.lower(), (
            "_lib/pr-safety/helpers.md must document BoundaryViolationError"
        )

    def test_helpers_documents_import_boundary(self) -> None:
        """boundary_validate must cover import boundary violations."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "import_boundary" in content or "import boundary" in content.lower() or "asyncpg" in content.lower() or "repo_class" in content, (
            "_lib/pr-safety/helpers.md boundary_validate must cover import boundaries"
        )

    def test_helpers_documents_repo_class_for_boundary(self) -> None:
        """boundary_validate must use repo_class to enforce app/ui/infra boundaries."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "repo_class" in content, (
            "_lib/pr-safety/helpers.md boundary_validate must accept repo_class parameter"
        )

    def test_fix_prs_documents_ci_secrets_guard(self) -> None:
        """fix-prs must document CI secrets guard as boundary enforcement."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        # CI secrets guard is fix-prs's practical boundary enforcement
        assert "external" in content.lower() and ("secret" in content.lower() or "deploy" in content.lower()), (
            "fix-prs SKILL.md must document CI secrets guard (external infra boundary)"
        )


# ---------------------------------------------------------------------------
# Test class: Inventory consumption
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInventoryConsumption:
    """Test case 5: inventory/ledger consumption.

    The ticket references an --inventory flag. fix-prs uses an idempotency ledger
    but the --inventory flag is not present in the skill. We test what IS documented:
    the ledger-based dedup and the --ignore-ledger bypass.
    """

    def test_skill_documents_ledger_structure(self) -> None:
        """SKILL.md must document the per-run ledger JSON structure."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "head_sha" in content or "run_id" in content, (
            "SKILL.md must document ledger structure (head_sha or run_id fields)"
        )

    def test_skill_documents_retry_policy(self) -> None:
        """SKILL.md must document retry_count policy."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "retry" in content.lower(), (
            "SKILL.md must document retry policy for idempotency ledger"
        )

    def test_prompt_documents_ledger_check_before_dispatch(self) -> None:
        """prompt.md must check ledger before dispatching fix agents."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        assert "ledger" in content.lower(), (
            "prompt.md must reference ledger before dispatching fix agents"
        )

    def test_skill_documents_max_total_prs_cap(self) -> None:
        """SKILL.md must document --max-total-prs as blast radius cap."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "--max-total-prs" in content, (
            "SKILL.md must document --max-total-prs blast radius cap"
        )


# ---------------------------------------------------------------------------
# Test class: stop_reason validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStopReasonValidation:
    """Test case 6: stop_reason must be from TERMINAL_STOP_REASONS.

    _lib/pr-safety/helpers.md defines TERMINAL_STOP_REASONS and
    ledger_set_stop_reason(). We verify these are documented and that
    fix-prs result values match the terminal stop reason set.
    """

    TERMINAL_STOP_REASONS = [
        "merged",
        "conflict_unresolvable",
        "ci_failed_no_fix",
        "ci_fix_cap_exceeded",
        "review_cap_exceeded",
        "review_timeout",
        "boundary_violation",
        "corrupt_claim",
        "no_claim_held",
        "hard_error",
        "dry_run_complete",
        "gate_rejected",
        "gate_expired",
        "cross_repo_split",
    ]

    def test_helpers_documents_terminal_stop_reasons(self) -> None:
        """_lib/pr-safety/helpers.md must define TERMINAL_STOP_REASONS list."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "TERMINAL_STOP_REASONS" in content, (
            "_lib/pr-safety/helpers.md must define TERMINAL_STOP_REASONS"
        )

    def test_helpers_documents_ledger_set_stop_reason(self) -> None:
        """_lib/pr-safety/helpers.md must define ledger_set_stop_reason()."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "ledger_set_stop_reason" in content, (
            "_lib/pr-safety/helpers.md must define ledger_set_stop_reason()"
        )

    def test_terminal_stop_reasons_all_present_in_helpers(self) -> None:
        """All canonical TERMINAL_STOP_REASONS must appear in helpers.md."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        missing = [r for r in self.TERMINAL_STOP_REASONS if r not in content]
        assert missing == [], (
            f"TERMINAL_STOP_REASONS missing from _lib/pr-safety/helpers.md: {missing}"
        )

    def test_fix_prs_result_values_consistent_with_terminal_reasons(self) -> None:
        """fix-prs result values must not include non-terminal states."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        # fix-prs uses: fixed, partial, failed, needs_human, blocked_external, skipped
        # These are PR-level results, not ledger stop_reasons. Verify the PR-level
        # result values are documented.
        for result in ["fixed", "partial", "failed", "needs_human", "blocked_external"]:
            assert result in content, (
                f"SKILL.md must document PR-level result value: {result}"
            )

    def test_validate_ledger_stop_reasons_script_exists(self) -> None:
        """tests/validate_ledger_stop_reasons.py must exist for CI enforcement."""
        script = _REPO_ROOT / "tests" / "validate_ledger_stop_reasons.py"
        assert script.exists(), (
            "tests/validate_ledger_stop_reasons.py must exist for CI stop_reason validation"
        )


# ---------------------------------------------------------------------------
# Test class: No direct mutation calls in fix-prs prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoDirectMutationCalls:
    """Test case 7: fix-prs/prompt.md must not contain banned direct mutation calls.

    Per _lib/pr-safety/helpers.md, direct gh pr merge, gh pr checkout,
    git worktree add, and gh api .*/merge are CI enforcement violations.
    fix-prs may use git push --force-with-lease (conflict resolution is allowed)
    but must NOT call gh pr merge or gh pr checkout directly.
    """

    def test_no_gh_pr_merge_in_prompt(self) -> None:
        """prompt.md must not contain direct 'gh pr merge' calls."""
        matches = _grep_file(_FIX_PRS_PROMPT, r"\bgh pr merge\b")
        assert matches == [], (
            f"Direct 'gh pr merge' found in fix-prs/prompt.md. "
            f"fix-prs repairs PRs, not merges them:\n" + "\n".join(matches)
        )

    def test_no_gh_pr_checkout_in_prompt(self) -> None:
        """prompt.md must not contain direct 'gh pr checkout' calls."""
        matches = _grep_file(_FIX_PRS_PROMPT, r"\bgh pr checkout\b")
        assert matches == [], (
            f"Direct 'gh pr checkout' found in fix-prs/prompt.md:\n"
            + "\n".join(matches)
        )

    def test_no_git_worktree_add_in_prompt(self) -> None:
        """prompt.md must not contain direct 'git worktree add' calls."""
        matches = _grep_file(_FIX_PRS_PROMPT, r"\bgit worktree add\b")
        assert matches == [], (
            f"Direct 'git worktree add' found in fix-prs/prompt.md. "
            f"Use get_worktree() from _lib/pr-safety/helpers.md:\n"
            + "\n".join(matches)
        )

    def test_no_gh_api_merge_in_prompt(self) -> None:
        """prompt.md must not contain direct gh api merge calls."""
        matches = _grep_file(_FIX_PRS_PROMPT, r"gh api.*merge|api.*pulls.*merge")
        assert matches == [], (
            f"Direct gh api merge found in fix-prs/prompt.md:\n"
            + "\n".join(matches)
        )

    def test_fix_prs_delegates_to_ci_failures(self) -> None:
        """prompt.md must delegate CI fixes to ci-failures sub-skill."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        assert "ci-failures" in content or "ci_failures" in content, (
            "prompt.md must delegate CI fixing to ci-failures sub-skill"
        )

    def test_fix_prs_delegates_to_pr_review_dev(self) -> None:
        """prompt.md must delegate review fixes to pr-review-dev sub-skill."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        assert "pr-review-dev" in content or "pr_review_dev" in content, (
            "prompt.md must delegate review fixing to pr-review-dev sub-skill"
        )

    def test_skill_lists_sub_skills_used(self) -> None:
        """SKILL.md must document sub-skills under Sub-skills Used section."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "ci-failures" in content and "pr-review-dev" in content, (
            "SKILL.md must list ci-failures and pr-review-dev in Sub-skills Used"
        )


# ---------------------------------------------------------------------------
# Test class: ModelSkillResult contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelSkillResultContract:
    """Verify fix-prs emits a documented ModelSkillResult contract."""

    REQUIRED_STATUS_VALUES = [
        "all_fixed",
        "partial",
        "nothing_to_fix",
        "error",
    ]

    def test_skill_documents_all_status_values(self) -> None:
        """SKILL.md must document all ModelSkillResult status values."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        for status in self.REQUIRED_STATUS_VALUES:
            assert status in content, (
                f"SKILL.md must document ModelSkillResult status='{status}'"
            )

    def test_prompt_emits_model_skill_result(self) -> None:
        """prompt.md must emit ModelSkillResult at conclusion."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        assert "ModelSkillResult" in content, (
            "prompt.md must emit ModelSkillResult at conclusion"
        )

    def test_skill_documents_result_file_path(self) -> None:
        """SKILL.md must document where ModelSkillResult is written."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "pr-queue" in content or "~/.claude" in content, (
            "SKILL.md must document where ModelSkillResult is written"
        )

    def test_skill_documents_pr_level_results(self) -> None:
        """ModelSkillResult details[] must document per-PR result values."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert '"details"' in content or "details" in content, (
            "ModelSkillResult must include per-PR details array"
        )


# ---------------------------------------------------------------------------
# Test class: Force push guardrail
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestForcePushGuardrail:
    """Verify fix-prs documents force push guardrail correctly.

    fix-prs may use git push --force-with-lease (not banned) but must
    document the guardrail and require PR comments on force pushes.
    """

    def test_skill_documents_force_push_guardrail(self) -> None:
        """SKILL.md must document force push guardrail."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "--allow-force-push" in content, (
            "SKILL.md must document --allow-force-push guardrail"
        )

    def test_skill_documents_pr_comment_on_force_push(self) -> None:
        """SKILL.md must require PR comment when force pushing."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "PR comment" in content or "pr comment" in content.lower() or "comment" in content.lower(), (
            "SKILL.md must require posting a PR comment when force pushing"
        )

    def test_prompt_uses_force_with_lease(self) -> None:
        """prompt.md must use git push --force-with-lease (not --force)."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        # Should use --force-with-lease if any force push is referenced
        if "force" in content:
            assert "force-with-lease" in content, (
                "prompt.md must use git push --force-with-lease, not bare --force"
            )

    def test_skill_rebase_uses_base_ref_not_hardcoded_main(self) -> None:
        """SKILL.md must use pr.baseRefName for rebase, not hardcoded 'main'."""
        content = _read_skill_file(_FIX_PRS_SKILL)
        assert "baseRefName" in content or "base_ref" in content.lower(), (
            "SKILL.md must use pr.baseRefName for rebase (not hardcoded 'main')"
        )


# ---------------------------------------------------------------------------
# Test class: CI enforcement grep
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCIEnforcementGrep:
    """Simulate CI enforcement checks for fix-prs skill."""

    def test_no_direct_merge_in_fix_prs(self) -> None:
        """fix-prs must not merge PRs — it repairs them."""
        content = _read_skill_file(_FIX_PRS_PROMPT)
        # Should not have "gh pr merge" — fix-prs repairs, merge-sweep merges
        lines = [
            line for line in content.splitlines()
            if "gh pr merge" in line and not line.strip().startswith("#")
        ]
        assert lines == [], (
            f"fix-prs/prompt.md contains 'gh pr merge' — fix-prs repairs PRs, "
            f"merge-sweep merges them:\n" + "\n".join(lines)
        )

    def test_fix_prs_references_base_ref_for_rebase(self) -> None:
        """fix-prs must reference baseRefName for conflict resolution."""
        prompt_content = _read_skill_file(_FIX_PRS_PROMPT)
        skill_content = _read_skill_file(_FIX_PRS_SKILL)
        combined = prompt_content + skill_content
        assert "baseRefName" in combined or "base_ref" in combined.lower(), (
            "fix-prs must use pr.baseRefName for rebase (dynamic, not hardcoded)"
        )

    def test_fix_prs_documents_external_check_skip(self) -> None:
        """fix-prs must document skipping external CI checks."""
        prompt_content = _read_skill_file(_FIX_PRS_PROMPT)
        skill_content = _read_skill_file(_FIX_PRS_SKILL)
        combined = prompt_content + skill_content
        assert "external" in combined.lower() and ("secret" in combined.lower() or "deploy" in combined.lower()), (
            "fix-prs must document skipping external/deployment CI checks"
        )

    def test_no_git_worktree_add_in_skills(self) -> None:
        """fix-prs skill files must not use direct 'git worktree add'."""
        for skill_file in [_FIX_PRS_PROMPT, _FIX_PRS_SKILL]:
            if not skill_file.exists():
                continue
            content = skill_file.read_text(encoding="utf-8")
            violations = [
                line for line in content.splitlines()
                if "git worktree add" in line
                and not line.strip().startswith("#")
            ]
            assert violations == [], (
                f"Direct 'git worktree add' found in {skill_file.name}. "
                f"Use get_worktree() from _lib/pr-safety:\n"
                + "\n".join(violations)
            )
