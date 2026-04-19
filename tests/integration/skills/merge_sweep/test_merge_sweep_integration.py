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
            (
                i
                for i, line in enumerate(lines)
                if "What This Prompt Does NOT Do" in line
            ),
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
            (
                i
                for i, line in enumerate(lines)
                if "What This Prompt Does NOT Do" in line
            ),
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
            (
                i
                for i, line in enumerate(lines)
                if "What This Prompt Does NOT Do" in line
            ),
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
        assert (
            "3600" in content
            or "1 hour" in content.lower()
            or "timeout" in content.lower()
        ), "prompt.md must document the poll timeout (3600s / 1 hour)"

    def test_prompt_documents_result_path(self) -> None:
        """prompt.md must document the result.json path."""
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "result.json" in content, (
            "prompt.md must document the result.json poll target path"
        )

    def test_prompt_documents_kcat_publish(self) -> None:
        """prompt.md must publish the command event via `kcat -P`.

        OMN-9214: the skill previously imported the non-existent
        `emit_via_daemon` symbol from `emit_client_wrapper.py`, causing 112
        consecutive merge-sweep refusals on 2026-04-19. The fix replaces that
        import with a direct `kcat -P` shell-out, mirroring the same pattern
        used by `skills/redeploy/prompt.md` (DEPLOY phase). This test locks in
        the replacement and prevents the broken symbol from reappearing.

        OMN-9215: additionally asserts the payload is wrapped in
        ``ModelEventEnvelope`` before produce — bare-payload sends fail the
        consumer's auto-wiring validation and every tick times out.
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "kcat -P" in content, (
            "prompt.md must publish via `kcat -P` (mirroring redeploy/prompt.md)"
        )
        assert "KAFKA_BOOTSTRAP_SERVERS" in content, (
            "prompt.md must reference KAFKA_BOOTSTRAP_SERVERS env var for the broker"
        )
        # Structural guard: the broken symbol and its import must not return.
        assert "emit_via_daemon" not in content, (
            "prompt.md must not reference `emit_via_daemon` — the symbol does not "
            "exist in emit_client_wrapper.py (OMN-9214)"
        )
        assert "emit_client_wrapper" not in content, (
            "prompt.md must not import from emit_client_wrapper — cmd-topic publish "
            "uses kcat, not the emit daemon (OMN-9214)"
        )
        # OMN-9215: envelope wrapping is mandatory — bare payloads fail the
        # consumer-side ModelEventEnvelope[object] validation.
        assert "ModelEventEnvelope" in content, (
            "prompt.md must wrap the command event in ModelEventEnvelope before "
            "produce (OMN-9215) — consumer auto-wiring validates this shape"
        )
        assert "envelope.model_dump_json()" in content, (
            "prompt.md must serialize the ModelEventEnvelope, not the raw "
            "command_event dict (OMN-9215)"
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
        required_fields = [
            "run_id",
            "dry_run",
            "merge_method",
            "repos",
            "emitted_at",
            "correlation_id",
        ]
        for field in required_fields:
            assert f'"{field}"' in content or f"`{field}`" in content, (
                f"SKILL.md must document wire schema field: {field}"
            )

    def test_skill_documents_arg_to_flag_mapping(self) -> None:
        """SKILL.md must document the arg → orchestrator entry flag mapping table."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert (
            "Orchestrator Field" in content
            or "orchestrator entry flag" in content.lower()
        ), "SKILL.md must document the arg → orchestrator entry flag mapping"


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
            assert arg in content, f"SKILL.md must document new v4.0.0 arg: {arg}"

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
        assert (
            "passthrough" in content.lower()
            or "pass through" in content.lower()
            or "directly" in content.lower()
        ), "SKILL.md must document that orchestrator result is surfaced directly"


# ---------------------------------------------------------------------------
# Test class: v5.0.0 version and changelog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVersionAndChangelog:
    """SKILL.md must reflect v5.0.0 with OMN-8208 in changelog."""

    def test_skill_version_is_v400(self) -> None:
        """SKILL.md frontmatter version must be 5.0.0."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        frontmatter_end = content.find("---", 3)
        if frontmatter_end > 0:
            frontmatter = content[:frontmatter_end]
            assert "5.0.0" in frontmatter, (
                "SKILL.md frontmatter version must be 5.0.0 (OMN-8208)"
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
        - Admin merge fallback lines (gh pr merge --admin) — conditional privileged
          operation documented as skill behavior, not standard orchestrator routing
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
            if "gh pr merge" in line
            and not line.strip().startswith("#")
            and "--admin"
            not in line  # admin-merge fallback is intentional documented behavior
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


# ---------------------------------------------------------------------------
# Test class: Pre-merge verification gate (OMN-7742)
# ---------------------------------------------------------------------------


_VERIFICATION_SWEEP_SKILL = _SKILLS_ROOT / "verification_sweep" / "SKILL.md"


@pytest.mark.unit
class TestVerifyPreMergeGate:
    """OMN-7742: --verify wires verification_sweep into merge_sweep as a pre-merge gate."""

    FAILURE_CATEGORIES = [
        "merged",
        "verification_failed",
        "verification_unavailable",
        "verification_timeout",
        "verification_tool_error",
        "skipped_no_mapping",
        "skipped_by_policy",
    ]

    TARGET_MAPPING_PATTERNS = [
        "projection",
        "handler",
        "route",
        "drizzle",
        "migrations",
        "topics.yaml",
        "contract.yaml",
    ]

    def test_verify_arg_in_skill_frontmatter(self) -> None:
        """SKILL.md frontmatter must declare --verify as an arg."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        frontmatter_end = content.find("---", 3)
        assert frontmatter_end > 0
        frontmatter = content[:frontmatter_end]
        assert "--verify" in frontmatter, (
            "--verify must appear in SKILL.md frontmatter args"
        )

    def test_verify_timeout_arg_in_skill_frontmatter(self) -> None:
        """SKILL.md frontmatter must declare --verify-timeout-seconds as an arg."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        frontmatter_end = content.find("---", 3)
        frontmatter = content[:frontmatter_end]
        assert "--verify-timeout-seconds" in frontmatter

    def test_verify_arg_mapped_to_orchestrator_field(self) -> None:
        """--verify must appear in the arg → orchestrator field mapping table."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "`--verify`" in content and "`verify: true`" in content, (
            "SKILL.md must map --verify to orchestrator `verify: true` field"
        )

    def test_all_seven_failure_categories_documented(self) -> None:
        """SKILL.md must document all 7 per-PR verification outcome categories."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        for category in self.FAILURE_CATEGORIES:
            assert f"`{category}`" in content, (
                f"SKILL.md must document verification category: {category}"
            )

    def test_target_mapping_patterns_documented(self) -> None:
        """SKILL.md must document the changed-file-to-target mapping patterns."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        for pattern in self.TARGET_MAPPING_PATTERNS:
            assert pattern in content, (
                f"SKILL.md must document target mapping pattern: {pattern}"
            )

    def test_batch_nonblocking_semantics_documented(self) -> None:
        """SKILL.md must state that one PR's failure does not block the batch."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL).lower()
        assert "does not block" in content or "not block" in content, (
            "SKILL.md must document that a single PR verification failure does "
            "not block other PRs in the sweep"
        )

    def test_changelog_documents_omn_7742(self) -> None:
        """Changelog must reference OMN-7742."""
        content = _read_skill_file(_MERGE_SWEEP_SKILL)
        assert "OMN-7742" in content, "Changelog must reference OMN-7742"

    def test_verification_sweep_documents_pre_merge_mode(self) -> None:
        """verification_sweep SKILL.md must document --pr pre-merge mode."""
        content = _read_skill_file(_VERIFICATION_SWEEP_SKILL)
        assert "--pr" in content, "verification_sweep must declare --pr arg"
        assert "pre-merge" in content.lower(), (
            "verification_sweep must document pre-merge mode"
        )

    def test_verification_sweep_documents_emittable_exit_statuses(self) -> None:
        """verification_sweep SKILL.md must document every status it can emit.

        `skipped_by_policy` is the only category it never emits — that decision
        is made by merge_sweep before verification_sweep is ever invoked.
        """
        content = _read_skill_file(_VERIFICATION_SWEEP_SKILL)
        emittable = [c for c in self.FAILURE_CATEGORIES if c != "skipped_by_policy"]
        for category in emittable:
            assert f"`{category}`" in content, (
                f"verification_sweep must document exit status: {category}"
            )

    def test_verification_sweep_documents_target_mapping(self) -> None:
        """verification_sweep SKILL.md must describe the changed-file target mapping."""
        content = _read_skill_file(_VERIFICATION_SWEEP_SKILL)
        for pattern in self.TARGET_MAPPING_PATTERNS:
            assert pattern in content, (
                f"verification_sweep must document target mapping pattern: {pattern}"
            )


# ---------------------------------------------------------------------------
# Test class: kcat publish end-to-end behaviour (OMN-9214)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKcatPublishBehaviour:
    """OMN-9214: prove the documented kcat publish step actually fires.

    The prompt documents a `kcat -P` shell-out; a previous regression
    (OMN-9214 root cause) shipped a non-existent `emit_via_daemon` import
    that no test ever exercised. These tests stub `kcat` on ``PATH`` and
    verify the real command executes with the correct topic + envelope.
    """

    COMMAND_TOPIC: str = "onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1"

    def _publish(
        self,
        command_event: dict[str, object],
        *,
        kafka_bootstrap: str,
    ) -> tuple[int, str, str]:
        """Execute the documented publish shell-out.

        Kept in sync with the shell command in
        ``plugins/onex/skills/merge_sweep/prompt.md`` under
        "## Publish Command Event". Any drift will be caught by
        :meth:`test_prompt_command_shape_matches_runtime`, which greps the
        prompt for the literal command pattern.

        OMN-9215: command_event is wrapped in ``ModelEventEnvelope`` so the
        consumer-side auto-wiring callback (which validates
        ``ModelEventEnvelope[object]`` before dispatch) accepts the message.
        """
        import shlex
        import subprocess
        from uuid import UUID

        from omnibase_core.models.events.model_event_envelope import (
            ModelEventEnvelope,
        )

        correlation_raw = command_event.get("correlation_id")
        correlation_id = UUID(str(correlation_raw)) if correlation_raw else None
        envelope = ModelEventEnvelope[dict](
            payload=command_event,
            correlation_id=correlation_id,
            event_type="omnimarket.pr-lifecycle-orchestrator-start",
            source_tool="merge-sweep-skill",
        )
        msg = envelope.model_dump_json()

        proc = subprocess.run(
            (
                f"echo {shlex.quote(msg)} | "
                f"kcat -P -b {shlex.quote(kafka_bootstrap)} "
                f"-t {self.COMMAND_TOPIC}"
            ),
            shell=True,
            capture_output=True,
            text=True,
            check=False,  # the test asserts on returncode directly
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _make_kcat_stub(self, tmp_path: Path, exit_code: int = 0) -> Path:
        """Create a stub `kcat` binary that records argv + stdin and exits."""
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir(parents=True, exist_ok=True)
        stub = stub_dir / "kcat"
        log = tmp_path / "kcat-invocation.log"
        stub.write_text(
            (
                "#!/usr/bin/env bash\n"
                f"exec > {shlex_quote_literal(str(log))} 2>&1\n"
                'printf "argv="\n'
                'printf "%s " "$@"\n'
                'printf "\\n"\n'
                'printf "stdin="\n'
                "cat\n"
                'printf "\\n"\n'
                f"exit {exit_code}\n"
            ),
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub_dir

    def test_publish_fires_kcat_with_correct_topic_and_envelope(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The documented shell-out must call ``kcat`` with our topic and envelope."""
        import json

        stub_dir = self._make_kcat_stub(tmp_path, exit_code=0)
        log = tmp_path / "kcat-invocation.log"

        monkeypatch.setenv("PATH", f"{stub_dir}:{(monkeypatch.undo and '') or ''}")
        # Re-set PATH explicitly because prev line may be a no-op on some pytest versions.
        monkeypatch.setenv("PATH", f"{stub_dir}:/usr/bin:/bin")

        envelope: dict[str, object] = {
            "run_id": "20260419-170000-abc123",
            "dry_run": False,
            "merge_method": "squash",
            "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
        }

        returncode, _stdout, _stderr = self._publish(
            envelope, kafka_bootstrap="localhost:19092"
        )
        assert returncode == 0, "stubbed kcat should exit 0"
        assert log.exists(), "kcat stub must have been invoked"

        invocation = log.read_text(encoding="utf-8")
        # Topic must land as a `-t` positional.
        assert f"-t {self.COMMAND_TOPIC}" in invocation, (
            f"kcat must be called with '-t {self.COMMAND_TOPIC}'; got:\n{invocation}"
        )
        # Broker must land as a `-b` positional.
        assert "-b localhost:19092" in invocation, (
            f"kcat must be called with '-b localhost:19092'; got:\n{invocation}"
        )
        # Produce mode must be `-P`.
        assert "-P " in invocation or "-P\n" in invocation, (
            f"kcat must be called in produce mode (-P); got:\n{invocation}"
        )
        # Envelope must arrive as a single JSON line on stdin and parse as
        # ModelEventEnvelope (OMN-9215 — consumer side validates this shape
        # before dispatching to HandlerPrLifecycleOrchestrator).
        from omnibase_core.models.events.model_event_envelope import (
            ModelEventEnvelope,
        )

        stdin_marker = "stdin="
        stdin_idx = invocation.index(stdin_marker)
        stdin_body = invocation[stdin_idx + len(stdin_marker) :].strip()
        parsed = json.loads(stdin_body)
        # Envelope shape: payload dict carries the command_event.
        assert "payload" in parsed, (
            "kcat stdin must be envelope-shaped with a top-level 'payload' "
            "field (OMN-9215). Got: " + stdin_body[:200]
        )
        # Round-trip through ModelEventEnvelope to prove the consumer-side
        # auto-wiring callback would accept this message.
        ModelEventEnvelope[object].model_validate(parsed)
        payload = parsed["payload"]
        assert payload["run_id"] == envelope["run_id"]
        assert payload["correlation_id"] == envelope["correlation_id"]
        assert payload["merge_method"] == "squash"

    def test_publish_surfaces_nonzero_exit_from_kcat(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When kcat exits non-zero the publish helper must propagate the failure."""
        stub_dir = self._make_kcat_stub(tmp_path, exit_code=2)
        monkeypatch.setenv("PATH", f"{stub_dir}:/usr/bin:/bin")

        returncode, _stdout, _stderr = self._publish(
            {"run_id": "x", "dry_run": True},
            kafka_bootstrap="localhost:19092",
        )
        assert returncode != 0, (
            "publish shell-out must surface kcat's non-zero exit "
            "(prompt documents status='error' on this path)"
        )

    def test_prompt_command_shape_matches_runtime(self) -> None:
        """Guard: prompt.md's publish command must still match the shape this suite exercises.

        If the prompt's command string drifts away from
        ``echo <envelope_json> | kcat -P -b <bootstrap> -t <topic>``, this
        test and the runtime invocation diverge silently. Pin both sides
        together.

        OMN-9215: the ``msg`` variable is now the serialized envelope, not the
        raw command_event. The shell-out template remains identical — the
        change is upstream (envelope construction).
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert "echo {shlex.quote(msg)} | kcat -P -b" in content, (
            "prompt.md publish command shape must match the runtime under test"
        )
        # The -t argument is passed as an f-string interpolation of COMMAND_TOPIC.
        # Assert both the literal topic is declared AND the kcat line references it.
        assert f'COMMAND_TOPIC = "{self.COMMAND_TOPIC}"' in content, (
            f"prompt.md must declare COMMAND_TOPIC = {self.COMMAND_TOPIC!r}"
        )
        assert "-t {COMMAND_TOPIC}" in content, (
            "prompt.md kcat command must pass '-t {COMMAND_TOPIC}' "
            "(f-string interpolation of the declared topic)"
        )
        # OMN-9215: msg must come from the envelope, not a bare command_event.
        assert "msg = envelope.model_dump_json()" in content, (
            "prompt.md must set `msg = envelope.model_dump_json()` so the "
            "serialized bytes on the wire carry the ModelEventEnvelope shape "
            "(OMN-9215)"
        )

    # -- Env-probe fail-fast path (CodeRabbit gap, OMN-9214) ------------------

    @staticmethod
    def _resolve_bootstrap(
        env: dict[str, str],
    ) -> tuple[str | None, dict[str, object] | None]:
        """Extracted helper mirroring the env-probe block in prompt.md.

        Keeping this runtime shape identical to the prompt is enforced by
        :meth:`test_prompt_documents_env_probe_fail_fast` below — any drift
        trips that structural guard.
        """
        kafka_bootstrap = env.get("KAFKA_BOOTSTRAP_SERVERS")
        if not kafka_bootstrap:
            return None, {
                "status": "error",
                "message": "KAFKA_BOOTSTRAP_SERVERS not set",
            }
        return kafka_bootstrap, None

    def test_env_probe_fails_fast_when_bootstrap_unset(self) -> None:
        """Fail-fast env-probe must return the documented error envelope when unset."""
        bootstrap, result = self._resolve_bootstrap({})
        assert bootstrap is None
        assert result is not None
        assert result["status"] == "error"
        assert result["message"] == "KAFKA_BOOTSTRAP_SERVERS not set"

    def test_env_probe_returns_bootstrap_when_set(self) -> None:
        """When KAFKA_BOOTSTRAP_SERVERS is set the probe must pass through the value."""
        expected = "broker.test:9092"
        bootstrap, result = self._resolve_bootstrap(
            {"KAFKA_BOOTSTRAP_SERVERS": expected}
        )
        assert bootstrap == expected
        assert result is None

    def test_prompt_documents_env_probe_fail_fast(self) -> None:
        """Structural guard: prompt.md must contain the fail-fast env probe.

        Pairs with :meth:`test_env_probe_fails_fast_when_bootstrap_unset` —
        the executable test above covers the behaviour; this test locks the
        prompt shape so a regression that deletes the probe (e.g., reverting
        to a silent default) is caught even if the helper stays intact.
        """
        content = _read_skill_file(_MERGE_SWEEP_PROMPT)
        assert 'os.environ.get("KAFKA_BOOTSTRAP_SERVERS")' in content, (
            "prompt.md must read KAFKA_BOOTSTRAP_SERVERS via os.environ.get"
        )
        assert "if not kafka_bootstrap:" in content, (
            "prompt.md must check `if not kafka_bootstrap:` and fail fast"
        )
        assert '"message": "KAFKA_BOOTSTRAP_SERVERS not set"' in content, (
            "prompt.md must emit the documented fail-fast error message"
        )


def shlex_quote_literal(s: str) -> str:
    """Local helper: quote for embedding inside the generated kcat stub shell script."""
    import shlex

    return shlex.quote(s)
