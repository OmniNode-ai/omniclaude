# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for hooks/bus_bootstrap factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_create_kafka_event_bus_returns_event_bus_kafka() -> None:
    """create_kafka_event_bus returns EventBusKafka constructed from config."""
    mock_config = MagicMock()
    mock_bus = MagicMock()

    with patch(
        "omniclaude.hooks.emit_bus_bootstrapper.EventBusKafka", return_value=mock_bus
    ) as mock_cls:
        from omniclaude.hooks.emit_bus_bootstrapper import create_kafka_event_bus

        result = create_kafka_event_bus(mock_config)

        mock_cls.assert_called_once_with(mock_config)
        assert result is mock_bus
