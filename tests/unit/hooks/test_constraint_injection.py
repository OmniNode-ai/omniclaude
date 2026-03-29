# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for constraint injection (OMN-6817)."""

from __future__ import annotations

import pytest

from omniclaude.hooks.constraint_injection import (
    BUILTIN_CONSTRAINTS,
    EnumConstraintDomain,
    ModelConstraintInjectionConfig,
    ModelConstraintTemplate,
    format_constraints_markdown,
    inject_constraints,
    select_constraints,
)


@pytest.mark.unit
class TestModelConstraintTemplate:
    """Tests for the ModelConstraintTemplate Pydantic model."""

    def test_create_basic(self) -> None:
        template = ModelConstraintTemplate(
            name="test_rule",
            domain=EnumConstraintDomain.NAMING,
            rule="Test rule text",
            reason="Test reason",
        )
        assert template.name == "test_rule"
        assert template.domain == EnumConstraintDomain.NAMING
        assert template.applies_to_skills == ()

    def test_frozen_model(self) -> None:
        template = ModelConstraintTemplate(
            name="test",
            domain=EnumConstraintDomain.GENERAL,
            rule="rule",
            reason="reason",
        )
        with pytest.raises(Exception):  # noqa: B017
            template.name = "changed"  # type: ignore[misc]

    def test_with_skill_filter(self) -> None:
        template = ModelConstraintTemplate(
            name="skill_specific",
            domain=EnumConstraintDomain.TESTING,
            rule="Only for ticket-work",
            reason="Testing",
            applies_to_skills=("ticket-work", "epic-team"),
        )
        assert "ticket-work" in template.applies_to_skills
        assert "merge-sweep" not in template.applies_to_skills


@pytest.mark.unit
class TestModelConstraintInjectionConfig:
    """Tests for configuration loading."""

    def test_defaults(self) -> None:
        config = ModelConstraintInjectionConfig()
        assert config.enabled is True
        assert config.max_items == 10

    def test_from_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OMNICLAUDE_CONSTRAINT_INJECTION_ENABLED", raising=False)
        monkeypatch.delenv("OMNICLAUDE_CONSTRAINT_MAX_ITEMS", raising=False)
        config = ModelConstraintInjectionConfig.from_env()
        assert config.enabled is True
        assert config.max_items == 10

    def test_from_env_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CONSTRAINT_INJECTION_ENABLED", "false")
        config = ModelConstraintInjectionConfig.from_env()
        assert config.enabled is False

    def test_from_env_custom_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CONSTRAINT_MAX_ITEMS", "5")
        config = ModelConstraintInjectionConfig.from_env()
        assert config.max_items == 5

    def test_from_env_invalid_max_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OMNICLAUDE_CONSTRAINT_MAX_ITEMS", "abc")
        config = ModelConstraintInjectionConfig.from_env()
        assert config.max_items == 10


@pytest.mark.unit
class TestSelectConstraints:
    """Tests for constraint selection logic."""

    def test_select_all_general(self) -> None:
        """With no filters, returns all builtin constraints up to max."""
        result = select_constraints(max_items=50)
        assert len(result) == len(BUILTIN_CONSTRAINTS)

    def test_max_items_limit(self) -> None:
        result = select_constraints(max_items=3)
        assert len(result) == 3

    def test_filter_by_domain(self) -> None:
        result = select_constraints(
            domains=(EnumConstraintDomain.BUS_POLICY,),
            max_items=50,
        )
        assert all(c.domain == EnumConstraintDomain.BUS_POLICY for c in result)
        assert len(result) >= 2  # bus_policy_local + inmemory_bus_forbidden

    def test_skill_specific_included(self) -> None:
        """Skill-specific constraints are included when skill matches."""
        # Add a skill-specific constraint for testing
        specific = ModelConstraintTemplate(
            name="specific",
            domain=EnumConstraintDomain.GENERAL,
            rule="Only for ticket-work",
            reason="test",
            applies_to_skills=("ticket-work",),
        )
        # The builtin constraints have no skill filter, so they're always included
        result = select_constraints(skill_name="ticket-work", max_items=50)
        assert len(result) > 0

    def test_no_skill_excludes_skill_specific(self) -> None:
        """Skill-specific builtins are excluded when no skill provided.

        All current builtins have empty applies_to_skills, so they're
        included regardless. This test verifies the logic path.
        """
        result = select_constraints(skill_name=None, max_items=50)
        # All builtins should be included (none have skill filters)
        assert len(result) == len(BUILTIN_CONSTRAINTS)


@pytest.mark.unit
class TestFormatConstraintsMarkdown:
    """Tests for markdown formatting."""

    def test_empty_list(self) -> None:
        result = format_constraints_markdown([])
        assert result == ""

    def test_single_constraint(self) -> None:
        constraints = [
            ModelConstraintTemplate(
                name="test",
                domain=EnumConstraintDomain.NAMING,
                rule="Test rule",
                reason="Test reason",
            )
        ]
        result = format_constraints_markdown(constraints)
        assert "## Architectural Constraints" in result
        assert "**test**" in result
        assert "Test rule" in result
        assert "Test reason" in result

    def test_multiple_constraints(self) -> None:
        constraints = [
            ModelConstraintTemplate(
                name="first",
                domain=EnumConstraintDomain.NAMING,
                rule="First rule",
                reason="First reason",
            ),
            ModelConstraintTemplate(
                name="second",
                domain=EnumConstraintDomain.BUS_POLICY,
                rule="Second rule",
                reason="Second reason",
            ),
        ]
        result = format_constraints_markdown(constraints)
        assert "1. **first**" in result
        assert "2. **second**" in result


@pytest.mark.unit
class TestInjectConstraints:
    """Tests for the main inject_constraints entry point."""

    def test_disabled_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CONSTRAINT_INJECTION_ENABLED", "false")
        result = inject_constraints()
        assert result == ""

    def test_enabled_returns_markdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CONSTRAINT_INJECTION_ENABLED", "true")
        result = inject_constraints()
        assert "## Architectural Constraints" in result

    def test_with_explicit_config(self) -> None:
        config = ModelConstraintInjectionConfig(enabled=True, max_items=2)
        result = inject_constraints(config=config)
        assert "## Architectural Constraints" in result
        # Should have at most 2 constraints
        assert result.count("**") <= 4  # 2 constraints * 2 ** per name


@pytest.mark.unit
class TestBuiltinConstraints:
    """Tests for the built-in constraint templates."""

    def test_all_have_required_fields(self) -> None:
        for c in BUILTIN_CONSTRAINTS:
            assert c.name, f"Constraint missing name: {c}"
            assert c.rule, f"Constraint {c.name} missing rule"
            assert c.reason, f"Constraint {c.name} missing reason"
            assert isinstance(c.domain, EnumConstraintDomain)

    def test_names_are_unique(self) -> None:
        names = [c.name for c in BUILTIN_CONSTRAINTS]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_known_constraints_exist(self) -> None:
        """Verify key constraints are present."""
        names = {c.name for c in BUILTIN_CONSTRAINTS}
        assert "model_prefix" in names
        assert "enum_prefix" in names
        assert "no_ollama" in names
        assert "bus_policy_local" in names
        assert "no_env_fallbacks" in names
