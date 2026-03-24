# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for session-start env var health check (OMN-6264)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestEnvHealthCheck:
    def test_missing_intelligence_url_warns(self) -> None:
        """When INTELLIGENCE_SERVICE_URL is not set, emit a warning."""
        from omniclaude.hooks.env_health_check import check_critical_env_vars

        with patch.dict(os.environ, {}, clear=True):
            result = check_critical_env_vars()
        assert any("INTELLIGENCE_SERVICE_URL" in w for w in result.warnings)

    def test_all_vars_present_no_warnings(self) -> None:
        """When all critical vars are set, no warnings."""
        from omniclaude.hooks.env_health_check import check_critical_env_vars

        env = {
            "INTELLIGENCE_SERVICE_URL": "http://localhost:8053",
            "KAFKA_BOOTSTRAP_SERVERS": "localhost:19092",
        }
        with patch.dict(os.environ, env, clear=True):
            result = check_critical_env_vars()
        assert len(result.warnings) == 0

    def test_missing_kafka_warns(self) -> None:
        """When KAFKA_BOOTSTRAP_SERVERS is not set, emit a warning."""
        from omniclaude.hooks.env_health_check import check_critical_env_vars

        with patch.dict(os.environ, {}, clear=True):
            result = check_critical_env_vars()
        assert any("KAFKA_BOOTSTRAP_SERVERS" in w for w in result.warnings)

    def test_result_never_raises(self) -> None:
        """Health check must never raise -- it returns a result object."""
        from omniclaude.hooks.env_health_check import check_critical_env_vars

        # Even with bizarre env state, should not raise
        with patch.dict(os.environ, {"INTELLIGENCE_SERVICE_URL": ""}, clear=True):
            result = check_critical_env_vars()
        assert result is not None
