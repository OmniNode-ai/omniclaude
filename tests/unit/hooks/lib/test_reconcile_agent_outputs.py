"""Tests for reconcile_agent_outputs module (OMN-1855).

All tests run WITHOUT omnibase_core installed -- they exercise the fallback
classifier.  The module must be importable standalone with no env vars, no hook
initialisation, and no infrastructure dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure plugin lib is on sys.path (conftest.py also does this, but make the
# test file self-sufficient for direct invocation).
_plugin_lib = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _plugin_lib not in sys.path:
    sys.path.insert(0, _plugin_lib)

import pytest
from reconcile_agent_outputs import (
    AMBIGUOUS,
    CONFLICTING,
    IDENTICAL,
    LOW_CONFLICT,
    OPPOSITE,
    ORTHOGONAL,
    FieldDecision,
    ReconciliationResult,
    flatten_to_paths,
    reconcile_outputs,
    unflatten_paths,
)

# =============================================================================
# 1. Import isolation
# =============================================================================


class TestImportIsolation:
    """Verify the module can be imported without side effects."""

    def test_import_isolation(self) -> None:
        """Import reconcile_agent_outputs with no env vars, no hook init."""
        # If we got here the import already succeeded.  Verify key exports.
        assert FieldDecision is not None
        assert ReconciliationResult is not None
        assert flatten_to_paths is not None
        assert unflatten_paths is not None
        assert reconcile_outputs is not None


# =============================================================================
# 2-4. Flatten / unflatten helpers
# =============================================================================


class TestFlattenToPathsHelper:
    """Tests for flatten_to_paths."""

    def test_flatten_to_paths(self) -> None:
        nested = {"db": {"pool": {"max_size": 10, "min_size": 2}}, "port": 5432}
        result = flatten_to_paths(nested)
        assert result == {
            "db.pool.max_size": 10,
            "db.pool.min_size": 2,
            "port": 5432,
        }

    def test_flatten_empty_dict(self) -> None:
        assert flatten_to_paths({}) == {}

    def test_flatten_already_flat(self) -> None:
        flat = {"a": 1, "b": 2}
        assert flatten_to_paths(flat) == {"a": 1, "b": 2}


class TestUnflattenPathsHelper:
    """Tests for unflatten_paths."""

    def test_unflatten_paths(self) -> None:
        flat = {"db.pool.max_size": 10, "db.pool.min_size": 2, "port": 5432}
        result = unflatten_paths(flat)
        assert result == {
            "db": {"pool": {"max_size": 10, "min_size": 2}},
            "port": 5432,
        }

    def test_unflatten_empty_dict(self) -> None:
        assert unflatten_paths({}) == {}


class TestFlattenUnflattenRoundtrip:
    """Verify flatten then unflatten equals original."""

    def test_flatten_unflatten_roundtrip(self) -> None:
        original = {
            "db": {"host": "localhost", "port": 5432},
            "cache": {"ttl": 300},
            "log_level": "INFO",
        }
        assert unflatten_paths(flatten_to_paths(original)) == original

    def test_roundtrip_deeply_nested(self) -> None:
        original = {"a": {"b": {"c": {"d": 42}}}}
        assert unflatten_paths(flatten_to_paths(original)) == original


# =============================================================================
# 5-11. Conflict classification tests
# =============================================================================


class TestIdenticalValues:
    """Two agents produce the same value -> IDENTICAL, auto-resolved."""

    def test_identical_values(self) -> None:
        base = {"db": {"host": "localhost"}}
        outputs = {
            "agent-alpha": {"db": {"host": "prod-db.internal"}},
            "agent-beta": {"db": {"host": "prod-db.internal"}},
        }
        result = reconcile_outputs(base, outputs)

        dec = result.field_decisions["db.host"]
        assert dec.conflict_type == IDENTICAL
        assert dec.chosen_value == "prod-db.internal"
        assert dec.needs_approval is False
        assert dec.needs_review is False
        assert "db.host" in result.merged_values
        assert result.merged_values["db.host"] == "prod-db.internal"
        assert "db.host" in result.auto_resolved_fields
        assert result.requires_approval is False


class TestOrthogonalValues:
    """Two agents modify non-overlapping keys -> ORTHOGONAL, auto-resolved."""

    def test_orthogonal_disjoint_leaf_fields(self) -> None:
        """When agents touch entirely different leaf fields, each field is a
        single-agent field and auto-included."""
        base = {"config": {}}
        outputs = {
            "agent-alpha": {"config": {"timeout": 30}},
            "agent-beta": {"config": {"retries": 3}},
        }
        result = reconcile_outputs(base, outputs)

        # Each agent touches a unique leaf, so both are single-agent fields
        # that auto-include.  Verify they are in merged_values.
        assert "config.timeout" in result.merged_values
        assert result.merged_values["config.timeout"] == 30
        assert "config.retries" in result.merged_values
        assert result.merged_values["config.retries"] == 3
        assert result.requires_approval is False

    def test_orthogonal_fallback_classifier_directly(self) -> None:
        """Verify the fallback classifier returns ORTHOGONAL for dicts with
        non-overlapping keys.

        Note: reconcile_outputs flattens all nested dicts to leaf paths, so
        two agents producing dict values on the same *leaf* field is rare in
        practice.  This test exercises the _fallback_classify function
        directly to verify the ORTHOGONAL code path.
        """
        from reconcile_agent_outputs import _fallback_classify

        result = _fallback_classify(
            base_value={},
            agent_values={
                "agent-alpha": {"timeout": 30},
                "agent-beta": {"retries": 3},
            },
        )
        assert result == ORTHOGONAL


class TestLowConflictValues:
    """Fallback classifier does not produce LOW_CONFLICT by itself (it only
    returns IDENTICAL / OPPOSITE / ORTHOGONAL / AMBIGUOUS).  We verify the
    routing logic handles LOW_CONFLICT correctly by testing with a mock."""

    def test_low_conflict_data_model(self) -> None:
        """FieldDecision accepts LOW_CONFLICT as a valid conflict_type."""
        dec = FieldDecision(
            field="retry.delay",
            conflict_type=LOW_CONFLICT,
            sources=["agent-a", "agent-b"],
            chosen_value=100,
            rationale="Minor difference.",
            needs_approval=False,
            needs_review=False,
        )
        assert dec.conflict_type == LOW_CONFLICT
        assert dec.needs_approval is False

    def test_low_conflict_routing_via_mock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mock _classify to return LOW_CONFLICT, verify reconcile_outputs
        auto-resolves with lexically-first agent and flags for review."""
        import reconcile_agent_outputs as mod

        monkeypatch.setattr(
            mod, "_classify", lambda _base, _vals, classifier=None: LOW_CONFLICT
        )

        base = {"retry": {"delay": 100}}
        outputs = {
            "agent-beta": {"retry": {"delay": 150}},
            "agent-alpha": {"retry": {"delay": 120}},
        }
        result = reconcile_outputs(base, outputs)

        dec = result.field_decisions["retry.delay"]
        assert dec.conflict_type == LOW_CONFLICT
        assert dec.needs_approval is False
        assert dec.needs_review is False
        # Lexically-first agent is "agent-alpha"
        assert dec.chosen_value == 120
        assert result.merged_values["retry.delay"] == 120
        assert "retry.delay" in result.optional_review_fields
        assert "retry.delay" in result.auto_resolved_fields
        assert result.requires_approval is False


class TestConflictingValues:
    """Fallback classifier does not produce CONFLICTING directly.  We verify
    the FieldDecision model and routing contract for CONFLICTING."""

    def test_conflicting_data_model(self) -> None:
        """FieldDecision accepts CONFLICTING as a valid conflict_type."""
        dec = FieldDecision(
            field="auth.strategy",
            conflict_type=CONFLICTING,
            sources=["agent-a", "agent-b"],
            chosen_value="jwt",
            rationale="Significant difference. Review recommended.",
            needs_approval=False,
            needs_review=True,
        )
        assert dec.conflict_type == CONFLICTING
        assert dec.needs_review is True
        assert dec.needs_approval is False

    def test_conflicting_routing_via_mock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mock _classify to return CONFLICTING, verify reconcile_outputs
        auto-resolves with lexically-first agent and sets needs_review."""
        import reconcile_agent_outputs as mod

        monkeypatch.setattr(
            mod, "_classify", lambda _base, _vals, classifier=None: CONFLICTING
        )

        base = {"auth": {"strategy": "basic"}}
        outputs = {
            "agent-beta": {"auth": {"strategy": "oauth2"}},
            "agent-alpha": {"auth": {"strategy": "jwt"}},
        }
        result = reconcile_outputs(base, outputs)

        dec = result.field_decisions["auth.strategy"]
        assert dec.conflict_type == CONFLICTING
        assert dec.needs_review is True
        assert dec.needs_approval is False
        # Lexically-first agent is "agent-alpha"
        assert dec.chosen_value == "jwt"
        assert result.merged_values["auth.strategy"] == "jwt"
        assert "auth.strategy" in result.optional_review_fields
        assert "auth.strategy" in result.auto_resolved_fields
        assert result.requires_approval is False


class TestOppositeValues:
    """Two agents produce True/False -> OPPOSITE, needs_approval, no merged value."""

    def test_opposite_values(self) -> None:
        base = {"feature": {"enabled": False}}
        outputs = {
            "agent-alpha": {"feature": {"enabled": True}},
            "agent-beta": {"feature": {"enabled": False}},
        }
        result = reconcile_outputs(base, outputs)

        dec = result.field_decisions["feature.enabled"]
        assert dec.conflict_type == OPPOSITE
        assert dec.needs_approval is True
        assert dec.chosen_value is None
        assert "feature.enabled" not in result.merged_values
        assert "feature.enabled" in result.approval_fields
        assert result.requires_approval is True


class TestAmbiguousValues:
    """Two agents produce very different strings -> AMBIGUOUS."""

    def test_ambiguous_values(self) -> None:
        base = {"strategy": "default"}
        outputs = {
            "agent-alpha": {"strategy": "expand_infrastructure"},
            "agent-beta": {"strategy": "reduce_costs"},
        }
        result = reconcile_outputs(base, outputs)

        dec = result.field_decisions["strategy"]
        assert dec.conflict_type == AMBIGUOUS
        assert dec.needs_approval is True
        assert dec.chosen_value is None
        assert "strategy" not in result.merged_values
        assert "strategy" in result.approval_fields
        assert result.requires_approval is True


class TestGI3Enforcement:
    """GI-3: OPPOSITE and AMBIGUOUS must have chosen_value=None, must NOT
    appear in merged_values, and requires_approval must be True."""

    def test_gi3_opposite(self) -> None:
        base = {"flag": True}
        outputs = {
            "agent-x": {"flag": True},
            "agent-y": {"flag": False},
        }
        result = reconcile_outputs(base, outputs)
        dec = result.field_decisions["flag"]

        assert dec.conflict_type == OPPOSITE
        assert dec.chosen_value is None, "GI-3: chosen_value must be None for OPPOSITE"
        assert "flag" not in result.merged_values, (
            "GI-3: OPPOSITE field must not be in merged_values"
        )
        assert result.requires_approval is True, (
            "GI-3: requires_approval must be True when OPPOSITE present"
        )

    def test_gi3_ambiguous(self) -> None:
        base = {"mode": "auto"}
        outputs = {
            "agent-x": {"mode": "manual"},
            "agent-y": {"mode": "scheduled"},
        }
        result = reconcile_outputs(base, outputs)
        dec = result.field_decisions["mode"]

        assert dec.conflict_type == AMBIGUOUS
        assert dec.chosen_value is None, "GI-3: chosen_value must be None for AMBIGUOUS"
        assert "mode" not in result.merged_values, (
            "GI-3: AMBIGUOUS field must not be in merged_values"
        )
        assert result.requires_approval is True, (
            "GI-3: requires_approval must be True when AMBIGUOUS present"
        )

    def test_gi3_rationale_contains_candidate_values(self) -> None:
        """GI-3 rationale must include all candidate values and which agent
        produced them."""
        base = {"flag": True}
        outputs = {
            "agent-x": {"flag": True},
            "agent-y": {"flag": False},
        }
        result = reconcile_outputs(base, outputs)
        dec = result.field_decisions["flag"]

        assert "agent-x" in dec.rationale
        assert "agent-y" in dec.rationale
        assert "True" in dec.rationale
        assert "False" in dec.rationale


# =============================================================================
# 12. Single-agent field
# =============================================================================


class TestSingleAgentField:
    """Field touched by only 1 agent is auto-included in merged_values."""

    def test_single_agent_field(self) -> None:
        base = {"x": 1}
        outputs = {
            "agent-a": {"x": 1, "y": 2},
            "agent-b": {"x": 1},
        }
        result = reconcile_outputs(base, outputs)

        # "y" only touched by agent-a
        assert "y" in result.merged_values
        assert result.merged_values["y"] == 2
        dec = result.field_decisions["y"]
        assert dec.sources == ["agent-a"]
        assert dec.needs_approval is False


# =============================================================================
# 13. Summary format
# =============================================================================


class TestSummaryFormat:
    """Verify summary contains 'Status:' line and field lists."""

    def test_summary_safe_to_apply(self) -> None:
        base = {"a": 1}
        outputs = {
            "agent-1": {"a": 1},
            "agent-2": {"a": 1},
        }
        result = reconcile_outputs(base, outputs)
        assert "Status:" in result.summary
        assert "SAFE TO APPLY" in result.summary

    def test_summary_requires_approval(self) -> None:
        base = {"flag": True}
        outputs = {
            "agent-1": {"flag": True},
            "agent-2": {"flag": False},
        }
        result = reconcile_outputs(base, outputs)
        assert "Status:" in result.summary
        assert "REQUIRES HUMAN APPROVAL" in result.summary

    def test_summary_mentions_auto_resolved_fields(self) -> None:
        base = {"a": 1, "b": 2}
        outputs = {
            "agent-1": {"a": 10, "b": 2},
            "agent-2": {"a": 10, "b": 2},
        }
        result = reconcile_outputs(base, outputs)
        assert "Auto-resolved" in result.summary


# =============================================================================
# 14. Logger callback
# =============================================================================


class TestLoggerCallback:
    """Pass a logger, verify it receives structured dicts."""

    def test_logger_callback(self) -> None:
        log_entries: list[dict] = []

        def logger(entry: dict) -> None:
            log_entries.append(entry)

        base = {"x": 1}
        outputs = {
            "agent-a": {"x": 1, "y": 2},
            "agent-b": {"x": 1, "z": 3},
        }
        reconcile_outputs(base, outputs, logger=logger)

        assert len(log_entries) > 0
        # Each entry should have at least "event" and "field"
        for entry in log_entries:
            assert "event" in entry
            assert "field" in entry
            assert "conflict_type" in entry

    def test_logger_receives_correct_event_names(self) -> None:
        log_entries: list[dict] = []
        base = {"a": 1}
        outputs = {
            "agent-1": {"a": 1},
            "agent-2": {"a": 1},
        }
        reconcile_outputs(base, outputs, logger=lambda e: log_entries.append(e))

        events = {e["event"] for e in log_entries}
        assert "field_classified" in events


# =============================================================================
# 15. Requires two agents
# =============================================================================


class TestRequiresTwoAgents:
    """Error if fewer than 2 agent outputs provided."""

    def test_requires_two_agents_zero(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            reconcile_outputs({}, {})

    def test_requires_two_agents_one(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            reconcile_outputs({}, {"agent-only": {"x": 1}})

    def test_two_agents_succeeds(self) -> None:
        result = reconcile_outputs(
            {},
            {"agent-a": {"x": 1}, "agent-b": {"y": 2}},
        )
        assert isinstance(result, ReconciliationResult)


# =============================================================================
# Model immutability
# =============================================================================


class TestModelImmutability:
    """Verify frozen models reject mutation."""

    def test_field_decision_is_frozen(self) -> None:
        dec = FieldDecision(
            field="x",
            conflict_type=IDENTICAL,
            sources=["a"],
            chosen_value=1,
            rationale="test",
            needs_approval=False,
            needs_review=False,
        )
        with pytest.raises(Exception):
            dec.field = "y"  # type: ignore[misc]

    def test_reconciliation_result_is_frozen(self) -> None:
        result = reconcile_outputs(
            {"a": 1},
            {"agent-1": {"a": 1}, "agent-2": {"a": 1}},
        )
        with pytest.raises(Exception):
            result.requires_approval = True  # type: ignore[misc]
