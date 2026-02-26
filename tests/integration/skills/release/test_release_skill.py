# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for the release skill (v1.0.0).

Tests verify:
- Contract wiring: import, parse, topic routing, consumer group convention
- Skill file structure: SKILL.md and prompt.md exist with required content
- Dry-run contract: --dry-run produces DRY_RUN status without side effects
- Resume/idempotency: state model, phase machine, resume semantics documented
- Cross-references: merge-sweep, pr-safety, release.yml, auto-tag-reusable.yml
- CI enforcement: no direct git push or merge without guards

All tests are static analysis / structural tests that run without external
credentials, live GitHub access, or live repos. Safe for CI.

Test markers:
    @pytest.mark.unit  -- repeatable, no external mutations, CI-safe
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_RELEASE_DIR = _SKILLS_ROOT / "release"
_RELEASE_SKILL = _RELEASE_DIR / "SKILL.md"
_RELEASE_PROMPT = _RELEASE_DIR / "prompt.md"
_NODE_DIR = (
    _REPO_ROOT / "src" / "omniclaude" / "nodes" / "node_skill_release_orchestrator"
)
_CONTRACT_YAML = _NODE_DIR / "contract.yaml"
_NODE_PY = _NODE_DIR / "node.py"
_INIT_PY = _NODE_DIR / "__init__.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> str:
    """Read a file, skipping test if not present."""
    if not path.exists():
        pytest.skip(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


def _grep_file(path: Path, pattern: str) -> list[str]:
    """Return lines in file matching the pattern (regex)."""
    content = _read_file(path)
    compiled = re.compile(pattern)
    return [line for line in content.splitlines() if compiled.search(line)]


def _parse_contract() -> dict:
    """Parse contract.yaml and return as dict."""
    content = _read_file(_CONTRACT_YAML)
    return yaml.safe_load(content)


# ===========================================================================
# 3a: Contract Wiring Tests
# ===========================================================================


@pytest.mark.unit
class TestContractWiring:
    """Contract wiring: import, parse, topic routing, consumer group."""

    def test_node_directory_exists(self) -> None:
        """node_skill_release_orchestrator/ directory exists."""
        assert _NODE_DIR.is_dir(), f"Node directory missing: {_NODE_DIR}"

    def test_contract_yaml_exists(self) -> None:
        """contract.yaml exists in node directory."""
        assert _CONTRACT_YAML.is_file(), f"contract.yaml missing: {_CONTRACT_YAML}"

    def test_node_py_exists(self) -> None:
        """node.py exists in node directory."""
        assert _NODE_PY.is_file(), f"node.py missing: {_NODE_PY}"

    def test_init_py_exists(self) -> None:
        """__init__.py exists in node directory."""
        assert _INIT_PY.is_file(), f"__init__.py missing: {_INIT_PY}"

    def test_contract_parses_cleanly(self) -> None:
        """contract.yaml parses as valid YAML."""
        contract = _parse_contract()
        assert isinstance(contract, dict), "contract.yaml must parse to a dict"
        assert "name" in contract, "contract.yaml must have a 'name' field"

    def test_contract_name_matches_convention(self) -> None:
        """Contract name follows node_skill_<name>_orchestrator convention."""
        contract = _parse_contract()
        assert contract["name"] == "node_skill_release_orchestrator"

    def test_subscribe_topic(self) -> None:
        """Contract subscribes to onex.cmd.omniclaude.release.v1."""
        contract = _parse_contract()
        topic = contract["event_bus"]["subscribe"]["topic"]
        assert topic == "onex.cmd.omniclaude.release.v1", (
            f"Expected subscribe topic 'onex.cmd.omniclaude.release.v1', got '{topic}'"
        )

    def test_consumer_group(self) -> None:
        """Consumer group is omniclaude.skill.release."""
        contract = _parse_contract()
        group = contract["event_bus"]["subscribe"]["consumer_group"]
        assert group == "omniclaude.skill.release", (
            f"Expected consumer group 'omniclaude.skill.release', got '{group}'"
        )

    def test_consumer_group_convention(self) -> None:
        """Consumer group follows omniclaude.skill.<name> pattern."""
        contract = _parse_contract()
        group = contract["event_bus"]["subscribe"]["consumer_group"]
        pattern = re.compile(r"^omniclaude\.skill\.[a-z_]+$")
        assert pattern.match(group), (
            f"Consumer group '{group}' does not match pattern omniclaude.skill.<name>"
        )

    def test_success_topic_well_formed(self) -> None:
        """Success topic matches onex.evt.omniclaude.<skill>-completed.v1 convention."""
        contract = _parse_contract()
        topic = contract["event_bus"]["publish"]["success_topic"]
        assert topic == "onex.evt.omniclaude.release-completed.v1", (
            f"Expected 'onex.evt.omniclaude.release-completed.v1', got '{topic}'"
        )

    def test_failure_topic_well_formed(self) -> None:
        """Failure topic matches onex.evt.omniclaude.<skill>-failed.v1 convention."""
        contract = _parse_contract()
        topic = contract["event_bus"]["publish"]["failure_topic"]
        assert topic == "onex.evt.omniclaude.release-failed.v1", (
            f"Expected 'onex.evt.omniclaude.release-failed.v1', got '{topic}'"
        )

    def test_node_type_is_orchestrator(self) -> None:
        """Contract specifies ORCHESTRATOR_GENERIC node type."""
        contract = _parse_contract()
        assert contract["node_type"] == "ORCHESTRATOR_GENERIC"

    def test_node_imports_cleanly(self) -> None:
        """node_skill_release_orchestrator imports without circular deps."""
        # This test verifies the import chain works
        from omniclaude.nodes.node_skill_release_orchestrator import (
            NodeSkillReleaseOrchestrator,
        )

        assert NodeSkillReleaseOrchestrator is not None

    def test_node_class_name(self) -> None:
        """Node class follows NodeSkill<Name>Orchestrator naming."""
        from omniclaude.nodes.node_skill_release_orchestrator import (
            NodeSkillReleaseOrchestrator,
        )

        assert NodeSkillReleaseOrchestrator.__name__ == "NodeSkillReleaseOrchestrator"

    def test_init_exports_node_class(self) -> None:
        """__init__.py exports NodeSkillReleaseOrchestrator."""
        content = _read_file(_INIT_PY)
        assert "NodeSkillReleaseOrchestrator" in content

    def test_contract_has_capabilities(self) -> None:
        """Contract defines skill.release capability."""
        contract = _parse_contract()
        capabilities = contract.get("capabilities", [])
        cap_names = [c["name"] for c in capabilities]
        assert "skill.release" in cap_names, (
            f"Expected 'skill.release' capability, found: {cap_names}"
        )


# ===========================================================================
# 3b: Skill File Structure Tests
# ===========================================================================


@pytest.mark.unit
class TestSkillFileStructure:
    """SKILL.md and prompt.md exist with required content."""

    def test_skill_md_exists(self) -> None:
        """SKILL.md exists at skills/release/SKILL.md."""
        assert _RELEASE_SKILL.is_file(), f"SKILL.md missing: {_RELEASE_SKILL}"

    def test_prompt_md_exists(self) -> None:
        """prompt.md exists at skills/release/prompt.md."""
        assert _RELEASE_PROMPT.is_file(), f"prompt.md missing: {_RELEASE_PROMPT}"

    def test_skill_has_frontmatter(self) -> None:
        """SKILL.md has YAML frontmatter with required fields."""
        content = _read_file(_RELEASE_SKILL)
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        # Extract frontmatter
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md frontmatter not properly delimited"
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "release"
        assert "description" in fm
        assert "version" in fm

    def test_skill_has_arguments_table(self) -> None:
        """SKILL.md documents all required arguments."""
        content = _read_file(_RELEASE_SKILL)
        for arg in [
            "repos",
            "--bump",
            "--dry-run",
            "--resume",
            "--run-id",
            "--skip-pypi-wait",
            "--pypi-timeout-minutes",
            "--gate-attestation",
        ]:
            assert arg in content, f"SKILL.md missing argument: {arg}"

    def test_skill_has_dependency_graph(self) -> None:
        """SKILL.md documents the tier dependency graph."""
        content = _read_file(_RELEASE_SKILL)
        assert "Tier 1" in content, "SKILL.md missing Tier 1"
        assert "Tier 2" in content, "SKILL.md missing Tier 2"
        assert "Tier 3" in content, "SKILL.md missing Tier 3"
        assert "Tier 4" in content, "SKILL.md missing Tier 4"
        assert "omnibase_spi" in content, "SKILL.md missing omnibase_spi in tiers"
        assert "omnibase_core" in content, "SKILL.md missing omnibase_core in tiers"
        assert "omniclaude" in content, "SKILL.md missing omniclaude in tiers"

    def test_skill_has_error_table(self) -> None:
        """SKILL.md has an error table covering required error codes."""
        content = _read_file(_RELEASE_SKILL)
        for error_code in [
            "GRAPH_DRIFT",
            "NOTHING_TO_RELEASE",
            "LINT_FAILED",
            "PYPI_TIMEOUT",
            "TIER_BLOCKED",
            "GATE_REJECTED",
        ]:
            assert error_code in content, f"SKILL.md missing error code: {error_code}"

    def test_skill_has_model_skill_result(self) -> None:
        """SKILL.md defines ModelSkillResult with all status values."""
        content = _read_file(_RELEASE_SKILL)
        assert "ModelSkillResult" in content
        for status in ["SUCCESS", "PARTIAL", "FAILED", "DRY_RUN"]:
            assert status in content, f"SKILL.md missing status value: {status}"

    def test_skill_has_state_model(self) -> None:
        """SKILL.md documents the state model with phase machine."""
        content = _read_file(_RELEASE_SKILL)
        assert (
            "Phase State Machine" in content or "phase state machine" in content.lower()
        )
        for phase in [
            "PLANNED",
            "WORKTREE",
            "BUMPED",
            "PINNED",
            "CHANGELOG",
            "LOCKED",
            "LINT",
            "COMMITTED",
            "PUSHED",
            "PR_CREATED",
            "MERGED",
            "TAGGED",
            "PUBLISHED",
            "DONE",
        ]:
            assert phase in content, f"SKILL.md missing phase: {phase}"

    def test_skill_has_idempotency_keys(self) -> None:
        """SKILL.md documents idempotency keys for all mutations."""
        content = _read_file(_RELEASE_SKILL)
        assert "Idempotency" in content
        assert "PR dedupe" in content or "pr creation" in content.lower()
        assert "Tag dedupe" in content or "tag" in content.lower()
        assert "Worktree reuse" in content or "worktree" in content.lower()


# ===========================================================================
# 3b: Dry-Run / No-op Smoke Tests (structural)
# ===========================================================================


@pytest.mark.unit
class TestDryRunContract:
    """--dry-run produces DRY_RUN status without side effects."""

    def test_prompt_documents_dry_run_exit(self) -> None:
        """prompt.md documents --dry-run exits after plan display."""
        content = _read_file(_RELEASE_PROMPT)
        assert "--dry-run" in content, "prompt.md must document --dry-run"
        assert "DRY_RUN" in content, "prompt.md must mention DRY_RUN status on dry-run"

    def test_skill_documents_dry_run_flag(self) -> None:
        """SKILL.md lists --dry-run in arguments."""
        content = _read_file(_RELEASE_SKILL)
        assert "--dry-run" in content

    def test_dry_run_no_state_file_created(self) -> None:
        """prompt.md states dry-run does not create a state file."""
        content = _read_file(_RELEASE_PROMPT)
        # Verify the dry-run section mentions no state file
        dry_run_section = content[content.find("--dry-run") :]
        assert (
            "no state file" in dry_run_section.lower()
            or "no side effects" in dry_run_section.lower()
        ), "prompt.md dry-run section must state no state file is created"

    def test_nothing_to_release_is_not_error(self) -> None:
        """SKILL.md treats NOTHING_TO_RELEASE as a skip, not an error."""
        content = _read_file(_RELEASE_SKILL)
        assert "NOTHING_TO_RELEASE" in content
        # Should appear in skip context, not fatal error context
        lines = _grep_file(_RELEASE_SKILL, "NOTHING_TO_RELEASE")
        assert any("skip" in line.lower() for line in lines), (
            "NOTHING_TO_RELEASE should be described as a skip, not an error"
        )


# ===========================================================================
# 3b: Full Cycle Structural Tests
# ===========================================================================


@pytest.mark.unit
class TestFullCycleStructure:
    """Verify all 12 per-repo sub-steps are documented in prompt.md."""

    def test_all_12_sub_steps_documented(self) -> None:
        """prompt.md documents all 12 per-repo release sub-steps."""
        content = _read_file(_RELEASE_PROMPT)
        for step_name in [
            "WORKTREE",
            "BUMP",
            "PIN",
            "CHANGELOG",
            "LOCK",
            "LINT",
            "COMMIT",
            "PUSH",
            "PR",
            "MERGE",
            "TAG",
            "PUBLISH",
        ]:
            assert step_name in content, f"prompt.md missing sub-step: {step_name}"

    def test_sub_steps_have_state_updates(self) -> None:
        """prompt.md documents state updates after each sub-step."""
        content = _read_file(_RELEASE_PROMPT)
        state_update_count = content.lower().count("state update")
        assert state_update_count >= 10, (
            f"Expected at least 10 'State update' mentions, found {state_update_count}"
        )

    def test_five_phases_present(self) -> None:
        """prompt.md implements all 5 phases."""
        content = _read_file(_RELEASE_PROMPT)
        assert "Phase 0" in content, "prompt.md missing Phase 0"
        assert "Phase 1" in content, "prompt.md missing Phase 1"
        assert "Phase 2" in content, "prompt.md missing Phase 2"
        assert "Phase 3" in content, "prompt.md missing Phase 3"
        assert "Phase 4" in content, "prompt.md missing Phase 4"


# ===========================================================================
# 3c: Resume + Idempotency Tests (structural)
# ===========================================================================


@pytest.mark.unit
class TestResumeSemantics:
    """Resume and idempotency documented in prompt.md and SKILL.md."""

    def test_resume_flag_documented(self) -> None:
        """SKILL.md documents --resume argument."""
        content = _read_file(_RELEASE_SKILL)
        assert "--resume" in content

    def test_prompt_documents_resume_flow(self) -> None:
        """prompt.md documents resume flow (load state, skip DONE repos)."""
        content = _read_file(_RELEASE_PROMPT)
        assert "--resume" in content
        assert "state file" in content.lower()

    def test_resume_skips_done_repos(self) -> None:
        """prompt.md states resumed repos in DONE phase are skipped."""
        content = _read_file(_RELEASE_PROMPT)
        assert "DONE" in content
        # Look for skip/DONE combination
        lines = [
            line
            for line in content.splitlines()
            if "DONE" in line and ("skip" in line.lower() or "continue" in line.lower())
        ]
        assert lines, "prompt.md must document skipping DONE repos on resume"

    def test_pr_dedupe_documented(self) -> None:
        """prompt.md documents PR deduplication check."""
        content = _read_file(_RELEASE_PROMPT)
        pr_section = content[content.find("Sub-Step 9") :]
        assert (
            "existing" in pr_section.lower()
            or "dedupe" in pr_section.lower()
            or "already" in pr_section.lower()
        ), "Sub-Step 9 (PR) must document idempotent PR creation"

    def test_tag_dedupe_documented(self) -> None:
        """prompt.md documents tag deduplication check."""
        content = _read_file(_RELEASE_PROMPT)
        tag_section = content[content.find("Sub-Step 11") :]
        assert (
            "existing" in tag_section.lower()
            or "dedupe" in tag_section.lower()
            or "already" in tag_section.lower()
        ), "Sub-Step 11 (TAG) must document idempotent tag creation"

    def test_worktree_reuse_documented(self) -> None:
        """prompt.md documents worktree reuse on resume."""
        content = _read_file(_RELEASE_PROMPT)
        wt_section = content[content.find("Sub-Step 1") :]
        assert "reuse" in wt_section.lower() or "Reusing" in wt_section, (
            "Sub-Step 1 (WORKTREE) must document worktree reuse"
        )

    def test_fresh_run_starts_clean(self) -> None:
        """SKILL.md documents that new run_id starts fresh."""
        content = _read_file(_RELEASE_SKILL)
        assert "Run Marker" in content or "run_id" in content.lower()

    def test_atomic_writes_documented(self) -> None:
        """SKILL.md documents atomic state file writes."""
        content = _read_file(_RELEASE_SKILL)
        assert "atomic" in content.lower()
        assert "rename" in content.lower() or "temp" in content.lower()

    def test_mid_tier_failure_blocks_later_tiers(self) -> None:
        """prompt.md documents that mid-tier failure blocks later tiers."""
        content = _read_file(_RELEASE_PROMPT)
        assert "BLOCKED" in content
        assert "later tiers" in content.lower() or "remaining repos" in content.lower()


# ===========================================================================
# 3c: Cross-reference Tests
# ===========================================================================


@pytest.mark.unit
class TestCrossReferences:
    """Verify cross-references to related skills and workflows."""

    def test_merge_sweep_referenced_in_skill(self) -> None:
        """SKILL.md references merge-sweep skill."""
        content = _read_file(_RELEASE_SKILL)
        assert "merge-sweep" in content

    def test_pr_safety_referenced_in_skill(self) -> None:
        """SKILL.md references pr-safety helpers."""
        content = _read_file(_RELEASE_SKILL)
        assert "pr-safety" in content

    def test_release_yml_referenced_in_skill(self) -> None:
        """SKILL.md references release.yml GitHub Action."""
        content = _read_file(_RELEASE_SKILL)
        assert "release.yml" in content

    def test_auto_tag_reusable_referenced_in_skill(self) -> None:
        """SKILL.md references auto-tag-reusable.yml GitHub Action."""
        content = _read_file(_RELEASE_SKILL)
        assert "auto-tag-reusable" in content

    def test_merge_sweep_referenced_in_prompt(self) -> None:
        """prompt.md references merge-sweep for merge strategy."""
        content = _read_file(_RELEASE_PROMPT)
        assert "merge-sweep" in content

    def test_pr_safety_referenced_in_prompt(self) -> None:
        """prompt.md references pr-safety for PR creation guards."""
        content = _read_file(_RELEASE_PROMPT)
        assert "pr-safety" in content

    def test_release_yml_referenced_in_prompt(self) -> None:
        """prompt.md references release.yml for PyPI publish trigger."""
        content = _read_file(_RELEASE_PROMPT)
        assert "release.yml" in content

    def test_auto_tag_reusable_referenced_in_prompt(self) -> None:
        """prompt.md references auto-tag-reusable.yml."""
        content = _read_file(_RELEASE_PROMPT)
        assert "auto-tag-reusable" in content

    def test_slack_gate_referenced(self) -> None:
        """prompt.md references slack-gate skill for HIGH_RISK gate."""
        content = _read_file(_RELEASE_PROMPT)
        assert "slack-gate" in content or "slack_gate" in content


# ===========================================================================
# 3c: Drift Guard Tests
# ===========================================================================


@pytest.mark.unit
class TestDriftGuard:
    """Drift guard is documented and functional."""

    def test_drift_guard_in_prompt(self) -> None:
        """prompt.md documents drift guard check."""
        content = _read_file(_RELEASE_PROMPT)
        assert "drift_guard" in content or "GRAPH_DRIFT" in content

    def test_drift_guard_in_skill(self) -> None:
        """SKILL.md documents GRAPH_DRIFT error."""
        content = _read_file(_RELEASE_SKILL)
        assert "GRAPH_DRIFT" in content

    def test_tier_graph_defined_in_prompt(self) -> None:
        """prompt.md defines the TIER_GRAPH constant."""
        content = _read_file(_RELEASE_PROMPT)
        assert "TIER_GRAPH" in content


# ===========================================================================
# 3c: Bump Inference Tests
# ===========================================================================


@pytest.mark.unit
class TestBumpInference:
    """Bump inference logic is documented."""

    def test_bump_inference_in_prompt(self) -> None:
        """prompt.md documents bump inference from conventional commits."""
        content = _read_file(_RELEASE_PROMPT)
        assert "infer_bump" in content or "conventional commit" in content.lower()

    def test_bump_override_documented(self) -> None:
        """prompt.md documents --bump override."""
        content = _read_file(_RELEASE_PROMPT)
        assert "--bump" in content

    def test_major_from_breaking_change(self) -> None:
        """prompt.md documents BREAKING CHANGE -> major bump."""
        content = _read_file(_RELEASE_PROMPT)
        assert "BREAKING" in content
        assert "major" in content.lower()

    def test_minor_from_feat(self) -> None:
        """prompt.md documents feat -> minor bump."""
        content = _read_file(_RELEASE_PROMPT)
        assert "feat" in content
        assert "minor" in content.lower()


# ===========================================================================
# 3c: Pin Policy Tests
# ===========================================================================


@pytest.mark.unit
class TestPinPolicy:
    """Pin policy uses exact ==X.Y.Z format."""

    def test_exact_pins_in_prompt(self) -> None:
        """prompt.md uses exact ==X.Y.Z pins for MVP."""
        content = _read_file(_RELEASE_PROMPT)
        assert "==" in content
        assert "exact pin" in content.lower() or "==X.Y.Z" in content

    def test_exact_pins_in_skill(self) -> None:
        """SKILL.md documents exact pin policy."""
        content = _read_file(_RELEASE_SKILL)
        assert "==X.Y.Z" in content or "exact pin" in content.lower()


# ===========================================================================
# 3d: CI Enforcement Checks
# ===========================================================================


@pytest.mark.unit
class TestCIEnforcement:
    """CI enforcement: no unguarded mutations in prompt.md."""

    def test_no_bare_git_push_force(self) -> None:
        """prompt.md never uses git push --force."""
        lines = _grep_file(_RELEASE_PROMPT, r"git push.*--force")
        assert not lines, f"prompt.md must not use 'git push --force': {lines}"

    def test_no_bare_git_reset_hard(self) -> None:
        """prompt.md never uses git reset --hard."""
        lines = _grep_file(_RELEASE_PROMPT, r"git reset.*--hard")
        assert not lines, f"prompt.md must not use 'git reset --hard': {lines}"

    def test_gate_attestation_validated_before_scan(self) -> None:
        """prompt.md validates --gate-attestation before scanning."""
        content = _read_file(_RELEASE_PROMPT)
        gate_idx = content.find("--gate-attestation")
        scan_idx = content.find("Step 0.2: Scan")
        if gate_idx >= 0 and scan_idx >= 0:
            assert gate_idx < scan_idx, (
                "--gate-attestation validation must precede repo scanning"
            )

    def test_high_risk_gate_required(self) -> None:
        """prompt.md requires HIGH_RISK gate for release."""
        content = _read_file(_RELEASE_PROMPT)
        assert "HIGH_RISK" in content, "Release must use HIGH_RISK gate"

    def test_silence_never_advances(self) -> None:
        """SKILL.md states silence never advances HIGH_RISK gate."""
        content = _read_file(_RELEASE_SKILL)
        assert "silence" in content.lower()
        assert "never" in content.lower() or "NOT" in content

    def test_plan_hash_audit_trail(self) -> None:
        """prompt.md documents plan_hash for audit trail."""
        content = _read_file(_RELEASE_PROMPT)
        assert "plan_hash" in content
        assert "sha256" in content.lower() or "SHA256" in content
