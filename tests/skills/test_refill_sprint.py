# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the refill-sprint skill definition and topic registration."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from omniclaude.hooks.topics import TopicBase


@pytest.mark.unit
class TestRefillSprintSkill:
    """Verify the refill-sprint skill is properly defined."""

    SKILL_DIR = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "onex"
        / "skills"
        / "refill_sprint"
    )

    def test_skill_md_exists(self) -> None:
        """SKILL.md must exist."""
        assert (self.SKILL_DIR / "SKILL.md").is_file()

    def test_prompt_md_exists(self) -> None:
        """prompt.md must exist."""
        assert (self.SKILL_DIR / "prompt.md").is_file()

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml must exist."""
        assert (self.SKILL_DIR / "topics.yaml").is_file()

    def test_skill_md_has_frontmatter(self) -> None:
        """SKILL.md must have valid YAML frontmatter."""
        content = (self.SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---")
        # Extract frontmatter between first two ---
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have YAML frontmatter delimited by ---"
        frontmatter = yaml.safe_load(parts[1])
        assert frontmatter["category"] == "workflow"
        assert "autopilot" in frontmatter["tags"]
        assert frontmatter["version"] == "1.0.0"

    def test_topics_yaml_matches_topic_base(self) -> None:
        """topics.yaml topics must match TopicBase constants."""
        content = yaml.safe_load((self.SKILL_DIR / "topics.yaml").read_text())
        topics = content["topics"]
        assert len(topics) == 2

        topic_values = {t.value for t in TopicBase}
        for topic in topics:
            assert topic in topic_values, f"Topic {topic} not found in TopicBase enum"


@pytest.mark.unit
class TestRefillSprintTopics:
    """Verify topic constants are registered."""

    def test_sprint_auto_pull_completed_topic(self) -> None:
        """SPRINT_AUTO_PULL_COMPLETED must be a valid TopicBase member."""
        assert (
            TopicBase.SPRINT_AUTO_PULL_COMPLETED
            == "onex.evt.omniclaude.sprint-auto-pull-completed.v1"
        )

    def test_tech_debt_queue_empty_topic(self) -> None:
        """TECH_DEBT_QUEUE_EMPTY must be a valid TopicBase member."""
        assert (
            TopicBase.TECH_DEBT_QUEUE_EMPTY
            == "onex.evt.omniclaude.tech-debt-queue-empty.v1"
        )

    def test_topics_follow_naming_convention(self) -> None:
        """Both topics must follow ONEX naming convention."""
        for topic in [
            TopicBase.SPRINT_AUTO_PULL_COMPLETED,
            TopicBase.TECH_DEBT_QUEUE_EMPTY,
        ]:
            parts = topic.split(".")
            assert len(parts) == 5, f"Topic {topic} must have 5 dot-separated segments"
            assert parts[0] == "onex"
            assert parts[1] == "evt"
            assert parts[2] == "omniclaude"
            assert parts[4].startswith("v")


@pytest.mark.unit
class TestRefillSprintPrompt:
    """Verify prompt.md has required sections."""

    PROMPT_PATH = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "onex"
        / "skills"
        / "refill_sprint"
        / "prompt.md"
    )

    def test_has_argument_parsing(self) -> None:
        """prompt.md must have argument parsing section."""
        content = self.PROMPT_PATH.read_text()
        assert "## Argument Parsing" in content

    def test_has_all_phases(self) -> None:
        """prompt.md must define all 5 phases."""
        content = self.PROMPT_PATH.read_text()
        assert "## Phase 1: Capacity Check" in content
        assert "## Phase 2: Candidate Selection" in content
        assert "## Phase 3: Scope Verification" in content
        assert "## Phase 4: Pull and Label" in content
        assert "## Phase 5: Notification and Events" in content

    def test_has_dry_run_support(self) -> None:
        """prompt.md must reference --dry-run flag."""
        content = self.PROMPT_PATH.read_text()
        assert "--dry-run" in content

    def test_has_zombie_exclusion(self) -> None:
        """prompt.md must exclude tickets with 2+ failed attempts."""
        content = self.PROMPT_PATH.read_text()
        assert "[auto-pull-attempt]" in content

    def test_has_time_box_reference(self) -> None:
        """prompt.md must reference time-box policy."""
        content = self.PROMPT_PATH.read_text()
        assert "30 min" in content
        assert "20 tool calls" in content
