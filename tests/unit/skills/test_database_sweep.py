# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for database-sweep skill definition.

Updated for thin dispatch-only shim (OMN-8768). Phase/classification logic
now lives in node_database_sweep; this test validates the shim contract.
"""

from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "database_sweep"
)


@pytest.mark.unit
class TestDatabaseSweepSkill:
    """Validate database-sweep skill artifacts."""

    def test_skill_md_exists(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()

    def test_skill_md_has_valid_frontmatter(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---")
        parts = content.split("---", 2)
        assert len(parts) >= 3, "Frontmatter not properly delimited"
        fm = yaml.safe_load(parts[1])
        assert fm["description"], "description required"
        assert fm["version"] == "3.0.0"
        assert fm["category"] == "verification"
        assert "database" in fm["tags"]
        assert "dispatch-only" in fm["tags"]

    def test_skill_md_has_required_phases(self) -> None:
        """Dispatch shim must reference backing node (not inline phases)."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_database_sweep" in content

    def test_skill_md_has_staleness_threshold(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "staleness-threshold" in content or "staleness_threshold" in content

    def test_skill_md_classifies_tables(self) -> None:
        """Thin shim documents dispatch path; classifications live in node contract."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        # The shim itself needn't repeat all classifications — backing node owns them.
        assert "node_database_sweep" in content

    def test_topics_yaml_exists(self) -> None:
        assert (SKILL_DIR / "topics.yaml").is_file()

    def test_topics_yaml_has_required_topics(self) -> None:
        content = yaml.safe_load((SKILL_DIR / "topics.yaml").read_text())
        topics = content.get("topics", [])
        assert "onex.cmd.omniclaude.database-sweep.v1" in topics

    def test_skill_md_has_dry_run_contract(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--dry-run" in content

    def test_skill_md_references_intelligence_schema(self) -> None:
        """Thin shim dispatch omits internal table names; node contract owns them."""
        # The shim no longer inline-lists tables. Check backing node reference.
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_database_sweep" in content

    def test_skill_md_has_migration_tracking(self) -> None:
        """Migration tracking is in node; shim must dispatch to it."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_database_sweep" in content

    def test_skill_md_covers_all_databases(self) -> None:
        """Thin shim dispatches to node which owns database coverage."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_database_sweep" in content

    def test_skill_md_classifies_migration_state(self) -> None:
        """Migration state classification lives in node; shim dispatches."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_database_sweep" in content

    def test_skill_md_handles_drizzle_migrations(self) -> None:
        """Drizzle migration handling is in node_database_sweep."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_database_sweep" in content
