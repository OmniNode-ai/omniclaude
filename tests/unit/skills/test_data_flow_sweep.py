# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for data-flow-sweep skill definition.

Validates SKILL.md structure, topics.yaml consistency, and phase contracts.
"""

from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "data_flow_sweep"
)


@pytest.mark.unit
class TestDataFlowSweepSkill:
    """Validate data-flow-sweep skill artifacts."""

    def test_skill_md_exists(self) -> None:
        """SKILL.md must exist."""
        assert (SKILL_DIR / "SKILL.md").is_file()

    def test_skill_md_has_valid_frontmatter(self) -> None:
        """SKILL.md must have parseable YAML frontmatter."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---")
        parts = content.split("---", 2)
        assert len(parts) >= 3, "Frontmatter not properly delimited"
        fm = yaml.safe_load(parts[1])
        assert fm["description"], "description required"
        assert fm["version"] == "1.0.0"
        assert fm["category"] == "verification"
        assert "data-flow" in fm["tags"]

    def test_skill_md_has_required_phases(self) -> None:
        """SKILL.md must define all 5 phases."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for phase in [
            "Phase 1",
            "Phase 2",
            "Phase 3",
            "Phase 4",
            "Phase 5",
        ]:
            assert phase in content, f"Missing {phase}"

    def test_skill_md_has_dispatch_rules(self) -> None:
        """SKILL.md must contain dispatch rules section."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "Dispatch Rules" in content
        assert "polymorphic-agent" in content

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml must exist."""
        assert (SKILL_DIR / "topics.yaml").is_file()

    def test_topics_yaml_has_required_topics(self) -> None:
        """topics.yaml must declare cmd and evt topics."""
        content = yaml.safe_load((SKILL_DIR / "topics.yaml").read_text())
        topics = content.get("topics", [])
        assert "onex.cmd.omniclaude.data-flow-sweep.v1" in topics
        assert "onex.evt.omniclaude.data-flow-sweep-completed.v1" in topics
        assert "onex.evt.omniclaude.data-flow-sweep-failed.v1" in topics

    def test_skill_md_has_dry_run_contract(self) -> None:
        """SKILL.md must specify --dry-run produces zero side effects."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--dry-run" in content
        assert "zero side effects" in content.lower() or "no tickets" in content.lower()

    def test_skill_md_references_omnidash_topics_yaml(self) -> None:
        """SKILL.md must reference omnidash/topics.yaml as source of truth."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "topics.yaml" in content
        assert "omnidash" in content.lower()

    def test_skill_md_classifies_producer_status(self) -> None:
        """SKILL.md must define producer classification statuses."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for status in ["ACTIVE", "EMPTY", "MISSING"]:
            assert status in content, f"Missing producer classification: {status}"

    def test_skill_md_classifies_flow_status(self) -> None:
        """SKILL.md must define consumer/DB flow classification statuses."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for status in ["FLOWING", "STALE", "LAGGING", "EMPTY_TABLE", "MISSING_TABLE"]:
            assert status in content, f"Missing flow classification: {status}"

    def test_skill_md_has_rpk_commands(self) -> None:
        """SKILL.md must use rpk for Redpanda topic inspection."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "rpk topic" in content
        assert "rpk group" in content

    def test_skill_md_has_psql_commands(self) -> None:
        """SKILL.md must use psql for DB table health checks."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "psql" in content
        assert "omnidash_analytics" in content

    def test_skill_md_has_topic_single_filter(self) -> None:
        """SKILL.md must support --topic for single-topic filtering."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--topic" in content

    def test_skill_md_has_skip_playwright_option(self) -> None:
        """SKILL.md must support --skip-playwright to skip dashboard verification."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--skip-playwright" in content

    def test_skill_md_has_integration_points(self) -> None:
        """SKILL.md must document integration with autopilot and sibling sweeps."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "autopilot" in content
        assert "dashboard-sweep" in content
        assert "integration-sweep" in content

    def test_skill_md_has_linear_ticket_creation(self) -> None:
        """SKILL.md must define Linear ticket creation for broken flows."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "Linear ticket" in content or "Linear" in content
        assert "Active Sprint" in content

    def test_skill_md_consumer_group_reference(self) -> None:
        """SKILL.md must reference the omnidash consumer group."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "omnidash-read-model" in content

    def test_skill_md_has_health_matrix_output(self) -> None:
        """SKILL.md must define a health matrix output table."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "Topic" in content and "Status" in content
        assert "Producer" in content or "Consumer" in content


@pytest.mark.unit
class TestDataFlowSweepNodeScaffold:
    """Validate ONEX node scaffold for data-flow-sweep."""

    NODE_DIR = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "omniclaude"
        / "nodes"
        / "node_skill_data_flow_sweep_orchestrator"
    )

    def test_node_directory_exists(self) -> None:
        """Node scaffold directory must exist."""
        assert self.NODE_DIR.is_dir()

    def test_contract_yaml_exists(self) -> None:
        """contract.yaml must exist in node directory."""
        assert (self.NODE_DIR / "contract.yaml").is_file()

    def test_node_py_exists(self) -> None:
        """node.py must exist in node directory."""
        assert (self.NODE_DIR / "node.py").is_file()

    def test_init_py_exists(self) -> None:
        """__init__.py must exist in node directory."""
        assert (self.NODE_DIR / "__init__.py").is_file()

    def test_contract_has_correct_name(self) -> None:
        """contract.yaml must declare correct node name."""
        content = yaml.safe_load((self.NODE_DIR / "contract.yaml").read_text())
        assert content["name"] == "node_skill_data_flow_sweep_orchestrator"

    def test_contract_has_event_bus_config(self) -> None:
        """contract.yaml must define event bus subscribe/publish topics."""
        content = yaml.safe_load((self.NODE_DIR / "contract.yaml").read_text())
        eb = content["event_bus"]
        assert "data-flow-sweep" in eb["subscribe"]["topic"]
        assert "data-flow-sweep-completed" in eb["publish"]["success_topic"]
        assert "data-flow-sweep-failed" in eb["publish"]["failure_topic"]

    def test_contract_topics_match_topics_yaml(self) -> None:
        """contract.yaml event bus topics must match topics.yaml declarations."""
        contract = yaml.safe_load((self.NODE_DIR / "contract.yaml").read_text())
        topics_yaml = yaml.safe_load((SKILL_DIR / "topics.yaml").read_text())
        topics = topics_yaml.get("topics", [])

        eb = contract["event_bus"]
        assert eb["subscribe"]["topic"] in topics
        assert eb["publish"]["success_topic"] in topics
        assert eb["publish"]["failure_topic"] in topics

    def test_contract_node_type_is_orchestrator(self) -> None:
        """contract.yaml must declare ORCHESTRATOR_GENERIC node type."""
        content = yaml.safe_load((self.NODE_DIR / "contract.yaml").read_text())
        assert content["node_type"] == "ORCHESTRATOR_GENERIC"
