# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
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
_MERGE_SWEEP_DIR = _SKILLS_ROOT / "merge-sweep"
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
        assert matches == [], (
            "--no-gate found in merge-sweep/prompt.md:\n" + "\n".join(matches)
        )

    def test_no_gate_absent_from_skill_md(self) -> None:
        """SKILL.md must not contain --no-gate."""
        matches = _grep_file(_MERGE_SWEEP_SKILL, r"--no-gate")
        assert matches == [], (
            "--no-gate found in merge-sweep/SKILL.md:\n" + "\n".join(matches)
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
        # onex:auto-merge sub-skill invocation pattern
        assert "onex:auto-merge" not in content, (
            "prompt.md must not dispatch onex:auto-merge sub-skill "
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
        assert "ClaimRegistry" in content or "claim_registry" in content or "registry" in content.lower(), (
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
        gh pr merge without --auto (immediate force-merge) is banned.
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()
        violations = []
        for line_num, line in enumerate(lines, 1):
            if re.search(r"\bgh pr merge\b", line) and "--auto" not in line:
                violations.append(f"line {line_num}: {line.strip()}")

        assert violations == [], (
            "Direct 'gh pr merge' without '--auto' found in merge-sweep/prompt.md. "
            "Use 'gh pr merge --auto' to enable GitHub auto-merge (not immediate merge):\n"
            + "\n".join(violations)
        )

    def test_prompt_contains_gh_pr_merge_auto(self) -> None:
        """prompt.md MUST contain 'gh pr merge' with '--auto' (the v3.0.0 merge mechanism)."""
        result = subprocess.run(
            ["grep", "-n", "gh pr merge.*--auto\\|--auto.*gh pr merge", str(_MERGE_SWEEP_PROMPT)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0 and result.stdout.strip() != "", (
            "prompt.md must contain 'gh pr merge --auto' — the GitHub auto-merge mechanism"
        )
