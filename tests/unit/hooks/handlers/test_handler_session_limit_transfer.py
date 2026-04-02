# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for handler_session_limit_transfer — transfer decision logic."""

from __future__ import annotations

import pytest

from omniclaude.hooks.handlers.handler_session_limit_transfer import (
    EnumTransferAction,
    ModelTransferDecision,
    determine_transfer_action,
)
from omniclaude.hooks.model_session_checkpoint import EnumCheckpointReason
from omniclaude.hooks.statusline_parser import ModelLimitStatus


@pytest.mark.unit
class TestDetermineTransferAction:
    """Tests for the top-level transfer decision function."""

    def test_all_ok_no_action(self) -> None:
        status = ModelLimitStatus(
            context_percent=50, session_percent=30, weekly_percent=20
        )
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.NONE
        assert decision.checkpoint_needed is False

    def test_context_critical_checkpoint_and_exit(self) -> None:
        status = ModelLimitStatus(context_percent=92)
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.CHECKPOINT_AND_EXIT
        assert decision.reason == EnumCheckpointReason.CONTEXT_LIMIT
        assert decision.urgency == "critical"
        assert decision.checkpoint_needed is True

    def test_session_critical_checkpoint_and_exit(self) -> None:
        status = ModelLimitStatus(session_percent=96)
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.CHECKPOINT_AND_EXIT
        assert decision.reason == EnumCheckpointReason.SESSION_LIMIT
        assert decision.urgency == "critical"
        assert decision.checkpoint_needed is True

    def test_weekly_critical_transfers_to_local_llm(self) -> None:
        status = ModelLimitStatus(weekly_percent=92)
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.TRANSFER_TO_LOCAL_LLM
        assert decision.reason == EnumCheckpointReason.WEEKLY_LIMIT
        assert decision.urgency == "critical"
        assert decision.checkpoint_needed is True
        assert decision.suggested_model == "local_vllm"

    def test_weekly_warn_switches_to_haiku(self) -> None:
        status = ModelLimitStatus(weekly_percent=82)
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.SWITCH_TO_HAIKU
        assert decision.reason == EnumCheckpointReason.WEEKLY_LIMIT
        assert decision.urgency == "warn"
        assert decision.checkpoint_needed is False
        assert decision.suggested_model == "haiku"

    def test_context_warn_checkpoint_and_exit(self) -> None:
        status = ModelLimitStatus(context_percent=82)
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.CHECKPOINT_AND_EXIT
        assert decision.reason == EnumCheckpointReason.CONTEXT_LIMIT
        assert decision.urgency == "warn"
        assert decision.checkpoint_needed is True

    def test_session_warn_checkpoint_and_exit(self) -> None:
        status = ModelLimitStatus(session_percent=87)
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.CHECKPOINT_AND_EXIT
        assert decision.reason == EnumCheckpointReason.SESSION_LIMIT
        assert decision.urgency == "warn"
        assert decision.checkpoint_needed is True

    def test_context_critical_takes_priority_over_weekly(self) -> None:
        """Context critical beats weekly critical."""
        status = ModelLimitStatus(context_percent=92, weekly_percent=92)
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.CHECKPOINT_AND_EXIT
        assert decision.reason == EnumCheckpointReason.CONTEXT_LIMIT

    def test_none_percentages_no_action(self) -> None:
        status = ModelLimitStatus()
        decision = determine_transfer_action(status)
        assert decision.action == EnumTransferAction.NONE

    def test_decision_has_message(self) -> None:
        status = ModelLimitStatus(context_percent=92)
        decision = determine_transfer_action(status)
        assert len(decision.message) > 0


@pytest.mark.unit
class TestEnumTransferAction:
    """Tests for transfer action enum."""

    def test_all_variants(self) -> None:
        assert set(EnumTransferAction) == {
            "none",
            "checkpoint_and_exit",
            "switch_to_haiku",
            "transfer_to_local_llm",
        }


@pytest.mark.unit
class TestModelTransferDecision:
    """Tests for the transfer decision model."""

    def test_defaults(self) -> None:
        d = ModelTransferDecision()
        assert d.action == EnumTransferAction.NONE
        assert d.checkpoint_needed is False
        assert d.suggested_model is None

    def test_frozen(self) -> None:
        d = ModelTransferDecision()
        with pytest.raises(Exception):
            d.action = EnumTransferAction.CHECKPOINT_AND_EXIT  # type: ignore[misc]
