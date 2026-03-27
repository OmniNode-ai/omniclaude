# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for runtime-sweep skill definition.

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
    / "runtime_sweep"
)


@pytest.mark.unit
class TestRuntimeSweepSkill:
    """Validate runtime-sweep skill artifacts."""

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
        assert "runtime" in fm["tags"]

    def test_skill_md_has_required_phases(self) -> None:
        """SKILL.md must define all 4 phases."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for phase in ["Phase 1", "Phase 2", "Phase 3", "Phase 4"]:
            assert phase in content, f"Missing {phase}"

    def test_skill_md_checks_node_descriptions(self) -> None:
        """SKILL.md must audit node descriptions for placeholders."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "PLACEHOLDER" in content
        assert "description" in content.lower()

    def test_skill_md_checks_handler_wiring(self) -> None:
        """SKILL.md must audit handler wiring."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "WIRED" in content
        assert "UNWIRED" in content

    def test_skill_md_checks_topic_symmetry(self) -> None:
        """SKILL.md must audit topic symmetry (producer + consumer)."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "PRODUCER_ONLY" in content
        assert "CONSUMER_ONLY" in content
        assert "SYMMETRIC" in content

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml must exist."""
        assert (SKILL_DIR / "topics.yaml").is_file()

    def test_topics_yaml_has_required_topics(self) -> None:
        """topics.yaml must declare cmd and evt topics."""
        content = yaml.safe_load((SKILL_DIR / "topics.yaml").read_text())
        topics = content.get("topics", [])
        assert "onex.cmd.omniclaude.runtime-sweep.v1" in topics
        assert "onex.evt.omniclaude.runtime-sweep-completed.v1" in topics
        assert "onex.evt.omniclaude.runtime-sweep-failed.v1" in topics

    def test_skill_md_has_dry_run_contract(self) -> None:
        """SKILL.md must specify --dry-run produces zero side effects."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--dry-run" in content

    def test_skill_md_has_scope_arg(self) -> None:
        """SKILL.md must support --scope arg for omnidash-only vs all-repos."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--scope" in content
        assert "omnidash-only" in content
        assert "all-repos" in content
