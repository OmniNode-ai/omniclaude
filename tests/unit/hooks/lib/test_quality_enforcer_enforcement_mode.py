# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for enforcement mode string consistency in quality_enforcer.py.

Verifies that _build_violations_system_message uses the correct enforcement mode
strings aligned with Settings.enforcement_mode Literal type:
  Literal["advisory", "blocking", "auto-fix"]

Ticket: OMN-1487 — Fix inconsistent enforcement mode strings in quality_enforcer.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# Ensure src is on path
_SRC = Path(__file__).resolve().parents[4] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Import quality_enforcer; reload defensively to ensure clean module state in
# test splits where prior tests may have polluted the module cache via mock patching.
import types

import omniclaude.lib.utils.quality_enforcer as _qe_mod

if isinstance(_qe_mod, types.ModuleType):
    importlib.reload(_qe_mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_enforcer_class() -> type:
    """Get QualityEnforcer class from the (already-reloaded) module.

    NOTE: Do NOT reload here — reloading inside a test that uses
    ``patch(...)`` on the module creates a new class object that the
    patches do not apply to, causing 'MagicMock can't be used in await'
    errors.  The module-level reload above is sufficient.
    """
    return _qe_mod.QualityEnforcer


def _make_violation():
    """Return a minimal Violation-like object."""
    from dataclasses import dataclass

    @dataclass
    class FakeViolation:
        name: str = "badNaming"
        suggestion: str = "GoodNaming"
        line: int = 1
        rule: str = "class names must use PascalCase"
        violation_type: str = "naming"
        expected_format: str = "PascalCase"

    return FakeViolation()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnforcementModeBanner:
    """Enforcement mode strings must be consistent with Settings Literal type."""

    def test_blocking_mode_shows_blocked_banner(self) -> None:
        """When mode='blocking', the system message must show WRITE BLOCKED."""
        QualityEnforcer = _get_enforcer_class()

        enforcer = QualityEnforcer()
        violations = [_make_violation()]
        msg = enforcer._build_violations_system_message(
            violations, "/repo/src/module.py", mode="blocking"
        )

        assert isinstance(msg, str), f"Expected str, got {type(msg)}"
        assert "WRITE BLOCKED" in msg
        assert "NAMING CONVENTION VIOLATIONS - WRITE BLOCKED" in msg
        assert "NAMING CONVENTION WARNINGS" not in msg

    def test_advisory_mode_shows_warning_banner(self) -> None:
        """When mode='advisory', the system message must show warnings (not blocked)."""
        QualityEnforcer = _get_enforcer_class()

        enforcer = QualityEnforcer()
        violations = [_make_violation()]
        msg = enforcer._build_violations_system_message(
            violations, "/repo/src/module.py", mode="advisory"
        )

        assert isinstance(msg, str), f"Expected str, got {type(msg)}"
        assert "NAMING CONVENTION WARNINGS" in msg
        assert "WRITE BLOCKED" not in msg
        assert "Write will proceed" in msg

    def test_default_mode_shows_warning_banner(self) -> None:
        """Default mode (no explicit mode arg) must show warnings, not blocked."""
        QualityEnforcer = _get_enforcer_class()

        enforcer = QualityEnforcer()
        violations = [_make_violation()]
        # Call without mode arg to test default
        msg = enforcer._build_violations_system_message(
            violations, "/repo/src/module.py"
        )

        assert isinstance(msg, str), f"Expected str, got {type(msg)}"
        assert "NAMING CONVENTION WARNINGS" in msg
        assert "WRITE BLOCKED" not in msg

    def test_blocking_mode_footer_shows_fix_guidance(self) -> None:
        """Blocking mode footer must instruct user to fix violations."""
        QualityEnforcer = _get_enforcer_class()

        enforcer = QualityEnforcer()
        violations = [_make_violation()]
        msg = enforcer._build_violations_system_message(
            violations, "/repo/src/module.py", mode="blocking"
        )

        assert isinstance(msg, str), f"Expected str, got {type(msg)}"
        assert "Fix the violations above and try again" in msg

    def test_no_stale_block_string_in_source(self) -> None:
        """Ensure the source code does not contain the old 'block' string checks.

        The Settings Literal type defines 'blocking', not 'block'.
        quality_enforcer.py must not check for the bare 'block' string.
        """
        source_path = (
            Path(__file__).resolve().parents[4]
            / "src"
            / "omniclaude"
            / "lib"
            / "utils"
            / "quality_enforcer.py"
        )
        source = source_path.read_text()

        # Should not contain set-membership checks that include "block" as a
        # distinct value from "blocking". The old pattern was:
        #   if mode in {"block", "blocking"}:
        # The fix standardizes on just "blocking".
        assert '{"block", "blocking"}' not in source, (
            'Found stale {"block", "blocking"} check in quality_enforcer.py. '
            'Use "blocking" consistently per Settings Literal type.'
        )
