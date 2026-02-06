# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pytest configuration for lib/core unit tests.

This conftest.py sets up module-level mocking for omnibase_infra and omnibase_core
dependencies BEFORE any omniclaude modules are imported. This is critical because
the import chain (omniclaude -> hooks -> schemas) requires omnibase_infra.utils
which is not available in the test environment.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock

# ==============================================================================
# Module-level dependency mocking
# ==============================================================================
# These mocks MUST be applied before any omniclaude imports happen.
# pytest loads conftest.py before collecting tests, ensuring proper mock timing.


def _setup_omnibase_mocks() -> None:
    """Setup comprehensive mocks for omnibase_infra and omnibase_core.

    Only mocks when the real package is NOT installed. If omnibase_infra
    is available, we skip mocking entirely to avoid poisoning sys.modules
    (which breaks subpackage imports like omnibase_infra.runtime.emit_daemon
    when running the full test suite).
    """
    # Skip if already mocked (allows re-running)
    if "omnibase_infra" in sys.modules and hasattr(
        sys.modules["omnibase_infra"], "_is_mock"
    ):
        return

    # Skip if the real package is available — mocking would shadow it
    try:
        import omnibase_infra  # noqa: F401

        return
    except ImportError:
        pass

    # Create mock for omnibase_infra.utils.ensure_timezone_aware
    def mock_ensure_timezone_aware(dt: datetime | None) -> datetime | None:
        """Mock implementation of ensure_timezone_aware."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    # Create comprehensive mock modules for omnibase_infra
    mock_omnibase_infra = MagicMock()
    mock_omnibase_infra._is_mock = True

    # Mock omnibase_infra.utils
    mock_utils = MagicMock()
    mock_utils.ensure_timezone_aware = mock_ensure_timezone_aware
    mock_omnibase_infra.utils = mock_utils

    # Mock omnibase_infra.event_bus
    mock_event_bus = MagicMock()
    mock_event_bus_kafka = MagicMock()
    mock_event_bus_kafka.EventBusKafka = MagicMock()
    mock_event_bus.event_bus_kafka = mock_event_bus_kafka
    mock_omnibase_infra.event_bus = mock_event_bus

    # Mock omnibase_infra.event_bus.models
    mock_models = MagicMock()
    mock_config = MagicMock()
    mock_config.ModelKafkaEventBusConfig = MagicMock()
    mock_models.config = mock_config
    mock_omnibase_infra.event_bus.models = mock_models

    # Mock omnibase_infra.runtime
    mock_runtime = MagicMock()
    mock_runtime.RequestResponseWiring = MagicMock()
    mock_omnibase_infra.runtime = mock_runtime

    # Register all mocks in sys.modules
    sys.modules["omnibase_infra"] = mock_omnibase_infra
    sys.modules["omnibase_infra.utils"] = mock_utils
    sys.modules["omnibase_infra.event_bus"] = mock_event_bus
    sys.modules["omnibase_infra.event_bus.event_bus_kafka"] = mock_event_bus_kafka
    sys.modules["omnibase_infra.event_bus.models"] = mock_models
    sys.modules["omnibase_infra.event_bus.models.config"] = mock_config
    sys.modules["omnibase_infra.runtime"] = mock_runtime
    sys.modules["omnibase_infra.runtime.request_response_wiring"] = mock_runtime


# Apply mocks immediately when conftest is loaded (before test collection)
_setup_omnibase_mocks()
