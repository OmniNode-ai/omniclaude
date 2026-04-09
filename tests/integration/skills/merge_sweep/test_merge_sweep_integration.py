# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the merge-sweep skill (v4.0.0).

Tests verify the skill → orchestrator delegation contract (OMN-8088):
- SKILL.md declares publish-monitor pattern (not inline orchestration)
- All CLI args map to documented orchestrator entry flags
- Correct command topic documented
- Correct completion event topics documented
- Backward-compatible CLI surface (all v3.x args still accepted)
- `--dry-run` maps to `dry_run: true` in command event
- No orchestration logic in SKILL.md (no direct gh pr merge, no claim registry)
- prompt.md reflects thin-trigger steps (parse → publish → monitor → report)

All tests are static analysis / structural tests that run without external
credentials, live GitHub access, or live PRs. Safe for CI.

Test markers:
    @pytest.mark.unit  — repeatable, no external mutations, CI-safe
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
_MERGE_SWEEP_DIR = _SKILLS_ROOT / "merge_sweep"
_MERGE_SWEEP_PROMPT = _MERGE_SWEEP_DIR / "prompt.md"
_MERGE_SWEEP_SKILL = _MERGE_SWEEP_DIR / "SKILL.md"
_MERGE_SWEEP_TOPICS = _MERGE_SWEEP_DIR / "topics.yaml"


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
# Test class: Thin-trigger pattern (core contract, OMN-8088)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThinTriggerPattern:
    """Skill must be a pure publish-monitor entry point with zero orchestration logic."""

    def test_skill_documents_publish_monitor_pattern(self) -> None:
        """SKILL.md must describe the publish-monitor pattern."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "publish" in content.lower() and "monitor" in content.lower(), (
            "SKILL.md must document the publish-monitor pattern"
        )

    def test_skill_states_no_orchestration_logic(self) -> None:
        """SKILL.md must state that orchestration is delegated to the node."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "pr_lifecycle_orchestrator" in content, (
            "SKILL.md must reference pr_lifecycle_orchestrator as the orchestration owner"
        )
        assert "delegated" in content.lower() or "delegates" in content.lower(), (
            "SKILL.md must state that orchestration is delegated to the node"
        )

    def test_skill_describes_entry_point_only(self) -> None:
        """SKILL.md must describe the skill as a pure entry point."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "entry point" in content.lower(), (
            "SKILL.md must describe the skill as a pure entry point"
        )

    def test_skill_has_what_this_skill_does_not_do_section(self) -> None:
        """SKILL.md must have a 'What This Skill Does NOT Do' section."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "What This Skill Does NOT Do" in content, (
            "SKILL.md must have a 'What This Skill Does NOT Do' section"
        )

    def test_prompt_does_not_call_gh_pr_merge_directly(self) -> None:
        """prompt.md must not actively call gh pr merge (delegated to orchestrator).

        References in the 'What This Prompt Does NOT Do' disclaimer section are allowed —
        they exist to document what is explicitly excluded.
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()
        # Find the 'NOT Do' disclaimer section — references there are allowed
        not_do_start = next(
            (i for i, line in enumerate(lines) if "What This Prompt Does NOT Do" in line),
            len(lines),
        )
        violations = []
        for i, line in enumerate(lines):
            if i >= not_do_start:
                break  # everything after the disclaimer section is allowed
            if "gh pr merge" in line and not line.strip().startswith("#"):
                violations.append(f"line {i + 1}: {line.strip()}")
        assert violations == [], (
            "prompt.md must not actively call 'gh pr merge' — delegated to orchestrator:\n"
            + "\n".join(violations)
        )

    def test_prompt_does_not_reference_claim_registry(self) -> None:
        """prompt.md must not reference ClaimRegistry (delegated to orchestrator)."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "ClaimRegistry" not in content and "claim_registry" not in content, (
            "prompt.md must not reference ClaimRegistry — claim management is in the orchestrator"
        )

    def test_prompt_does_not_classify_prs(self) -> None:
        """prompt.md must not contain active PR classification predicates.

        References in the 'What This Prompt Does NOT Do' disclaimer section are allowed.
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()
        not_do_start = next(
            (i for i, line in enumerate(lines) if "What This Prompt Does NOT Do" in line),
            len(lines),
        )
        forbidden = ["needs_branch_update", "is_merge_ready", "needs_polish"]
        for pred in forbidden:
            violations = [
                f"line {i + 1}: {line.strip()}"
                for i, line in enumerate(lines[:not_do_start])
                if pred in line
            ]
            assert violations == [], (
                f"prompt.md must not actively use {pred}() — PR classification is in orchestrator:\n"
                + "\n".join(violations)
            )

    def test_prompt_does_not_dispatch_pr_polish(self) -> None:
        """prompt.md must not actively dispatch pr-polish.

        References in the 'What This Prompt Does NOT Do' disclaimer section are allowed.
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        lines = content.splitlines()
        not_do_start = next(
            (i for i, line in enumerate(lines) if "What This Prompt Does NOT Do" in line),
            len(lines),
        )
        violations = [
            f"line {i + 1}: {line.strip()}"
            for i, line in enumerate(lines[:not_do_start])
            if "pr-polish" in line or "pr_polish" in line
        ]
        assert violations == [], (
            "prompt.md must not actively dispatch pr-polish — delegated to orchestrator:\n"
            + "\n".join(violations)
        )

    def test_prompt_has_what_it_does_not_do_section(self) -> None:
        """prompt.md must have a 'What This Prompt Does NOT Do' section."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "What This Prompt Does NOT Do" in content, (
            "prompt.md must have a 'What This Prompt Does NOT Do' section"
        )


# ---------------------------------------------------------------------------
# Test class: Publish-monitor steps in prompt.md
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPromptPublishMonitorSteps:
    """prompt.md must define the 5 thin-trigger steps: announce, parse, map, publish, monitor."""

    def test_prompt_has_announce_step(self) -> None:
        """prompt.md must have an announce step."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "Announce" in content or "announce" in content.lower(), (
            "prompt.md must have an announce step"
        )

    def test_prompt_has_parse_arguments_step(self) -> None:
        """prompt.md must have a parse arguments step."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "Parse" in content and "Arguments" in content, (
            "prompt.md must have a parse arguments step"
        )

    def test_prompt_has_publish_step(self) -> None:
        """prompt.md must have a publish command event step."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "Publish" in content and "Command Event" in content, (
            "prompt.md must have a 'Publish Command Event' step"
        )

    def test_prompt_has_monitor_step(self) -> None:
        """prompt.md must have a monitor completion step."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "Monitor" in content and "Completion" in content, (
            "prompt.md must have a 'Monitor Completion' step"
        )

    def test_prompt_documents_poll_interval(self) -> None:
        """prompt.md must document the poll interval for monitoring."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "poll_interval" in content or "10 second" in content.lower(), (
            "prompt.md must document the poll interval (10 seconds)"
        )

    def test_prompt_documents_poll_timeout(self) -> None:
        """prompt.md must document the poll timeout."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "3600" in content or "1 hour" in content.lower() or "timeout" in content.lower(), (
            "prompt.md must document the poll timeout (3600s / 1 hour)"
        )

    def test_prompt_documents_result_path(self) -> None:
        """prompt.md must document the result.json path."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "result.json" in content, (
            "prompt.md must document the result.json poll target path"
        )

    def test_prompt_documents_emit_daemon_publish(self) -> None:
        """prompt.md must reference emit_via_daemon for publishing."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "emit_via_daemon" in content or "emit daemon" in content.lower(), (
            "prompt.md must use emit_via_daemon to publish the command event"
        )


# ---------------------------------------------------------------------------
# Test class: Command topic and wire schema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommandTopicAndSchema:
    """Skill must document the correct Kafka command topic and wire schema."""

    COMMAND_TOPIC = "onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1"
    COMPLETED_TOPIC = "onex.evt.omnimarket.pr-lifecycle-orchestrator-completed.v1"
    FAILED_TOPIC = "onex.evt.omnimarket.pr-lifecycle-orchestrator-failed.v1"

    def test_skill_documents_command_topic(self) -> None:
        """SKILL.md must document the correct command topic."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert self.COMMAND_TOPIC in content, (
            f"SKILL.md must document command topic: {self.COMMAND_TOPIC}"
        )

    def test_skill_documents_completed_topic(self) -> None:
        """SKILL.md must document the orchestrator completion topic."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert self.COMPLETED_TOPIC in content, (
            f"SKILL.md must document completion topic: {self.COMPLETED_TOPIC}"
        )

    def test_skill_documents_failed_topic(self) -> None:
        """SKILL.md must document the orchestrator failure topic."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert self.FAILED_TOPIC in content, (
            f"SKILL.md must document failure topic: {self.FAILED_TOPIC}"
        )

    def test_topics_yaml_includes_command_topic(self) -> None:
        """topics.yaml must include the orchestrator command topic."""
        content = _read_skill_file(_MERGE_SWEEP_TOPICS)
        assert self.COMMAND_TOPIC in content, (
            f"topics.yaml must include: {self.COMMAND_TOPIC}"
        )

    def test_topics_yaml_includes_completed_topic(self) -> None:
        """topics.yaml must include the orchestrator completed topic."""
        content = _read_skill_file(_MERGE_SWEEP_TOPICS)
        assert self.COMPLETED_TOPIC in content, (
            f"topics.yaml must include: {self.COMPLETED_TOPIC}"
        )

    def test_prompt_publishes_to_correct_topic(self) -> None:
        """prompt.md must reference the correct command topic when publishing."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert self.COMMAND_TOPIC in content, (
            f"prompt.md must publish to: {self.COMMAND_TOPIC}"
        )

    def test_skill_documents_wire_schema_fields(self) -> None:
        """SKILL.md must document required wire schema fields."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        required_fields = ["run_id", "dry_run", "merge_method", "repos", "emitted_at", "correlation_id"]
        for field in required_fields:
            assert f'"{field}"' in content or f"`{field}`" in content, (
                f"SKILL.md must document wire schema field: {field}"
            )

    def test_skill_documents_arg_to_flag_mapping(self) -> None:
        """SKILL.md must document the arg → orchestrator entry flag mapping table."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "Orchestrator Field" in content or "orchestrator entry flag" in content.lower(), (
            "SKILL.md must document the arg → orchestrator entry flag mapping"
        )


# ---------------------------------------------------------------------------
# Test class: Backward-compatible CLI surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackwardCompatibleCLI:
    """All v3.x CLI args must still be documented in SKILL.md (backward compat)."""

    V3_ARGS = [
        "--repos",
        "--dry-run",
        "--merge-method",
        "--require-approval",
        "--require-up-to-date",
        "--max-total-merges",
        "--max-parallel-prs",
        "--max-parallel-repos",
        "--max-parallel-polish",
        "--skip-polish",
        "--polish-clean-runs",
        "--authors",
        "--since",
        "--label",
        "--resume",
        "--reset-state",
        "--run-id",
    ]

    V4_NEW_ARGS = [
        "--inventory-only",
        "--fix-only",
        "--merge-only",
    ]

    def test_all_v3_args_still_documented(self) -> None:
        """SKILL.md must document all v3.x args (backward compat)."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        for arg in self.V3_ARGS:
            assert arg in content, (
                f"SKILL.md must still document {arg} for backward compatibility"
            )

    def test_v4_new_args_documented(self) -> None:
        """SKILL.md must document new v4.0.0 orchestrator entry flags."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        for arg in self.V4_NEW_ARGS:
            assert arg in content, (
                f"SKILL.md must document new v4.0.0 arg: {arg}"
            )

    def test_dry_run_arg_in_frontmatter(self) -> None:
        """SKILL.md frontmatter must list --dry-run as an arg."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        frontmatter_end = content.find("---", 3)
        if frontmatter_end > 0:
            frontmatter = content[:frontmatter_end]
            assert "--dry-run" in frontmatter, (
                "--dry-run must appear in SKILL.md frontmatter args"
            )

    def test_prompt_parses_all_v3_args(self) -> None:
        """prompt.md must parse all v3.x args."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        for arg in self.V3_ARGS:
            assert arg in content, (
                f"prompt.md must parse {arg} for backward compatibility"
            )

    def test_dry_run_maps_to_command_event_field(self) -> None:
        """prompt.md must document --dry-run mapping to dry_run: true in command event."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "dry_run" in content, (
            "prompt.md must show --dry-run mapping to dry_run field in command event"
        )

    def test_dry_run_causes_no_mutations(self) -> None:
        """SKILL.md must document that --dry-run produces zero filesystem writes."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "--dry-run" in content and (
            "zero filesystem writes" in content.lower()
            or "no mutations" in content.lower()
            or "print candidates" in content.lower()
        ), "SKILL.md must document --dry-run as zero-write operation"

    def test_prompt_dry_run_exits_before_publish(self) -> None:
        """prompt.md must exit before publishing when --dry-run is set."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "dry run complete" in content.lower() or "dry_run" in content, (
            "prompt.md must handle --dry-run before the publish step"
        )


# ---------------------------------------------------------------------------
# Test class: ModelSkillResult contract (status values unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelSkillResultContract:
    """Verify merge-sweep emits a backward-compatible ModelSkillResult."""

    REQUIRED_STATUS_VALUES = [
        "queued",
        "nothing_to_merge",
        "partial",
        "error",
    ]

    def test_skill_documents_all_status_values(self) -> None:
        """SKILL.md must document all ModelSkillResult status values (unchanged from v3.x)."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        for status in self.REQUIRED_STATUS_VALUES:
            assert status in content, (
                f"SKILL.md must document ModelSkillResult status='{status}'"
            )

    def test_skill_documents_result_file_path(self) -> None:
        """SKILL.md must document where ModelSkillResult is written."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "skill-results" in content or "ONEX_STATE_DIR" in content, (
            "SKILL.md must document where ModelSkillResult is written"
        )

    def test_prompt_writes_skill_result(self) -> None:
        """prompt.md must write ModelSkillResult at conclusion."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "skill_result" in content or "merge-sweep.json" in content, (
            "prompt.md must write skill result at conclusion"
        )

    def test_skill_documents_result_passthrough(self) -> None:
        """SKILL.md must document that orchestrator result is passed through unchanged."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "passthrough" in content.lower() or "pass through" in content.lower() or "directly" in content.lower(), (
            "SKILL.md must document that orchestrator result is surfaced directly"
        )


# ---------------------------------------------------------------------------
# Test class: v4.0.0 version and changelog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVersionAndChangelog:
    """SKILL.md must reflect v4.0.0 with OMN-8088 in changelog."""

    def test_skill_version_is_v400(self) -> None:
        """SKILL.md frontmatter version must be 4.0.0."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        frontmatter_end = content.find("---", 3)
        if frontmatter_end > 0:
            frontmatter = content[:frontmatter_end]
            assert "4.0.0" in frontmatter, (
                "SKILL.md frontmatter version must be 4.0.0 (OMN-8088)"
            )

    def test_skill_changelog_documents_omn_8088(self) -> None:
        """SKILL.md changelog must document OMN-8088 as the source of v4.0.0."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "OMN-8088" in content, (
            "SKILL.md changelog must reference OMN-8088 for the thin-trigger rewrite"
        )

    def test_skill_changelog_preserves_v3_history(self) -> None:
        """SKILL.md changelog must preserve v3.x version history."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        for version in ["v3.6.0", "v3.5.0", "v3.0.0"]:
            assert version in content, (
                f"SKILL.md changelog must preserve {version} history"
            )


# ---------------------------------------------------------------------------
# Test class: No orchestration anti-patterns in SKILL.md
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoOrchestrationAntiPatterns:
    """SKILL.md and prompt.md must not contain orchestration logic."""

    def test_no_gate_in_skill(self) -> None:
        """SKILL.md must not contain --no-gate patterns."""
        matches = _grep_file(_MERGE_SWEEP_SKILL, r"--no-gate")
        assert matches == [], "--no-gate found in SKILL.md:\n" + "\n".join(matches)

    def test_no_gate_in_prompt(self) -> None:
        """prompt.md must not contain --no-gate patterns."""
        matches = _grep_file(_MERGE_SWEEP_PROMPT, r"--no-gate")
        assert matches == [], "--no-gate found in prompt.md:\n" + "\n".join(matches)

    def test_no_gate_attestation_in_skill(self) -> None:
        """SKILL.md must not reference --gate-attestation (removed in v3.0.0)."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        frontmatter_end = content.find("---", 3)
        if frontmatter_end > 0:
            frontmatter = content[:frontmatter_end]
            assert "--gate-attestation" not in frontmatter, (
                "--gate-attestation found in SKILL.md frontmatter (removed in v3.0.0)"
            )

    def test_no_direct_gh_pr_merge_in_skill(self) -> None:
        """SKILL.md must not contain active gh pr merge instructions.

        References are allowed in:
        - 'What This Skill Does NOT Do' disclaimer section
        - 'Integration Test' section (documenting what is excluded from tests)
        - Changelog and See Also sections
        """
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        lines = content.splitlines()
        # Find start of disclaimer/informational sections
        disclaimer_starts = [
            i
            for i, line in enumerate(lines)
            if any(
                keyword in line
                for keyword in [
                    "What This Skill Does NOT Do",
                    "Integration Test",
                    "## Changelog",
                    "## See Also",
                ]
            )
        ]
        first_disclaimer = min(disclaimer_starts) if disclaimer_starts else len(lines)
        violations = [
            f"line {i + 1}: {line.strip()}"
            for i, line in enumerate(lines[:first_disclaimer])
            if "gh pr merge" in line and not line.strip().startswith("#")
        ]
        assert violations == [], (
            "SKILL.md must not contain active gh pr merge instructions (orchestrator owns this):\n"
            + "\n".join(violations)
        )

    def test_no_track_a_b_orchestration_in_prompt(self) -> None:
        """prompt.md must not contain Track A/B orchestration logic."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "Track A" not in content and "Track B" not in content, (
            "prompt.md must not contain Track A/B orchestration — delegated to orchestrator"
        )
