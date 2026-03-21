# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for FrictionObserverNode classification rules loaded from contract.yaml."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SHARED_PATH = str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from friction_classifier import ClassificationRule, load_rules_from_yaml, match_signal
from friction_recorder import FrictionSeverity
from friction_signal import FrictionSignal

_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "src"
    / "omniclaude"
    / "nodes"
    / "node_friction_observer_compute"
    / "contract.yaml"
)


@pytest.mark.unit
class TestFrictionObserverContract:
    """Verify classification rules from the real contract.yaml."""

    @pytest.fixture
    def rules(self):
        return load_rules_from_yaml(_CONTRACT_PATH)

    def test_contract_loads(self, rules):
        assert len(rules) >= 10  # 9 specific rules + 1 wildcard

    def test_skill_failed(self, rules):
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="skill.completed",
            payload={"status": "failed", "skill_name": "deploy", "error": "CI red"},
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "tooling/skill-failed"
        assert result.severity == FrictionSeverity.MEDIUM
        assert "deploy" in result.description
        assert "CI red" in result.description

    def test_skill_blocked(self, rules):
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="skill.completed",
            payload={
                "status": "blocked",
                "skill_name": "merge",
                "blocked_reason": "merge conflict",
            },
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "tooling/skill-blocked"
        assert result.severity == FrictionSeverity.HIGH

    def test_skill_error(self, rules):
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="skill.completed",
            payload={"status": "error", "skill_name": "release", "error": "timeout"},
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "tooling/skill-error"
        assert result.severity == FrictionSeverity.HIGH

    def test_circuit_breaker(self, rules):
        sig = FrictionSignal(
            source="kafka_consumer",
            event_type="circuit.breaker.tripped",
            payload={"failure_count": "5", "threshold": "3"},
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "kafka/circuit-breaker"
        assert result.severity == FrictionSeverity.HIGH

    def test_budget_cap_hit(self, rules):
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="budget.cap.hit",
            payload={"tokens_used": "50000", "tokens_budget": "40000"},
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "tooling/budget-exceeded"
        assert result.severity == FrictionSeverity.MEDIUM

    def test_session_failed(self, rules):
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="session.outcome",
            payload={"outcome": "failed", "reason": "unhandled error"},
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "tooling/session-failed"

    def test_session_success_falls_to_wildcard(self, rules):
        """Successful session outcome should NOT match the failed rule."""
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="session.outcome",
            payload={"outcome": "success"},
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "unknown/unclassified"  # wildcard

    def test_unknown_event_type_wildcard(self, rules):
        sig = FrictionSignal(
            source="cursor",
            event_type="cursor.extension.crash",
            payload={},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "unknown/unclassified"
        assert "cursor.extension.crash" in result.description

    def test_qualifier_miss_falls_to_wildcard(self, rules):
        """Event type matches skill.completed but payload lacks 'status' field.
        Should miss all qualified rules and fall through to wildcard."""
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="skill.completed",
            payload={"skill_name": "deploy"},  # no 'status' key
            timestamp=datetime.now(UTC),
            session_id="s1",
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.surface == "unknown/unclassified"
        assert result.rule_id == "wildcard"

    def test_disabled_rule_skipped(self):
        """Disabled rules should be skipped even if they would match."""
        rules = [
            ClassificationRule(
                rule_id="disabled_one",
                event_pattern="test.event",
                surface="tooling/test",
                severity="high",
                description_template="should not match",
                enabled=False,
            ),
            ClassificationRule(
                rule_id="fallback",
                event_pattern="*",
                surface="unknown/unclassified",
                severity="low",
                description_template="fallback",
            ),
        ]
        sig = FrictionSignal(
            source="test",
            event_type="test.event",
            payload={},
            timestamp=datetime.now(UTC),
        )
        result = match_signal(sig, rules)
        assert result is not None
        assert result.rule_id == "fallback"
