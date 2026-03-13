# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared fixtures for skill bootstrapper runtime tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def set_plugin_root(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure CLAUDE_PLUGIN_ROOT is set for all runtime tests.

    This makes HandlerGitHub construction succeed in test environments
    without requiring the real plugin deployment.
    """
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
