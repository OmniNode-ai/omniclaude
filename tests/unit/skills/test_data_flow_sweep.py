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
