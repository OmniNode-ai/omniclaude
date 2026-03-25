# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Enforce that hook scripts distinguish crashes from intentional allow/block.

Policy: Non-zero, non-2 exit codes from Python handlers must be logged with
[HOOK_CRASH] prefix and tracked via error counters. The tool call is still
allowed (fail-open) but the error is visible for monitoring.
"""

import pathlib

import pytest

HOOKS_DIR = pathlib.Path("plugins/onex/hooks/scripts")


@pytest.mark.unit
def test_hook_crash_handling() -> None:
    """Hook scripts must log crashes distinctly from allow/block."""
    hook = HOOKS_DIR / "pre_tool_use_context_scope_auditor.sh"
    content = hook.read_text()
    # Must handle exit code 1 (crash) differently from 0 (allow) and 2 (block)
    assert "HOOK_CRASH" in content, "Hook must log crashes with [HOOK_CRASH] prefix"
    assert "EXIT_CODE -ne 0" in content or "EXIT_CODE != 0" in content, (
        "Hook must check for non-zero exit codes beyond just exit 2"
    )


@pytest.mark.unit
def test_hook_error_counter_tracking() -> None:
    """Hook scripts with crash handling must track consecutive error counts."""
    hook = HOOKS_DIR / "pre_tool_use_context_scope_auditor.sh"
    content = hook.read_text()
    assert "error-counts" in content, (
        "Hook must track errors in .onex_state/hooks/error-counts/"
    )
    assert "hook-health-degraded.flag" in content, (
        "Hook must write degraded flag after consecutive failures"
    )
