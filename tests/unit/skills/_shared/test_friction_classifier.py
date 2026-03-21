# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SHARED_PATH = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from friction_classifier import (
    ClassificationRule,
    load_rules_from_yaml,
    match_signal,
)
from friction_recorder import FrictionSeverity
from friction_signal import FrictionSignal


@pytest.mark.unit
class TestClassificationRule:
    def test_exact_event_type_match(self):
        rules = [
            ClassificationRule(
                rule_id="cb_tripped",
                event_pattern="circuit.breaker.tripped",
                surface="kafka/circuit-breaker",
                severity="high",
                description_template="CB tripped",
            ),
        ]
        signal = FrictionSignal(
            source="test",
            event_type="circuit.breaker.tripped",
            payload={},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(signal, rules)
        assert result is not None
        assert result.surface == "kafka/circuit-breaker"
        assert result.severity == FrictionSeverity.HIGH

    def test_field_qualifier_match(self):
        rules = [
            ClassificationRule(
                rule_id="skill_failed",
                event_pattern="skill.completed:status=failed",
                surface="tooling/skill-failed",
                severity="medium",
                description_template="Skill {payload.skill_name} failed",
            ),
        ]
        signal = FrictionSignal(
            source="test",
            event_type="skill.completed",
            payload={"status": "failed", "skill_name": "deploy"},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(signal, rules)
        assert result is not None
        assert result.surface == "tooling/skill-failed"
        assert result.severity == FrictionSeverity.MEDIUM
        assert result.description == "Skill deploy failed"

    def test_field_qualifier_no_match(self):
        """skill.completed with status=success should NOT match status=failed rule."""
        rules = [
            ClassificationRule(
                rule_id="skill_failed_2",
                event_pattern="skill.completed:status=failed",
                surface="tooling/skill-failed",
                severity="medium",
                description_template="failed",
            ),
        ]
        signal = FrictionSignal(
            source="test",
            event_type="skill.completed",
            payload={"status": "success"},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(signal, rules)
        assert result is None

    def test_wildcard_fallback(self):
        rules = [
            ClassificationRule(
                rule_id="specific",
                event_pattern="specific.event",
                surface="tooling/specific",
                severity="high",
                description_template="specific",
            ),
            ClassificationRule(
                rule_id="wildcard",
                event_pattern="*",
                surface="unknown/unclassified",
                severity="low",
                description_template="Unclassified: {event_type}",
            ),
        ]
        signal = FrictionSignal(
            source="test",
            event_type="something.else",
            payload={},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(signal, rules)
        assert result is not None
        assert result.surface == "unknown/unclassified"
        assert result.description == "Unclassified: something.else"

    def test_first_match_wins(self):
        rules = [
            ClassificationRule(
                rule_id="r1",
                event_pattern="skill.completed:status=failed",
                surface="tooling/skill-failed",
                severity="medium",
                description_template="first",
            ),
            ClassificationRule(
                rule_id="r2",
                event_pattern="skill.completed:status=failed",
                surface="tooling/other",
                severity="high",
                description_template="second",
            ),
        ]
        signal = FrictionSignal(
            source="test",
            event_type="skill.completed",
            payload={"status": "failed"},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(signal, rules)
        assert result is not None
        assert result.description == "first"

    def test_template_missing_key_resolves_empty(self):
        rules = [
            ClassificationRule(
                rule_id="fallback",
                event_pattern="*",
                surface="unknown/unclassified",
                severity="low",
                description_template="Skill {payload.nonexistent} failed",
            ),
        ]
        signal = FrictionSignal(
            source="test",
            event_type="test",
            payload={},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(signal, rules)
        assert result is not None
        assert result.description == "Skill  failed"

    def test_no_rules_returns_none(self):
        signal = FrictionSignal(
            source="test",
            event_type="test",
            payload={},
            timestamp=datetime.now(UTC),
        )
        assert match_signal(signal, []) is None


@pytest.mark.unit
class TestLoadRulesFromYaml:
    def test_load_from_contract(self, tmp_path: Path):
        contract = tmp_path / "contract.yaml"
        contract.write_text("""
name: test_node
classification_rules:
  - rule_id: skill_failed
    event_pattern: "skill.completed:status=failed"
    surface: "tooling/skill-failed"
    severity: "medium"
    description_template: "Skill failed"
  - rule_id: wildcard
    event_pattern: "*"
    surface: "unknown/unclassified"
    severity: "low"
    description_template: "Unknown"
""")
        rules = load_rules_from_yaml(contract)
        assert len(rules) == 2
        assert rules[0].rule_id == "skill_failed"
        assert rules[0].event_pattern == "skill.completed:status=failed"
        assert rules[1].rule_id == "wildcard"

    def test_missing_classification_rules_returns_empty(self, tmp_path: Path):
        contract = tmp_path / "contract.yaml"
        contract.write_text("name: test_node\n")
        rules = load_rules_from_yaml(contract)
        assert rules == []

    def test_missing_required_field_raises(self, tmp_path: Path):
        contract = tmp_path / "contract.yaml"
        contract.write_text("""
name: test_node
classification_rules:
  - event_pattern: "foo"
    surface: "tooling/foo"
    severity: "low"
""")
        with pytest.raises(ValueError, match="missing required fields"):
            load_rules_from_yaml(contract)

    def test_invalid_severity_raises(self, tmp_path: Path):
        contract = tmp_path / "contract.yaml"
        contract.write_text("""
name: test_node
classification_rules:
  - rule_id: bad
    event_pattern: "foo"
    surface: "tooling/foo"
    severity: "critical"
    description_template: "bad"
""")
        with pytest.raises(ValueError, match="invalid severity"):
            load_rules_from_yaml(contract)

    def test_duplicate_rule_id_raises(self, tmp_path: Path):
        contract = tmp_path / "contract.yaml"
        contract.write_text("""
name: test_node
classification_rules:
  - rule_id: dupe
    event_pattern: "foo"
    surface: "tooling/foo"
    severity: "low"
    description_template: "a"
  - rule_id: dupe
    event_pattern: "bar"
    surface: "tooling/bar"
    severity: "low"
    description_template: "b"
""")
        with pytest.raises(ValueError, match="Duplicate rule_id"):
            load_rules_from_yaml(contract)
