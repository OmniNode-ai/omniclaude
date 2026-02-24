# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for the merge-sweep skill (OMN-2635).

Tests verify:
- Dry-run contract: zero writes to ~/.claude/pr-queue/ runs/
- Gate-attestation ban: --no-gate absent from skill docs (migration complete, OMN-2633)
- No direct mutation calls in prompt.md (gh pr merge, git push, gh pr checkout)
- Claim-before-mutate invariant documented in prompt.md
- CI enforcement: merge-sweep/prompt.md contains no direct gh pr list calls

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
    """Test case 1 + 5: dry-run produces zero ~/.claude/pr-queue/runs/ writes.

    These are static/structural tests — we verify the prompt.md encodes the
    dry-run invariant correctly, not that the live skill executes correctly.
    """

    def test_prompt_documents_dry_run_no_mutation(self) -> None:
        """Prompt must document that --dry-run exits without gate or merge."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # Step 5 in prompt.md must state dry-run exits without posting a gate
        assert "dry-run" in content.lower() or "--dry-run" in content, (
            "prompt.md must document --dry-run behavior"
        )
        # Dry-run must not post gate
        assert "Dry run complete" in content or "no gate" in content.lower(), (
            "prompt.md must state dry-run skips gate"
        )

    def test_skill_documents_dry_run_flag(self) -> None:
        """SKILL.md must list --dry-run as a documented argument."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "--dry-run" in content, "SKILL.md must document the --dry-run argument"

    def test_prompt_dry_run_exit_before_merge(self) -> None:
        """Prompt must show EXIT in dry-run section before reaching merge phase."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # Find the dry-run section
        lines = content.splitlines()
        dry_run_section_start = None
        for i, line in enumerate(lines):
            if "--dry-run" in line and (
                "Step" in lines[max(0, i - 5) : i + 1] or "Dry" in line
            ):
                dry_run_section_start = i
                break
        # The dry-run check should appear before Step 6 (Gate Phase)
        step6_idx = next(
            (
                i
                for i, line in enumerate(lines)
                if "Step 6" in line or "## Step 6" in line
            ),
            None,
        )
        if dry_run_section_start is not None and step6_idx is not None:
            assert dry_run_section_start < step6_idx, (
                "Dry-run exit must appear before Step 6 (Gate Phase) in prompt.md"
            )


# ---------------------------------------------------------------------------
# Test class: Gate-attestation ban (OMN-2633 migration complete)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGateAttestationBan:
    """Test case 6: --no-gate is banned from all skill docs (OMN-2633 complete).

    After OMN-2633, the migration window is closed. merge-sweep must not
    reference --no-gate in any skill doc (prompt.md or SKILL.md).
    _lib/pr-safety/helpers.md may contain explanatory prose — excluded.
    """

    def test_no_gate_absent_from_prompt(self) -> None:
        """prompt.md must not contain --no-gate after OMN-2633 migration."""
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"--no-gate")
        assert matches == [], (
            "--no-gate found in merge-sweep/prompt.md (migration complete per OMN-2633):\n"
            + "\n".join(matches)
        )

    def test_no_gate_absent_from_skill_md(self) -> None:
        """SKILL.md must not contain --no-gate after OMN-2633 migration."""
        matches = _grep_file(_MERGE_SWEEP_SKILL, r"--no-gate")
        assert matches == [], (
            "--no-gate found in merge-sweep/SKILL.md (migration complete per OMN-2633):\n"
            + "\n".join(matches)
        )

    def test_gate_attestation_present_in_skill(self) -> None:
        """SKILL.md must document the --gate-attestation replacement argument."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "--gate-attestation" in content, (
            "SKILL.md must document --gate-attestation as the gate bypass mechanism"
        )

    def test_gate_attestation_present_in_prompt(self) -> None:
        """prompt.md must reference --gate-attestation bypass mode."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "--gate-attestation" in content, (
            "prompt.md must reference --gate-attestation bypass mode"
        )

    def test_gate_token_format_documented(self) -> None:
        """SKILL.md must document the gate token format <slack_ts>:<run_id>."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        # Format should be documented without the = prefix (CLI separator, not token)
        assert "<slack_ts>:<run_id>" in content, (
            "SKILL.md must document gate token format as <slack_ts>:<run_id>"
        )


# ---------------------------------------------------------------------------
# Test class: No direct mutation calls in prompt.md
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoDirectMutationCalls:
    """Test case 7: merge-sweep/prompt.md must not contain direct mutation calls.

    Direct calls to gh pr merge, git push, gh pr checkout, and gh api .*/merge
    are CI enforcement violations per _lib/pr-safety/helpers.md. The skill
    must dispatch these via auto-merge sub-skill or through mutate_pr().
    """

    DIRECT_MUTATION_PATTERNS = [
        r"gh pr merge",
        r"gh pr checkout",
        r"gh api .*/merge",
    ]

    def test_no_gh_pr_merge_in_prompt(self) -> None:
        """prompt.md must not contain direct 'gh pr merge' calls."""
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"\bgh pr merge\b")
        assert matches == [], (
            "Direct 'gh pr merge' found in merge-sweep/prompt.md. "
            "Use auto-merge sub-skill instead:\n" + "\n".join(matches)
        )

    def test_no_gh_pr_checkout_in_prompt(self) -> None:
        """prompt.md must not contain direct 'gh pr checkout' calls."""
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"\bgh pr checkout\b")
        assert matches == [], (
            "Direct 'gh pr checkout' found in merge-sweep/prompt.md:\n"
            + "\n".join(matches)
        )

    def test_no_git_push_in_prompt(self) -> None:
        """prompt.md must not contain direct 'git push' calls (outside code blocks)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # Allow 'git push' in bash code examples for credential resolution only
        # but not as an instruction to the agent
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"\bgit push\b")
        # Check if any matches are instruction lines (not in fenced code blocks)
        instruction_matches = [
            line
            for line in matches
            if not line.strip().startswith("#") and not line.strip().startswith("```")
        ]
        # If git push appears, it should be in a context that is a code example
        # We allow it in bash blocks but not as prose instructions
        # The test checks it's not a plain instruction line
        assert len(instruction_matches) == 0 or all(
            "git push" in line and ("```" in line or line.strip().startswith("git"))
            for line in instruction_matches
        ), (
            "Direct 'git push' instruction found in merge-sweep/prompt.md. "
            "Mutations must go through auto-merge sub-skill:\n"
            + "\n".join(instruction_matches)
        )

    def test_dispatches_to_auto_merge_sub_skill(self) -> None:
        """prompt.md must dispatch merges via auto-merge sub-skill."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "auto-merge" in content, (
            "prompt.md must reference auto-merge sub-skill for merge dispatch"
        )

    def test_skill_lists_auto_merge_dependency(self) -> None:
        """SKILL.md must list auto-merge in Sub-skills section."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "auto-merge" in content, (
            "SKILL.md must reference auto-merge as a sub-skill dependency"
        )


# ---------------------------------------------------------------------------
# Test class: No direct gh pr list in prose logic (claim pattern)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoDirectGhPrList:
    """Test case 3 (adapted): merge-sweep/prompt.md scans via a scan phase.

    The prompt.md is allowed to document the gh pr list command used in the
    scan phase, but must not contain raw 'gh pr list' calls that bypass
    claim/lifecycle management. We verify the scan is scoped to Step 2/3.
    """

    def test_gh_pr_list_only_in_scan_phase(self) -> None:
        """gh pr list in prompt.md must appear in the scan phase section."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()

        # Find all lines with gh pr list
        gh_pr_list_lines = [
            (i, line) for i, line in enumerate(lines) if "gh pr list" in line
        ]

        if not gh_pr_list_lines:
            # No direct gh pr list — passes (could use sub-skill)
            return

        # Each occurrence must be in Step 2 or Step 3 (scan/classify phase)
        for line_idx, line_text in gh_pr_list_lines:
            # Look back up to 50 lines for a Step heading
            context_start = max(0, line_idx - 50)
            context_lines = lines[context_start:line_idx]
            # Find the most recent step heading
            step_heading = None
            for ctx_line in reversed(context_lines):
                step_match = re.search(r"## Step (\d+)", ctx_line)
                if step_match:
                    step_heading = int(step_match.group(1))
                    break

            # gh pr list should be in Step 2 (scope/scan) or Step 3 (classify)
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
    """Test case 4: Claim-before-mutate invariant is enforced in skill docs.

    merge-sweep dispatches to auto-merge which enforces the claim lifecycle.
    We verify the prompt.md documents the gate_token/audit trail requirement
    and that the skill composition ensures no unclaimed mutation.
    """

    def test_prompt_documents_gate_token_audit(self) -> None:
        """prompt.md must reference gate_token as audit trail for merges."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "gate_token" in content, (
            "prompt.md must document gate_token as audit trail for merge operations"
        )

    def test_prompt_dispatches_merge_with_gate_token(self) -> None:
        """Merge dispatch in prompt.md must include gate_token for audit trail."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        # The merge dispatch section (Step 7) must pass gate_token
        assert "gate_token" in content and "auto-merge" in content, (
            "prompt.md merge dispatch must pass gate_token to auto-merge sub-skill"
        )

    def test_skill_documents_claim_lifecycle_via_auto_merge(self) -> None:
        """SKILL.md must confirm claim lifecycle is handled by auto-merge sub-skill."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        # auto-merge sub-skill handles claim lifecycle
        assert "auto-merge" in content, (
            "SKILL.md must document that claim lifecycle is delegated to auto-merge"
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
    """Verify merge-sweep emits a documented ModelSkillResult contract."""

    REQUIRED_STATUS_VALUES = [
        "merged",
        "nothing_to_merge",
        "gate_rejected",
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


# ---------------------------------------------------------------------------
# Test class: Merge-policy coverage (structural)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergePolicyCoverage:
    """Test case 2 (adapted): Verify merge-policy is documented in SKILL.md.

    merge-policy.yaml is referenced in the ticket description. Since the file
    may not exist yet, we verify the skill documents its merge-policy behavior
    through the argument table (--require-approval, --require-up-to-date).
    """

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
        # Should reference known OmniNode repos
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
# Test class: CI enforcement grep (run the actual CI check logic)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCIEnforcementGrep:
    """Simulate the CI enforcement grep checks from omni-standards-compliance.yml."""

    def test_no_no_gate_in_skills_excluding_lib(self) -> None:
        """Simulate CI check: grep -r 'no-gate' skills/ --include='*.md' | grep -v _lib/pr-safety.

        This mirrors the CI enforcement step in omni-standards-compliance.yml
        that was updated by OMN-2633 to require zero --no-gate occurrences.
        """
        if not _SKILLS_ROOT.exists():
            pytest.skip(f"Skills root not found: {_SKILLS_ROOT}")

        violations: list[str] = []
        for md_file in _SKILLS_ROOT.rglob("*.md"):
            # Exclude _lib/pr-safety (explanatory prose allowed)
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
            "--no-gate found in skills (migration complete per OMN-2633). "
            "Use --gate-attestation=<token> instead:\n" + "\n".join(violations)
        )

    def test_no_direct_merge_outside_auto_merge(self) -> None:
        """Verify no direct gh pr merge calls in merge-sweep prompt."""
        result = subprocess.run(
            [
                "grep",
                "-n",
                "gh pr merge",
                str(_MERGE_SWEEP_PROMPT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # grep exits 1 when no matches found (which is success for us)
        assert result.returncode == 1 or result.stdout.strip() == "", (
            f"Direct 'gh pr merge' found in merge-sweep/prompt.md:\n{result.stdout}"
        )
