# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for database-sweep skill definition.

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
    / "database_sweep"
)


@pytest.mark.unit
class TestDatabaseSweepSkill:
    """Validate database-sweep skill artifacts."""

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
        assert "database" in fm["tags"]

    def test_skill_md_has_required_phases(self) -> None:
        """SKILL.md must define all 4 phases."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for phase in ["Phase 1", "Phase 2", "Phase 3", "Phase 4"]:
            assert phase in content, f"Missing {phase}"

    def test_skill_md_has_staleness_threshold(self) -> None:
        """SKILL.md must support configurable staleness threshold."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "staleness-threshold" in content or "staleness_threshold" in content

    def test_skill_md_classifies_tables(self) -> None:
        """SKILL.md must define table classification statuses."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for status in [
            "HEALTHY",
            "STALE",
            "EMPTY",
            "MISSING",
            "ORPHAN",
            "NO_TIMESTAMP",
        ]:
            assert status in content, f"Missing classification: {status}"

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml must exist."""
        assert (SKILL_DIR / "topics.yaml").is_file()

    def test_topics_yaml_has_required_topics(self) -> None:
        """topics.yaml must declare cmd and evt topics."""
        content = yaml.safe_load((SKILL_DIR / "topics.yaml").read_text())
        topics = content.get("topics", [])
        assert "onex.cmd.omniclaude.database-sweep.v1" in topics
        assert "onex.evt.omniclaude.database-sweep-completed.v1" in topics
        assert "onex.evt.omniclaude.database-sweep-failed.v1" in topics

    def test_skill_md_has_dry_run_contract(self) -> None:
        """SKILL.md must specify --dry-run produces zero side effects."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--dry-run" in content

    def test_skill_md_references_intelligence_schema(self) -> None:
        """SKILL.md must reference intelligence-schema.ts as table source."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "intelligence-schema" in content

    def test_skill_md_has_migration_tracking(self) -> None:
        """SKILL.md must include migration tracking phase."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "Migration Tracking" in content
        assert "alembic_version" in content
        assert (
            "schema fingerprint" in content.lower()
            or "schema_fingerprint" in content.lower()
        )

    def test_skill_md_covers_all_databases(self) -> None:
        """SKILL.md must cover all ONEX databases including correct names."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for db in [
            "omnibase_infra",
            "omniintelligence",
            "omnimemory_db",
            "omnidash_analytics",
        ]:
            assert db in content, f"Missing database: {db}"

    def test_skill_md_classifies_migration_state(self) -> None:
        """SKILL.md must define migration classification statuses."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        for status in ["CURRENT", "PENDING", "AHEAD", "FAILED", "NO_TABLE"]:
            assert status in content, f"Missing migration classification: {status}"

    def test_skill_md_handles_drizzle_migrations(self) -> None:
        """SKILL.md must handle Drizzle migrations for omnidash."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "drizzle" in content.lower()
        assert "omnidash/migrations/" in content
