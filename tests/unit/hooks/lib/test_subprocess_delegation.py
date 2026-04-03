# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for subprocess delegation handler [OMN-7410]."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest


class TestSubprocessHandler:
    """Verify subprocess delegation routing and execution."""

    def test_subprocess_handler_runs_approved_task(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: str
    ) -> None:
        monkeypatch.delenv("DELEGATION_DISABLE_SUBPROCESS_HANDLER", raising=False)

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _call_subprocess_handler,
        )

        fake_result = subprocess.CompletedProcess(
            args=["ruff", "check", "src/"],
            returncode=0,
            stdout="All checks passed.\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=fake_result) as mock_run:
            result = _call_subprocess_handler("lint", str(tmp_path))

        mock_run.assert_called_once()
        assert result["pass_fail"] == "pass"
        assert "All checks passed" in result["output"]
        assert result["elapsed_seconds"] >= 0
        assert result["command"] == "ruff check src/"

    def test_subprocess_handler_timeout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: str
    ) -> None:
        monkeypatch.delenv("DELEGATION_DISABLE_SUBPROCESS_HANDLER", raising=False)

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _call_subprocess_handler,
        )

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["pytest"], timeout=5),
        ):
            result = _call_subprocess_handler("test_run", str(tmp_path), timeout_override=5)

        assert result["pass_fail"] == "error"
        assert "Timeout" in result["output"]
        assert result["elapsed_seconds"] >= 0

    def test_subprocess_rejects_unapproved_intent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: str
    ) -> None:
        monkeypatch.delenv("DELEGATION_DISABLE_SUBPROCESS_HANDLER", raising=False)

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _call_subprocess_handler,
        )

        with pytest.raises(ValueError, match="not an approved subprocess intent"):
            _call_subprocess_handler("rm_rf_everything", str(tmp_path))

    def test_subprocess_disabled_by_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: str
    ) -> None:
        monkeypatch.setenv("DELEGATION_DISABLE_SUBPROCESS_HANDLER", "true")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _call_subprocess_handler,
        )

        with pytest.raises(ValueError, match="disabled by env flag"):
            _call_subprocess_handler("lint", str(tmp_path))

    def test_subprocess_handler_captures_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: str
    ) -> None:
        monkeypatch.delenv("DELEGATION_DISABLE_SUBPROCESS_HANDLER", raising=False)

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _call_subprocess_handler,
        )

        fake_result = subprocess.CompletedProcess(
            args=["mypy", "src/"],
            returncode=1,
            stdout="",
            stderr="src/foo.py:10: error: Missing return\n",
        )

        with patch("subprocess.run", return_value=fake_result):
            result = _call_subprocess_handler("type_check", str(tmp_path))

        assert result["pass_fail"] == "fail"
        assert "Missing return" in result["output"]
