# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the merge-sweep skill (v3.0.0).

Tests verify:
- Dry-run contract: zero mutations when --dry-run is set
- Gate-free design: no Slack gate patterns anywhere in skill docs
- GitHub auto-merge: gh pr merge --auto used in prompt (not immediate merge)
- pr-polish: Track B dispatches pr-polish for blocking-issue PRs
- Claim-before-mutate: run_id audit trail documented in prompt.md
- Two-track classification: needs_polish() and is_merge_ready() predicates documented
- CI enforcement: no bare gh pr merge (without --auto) in prompt.md
- ModelSkillResult contract: correct status values (queued, nothing_to_merge, partial, error)

All tests are static analysis / structural tests that run without external
credentials, live GitHub access, or live PRs. Safe for CI.

Test markers:
    @pytest.mark.unit  — repeatable, no external mutations, CI-safe
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_MERGE_SWEEP_DIR = _SKILLS_ROOT / "merge_sweep"
_MERGE_SWEEP_PROMPT = _MERGE_SWEEP_DIR / "prompt.md"
_MERGE_SWEEP_SKILL = _MERGE_SWEEP_DIR / "SKILL.md"
_PR_SAFETY_HELPERS = _SKILLS_ROOT / "_lib" / "pr-safety" / "helpers.md"
_PR_QUEUE_RUNS = Path.home() / ".claude" / "pr-queue" / "runs"


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
    """Dry-run produces zero mutations (no auto-merge enabled, no pr-polish dispatched)."""

    def test_prompt_documents_dry_run_no_mutation(self) -> None:
        """Prompt must document that --dry-run exits without enabling auto-merge."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "--dry-run" in content, "prompt.md must document --dry-run behavior"
        assert "Dry run complete" in content or "no auto-merge" in content.lower(), (
            "prompt.md must state dry-run skips auto-merge and polish"
        )

    def test_skill_documents_dry_run_flag(self) -> None:
        """SKILL.md must list --dry-run as a documented argument."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "--dry-run" in content, "SKILL.md must document the --dry-run argument"

    def test_prompt_dry_run_exit_before_phase_a(self) -> None:
        """Dry-run check (Step 5) must appear before Phase A (Step 6) in prompt.md."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()
        dry_run_section_start = None
        for i, line in enumerate(lines):
            if "--dry-run" in line and (
                "Step" in " ".join(lines[max(0, i - 5) : i + 1]) or "Dry" in line
            ):
                dry_run_section_start = i
                break
        step6_idx = next(
            (i for i, line in enumerate(lines) if "## Step 6" in line),
            None,
        )
        if dry_run_section_start is not None and step6_idx is not None:
            assert dry_run_section_start < step6_idx, (
                "Dry-run exit must appear before Step 6 (Phase A) in prompt.md"
            )


# ---------------------------------------------------------------------------
# Test class: Gate-free design (v3.0.0 removes gate entirely)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGateFreeDesign:
    """v3.0.0 removes the Slack gate entirely. No gate patterns should exist.

    --no-gate was banned in OMN-2633. --gate-attestation was the intermediate
    replacement. Both are now removed — merge-sweep uses GitHub auto-merge
    instead of any Slack gate mechanism.
    """

    def test_no_gate_absent_from_prompt(self) -> None:
        """prompt.md must not contain --no-gate."""
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"--no-gate")
        assert matches == [], "--no-gate found in merge-sweep/prompt.md:\n" + "\n".join(
            matches
        )

    def test_no_gate_absent_from_skill_md(self) -> None:
        """SKILL.md must not contain --no-gate."""
        matches = _grep_file(_MERGE_SWEEP_SKILL, r"--no-gate")
        assert matches == [], "--no-gate found in merge-sweep/SKILL.md:\n" + "\n".join(
            matches
        )

    def test_gate_attestation_not_in_skill_args(self) -> None:
        """SKILL.md args section must not list --gate-attestation (removed in v3.0.0)."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        # Check the frontmatter args block — gate-attestation must not be an arg
        # It may appear in changelog prose but not as an active argument
        frontmatter_end = content.find("---", 3)  # end of YAML frontmatter
        if frontmatter_end > 0:
            frontmatter = content[:frontmatter_end]
            assert "--gate-attestation" not in frontmatter, (
                "--gate-attestation found in SKILL.md frontmatter args (removed in v3.0.0). "
                "GitHub auto-merge replaces the gate mechanism."
            )

    def test_gate_attestation_not_in_prompt_args(self) -> None:
        """prompt.md must not list --gate-attestation as a parsed argument."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # Check the argument parsing section — gate-attestation must not be listed
        assert "--gate-attestation" not in content, (
            "--gate-attestation found in merge-sweep/prompt.md (removed in v3.0.0). "
            "GitHub auto-merge replaces the gate mechanism."
        )

    def test_no_slack_gate_poll_in_prompt(self) -> None:
        """prompt.md must not reference slack_gate_poll.py (gate removed)."""
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"slack_gate_poll")
        assert matches == [], (
            "slack_gate_poll.py found in prompt.md — gate was removed in v3.0.0:\n"
            + "\n".join(matches)
        )

    def test_skill_documents_github_auto_merge_mechanism(self) -> None:
        """SKILL.md must document GitHub auto-merge as the merge mechanism."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "auto-merge" in content.lower() or "--auto" in content, (
            "SKILL.md must document GitHub auto-merge (gh pr merge --auto) as the mechanism"
        )


# ---------------------------------------------------------------------------
# Test class: GitHub auto-merge and pr-polish dispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutoMergeAndPolishDispatch:
    """v3.0.0 uses gh pr merge --auto (Track A) and pr-polish (Track B).

    The skill must NOT call gh pr merge without --auto (immediate merge).
    It MUST call gh pr merge --auto to enable GitHub's native auto-merge.
    It MUST dispatch pr-polish for PRs with blocking issues.
    """

    def test_prompt_uses_github_auto_merge_flag(self) -> None:
        """prompt.md must contain 'gh pr merge' with '--auto' flag."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "--auto" in content, (
            "prompt.md must use 'gh pr merge --auto' to enable GitHub auto-merge"
        )

    def test_prompt_dispatches_pr_polish_for_blocking_prs(self) -> None:
        """prompt.md must dispatch pr-polish for PRs with blocking issues (Track B)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "pr-polish" in content, (
            "prompt.md must dispatch pr-polish for blocking-issue PRs (Track B)"
        )

    def test_skill_documents_pr_polish_as_sub_skill(self) -> None:
        """SKILL.md must list pr-polish in Sub-skills Used section."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "pr-polish" in content, (
            "SKILL.md must document pr-polish as a Track B sub-skill"
        )

    def test_prompt_documents_needs_polish_predicate(self) -> None:
        """prompt.md must document needs_polish() classification predicate."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "needs_polish" in content, (
            "prompt.md must document needs_polish() predicate for Track B classification"
        )

    def test_prompt_documents_two_tracks(self) -> None:
        """prompt.md must document both Track A (auto-merge) and Track B (polish)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "Track A" in content, "prompt.md must reference Track A (auto-merge)"
        assert "Track B" in content, "prompt.md must reference Track B (pr-polish)"

    def test_prompt_does_not_dispatch_auto_merge_sub_skill(self) -> None:
        """prompt.md must not call the auto-merge sub-skill (replaced by direct --auto flag)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # onex:auto_merge sub-skill invocation pattern
        assert "onex:auto_merge" not in content, (
            "prompt.md must not dispatch onex:auto_merge sub-skill "
            "(v3.0.0 uses gh pr merge --auto directly)"
        )

    def test_no_gh_pr_checkout_in_prompt(self) -> None:
        """prompt.md must not contain direct 'gh pr checkout' calls."""
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"\bgh pr checkout\b")
        assert matches == [], (
            "Direct 'gh pr checkout' found in merge-sweep/prompt.md:\n"
            + "\n".join(matches)
        )

    def test_prompt_documents_worktree_for_polish(self) -> None:
        """prompt.md must document worktree creation for pr-polish (needs git context)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "worktree" in content.lower(), (
            "prompt.md must document worktree creation for pr-polish Track B agents"
        )


# ---------------------------------------------------------------------------
# Test class: No direct gh pr list outside scan phase
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoDirectGhPrList:
    """gh pr list in prompt.md must appear only in the scan phase (Step 2/3)."""

    def test_gh_pr_list_only_in_scan_phase(self) -> None:
        """gh pr list in prompt.md must appear in the scan phase section."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()

        gh_pr_list_lines = [
            (i, line) for i, line in enumerate(lines) if "gh pr list" in line
        ]

        if not gh_pr_list_lines:
            return  # No direct gh pr list — passes (could use sub-skill)

        for line_idx, line_text in gh_pr_list_lines:
            context_start = max(0, line_idx - 50)
            context_lines = lines[context_start:line_idx]
            step_heading = None
            for ctx_line in reversed(context_lines):
                step_match = re.search(r"## Step (\d+)", ctx_line)
                if step_match:
                    step_heading = int(step_match.group(1))
                    break

            if step_heading is not None:
                assert step_heading in (2, 3), (
                    f"gh pr list found outside scan phase (Step 2/3) at line {line_idx + 1}. "
                    f"Found in Step {step_heading}: {line_text!r}"
                )


# ---------------------------------------------------------------------------
# Test class: Claim-before-mutate invariant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClaimBeforeMutate:
    """Claim-before-mutate invariant: acquire claim before any PR mutation.

    In v3.0.0, the audit trail is run_id (not gate_token). Claims are
    acquired before enabling auto-merge (Phase A) and before dispatching
    pr-polish (Phase B).
    """

    def test_prompt_documents_run_id_audit_trail(self) -> None:
        """prompt.md must document run_id as the audit trail for operations."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "run_id" in content, (
            "prompt.md must document run_id as the audit trail for merge operations"
        )

    def test_prompt_documents_claim_registry(self) -> None:
        """prompt.md must reference ClaimRegistry for claim-before-mutate enforcement."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert (
            "ClaimRegistry" in content
            or "claim_registry" in content
            or "registry" in content.lower()
        ), (
            "prompt.md must reference claim registry before enabling auto-merge or dispatching polish"
        )

    def test_prompt_acquires_claim_before_phase_a(self) -> None:
        """prompt.md must show claim acquisition before Phase A auto-merge enable."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # Both acquire and auto should appear in the Phase A section
        assert "acquire" in content and "--auto" in content, (
            "prompt.md must acquire a claim before enabling auto-merge in Phase A"
        )

    def test_skill_documents_claim_lifecycle(self) -> None:
        """SKILL.md must document claim lifecycle in the execution algorithm."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "claim" in content.lower(), (
            "SKILL.md must document the claim registry lifecycle"
        )

    def test_helpers_md_documents_claim_not_held_error(self) -> None:
        """_lib/pr-safety/helpers.md must document ClaimNotHeldError."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "ClaimNotHeldError" in content, (
            "_lib/pr-safety/helpers.md must document ClaimNotHeldError for claim enforcement"
        )

    def test_helpers_md_documents_mutate_pr_claim_check(self) -> None:
        """_lib/pr-safety/helpers.md mutate_pr() must assert claim held."""
        if not _PR_SAFETY_HELPERS.exists():
            pytest.skip("_lib/pr-safety/helpers.md not found")
        content = _PR_SAFETY_HELPERS.read_text(encoding="utf-8")
        assert "mutate_pr" in content, (
            "_lib/pr-safety/helpers.md must define mutate_pr()"
        )
        assert "Assert claim held" in content or "claim not held" in content.lower(), (
            "mutate_pr() must document claim-held assertion"
        )


# ---------------------------------------------------------------------------
# Test class: ModelSkillResult contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelSkillResultContract:
    """Verify merge-sweep emits a documented ModelSkillResult contract (v3.0.0)."""

    REQUIRED_STATUS_VALUES = [
        "queued",
        "nothing_to_merge",
        "partial",
        "error",
    ]

    def test_skill_documents_all_status_values(self) -> None:
        """SKILL.md must document all ModelSkillResult status values."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        for status in self.REQUIRED_STATUS_VALUES:
            assert status in content, (
                f"SKILL.md must document ModelSkillResult status='{status}'"
            )

    def test_prompt_emits_model_skill_result(self) -> None:
        """prompt.md must emit ModelSkillResult at conclusion (Step 10)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "ModelSkillResult" in content, (
            "prompt.md must emit ModelSkillResult at conclusion"
        )

    def test_skill_documents_result_file_path(self) -> None:
        """SKILL.md must document where ModelSkillResult is written."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "skill-results" in content or "~/.claude" in content, (
            "SKILL.md must document where ModelSkillResult is written"
        )

    def test_prompt_documents_filters_in_result(self) -> None:
        """ModelSkillResult must include filters field for audit."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert '"filters"' in content or "filters" in content, (
            "ModelSkillResult must include filters field"
        )

    def test_skill_documents_polish_counters_in_result(self) -> None:
        """SKILL.md ModelSkillResult must include Track B counters."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "polished" in content or "polish_queue" in content, (
            "SKILL.md ModelSkillResult must document Track B (polish) counters"
        )


# ---------------------------------------------------------------------------
# Test class: Merge-policy coverage (structural)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergePolicyCoverage:
    """Verify merge-policy is documented in SKILL.md."""

    def test_skill_documents_merge_policy_args(self) -> None:
        """SKILL.md must document key merge-policy arguments."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "--require-approval" in content, (
            "SKILL.md must document --require-approval merge policy argument"
        )
        assert "--require-up-to-date" in content, (
            "SKILL.md must document --require-up-to-date merge policy argument"
        )

    def test_skill_documents_minimum_repos(self) -> None:
        """SKILL.md or prompt.md must reference at least one repo in scope."""
        prompt_content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        skill_content = _read_skill_file(_MERGE_SWEEP_SKILL)
        combined = prompt_content + skill_content
        has_repos = any(
            repo in combined
            for repo in [
                "OmniNode-ai/omniclaude",
                "OmniNode-ai/omnibase_core",
                "omni_home",
                "repos.yaml",
            ]
        )
        assert has_repos, (
            "Skill must reference at least one repo in scope or a repo manifest"
        )


# ---------------------------------------------------------------------------
# Test class: CI enforcement grep
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCIEnforcementGrep:
    """Simulate CI enforcement grep checks."""

    def test_no_no_gate_in_skills_excluding_lib(self) -> None:
        """Simulate CI check: zero --no-gate occurrences in skills/ (excl. _lib/pr-safety)."""
        if not _SKILLS_ROOT.exists():
            pytest.skip(f"Skills root not found: {_SKILLS_ROOT}")

        violations: list[str] = []
        for md_file in _SKILLS_ROOT.rglob("*.md"):
            if "_lib/pr-safety" in str(md_file):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                if "no-gate" in line:
                    rel_path = md_file.relative_to(_REPO_ROOT)
                    violations.append(f"{rel_path}:{line_num}: {line.strip()}")

        assert violations == [], (
            "--no-gate found in skills. Use GitHub auto-merge instead:\n"
            + "\n".join(violations)
        )

    def test_no_bare_gh_pr_merge_without_auto(self) -> None:
        """prompt.md must not contain 'gh pr merge' without '--auto' flag.

        gh pr merge --auto (enable GitHub auto-merge) is allowed and expected.
        gh pr merge without --auto (immediate force-merge) is banned UNLESS it is
        the documented fallback for when --auto fails with "clean status" error.
        The fallback is identified by nearby context mentioning "clean status" or
        "Fall back to direct merge" within a 5-line window.
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()
        violations = []
        for line_num, line in enumerate(lines, 1):
            if re.search(r"\bgh pr merge\b", line) and "--auto" not in line:
                # Check surrounding context (5 lines before/after) for fallback pattern
                context_start = max(0, line_num - 6)
                context_end = min(len(lines), line_num + 5)
                context = "\n".join(lines[context_start:context_end]).lower()
                is_fallback = (
                    "clean status" in context
                    or "fall back to direct merge" in context
                    or "merged_directly" in context
                )
                if not is_fallback:
                    violations.append(f"line {line_num}: {line.strip()}")

        assert violations == [], (
            "Direct 'gh pr merge' without '--auto' found in merge-sweep/prompt.md. "
            "Use 'gh pr merge --auto' to enable GitHub auto-merge (not immediate merge):\n"
            + "\n".join(violations)
        )

    def test_prompt_contains_gh_pr_merge_auto(self) -> None:
        """prompt.md MUST contain 'gh pr merge' with '--auto' (the v3.0.0 merge mechanism)."""
        result = subprocess.run(
            [
                "grep",
                "-n",
                "gh pr merge.*--auto\\|--auto.*gh pr merge",
                str(_MERGE_SWEEP_PROMPT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0 and result.stdout.strip() != "", (
            "prompt.md must contain 'gh pr merge --auto' — the GitHub auto-merge mechanism"
        )


# ---------------------------------------------------------------------------
# Test class: Proactive branch update (v3.1.0, OMN-3818)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProactiveBranchUpdate:
    """v3.1.0 adds proactive detection and update of stale (BEHIND/UNKNOWN) branches.

    PRs with mergeStateStatus BEHIND or UNKNOWN are updated BEFORE auto-merge is
    attempted (Step 5b), preventing the chicken-and-egg deadlock with strict branch
    protection.
    """

    def test_prompt_documents_needs_branch_update_predicate(self) -> None:
        """prompt.md must document needs_branch_update() classification predicate."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "needs_branch_update" in content, (
            "prompt.md must document needs_branch_update() predicate for Track A-update"
        )

    def test_skill_documents_needs_branch_update_predicate(self) -> None:
        """SKILL.md must document needs_branch_update() classification predicate."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "needs_branch_update" in content, (
            "SKILL.md must document needs_branch_update() predicate for Track A-update"
        )

    def test_prompt_includes_merge_state_status_in_scan_fields(self) -> None:
        """prompt.md must include mergeStateStatus in the JSON fields fetched during scan."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "mergeStateStatus" in content, (
            "prompt.md must include mergeStateStatus in scan JSON fields"
        )

    def test_skill_documents_track_a_update(self) -> None:
        """SKILL.md must document Track A-update for stale branch handling."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "Track A-update" in content, (
            "SKILL.md must document Track A-update (proactive branch updates)"
        )

    def test_prompt_documents_step_5b_before_step_6(self) -> None:
        """Step 5b (proactive branch update) must appear before Step 6 (auto-merge)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()
        step_5b_idx = next(
            (
                i
                for i, line in enumerate(lines)
                if "Step 5b" in line or "Phase A-update" in line
            ),
            None,
        )
        step_6_idx = next(
            (i for i, line in enumerate(lines) if "## Step 6" in line),
            None,
        )
        assert step_5b_idx is not None, (
            "prompt.md must contain Step 5b (proactive branch update)"
        )
        assert step_6_idx is not None, "prompt.md must contain Step 6 (Phase A)"
        assert step_5b_idx < step_6_idx, (
            "Step 5b (proactive branch update) must appear before Step 6 (Phase A auto-merge)"
        )

    def test_prompt_documents_branch_updated_result(self) -> None:
        """prompt.md must document branch_updated as a result value."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "branch_updated" in content, (
            "prompt.md must document 'branch_updated' result value for proactive updates"
        )

    def test_skill_documents_branch_updated_result(self) -> None:
        """SKILL.md must document branch_updated as a result value."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "branch_updated" in content, (
            "SKILL.md must document 'branch_updated' result value"
        )

    def test_skill_documents_proactive_branch_counter(self) -> None:
        """SKILL.md ModelSkillResult must include branches_updated_proactive counter."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "branches_updated_proactive" in content, (
            "SKILL.md ModelSkillResult must include branches_updated_proactive counter"
        )

    def test_prompt_documents_branch_update_queue(self) -> None:
        """prompt.md must document branch_update_queue for stale PRs."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "branch_update_queue" in content, (
            "prompt.md must document branch_update_queue[] for stale PRs"
        )

    def test_prompt_documents_classification_order(self) -> None:
        """prompt.md must specify that needs_branch_update is checked BEFORE is_merge_ready."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "first match wins" in content.lower() or "checked BEFORE" in content, (
            "prompt.md must document classification order "
            "(needs_branch_update checked BEFORE is_merge_ready)"
        )

    def test_prompt_uses_check_merge_state_helper(self) -> None:
        """prompt.md Step 5b must use check_merge_state() from pr-safety helpers."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "check_merge_state" in content, (
            "prompt.md must use check_merge_state() from @_lib/pr-safety/helpers.md"
        )

    def test_prompt_uses_update_pr_branch_helper(self) -> None:
        """prompt.md Step 5b must use update_pr_branch() from pr-safety helpers."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "update_pr_branch" in content, (
            "prompt.md must use update_pr_branch() from @_lib/pr-safety/helpers.md"
        )

    def test_skill_documents_behind_unknown_handling(self) -> None:
        """SKILL.md failure table must document BEHIND/UNKNOWN handling."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "BEHIND" in content and "UNKNOWN" in content, (
            "SKILL.md failure handling must document BEHIND and UNKNOWN mergeStateStatus"
        )

    def test_pr_scan_sh_includes_merge_state_status(self) -> None:
        """_bin/pr-scan.sh must include mergeStateStatus in default JSON fields."""
        pr_scan_path = _REPO_ROOT / "plugins" / "onex" / "_bin" / "pr-scan.sh"
        if not pr_scan_path.exists():
            pytest.skip("_bin/pr-scan.sh not found")
        content = pr_scan_path.read_text(encoding="utf-8")
        assert "mergeStateStatus" in content, (
            "_bin/pr-scan.sh must include mergeStateStatus in default JSON fields"
        )


# ---------------------------------------------------------------------------
# Test class: Post-scan coverage assertion (v3.2.0, OMN-4517)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostScanCoverageAssertion:
    """v3.2.0 adds a post-scan coverage assertion to detect repos silently missed.

    The parallel scan fan-out must be validated: every configured repo must have
    returned a result (even an empty list). A repo with zero PRs is distinct from
    a repo that silently failed to return any result.
    """

    def test_prompt_initializes_repo_scan_results_dict(self) -> None:
        """prompt.md must initialize repo_scan_results before scanning."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "repo_scan_results" in content, (
            "prompt.md must initialize repo_scan_results dict before scan phase"
        )

    def test_prompt_distinguishes_zero_prs_from_scan_failure(self) -> None:
        """prompt.md must distinguish between zero-PRs (confirmed empty) and scan failure."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # Both None sentinel and empty list concept must be documented
        assert "None" in content and (
            "[]" in content or "empty list" in content.lower()
        ), "prompt.md must distinguish scan_failure (None) from zero-PRs (empty list)"

    def test_prompt_documents_post_scan_assertion(self) -> None:
        """prompt.md must document the post-scan coverage assertion after scan phase."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert (
            "Post-Scan Coverage Assertion" in content or "post-scan" in content.lower()
        ), "prompt.md must document the post-scan coverage assertion (OMN-4517)"

    def test_prompt_logs_warning_for_scan_failures(self) -> None:
        """prompt.md must log WARNING for repos that did not return scan results."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "WARNING" in content and "scan" in content.lower(), (
            "prompt.md must log WARNING for repos that silently missed the scan"
        )

    def test_prompt_records_scan_failed_result(self) -> None:
        """prompt.md must record result: scan_failed for repos that never returned."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "scan_failed" in content, (
            "prompt.md must record 'result: scan_failed' in ModelSkillResult details"
        )

    def test_skill_documents_repos_scanned_counter(self) -> None:
        """SKILL.md ModelSkillResult must include repos_scanned counter."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "repos_scanned" in content, (
            "SKILL.md ModelSkillResult must include repos_scanned counter (OMN-4517)"
        )

    def test_skill_documents_repos_failed_counter(self) -> None:
        """SKILL.md ModelSkillResult must include repos_failed counter."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "repos_failed" in content, (
            "SKILL.md ModelSkillResult must include repos_failed counter (OMN-4517)"
        )

    def test_prompt_documents_repos_scanned_counter(self) -> None:
        """prompt.md ModelSkillResult must include repos_scanned counter."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "repos_scanned" in content, (
            "prompt.md ModelSkillResult must include repos_scanned counter (OMN-4517)"
        )

    def test_prompt_documents_repos_failed_counter(self) -> None:
        """prompt.md ModelSkillResult must include repos_failed counter."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "repos_failed" in content, (
            "prompt.md ModelSkillResult must include repos_failed counter (OMN-4517)"
        )

    def test_skill_documents_scan_failed_in_failure_table(self) -> None:
        """SKILL.md failure handling table must document scan_failed case."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "scan_failed" in content, (
            "SKILL.md failure handling table must document scan_failed result (OMN-4517)"
        )

    def test_skill_documents_scan_failed_result_value(self) -> None:
        """SKILL.md must list scan_failed as a result value."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        # Result values section or details section must include scan_failed
        assert "scan_failed" in content, (
            "SKILL.md must document scan_failed as a result value for repos that missed the scan"
        )

    def test_prompt_slack_summary_includes_scan_failure_warning(self) -> None:
        """prompt.md Slack summary must include scan failure warning when repos_failed > 0."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "scan_failure_details" in content or "repos_failed" in content, (
            "prompt.md Slack summary must include scan failure warning (OMN-4517)"
        )

    def test_skill_slack_summary_documents_scan_failure_line(self) -> None:
        """SKILL.md Slack summary format must show scan failure count."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert (
            "Scan failures" in content
            or "repos_failed" in content
            or "repos scanned" in content.lower()
        ), "SKILL.md Slack summary must document scan failure info (OMN-4517)"

    def test_scan_failure_does_not_abort_run(self) -> None:
        """prompt.md must document that scan failures do NOT abort the run."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert (
            "do NOT abort" in content
            or "NOT abort" in content
            or "not abort" in content.lower()
        ), "prompt.md must document that scan failures do not abort the run (OMN-4517)"

    def test_prompt_version_updated_to_v320(self) -> None:
        """SKILL.md version must be bumped to 3.2.0 for OMN-4517 changes."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "3.2.0" in content, "SKILL.md version must be bumped to 3.2.0 (OMN-4517)"

    def test_prompt_documents_all_details_merge(self) -> None:
        """prompt.md must merge scan_failure_details into the final details list."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "scan_failure_details" in content, (
            "prompt.md must include scan_failure_details in the collected results/details list"
        )
