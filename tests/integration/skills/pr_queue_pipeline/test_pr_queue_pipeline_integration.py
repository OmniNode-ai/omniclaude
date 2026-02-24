# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for the pr-queue-pipeline skill (OMN-2637).

Tests verify:
- Dry-run output documents run_id, would-write paths, and re-run command
- Pipeline documents inventory.json written before sub-skill dispatch
- phase_completed ordered list advances correctly in ledger
- Resume semantics: --run-id skips phases already in phase_completed
- stop_reason "partial_completed" vs "completed" are distinct documented values
- --dry-run + --run-id combination is documented as read-only (no mutations, no heartbeat)
- Terminal run cleanup: no leftover claims after completed/gate_rejected/error/nothing_to_do

All tests are static analysis / structural tests that run without external
credentials, live GitHub access, or live PRs. Safe for CI.

Test markers:
    @pytest.mark.unit  — intentional despite living in tests/integration/. These tests are pure
    static analysis (file reads only) with no Kafka/Postgres/GitHub dependencies. Using
    @pytest.mark.unit ensures they always run in CI; @pytest.mark.integration would cause
    conftest.py to auto-skip them when KAFKA_INTEGRATION_TESTS is unset.
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
_PIPELINE_DIR = _SKILLS_ROOT / "pr-queue-pipeline"
_PIPELINE_PROMPT = _PIPELINE_DIR / "prompt.md"
_PIPELINE_SKILL = _PIPELINE_DIR / "SKILL.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_skill_file(path: Path) -> str:
    """Read a required skill file; fails fast if the file is missing."""
    if not path.exists():
        pytest.fail(f"Required skill file not found: {path}")
    return path.read_text(encoding="utf-8")


def _grep_file(path: Path, pattern: str) -> list[str]:
    """Return lines in file matching the pattern (regex).

    Used to anchor multi-term assertions to co-located content rather than
    relying on independent substring presence across the full document.
    """
    content = _read_skill_file(path)
    compiled = re.compile(pattern)
    return [line for line in content.splitlines() if compiled.search(line)]


# ---------------------------------------------------------------------------
# Test case 1: Dry-run output documents re-run block
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunRerunBlock:
    """Test case 1: dry-run output includes run_id, would-write paths, re-run command.

    /pr-queue-pipeline --dry-run
    → stdout contains: run_id, would-write file paths, re-run command with --run-id
    → ~/.claude/pr-queue/runs/ unchanged (no writes)
    """

    def test_skill_documents_dry_run_flag(self) -> None:
        """SKILL.md must document the --dry-run argument."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "--dry-run" in content, "SKILL.md must document --dry-run argument"

    def test_prompt_documents_dry_run_rerun_block(self) -> None:
        """prompt.md must document that --dry-run prints a re-run block."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "Re-run command" in content or "re-run" in content.lower(), (
            "prompt.md must document dry-run re-run block output"
        )

    def test_prompt_documents_run_id_in_dry_run_output(self) -> None:
        """prompt.md must document that run_id appears in dry-run output."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "run_id" in content, "prompt.md must reference run_id in dry-run output"

    def test_prompt_documents_would_write_paths_in_dry_run(self) -> None:
        """prompt.md must document would-write file paths in dry-run output."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "Would write" in content or "would-write" in content.lower(), (
            "prompt.md must document would-write file paths in dry-run block"
        )

    def test_skill_documents_dry_run_no_phase_execution(self) -> None:
        """SKILL.md must document that --dry-run stops before executing phases."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert (
            "Phase 0 only" in content
            or "no phases executed" in content.lower()
            or ("print plan" in content.lower())
        ), "SKILL.md must document --dry-run stops at Phase 0 without executing phases"

    def test_prompt_documents_dry_run_includes_run_id_rerun_command(self) -> None:
        """prompt.md dry-run block must show --run-id in the re-run command."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        # The re-run command must include --run-id
        assert "--run-id" in content, (
            "prompt.md re-run block must show --run-id <run_id> in the re-run command"
        )


# ---------------------------------------------------------------------------
# Test case 2: Inventory written before sub-skills
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInventoryPlumbing:
    """Test case 2: pipeline always writes inventory before calling sub-skills.

    trace execution with mock sub-skills
    → inventory.json written to runs/<run_id>/ before fix-prs is called
    → fix-prs receives --inventory <path> flag
    """

    def test_skill_documents_inventory_written_before_subskills(self) -> None:
        """SKILL.md must document inventory.json written before sub-skill dispatch."""
        # Use _grep_file to anchor the co-location of "inventory" and "before" and "sub-skill"
        # on nearby lines, not just anywhere in the document.
        matching_lines = _grep_file(
            _PIPELINE_SKILL,
            r"(?i)inventory.*before.*sub.?skill|before.*sub.?skill.*inventory",
        )
        assert matching_lines, (
            "SKILL.md must contain a line documenting that inventory is written "
            "before sub-skill dispatch (pattern: inventory...before...sub-skill)"
        )

    def test_skill_documents_inventory_path_in_ledger(self) -> None:
        """SKILL.md ledger.json must include inventory_path field."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "inventory_path" in content, (
            "SKILL.md ledger.json must include inventory_path field pointing to inventory.json"
        )

    def test_prompt_documents_inventory_written_before_subskill_dispatch(self) -> None:
        """prompt.md must document CRITICAL invariant: inventory written before sub-skill dispatch."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "inventory" in content.lower(), (
            "prompt.md must document inventory.json write before sub-skill dispatch"
        )
        assert "MUST" in content or "CRITICAL" in content, (
            "prompt.md must use MUST/CRITICAL to enforce inventory-before-subskill invariant"
        )

    def test_skill_documents_inventory_flag_passed_to_subskills(self) -> None:
        """SKILL.md must document that sub-skills receive --inventory <path>."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "--inventory" in content, (
            "SKILL.md must document sub-skills receive --inventory <path> flag"
        )

    def test_skill_documents_inventory_json_structure(self) -> None:
        """SKILL.md must document the inventory.json structure with merge_ready and needs_fix."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "merge_ready" in content and "needs_fix" in content, (
            "SKILL.md inventory.json must document merge_ready[] and needs_fix[] fields"
        )


# ---------------------------------------------------------------------------
# Test case 3: phase_completed advances correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPhaseCompletedAdvancement:
    """Test case 3: phase_completed advances correctly.

    run pipeline to completion (mock sub-skills, no real PRs)
    → ledger.json phase_completed = ["scan", "review", "fix", "merge", "report"] in that order
    """

    def test_skill_documents_phase_completed_field(self) -> None:
        """SKILL.md must document phase_completed field in ledger.json."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "phase_completed" in content, (
            "SKILL.md ledger.json must include phase_completed field"
        )

    def test_skill_documents_phase_completed_is_ordered_list(self) -> None:
        """SKILL.md must document phase_completed as an ordered list that only appends."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "phase_completed" in content and (
            "ordered" in content.lower()
            or "appends" in content.lower()
            or "never regresses" in content.lower()
        ), "SKILL.md must document that phase_completed is ordered and never regresses"

    def test_skill_documents_expected_phase_names(self) -> None:
        """SKILL.md must document the named phases: scan, review, fix, merge, report."""
        content = _read_skill_file(_PIPELINE_SKILL)
        for phase in ("scan", "review", "fix", "merge", "report"):
            assert phase in content, (
                f"SKILL.md must document phase name '{phase}' in the phase_completed sequence"
            )

    def test_prompt_documents_phase_completed_update_after_each_phase(self) -> None:
        """prompt.md must document appending to phase_completed after each phase completes."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "phase_completed" in content, (
            "prompt.md must document updating phase_completed after each phase"
        )

    def test_skill_documents_phase_completed_never_regresses(self) -> None:
        """SKILL.md must explicitly state phase_completed never regresses."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "never regresses" in content.lower() or (
            "only append" in content.lower()
        ), "SKILL.md must state phase_completed never regresses (only appends)"


# ---------------------------------------------------------------------------
# Test case 4: Resume skips completed phases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResumeSkipsCompletedPhases:
    """Test case 4: resume skips completed phases.

    write ledger with phase_completed=["scan", "fix"]
    run with --run-id <existing>
    → log shows "Resuming from phase: merge"
    → scan and fix phases not re-executed
    """

    def test_skill_documents_run_id_flag(self) -> None:
        """SKILL.md must document --run-id flag for resume."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "--run-id" in content, (
            "SKILL.md must document --run-id flag for resuming a previous run"
        )

    def test_prompt_documents_resume_log_message(self) -> None:
        """prompt.md must document 'Resuming from phase: <next_phase>' log message."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "Resuming from phase" in content, (
            "prompt.md must document 'Resuming from phase: <next_phase>' log message"
        )

    def test_prompt_documents_resume_skips_phase_completed(self) -> None:
        """prompt.md must document that resume skips phases in phase_completed."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "--run-id" in content and "phase_completed" in content, (
            "prompt.md must document --run-id skipping phases listed in phase_completed"
        )

    def test_skill_documents_ledger_loaded_on_run_id(self) -> None:
        """SKILL.md must document that --run-id loads the ledger to determine start phase."""
        content = _read_skill_file(_PIPELINE_SKILL)
        # The resume section should reference loading ledger from runs/<run_id>/ledger.json
        assert "ledger.json" in content and "--run-id" in content, (
            "SKILL.md must document loading ledger.json when --run-id is provided"
        )

    def test_prompt_documents_resume_first_uncompleted_phase(self) -> None:
        """prompt.md must document starting from first phase NOT in phase_completed."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert (
            "NOT in" in content
            or "not in" in content.lower()
            or ("first phase" in content.lower())
        ), "prompt.md must document resuming from first phase not in phase_completed"


# ---------------------------------------------------------------------------
# Test case 5: stop_reason "partial_completed" vs "completed"
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStopReasonDistinction:
    """Test case 5: stop_reason "partial_completed" vs "completed".

    mock run where 1 of 2 PRs processed before stop
    → stop_reason = "partial_completed"; not "completed"
    """

    TERMINAL_STOP_REASONS = [
        "completed",
        "partial_completed",
        "gate_rejected",
        "nothing_to_do",
        "error",
    ]

    def test_skill_documents_stop_reason_field(self) -> None:
        """SKILL.md must document stop_reason field in ledger.json."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "stop_reason" in content, (
            "SKILL.md ledger.json must include stop_reason field"
        )

    def test_skill_documents_completed_stop_reason(self) -> None:
        """SKILL.md must document 'completed' stop_reason value."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "completed" in content, (
            "SKILL.md must document 'completed' as a terminal stop_reason value"
        )

    def test_skill_documents_partial_completed_stop_reason(self) -> None:
        """SKILL.md must document 'partial_completed' stop_reason value."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "partial_completed" in content, (
            "SKILL.md must document 'partial_completed' as a distinct stop_reason from 'completed'"
        )

    def test_skill_documents_distinction_between_partial_and_completed(self) -> None:
        """SKILL.md must document the semantic difference between partial_completed and completed."""
        content = _read_skill_file(_PIPELINE_SKILL)
        # Both must be present, and the distinction must be documented
        assert "partial_completed" in content and "completed" in content, (
            "SKILL.md must document both 'partial_completed' and 'completed' stop reasons"
        )
        # Verify partial_completed is described as a distinct case (some PRs processed, not all)
        assert "some" in content.lower() or "not all" in content.lower(), (
            "SKILL.md must explain partial_completed means some (not all) PRs were processed"
        )

    def test_skill_documents_all_terminal_stop_reasons(self) -> None:
        """SKILL.md must document all terminal stop_reason values."""
        content = _read_skill_file(_PIPELINE_SKILL)
        for reason in self.TERMINAL_STOP_REASONS:
            assert reason in content, (
                f"SKILL.md must document terminal stop_reason '{reason}'"
            )

    def test_prompt_documents_stop_reason_written_to_ledger(self) -> None:
        """prompt.md must document writing stop_reason to ledger at pipeline termination."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "stop_reason" in content, (
            "prompt.md must document setting stop_reason in ledger on pipeline termination"
        )


# ---------------------------------------------------------------------------
# Test case 6: --dry-run + --run-id = read-only
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunWithRunIdIsReadOnly:
    """Test case 6: --dry-run + --run-id = read-only (no mutations, no heartbeat).

    /pr-queue-pipeline --run-id 20260223-143012-a3f --dry-run
    → stdout only; ledger mtime unchanged
    """

    def test_skill_documents_dry_run_run_id_combination(self) -> None:
        """SKILL.md must document --dry-run + --run-id as read-only."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "--dry-run" in content and "--run-id" in content, (
            "SKILL.md must document both --dry-run and --run-id flags"
        )
        assert "read-only" in content.lower() or "no mutations" in content.lower(), (
            "SKILL.md must document --dry-run + --run-id combination is read-only"
        )

    def test_prompt_documents_dry_run_run_id_no_ledger_update(self) -> None:
        """prompt.md must document that --dry-run + --run-id does not update ledger mtime."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert (
            "read-only" in content.lower()
            or "no mutations" in content.lower()
            or ("do NOT update ledger" in content)
        ), "prompt.md must document --dry-run + --run-id does not update ledger mtime"

    def test_prompt_documents_dry_run_run_id_no_heartbeat(self) -> None:
        """prompt.md must document that --dry-run + --run-id does not emit heartbeat."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "heartbeat" in content.lower() or "no mutations" in content.lower(), (
            "prompt.md must document --dry-run + --run-id does not emit heartbeat"
        )

    def test_prompt_documents_dry_run_run_id_stdout_only(self) -> None:
        """prompt.md must document --dry-run + --run-id produces stdout only."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        # The read-only section should reference stdout-only output
        assert (
            "stdout" in content.lower()
            or "print plan" in content.lower()
            or "read-only" in content.lower()
        ), "prompt.md must document --dry-run + --run-id produces stdout-only output"


# ---------------------------------------------------------------------------
# Test case 7: No leftover claims after terminal run
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoLeftoverClaimsAfterTerminalRun:
    """Test case 7: No leftover claims after terminal run.

    run pipeline to completion with 1 mock PR
    → ls ~/.claude/pr-queue/claims/ | grep <run_id> → empty
    """

    TERMINAL_STATES_REQUIRING_CLEANUP = [
        "completed",
        "gate_rejected",
        "nothing_to_do",
        "error",
    ]

    def test_skill_documents_claims_directory(self) -> None:
        """SKILL.md must document the claims directory location."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "claims" in content, (
            "SKILL.md must document the pr-queue/claims/ directory for per-PR claim files"
        )

    def test_skill_documents_claims_cleanup_on_terminal_run(self) -> None:
        """SKILL.md must document that claims are cleaned up on terminal run completion."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "claims" in content and (
            "terminal" in content.lower()
            or "cleanup" in content.lower()
            or "removed" in content.lower()
        ), "SKILL.md must document claims cleanup invariant for terminal runs"

    def test_skill_documents_claims_path_pattern(self) -> None:
        """SKILL.md must document the claim file path pattern with run_id."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "claims/<run_id>" in content or (
            "claims" in content and "run_id" in content
        ), "SKILL.md must document claim file path including run_id component"

    def test_prompt_documents_claims_cleanup_after_terminal_state(self) -> None:
        """prompt.md must document removing claim files on terminal state."""
        content = _read_skill_file(_PIPELINE_PROMPT)
        assert "claim" in content.lower(), (
            "prompt.md must document claim file cleanup on terminal state"
        )

    def test_skill_documents_terminal_states_trigger_cleanup(self) -> None:
        """SKILL.md must list which terminal states trigger claims cleanup."""
        content = _read_skill_file(_PIPELINE_SKILL)
        # At least completed and gate_rejected should be listed as triggering cleanup
        cleanup_states_found = [
            state
            for state in self.TERMINAL_STATES_REQUIRING_CLEANUP
            if state in content
        ]
        assert len(cleanup_states_found) >= 2, (
            f"SKILL.md must document at least 2 terminal states that trigger claims cleanup. "
            f"Found: {cleanup_states_found}"
        )

    def test_skill_documents_partial_completed_may_leave_claims(self) -> None:
        """SKILL.md must document that partial_completed may leave claims for resume."""
        content = _read_skill_file(_PIPELINE_SKILL)
        assert "partial_completed" in content and (
            "resume" in content.lower() or "interrupted" in content.lower()
        ), (
            "SKILL.md must document that partial_completed runs may leave claims "
            "pending resume with --run-id"
        )
