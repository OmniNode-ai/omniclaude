# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for systemd_helper dual-scope probe [OMN-8853].

Validates check_systemd_unit() covers all 4 observable cases:
  1. system-only active
  2. user-only active
  3. both scopes active
  4. neither scope (MISSING — only reported after probing BOTH)

Also covers inactive-but-present states in each scope.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# systemd_helper is importable via conftest.py _SHARED_DIR path injection.
from systemd_helper import EnumSystemdUnitState, check_systemd_unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed_process(
    returncode: int, stdout: str = "", stderr: str = ""
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


_ACTIVE_OUTPUT = "ActiveState=active\nSubState=running\n"
_INACTIVE_OUTPUT = "ActiveState=inactive\nSubState=dead\n"
_NOT_FOUND_OUTPUT = "Could not find unit"


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckSystemdUnit:
    """All four observable cases for dual-scope systemd probe."""

    def test_system_only_active(self) -> None:
        """Unit active in system scope, absent/inactive in user scope."""
        system_proc = _make_completed_process(0, _ACTIVE_OUTPUT)
        user_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ):
            result = check_systemd_unit("deploy-agent.service")

        assert result == EnumSystemdUnitState.SYSTEM_ACTIVE

    def test_user_only_active(self) -> None:
        """Unit absent/inactive in system scope, active in user scope."""
        system_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)
        user_proc = _make_completed_process(0, _ACTIVE_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ):
            result = check_systemd_unit("some-user.service")

        assert result == EnumSystemdUnitState.USER_ACTIVE

    def test_both_active(self) -> None:
        """Unit active in BOTH system and user scope."""
        system_proc = _make_completed_process(0, _ACTIVE_OUTPUT)
        user_proc = _make_completed_process(0, _ACTIVE_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ):
            result = check_systemd_unit("some-dual.service")

        assert result == EnumSystemdUnitState.BOTH_ACTIVE

    def test_missing_from_both_scopes(self) -> None:
        """Unit not found in either scope — only after probing BOTH."""
        system_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)
        user_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ):
            result = check_systemd_unit("nonexistent.service")

        assert result == EnumSystemdUnitState.MISSING

    def test_system_inactive(self) -> None:
        """Unit present in system scope but inactive, absent from user."""
        system_proc = _make_completed_process(3, _INACTIVE_OUTPUT)
        user_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ):
            result = check_systemd_unit("stopped.service")

        assert result == EnumSystemdUnitState.SYSTEM_INACTIVE

    def test_user_inactive(self) -> None:
        """Unit absent from system scope, present in user scope but inactive."""
        system_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)
        user_proc = _make_completed_process(3, _INACTIVE_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ):
            result = check_systemd_unit("stopped-user.service")

        assert result == EnumSystemdUnitState.USER_INACTIVE

    def test_always_probes_both_scopes(self) -> None:
        """subprocess.run must be called exactly twice (system + user)."""
        system_proc = _make_completed_process(0, _ACTIVE_OUTPUT)
        user_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ) as mock_run:
            check_systemd_unit("deploy-agent.service")

        assert mock_run.call_count == 2

    def test_system_call_uses_system_scope(self) -> None:
        """First subprocess.run call must NOT include --user flag."""
        system_proc = _make_completed_process(0, _ACTIVE_OUTPUT)
        user_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ) as mock_run:
            check_systemd_unit("deploy-agent.service")

        first_call_args = mock_run.call_args_list[0][0][0]
        assert "--user" not in first_call_args

    def test_user_call_uses_user_scope(self) -> None:
        """Second subprocess.run call must include --user flag."""
        system_proc = _make_completed_process(4, _NOT_FOUND_OUTPUT)
        user_proc = _make_completed_process(0, _ACTIVE_OUTPUT)

        with patch(
            "systemd_helper.subprocess.run", side_effect=[system_proc, user_proc]
        ) as mock_run:
            check_systemd_unit("some-user.service")

        second_call_args = mock_run.call_args_list[1][0][0]
        assert "--user" in second_call_args
