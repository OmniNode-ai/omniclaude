# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the aggregators package.

Covers:
    - ConfigSessionAggregator field defaults and validation
    - EnumSessionStatus values and string coercion
    - ProtocolSessionAggregator runtime checkability
    - Aggregators package re-exports
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# EnumSessionStatus
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnumSessionStatus:
    def test_values(self) -> None:
        from omniclaude.aggregators.enums import EnumSessionStatus

        assert EnumSessionStatus.ORPHAN == "orphan"
        assert EnumSessionStatus.ACTIVE == "active"
        assert EnumSessionStatus.ENDED == "ended"
        assert EnumSessionStatus.TIMED_OUT == "timed_out"

    def test_from_string(self) -> None:
        from omniclaude.aggregators.enums import EnumSessionStatus

        assert EnumSessionStatus("orphan") is EnumSessionStatus.ORPHAN
        assert EnumSessionStatus("active") is EnumSessionStatus.ACTIVE

    def test_invalid_value(self) -> None:
        from omniclaude.aggregators.enums import EnumSessionStatus

        with pytest.raises(ValueError):
            EnumSessionStatus("invalid")

    def test_all_values_are_four(self) -> None:
        from omniclaude.aggregators.enums import EnumSessionStatus

        assert len(EnumSessionStatus) == 4


# ---------------------------------------------------------------------------
# ConfigSessionAggregator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConfigSessionAggregator:
    def test_defaults(self) -> None:
        from omniclaude.aggregators.config import ConfigSessionAggregator

        config = ConfigSessionAggregator()
        assert config.session_inactivity_timeout_seconds == 3600
        assert config.session_max_duration_seconds == 2592000
        assert config.orphan_buffer_duration_seconds == 300
        assert config.out_of_order_buffer_seconds == 60
        assert config.max_orphan_sessions == 10000
        assert config.timeout_sweep_interval_seconds == 60

    def test_custom_values(self) -> None:
        from omniclaude.aggregators.config import ConfigSessionAggregator

        config = ConfigSessionAggregator(
            session_inactivity_timeout_seconds=120,
            orphan_buffer_duration_seconds=60,
            max_orphan_sessions=500,
        )
        assert config.session_inactivity_timeout_seconds == 120
        assert config.orphan_buffer_duration_seconds == 60
        assert config.max_orphan_sessions == 500

    def test_too_low_timeout_rejected(self) -> None:
        from omniclaude.aggregators.config import ConfigSessionAggregator

        with pytest.raises(Exception):
            ConfigSessionAggregator(session_inactivity_timeout_seconds=5)

    def test_too_high_timeout_rejected(self) -> None:
        from omniclaude.aggregators.config import ConfigSessionAggregator

        with pytest.raises(Exception):
            ConfigSessionAggregator(session_inactivity_timeout_seconds=100_000)

    def test_finalized_session_warning_fields(self) -> None:
        from omniclaude.aggregators.config import ConfigSessionAggregator

        config = ConfigSessionAggregator()
        assert config.finalized_session_warning_threshold == 10000
        assert config.finalized_session_warning_interval_seconds == 3600

    def test_from_contract_defaults_match_inline_defaults(self) -> None:
        """Overlay resolution with no env override == in-source defaults.

        OMN-13560 Wave-2: the contract declares ``${env.VAR:default}`` for every
        tunable, so an unset environment must resolve to the same values the
        plain ``ConfigSessionAggregator()`` constructor produces.
        """
        from omniclaude.aggregators.config import ConfigSessionAggregator

        assert ConfigSessionAggregator.from_contract() == ConfigSessionAggregator()

    def test_from_contract_env_override_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A per-lane env override flows through the contract overlay seam."""
        from omniclaude.aggregators.config import ConfigSessionAggregator

        monkeypatch.setenv(
            "OMNICLAUDE_AGGREGATOR_SESSION_INACTIVITY_TIMEOUT_SECONDS", "120"
        )
        monkeypatch.setenv("OMNICLAUDE_AGGREGATOR_MAX_ORPHAN_SESSIONS", "500")

        resolved = ConfigSessionAggregator.from_contract()

        assert resolved.session_inactivity_timeout_seconds == 120
        assert resolved.max_orphan_sessions == 500
        # Untouched fields keep their inline contract defaults.
        assert resolved.timeout_sweep_interval_seconds == 60

    def test_from_contract_out_of_bounds_override_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An overlay value outside the field bounds fails at validation."""
        from omniclaude.aggregators.config import ConfigSessionAggregator

        monkeypatch.setenv(
            "OMNICLAUDE_AGGREGATOR_SESSION_INACTIVITY_TIMEOUT_SECONDS", "5"
        )

        with pytest.raises(Exception):
            ConfigSessionAggregator.from_contract()


# ---------------------------------------------------------------------------
# ProtocolSessionAggregator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProtocolSessionAggregator:
    def test_is_runtime_checkable(self) -> None:
        from omniclaude.aggregators.protocol_session_aggregator import (
            ProtocolSessionAggregator,
        )

        # Protocol must be runtime_checkable
        assert hasattr(ProtocolSessionAggregator, "__protocol_attrs__") or hasattr(
            ProtocolSessionAggregator, "__abstractmethods__"
        )

    def test_type_vars_exported(self) -> None:
        from omniclaude.aggregators.protocol_session_aggregator import (
            TEvent_contra,
            TSnapshot_co,
        )

        assert TSnapshot_co.__covariant__
        assert TEvent_contra.__contravariant__


# ---------------------------------------------------------------------------
# Package re-exports
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAggregatorsPackageExports:
    def test_all_exports_importable(self) -> None:
        from omniclaude import aggregators

        expected = {
            "ProtocolSessionAggregator",
            "SessionAggregator",
            "TSnapshot_co",
            "TEvent_contra",
            "EnumSessionStatus",
            "ConfigSessionAggregator",
            "PromptRecord",
            "ToolRecord",
            "SessionState",
            "AggregatorMetricsDict",
            "PromptSnapshotDict",
            "SessionSnapshotDict",
            "ToolSnapshotDict",
        }
        assert expected == set(aggregators.__all__)

    def test_session_aggregator_instantiable(self) -> None:
        from omniclaude.aggregators import ConfigSessionAggregator, SessionAggregator

        config = ConfigSessionAggregator()
        agg = SessionAggregator(config)
        assert agg.aggregator_id is not None
        assert isinstance(agg.aggregator_id, str)
