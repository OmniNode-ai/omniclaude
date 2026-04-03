# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for result-only delegation mode [OMN-7410]."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


class TestResultOnlyMode:
    """Verify normalized result-only response schema."""

    def test_result_only_strips_to_normalized_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DELEGATION_RESULT_ONLY", "true")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _format_result_only,
        )

        result = _format_result_only(
            response_text="Here is a 500 char analysis " * 20,
            model_name="qwen3-coder",
            handler_name="code_review",
            pass_fail="pass",
            elapsed_seconds=2.3,
            correlation_id="corr-123",
        )
        assert result["mode"] == "result_only"
        assert result["pass_fail"] == "pass"
        assert result["handler_name"] == "code_review"
        assert result["model_name"] == "qwen3-coder"
        assert result["correlation_id"] == "corr-123"
        assert result["elapsed_seconds"] == 2.3
        assert len(result["summary"]) <= 200
        assert isinstance(result["truncated"], bool)

    def test_result_only_subprocess_conforms(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DELEGATION_RESULT_ONLY", "true")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _format_result_only,
        )

        result = _format_result_only(
            response_text="src/foo.py:10: E302 expected 2 blank lines",
            model_name=None,
            handler_name="lint",
            pass_fail="fail",
            elapsed_seconds=1.1,
            correlation_id="corr-456",
        )
        assert result["mode"] == "result_only"
        assert result["model_name"] is None
        assert result["pass_fail"] == "fail"
        assert result["handler_name"] == "lint"
        assert isinstance(result["truncated"], bool)

    def test_result_only_truncates_long_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DELEGATION_RESULT_ONLY", "true")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _format_result_only,
        )

        long_text = "x" * 500
        result = _format_result_only(
            response_text=long_text,
            model_name="qwen3-coder",
            handler_name="research",
            pass_fail="pass",
            elapsed_seconds=3.0,
            correlation_id="corr-789",
        )
        assert result["truncated"] is True
        assert len(result["summary"]) <= 200

    def test_result_only_short_response_not_truncated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DELEGATION_RESULT_ONLY", "true")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _format_result_only,
        )

        result = _format_result_only(
            response_text="All good.",
            model_name=None,
            handler_name="lint",
            pass_fail="pass",
            elapsed_seconds=0.5,
            correlation_id="corr-000",
        )
        assert result["truncated"] is False
        assert result["summary"] == "All good."
