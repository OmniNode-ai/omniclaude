# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for limit_threshold_monitor — checkpoint decision logic."""

from __future__ import annotations

import pytest

from omniclaude.hooks.limit_threshold_monitor import (
    ModelCheckpointDecision,
    ModelLimitThresholds,
    evaluate_limits,
)
from omniclaude.hooks.model_session_checkpoint import EnumCheckpointReason
from omniclaude.hooks.statusline_parser import ModelLimitStatus


@pytest.mark.unit
class TestEvaluateLimits:
    """Tests for the evaluate_limits decision function."""

    def test_context_critical_triggers_checkpoint(self) -> None:
        status = ModelLimitStatus(context_percent=92)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.reason == EnumCheckpointReason.CONTEXT_LIMIT
        assert decision.urgency == "critical"

    def test_context_warn_triggers_checkpoint(self) -> None:
        status = ModelLimitStatus(context_percent=82)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.reason == EnumCheckpointReason.CONTEXT_LIMIT
        assert decision.urgency == "warn"

    def test_session_critical_triggers_checkpoint(self) -> None:
        status = ModelLimitStatus(session_percent=96)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.reason == EnumCheckpointReason.SESSION_LIMIT
        assert decision.urgency == "critical"

    def test_session_warn_triggers_checkpoint(self) -> None:
        status = ModelLimitStatus(session_percent=87)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.reason == EnumCheckpointReason.SESSION_LIMIT
        assert decision.urgency == "warn"

    def test_weekly_critical_triggers_checkpoint(self) -> None:
        status = ModelLimitStatus(weekly_percent=92)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.reason == EnumCheckpointReason.WEEKLY_LIMIT
        assert decision.urgency == "critical"

    def test_weekly_warn_triggers_checkpoint(self) -> None:
        status = ModelLimitStatus(weekly_percent=82)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.reason == EnumCheckpointReason.WEEKLY_LIMIT
        assert decision.urgency == "warn"

    def test_below_all_thresholds_no_checkpoint(self) -> None:
        status = ModelLimitStatus(
            context_percent=50,
            session_percent=30,
            weekly_percent=10,
        )
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is False
        assert decision.reason is None
        assert decision.urgency == "none"

    def test_all_none_no_checkpoint(self) -> None:
        status = ModelLimitStatus()
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is False

    def test_context_takes_priority_over_session(self) -> None:
        """When both context and session are critical, context wins."""
        status = ModelLimitStatus(context_percent=92, session_percent=96)
        decision = evaluate_limits(status)
        assert decision.reason == EnumCheckpointReason.CONTEXT_LIMIT

    def test_session_takes_priority_over_weekly(self) -> None:
        """When both session and weekly are critical, session wins."""
        status = ModelLimitStatus(session_percent=96, weekly_percent=92)
        decision = evaluate_limits(status)
        assert decision.reason == EnumCheckpointReason.SESSION_LIMIT

    def test_custom_thresholds(self) -> None:
        thresholds = ModelLimitThresholds(context_critical=70, context_warn=60)
        status = ModelLimitStatus(context_percent=75)
        decision = evaluate_limits(status, thresholds)
        assert decision.should_checkpoint is True
        assert decision.urgency == "critical"

    def test_custom_thresholds_below(self) -> None:
        thresholds = ModelLimitThresholds(context_critical=95, context_warn=90)
        status = ModelLimitStatus(context_percent=85)
        decision = evaluate_limits(status, thresholds)
        assert decision.should_checkpoint is False

    def test_exact_threshold_triggers(self) -> None:
        """At exactly the threshold value, should trigger."""
        status = ModelLimitStatus(context_percent=90)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.urgency == "critical"

    def test_one_below_threshold_does_not_trigger(self) -> None:
        """One below critical should be warn, not critical."""
        status = ModelLimitStatus(context_percent=89)
        decision = evaluate_limits(status)
        assert decision.should_checkpoint is True
        assert decision.urgency == "warn"  # 89 >= 80 (warn) but < 90 (critical)

    def test_decision_message_contains_percentage(self) -> None:
        status = ModelLimitStatus(context_percent=92)
        decision = evaluate_limits(status)
        assert "92%" in decision.message


@pytest.mark.unit
class TestModelLimitThresholds:
    """Tests for threshold configuration model."""

    def test_defaults(self) -> None:
        t = ModelLimitThresholds()
        assert t.context_warn == 80
        assert t.context_critical == 90
        assert t.session_warn == 85
        assert t.session_critical == 95
        assert t.weekly_warn == 80
        assert t.weekly_critical == 90

    def test_frozen(self) -> None:
        t = ModelLimitThresholds()
        with pytest.raises(Exception):
            t.context_warn = 50  # type: ignore[misc]


@pytest.mark.unit
class TestModelCheckpointDecision:
    """Tests for checkpoint decision model."""

    def test_defaults(self) -> None:
        d = ModelCheckpointDecision()
        assert d.should_checkpoint is False
        assert d.reason is None
        assert d.urgency == "none"
        assert d.message == ""
