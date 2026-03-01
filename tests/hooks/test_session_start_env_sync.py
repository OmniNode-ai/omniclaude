# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for session-start.sh env sync section (OMN-3245).

Tests verify that the env sync snippet in session-start.sh:
1. Fires when INFISICAL_ADDR is configured
2. Is skipped when INFISICAL_ADDR is not set
3. Runs in the background (non-blocking, uses & and disown)

These tests inspect the shell script content directly — no subprocess execution
is needed because the sync runs in a background subshell that is entirely
self-contained and guarded by the sync script's own throttle/flock logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# Path to the session-start.sh script under test
_SCRIPT_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "session-start.sh"
)

_SCRIPT_CONTENT: str | None = None


def _script() -> str:
    """Return the session-start.sh content (cached)."""
    global _SCRIPT_CONTENT
    if _SCRIPT_CONTENT is None:
        _SCRIPT_CONTENT = _SCRIPT_PATH.read_text(encoding="utf-8")
    return _SCRIPT_CONTENT


class TestSessionStartEnvSync:
    """Verify the env sync section in session-start.sh."""

    def test_sync_fires_when_infisical_configured(self) -> None:
        """Env sync block appears and is guarded by INFISICAL_ADDR check.

        When INFISICAL_ADDR is set, the block should call
        sync-omnibase-env.py via uv run python.
        """
        content = _script()
        # The guard condition must check INFISICAL_ADDR
        assert 'INFISICAL_ADDR' in content, (
            "session-start.sh must reference INFISICAL_ADDR for the env sync guard"
        )
        # The sync call must invoke sync-omnibase-env.py
        assert 'sync-omnibase-env.py' in content, (
            "session-start.sh must call sync-omnibase-env.py when INFISICAL_ADDR is set"
        )

    def test_sync_skipped_when_infisical_not_configured(self) -> None:
        """Env sync block uses -n guard so it is skipped when INFISICAL_ADDR is unset.

        The guard must use [[ -n "${INFISICAL_ADDR:-}" ]] (or equivalent)
        so that an unset or empty INFISICAL_ADDR prevents the sync from running.
        """
        content = _script()
        # Guard pattern: [[ -n "${INFISICAL_ADDR:-}" ]] skips when empty/unset
        assert '-n "${INFISICAL_ADDR' in content or "-n '${INFISICAL_ADDR" in content, (
            "session-start.sh must use -n guard on INFISICAL_ADDR to skip sync when unset"
        )

    def test_sync_is_backgrounded(self) -> None:
        """Env sync uses & and disown to run non-blocking.

        The snippet must background the subshell with & and call disown
        so that session startup is never blocked by the sync operation.
        """
        content = _script()
        # Find the env sync section
        assert 'sync-omnibase-env.py' in content, (
            "sync-omnibase-env.py must be present before checking backgrounding"
        )
        # The sync must be backgrounded with & (either bare & or ) &)
        # We verify both & and disown appear near the sync section
        assert 'disown' in content, (
            "session-start.sh must call disown after the sync background job "
            "to detach it from the shell and prevent blocking"
        )
        # Verify the subshell pattern: (...) &
        assert ') &' in content or ')&' in content, (
            "session-start.sh must background the sync using ') &' subshell pattern"
        )
