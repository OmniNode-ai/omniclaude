# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared fixtures for skill bootstrapper runtime tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def set_plugin_root(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure CLAUDE_PLUGIN_ROOT is set and ONEX_EVENT_BUS_TYPE is cleared.

    This makes HandlerGitHub construction succeed in test environments
    without requiring the real plugin deployment. Clearing ONEX_EVENT_BUS_TYPE
    prevents the bootstrapper's Kafka guard from firing in test environments
    where the host may have ONEX_EVENT_BUS_TYPE=kafka set.
    """
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    monkeypatch.delenv("ONEX_EVENT_BUS_TYPE", raising=False)
