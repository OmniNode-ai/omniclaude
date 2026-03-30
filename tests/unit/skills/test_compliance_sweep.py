# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for compliance-sweep skill definition.

Validates SKILL.md structure, prompt.md execution phases,
and skill contract completeness for OMN-6842 and OMN-6843.
"""

from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "compliance_sweep"
)


@pytest.mark.unit
class TestComplianceSweepSkillMd:
    """Validate compliance_sweep SKILL.md artifact."""

    def test_skill_md_exists(self) -> None:
        """SKILL.md must exist."""
        assert (SKILL_DIR / "SKILL.md").is_file()

    def test_skill_md_has_valid_frontmatter(self) -> None:
        """SKILL.md must have parseable YAML frontmatter with required fields."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---")
        parts = content.split("---", 2)
        assert len(parts) >= 3, "Frontmatter not properly delimited"
        fm = yaml.safe_load(parts[1])
        assert fm["description"], "description required"
        assert fm["version"] == "1.0.0"
        assert fm["mode"] == "full"
        assert fm["category"] == "verification"
        assert "compliance" in fm["tags"]
        assert "contracts" in fm["tags"]

    def test_skill_md_has_required_args(self) -> None:
        """SKILL.md frontmatter must declare all CLI arguments."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        arg_names = [a["name"] for a in fm["args"]]
        assert "--repos" in arg_names
        assert "--dry-run" in arg_names
        assert "--create-tickets" in arg_names
        assert "--max-tickets" in arg_names
        assert "--json" in arg_names

    def test_skill_md_documents_verdicts(self) -> None:
        """SKILL.md must document all compliance verdicts."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for verdict in [
            "COMPLIANT",
            "IMPERATIVE",
            "HYBRID",
            "ALLOWLISTED",
            "MISSING_CONTRACT",
        ]:
            assert verdict in content, f"Missing verdict: {verdict}"

    def test_skill_md_documents_violation_types(self) -> None:
        """SKILL.md must document violation types detected."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for violation in [
            "HARDCODED_TOPIC",
            "UNDECLARED_TRANSPORT",
            "MISSING_HANDLER_ROUTING",
            "LOGIC_IN_NODE",
            "DIRECT_DB_ACCESS",
        ]:
            assert violation in content, f"Missing violation type: {violation}"

    def test_skill_md_references_scanner(self) -> None:
        """SKILL.md must reference the onex_change_control scanner."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "onex_change_control" in content
        assert "arch-handler-contract-compliance" in content
        assert "handler_contract_compliance" in content

    def test_skill_md_documents_ticket_creation(self) -> None:
        """SKILL.md must document ticket creation behavior."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "create-tickets" in content
        assert "max-tickets" in content
        assert "Active Sprint" in content
        assert "contract-compliance" in content
        assert "idempotent" in content

    def test_skill_md_documents_output(self) -> None:
        """SKILL.md must document the report output."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "ModelComplianceSweepReport" in content
        assert "compliance-scan-" in content
        assert "docs/registry" in content

    def test_skill_md_has_default_repo_list(self) -> None:
        """SKILL.md must list default repos to scan."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for repo in ["omnibase_infra", "omniintelligence", "omnimemory"]:
            assert repo in content, f"Missing default repo: {repo}"


@pytest.mark.unit
class TestComplianceSweepPromptMd:
    """Validate compliance_sweep prompt.md execution contract."""

    def test_prompt_md_exists(self) -> None:
        """prompt.md must exist."""
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_prompt_md_has_announce(self) -> None:
        """prompt.md must include announce step."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "Announce" in content
        assert "compliance-sweep" in content

    def test_prompt_md_has_all_phases(self) -> None:
        """prompt.md must define all 7 phases."""
        content = (SKILL_DIR / "prompt.md").read_text()
        for phase_num in range(1, 8):
            assert f"Phase {phase_num}" in content, f"Missing Phase {phase_num}"

    def test_prompt_md_phase_1_discovery(self) -> None:
        """Phase 1 must scan for node directories."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "Discovery" in content
        assert "node_" in content
        assert "handlers" in content

    def test_prompt_md_phase_2_scanner(self) -> None:
        """Phase 2 must run the compliance scanner."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "arch_handler_contract_compliance" in content or (
            "arch-handler-contract-compliance" in content
        )

    def test_prompt_md_phase_3_aggregate(self) -> None:
        """Phase 3 must aggregate results into sweep report."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "Aggregate" in content
        assert "compliant_pct" in content
        assert "violation_histogram" in content or "violation histogram" in content

    def test_prompt_md_phase_5_summary(self) -> None:
        """Phase 5 must print human-readable summary."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "summary" in content.lower()
        assert "Per-repo breakdown" in content

    def test_prompt_md_phase_6_ticket_creation(self) -> None:
        """Phase 6 must handle ticket creation with guards."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "create-tickets" in content
        assert "dry-run" in content
        assert "max-tickets" in content or "max_tickets" in content

    def test_prompt_md_phase_7_event_emission(self) -> None:
        """Phase 7 must emit compliance.sweep.completed event."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "compliance.sweep.completed" in content

    def test_prompt_md_has_error_handling(self) -> None:
        """prompt.md must document error handling."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "Error handling" in content or "error handling" in content

    def test_prompt_md_ticket_dedup(self) -> None:
        """prompt.md must specify ticket deduplication strategy."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "idempotent" in content.lower() or "dedup" in content.lower()

    def test_prompt_md_groups_by_node(self) -> None:
        """prompt.md must group violations by node directory."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "node_dir" in content or "node directory" in content

    def test_prompt_md_max_tickets_default(self) -> None:
        """prompt.md must specify default max tickets (10)."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "default 10" in content or "default: 10" in content


@pytest.mark.unit
class TestComplianceSweepSkillCompleteness:
    """Cross-cutting validation of skill completeness."""

    def test_skill_dir_has_required_files(self) -> None:
        """Skill directory must contain SKILL.md and prompt.md."""
        assert (SKILL_DIR / "SKILL.md").is_file()
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_no_phantom_callables(self) -> None:
        """prompt.md must not reference executable functions that don't exist."""
        content = (SKILL_DIR / "prompt.md").read_text()
        # The skill delegates to existing onex_change_control infrastructure
        # It should NOT invent new callable functions
        assert "execute.py" not in content, (
            "prompt.md should not reference phantom execute.py scripts"
        )

    def test_ticket_format_includes_required_fields(self) -> None:
        """Ticket creation template must include handler paths and violations."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "handler" in content.lower()
        assert "violations" in content.lower() or "Violations" in content
        assert "contract.yaml" in content

    def test_report_path_convention(self) -> None:
        """Report should be saved to docs/registry/compliance-scan-<date>.json."""
        prompt = (SKILL_DIR / "prompt.md").read_text()
        skill = (SKILL_DIR / "SKILL.md").read_text()
        assert "compliance-scan-" in prompt
        assert "compliance-scan-" in skill
        assert "docs/registry" in prompt
