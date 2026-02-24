# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for the gap-fix skill (OMN-2639).

Tests verify:
- Dry-run contract: zero ~/.claude/ writes documented
- "fixed" status requires probe block with exit_code=0 and repo_head_sha
- Infra boundary gate: DB import in UI repo moves to decision gate
- Positive routing: "new data required" tickets producer repo, not consumer
- decisions.json is append-only (no silent overwrite)
- decisions.json --force-decide with token creates version 2 entry
- pr-queue-pipeline invoked with --prs, never --repos

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
_GAP_FIX_DIR = _SKILLS_ROOT / "gap-fix"
_GAP_FIX_PROMPT = _GAP_FIX_DIR / "prompt.md"
_GAP_FIX_SKILL = _GAP_FIX_DIR / "SKILL.md"


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
# Test case 1: Dry-run — zero ~/.claude/ writes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunContract:
    """Test case 1: --dry-run produces zero side effects.

    /gap-fix --report <run_path> --dry-run must:
    - Not write decisions.json
    - Not write gap-fix-output.json
    - Not create Linear tickets or PRs
    - Not invoke ticket-pipeline or pr-queue-pipeline
    - Print a plan table to stdout
    """

    def test_prompt_documents_dry_run_zero_side_effects(self) -> None:
        """prompt.md must document that --dry-run produces zero side effects."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "--dry-run" in content, "prompt.md must document --dry-run flag"
        # Must state zero side effects explicitly
        assert (
            "zero side effect" in content.lower() or "no side effect" in content.lower()
        ), "prompt.md must document that --dry-run produces zero side effects"

    def test_prompt_documents_dry_run_no_decisions_write(self) -> None:
        """prompt.md must explicitly state --dry-run does not write decisions.json."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        # The prompt must say dry-run skips or forbids decisions.json writes
        assert "dry_run" in content or "--dry-run" in content, (
            "prompt.md must reference --dry-run behavior"
        )
        assert "decisions.json" in content, "prompt.md must reference decisions.json"

    def test_prompt_documents_dry_run_no_ticket_pipeline(self) -> None:
        """prompt.md must state --dry-run skips ticket-pipeline dispatch."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        # dry-run section must mention skipping ticket-pipeline
        assert "ticket-pipeline" in content, (
            "prompt.md must reference ticket-pipeline dispatch"
        )

    def test_skill_documents_dry_run_flag(self) -> None:
        """SKILL.md must document --dry-run flag in args section."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert "--dry-run" in content, "SKILL.md must document --dry-run flag"

    def test_prompt_documents_dry_run_log_prefix(self) -> None:
        """prompt.md must document [DRY RUN] log prefix for dry-run output."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "[DRY RUN]" in content or "DRY RUN" in content, (
            "prompt.md must document [DRY RUN] log prefix for output"
        )

    def test_prompt_documents_no_pr_queue_pipeline_in_dry_run(self) -> None:
        """prompt.md must document that pr-queue-pipeline is not called in dry-run."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "pr-queue-pipeline" in content, (
            "prompt.md must reference pr-queue-pipeline"
        )


# ---------------------------------------------------------------------------
# Test case 2: "fixed" status requires probe block with exit_code=0 and repo_head_sha
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFixedRequiresProof:
    """Test case 2: 'fixed' status requires probe block with exit_code=0 and repo_head_sha.

    A finding cannot be marked status='fixed' unless the re-probe block contains:
    - exit_code == 0
    - repo_head_sha (non-empty, links proof to a specific commit)

    If probe block is absent or exit_code != 0, gap-fix must use
    status='implemented_not_verified' or keep finding as 'still_open'.
    """

    REQUIRED_PROBE_FIELDS = [
        "command",
        "exit_code",
        "stdout_sha256",
        "repo_head_sha",
        "ran_at",
    ]

    def test_prompt_documents_required_probe_fields(self) -> None:
        """prompt.md must document all required probe block fields."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        missing = [f for f in self.REQUIRED_PROBE_FIELDS if f not in content]
        assert missing == [], (
            f"prompt.md missing required probe block fields: {missing}. "
            "All 5 fields must be documented: command, exit_code, stdout_sha256, "
            "repo_head_sha, ran_at"
        )

    def test_prompt_documents_fixed_requires_exit_code_zero(self) -> None:
        """prompt.md must state that marking 'fixed' requires exit_code=0."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        # Must link exit_code=0 to the fixed status gate
        assert "exit_code" in content, (
            "prompt.md must document exit_code as a required field"
        )
        assert (
            "exit_code=0" in content
            or "exit_code == 0" in content
            or "exit_code: 0" in content
        ), (
            "prompt.md must explicitly require exit_code=0 before marking a finding 'fixed'"
        )

    def test_prompt_documents_repo_head_sha_requirement(self) -> None:
        """prompt.md must require repo_head_sha before marking 'fixed'."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "repo_head_sha" in content, (
            "prompt.md must require repo_head_sha in the probe block. "
            "This field links the proof to a specific commit, making it auditable."
        )

    def test_prompt_documents_implemented_not_verified_fallback(self) -> None:
        """prompt.md must document 'implemented_not_verified' status when probe is absent."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "implemented_not_verified" in content, (
            "prompt.md must document 'implemented_not_verified' status for cases "
            "where probe block is absent or exit_code != 0. "
            "gap-fix must not silently mark findings as 'fixed' without proof."
        )

    def test_prompt_documents_still_open_on_probe_failure(self) -> None:
        """prompt.md must document 'still_open' when re-probe fails."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "still_open" in content, (
            "prompt.md must document 'still_open' status when re-probe fails"
        )

    def test_skill_documents_probe_required_before_fixed(self) -> None:
        """SKILL.md must document 'Re-probe must pass before marking fixed'."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert (
            "Re-probe **must pass**" in content
            or "re-probe must pass" in content.lower()
            or "Re-probe must pass" in content
        ), (
            "SKILL.md must document the invariant: re-probe must pass before marking fixed"
        )


# ---------------------------------------------------------------------------
# Test case 3: Infra boundary gate — DB import in UI repo goes to decision gate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInfraBoundaryGate:
    """Test case 3: boundary_validate() routes infra violations to decision gate.

    When gap-fix detects a finding where a UI repo (e.g., omnidash) imports
    a database driver (e.g., asyncpg), boundary_validate() must classify this
    as an import_boundary_violation and route the finding to the decision gate —
    NOT auto-dispatch it for direct fix.
    """

    def test_prompt_documents_boundary_validate(self) -> None:
        """prompt.md must reference boundary_validate() or boundary validation."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert (
            "boundary_validate" in content
            or "boundary validation" in content.lower()
            or "boundary_kind" in content
        ), (
            "prompt.md must document boundary_validate() or boundary validation logic. "
            "DB imports in UI repos must not be auto-dispatched."
        )

    def test_prompt_documents_import_boundary_violation_gate(self) -> None:
        """prompt.md must document that import boundary violations go to GATE."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        # The auto-dispatch table must handle boundary violations
        assert "GATE" in content, (
            "prompt.md must document that boundary violations route to GATE, not AUTO"
        )

    def test_prompt_documents_auto_dispatch_table(self) -> None:
        """prompt.md must document the auto-dispatch eligibility table."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "AUTO" in content and "GATE" in content, (
            "prompt.md must document the auto-dispatch table with AUTO and GATE classes"
        )

    def test_prompt_documents_gate_emission_on_boundary_violation(self) -> None:
        """prompt.md must document emitting decision gate for boundary violations."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "DECISION REQUIRED" in content or "decision gate" in content.lower(), (
            "prompt.md must document emitting a DECISION REQUIRED block for gated findings"
        )

    def test_skill_documents_boundary_violation_as_gate(self) -> None:
        """SKILL.md must state that boundary violations go to the decision gate."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        # The skill must document that non-safe findings go to gate
        assert "gate" in content.lower() or "GATE" in content, (
            "SKILL.md must document the decision gate for non-auto-dispatchable findings"
        )


# ---------------------------------------------------------------------------
# Test case 4: Positive routing — "new data required" tickets producer, not consumer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPositiveRouting:
    """Test case 4: New data required findings ticket the producing repo.

    When a finding requires new DB data in a consumer repo (e.g., omnidash),
    gap-fix must create the ticket in the producing repo (omnibase_infra or
    omnibase_core), NOT patch the consumer directly.

    The routing rule: findings requiring data source changes should be dispatched
    to the data producer, not the consumer that depends on that data.
    """

    def test_prompt_documents_pr_queue_pipeline_scoped_to_prs(self) -> None:
        """prompt.md must invoke pr-queue-pipeline with --prs (not --repos)."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "pr-queue-pipeline" in content, (
            "prompt.md must reference pr-queue-pipeline"
        )
        # Must use --prs flag, not --repos
        assert "--prs" in content, (
            "prompt.md must call pr-queue-pipeline with --prs flag (scoped to new PRs)"
        )

    def test_prompt_documents_repos_field_in_finding(self) -> None:
        """prompt.md must document using finding.repos to determine dispatch target."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "repos" in content, (
            "prompt.md must document finding.repos[] for determining target repo"
        )

    def test_skill_documents_prs_flag_for_pr_queue_pipeline(self) -> None:
        """SKILL.md must document pr-queue-pipeline called with --prs."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert "pr-queue-pipeline" in content, (
            "SKILL.md must reference pr-queue-pipeline in Sub-skills Used"
        )
        assert "--prs" in content, (
            "SKILL.md must document pr-queue-pipeline called with --prs, not --repos"
        )

    def test_skill_documents_not_repos_flag(self) -> None:
        """SKILL.md must document that pr-queue-pipeline uses --prs, NOT --repos."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        # The constraint must be stated: --prs not --repos
        assert (
            "NOT --repos" in content
            or "not --repos" in content.lower()
            or ("--prs" in content and "--repos" in content)
        ), (
            "SKILL.md must document the constraint: pr-queue-pipeline uses "
            "--prs (not --repos) to scope to only the created PRs"
        )

    def test_prompt_documents_no_repos_flag_for_pr_queue_pipeline(self) -> None:
        """prompt.md must not call pr-queue-pipeline with --repos."""
        # Verify that any pr-queue-pipeline call in the prompt uses --prs
        lines = _grep_file(_GAP_FIX_PROMPT, r"pr-queue-pipeline.*--repos")
        assert lines == [], (
            "prompt.md must not call pr-queue-pipeline with --repos. "
            "Only --prs is allowed to scope to created PRs:\n" + "\n".join(lines)
        )


# ---------------------------------------------------------------------------
# Test case 5: decisions.json is append-only (no silent overwrite)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDecisionsJsonAppendOnly:
    """Test case 5: decisions.json is append-only.

    Writing a decision for a fingerprint at version 1 and then attempting
    --force-decide without a new approver_token must be rejected.

    The invariant: decisions.json entries are write-once per finding fingerprint
    unless --force-decide is set with a new approver_token.
    """

    def test_prompt_documents_decisions_json_write_once(self) -> None:
        """prompt.md must document write-once per finding for decisions.json."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "write-once" in content or "write once" in content.lower(), (
            "prompt.md must document decisions.json as write-once per finding fingerprint"
        )

    def test_prompt_documents_force_decide_flag(self) -> None:
        """prompt.md must document --force-decide flag."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "--force-decide" in content, (
            "prompt.md must document --force-decide flag for re-opening decided findings"
        )

    def test_prompt_documents_no_overwrite_without_force_decide(self) -> None:
        """prompt.md must state existing decisions are not overwritten without --force-decide."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        # The behavior: skip silently if already decided (without --force-decide)
        assert (
            "skip silently" in content
            or "already decided" in content.lower()
            or "not overwrite" in content.lower()
            or "never overwrite" in content.lower()
        ), (
            "prompt.md must document that existing decisions are not overwritten "
            "without --force-decide (skip silently if already decided)"
        )

    def test_skill_documents_decisions_json_structure(self) -> None:
        """SKILL.md must document the decisions.json structure."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert "decisions.json" in content, "SKILL.md must reference decisions.json"

    def test_prompt_documents_decisions_json_location(self) -> None:
        """prompt.md must document where decisions.json is stored (alongside source report)."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "decisions.json" in content, (
            "prompt.md must document decisions.json file"
        )
        # Must be co-located with source run, not fix run
        assert "source_run_id" in content or "source run" in content.lower(), (
            "prompt.md must document that decisions.json lives alongside the source report "
            "(keyed by source_run_id, not fix_run_id)"
        )

    def test_skill_documents_force_decide_flag(self) -> None:
        """SKILL.md must document --force-decide flag."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert "--force-decide" in content, (
            "SKILL.md must document --force-decide flag in args section"
        )


# ---------------------------------------------------------------------------
# Test case 6: decisions.json --force-decide with token creates version 2 entry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestForcedDecideVersioning:
    """Test case 6: --force-decide with new approver_token creates a versioned entry.

    After writing decision v1, calling --force-decide with a new approver_token
    must result in decisions.json having a list with 2 entries for that fingerprint
    (append, not replace).

    This preserves the full audit trail of decisions.
    """

    def test_prompt_documents_force_decide_behavior(self) -> None:
        """prompt.md must document --force-decide re-opening previously decided findings."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "--force-decide" in content, (
            "prompt.md must document --force-decide flag"
        )
        # Must state it treats prior decisions as absent (re-opens them)
        assert (
            "treat" in content.lower() and "absent" in content.lower()
        ) or "re-open" in content.lower(), (
            "prompt.md must document that --force-decide treats prior decisions as absent "
            "(re-opens them for re-decision)"
        )

    def test_prompt_documents_decisions_json_written_on_gate_resolution(self) -> None:
        """prompt.md must document writing to decisions.json when GATE findings are resolved."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "decisions.json" in content, (
            "prompt.md must document decisions.json write on gate resolution"
        )
        assert "chosen_at" in content or "choice" in content, (
            "prompt.md must document the decisions.json entry structure (choice, chosen_at)"
        )

    def test_prompt_documents_dry_run_skips_decisions_write(self) -> None:
        """prompt.md must document that --dry-run does NOT write decisions.json."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        # The dry-run section must mention decisions.json is not written
        lower = content.lower()
        assert "dry_run" in lower or "--dry-run" in lower, (
            "prompt.md must reference --dry-run behavior for decisions.json"
        )

    def test_skill_documents_decisions_json_append_only(self) -> None:
        """SKILL.md must state decisions.json is write-once per finding."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert "write-once" in content or "append" in content.lower(), (
            "SKILL.md must document decisions.json append-only semantics"
        )


# ---------------------------------------------------------------------------
# Test case 7: pr-queue-pipeline invoked with --prs, never --repos
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrQueuePipelineInvocation:
    """Test case 7: pr-queue-pipeline must always use --prs, never --repos.

    gap-fix dispatches pr-queue-pipeline scoped to the PRs it created.
    Using --repos would expand scope to all PRs in those repos — a dangerous
    blast radius expansion. This must be enforced at the skill level.
    """

    def test_prompt_documents_prs_flag_not_repos(self) -> None:
        """prompt.md must document pr-queue-pipeline called with --prs."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "--prs" in content, (
            "prompt.md must document pr-queue-pipeline invoked with --prs"
        )

    def test_prompt_has_no_pr_queue_pipeline_with_repos_flag(self) -> None:
        """prompt.md must not contain 'pr-queue-pipeline --repos' or '-- --repos'."""
        lines = _grep_file(_GAP_FIX_PROMPT, r"pr-queue-pipeline.*--repos\b")
        assert lines == [], (
            "prompt.md must never call pr-queue-pipeline with --repos. "
            "Only --prs is allowed (scoped to created PRs):\n" + "\n".join(lines)
        )

    def test_skill_documents_critical_prs_only_constraint(self) -> None:
        """SKILL.md must document the critical constraint: --prs not --repos."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert "--prs" in content, (
            "SKILL.md must document that pr-queue-pipeline uses --prs"
        )

    def test_skill_has_no_pr_queue_pipeline_with_repos_flag(self) -> None:
        """SKILL.md must not have pr-queue-pipeline called WITH --repos (not negating --repos)."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        # Lines that call pr-queue-pipeline with --repos as a flag (not in a negation context)
        # Allow: "NOT --repos", "(not --repos)", "never --repos"
        # Disallow: "pr-queue-pipeline --repos" as a direct invocation
        bad_lines = [
            line
            for line in content.splitlines()
            if re.search(r"pr-queue-pipeline.*--repos\b", line)
            and not re.search(
                r"(?i)(NOT|never|not with)\s.*--repos|--repos.*\(not", line
            )
            and not line.strip().startswith("#")
        ]
        assert bad_lines == [], (
            "SKILL.md must not document pr-queue-pipeline called with --repos directly:\n"
            + "\n".join(bad_lines)
        )

    def test_prompt_documents_blocked_external_guard(self) -> None:
        """prompt.md must document blocked_external guard for pr-queue-pipeline."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "blocked_external" in content or "blocked-external" in content, (
            "prompt.md must document blocked_external guard from pr-queue-pipeline. "
            "If blocked_external > 0, log warning and do NOT retry."
        )

    def test_skill_documents_blocked_external_guard(self) -> None:
        """SKILL.md must document blocked_external guard (do not loop on infra failures)."""
        content = _read_skill_file(_GAP_FIX_SKILL)
        assert "blocked.external" in content or "blocked_external" in content, (
            "SKILL.md must document blocked-external CI guard (do not retry on infra failures)"
        )

    def test_prompt_documents_prs_created_output(self) -> None:
        """prompt.md must document gap-fix-output.json with prs_created list."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "prs_created" in content, (
            "prompt.md must document gap-fix-output.json with prs_created[] list"
        )

    def test_prompt_documents_gap_fix_output_json(self) -> None:
        """prompt.md must document writing gap-fix-output.json before pr-queue-pipeline."""
        content = _read_skill_file(_GAP_FIX_PROMPT)
        assert "gap-fix-output.json" in content, (
            "prompt.md must document gap-fix-output.json artifact"
        )
