# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the SubagentStop secret-leak guard [OMN-15062].

RED-first coverage: proves the exact failure mode from 2026-07-24 (a
credential-investigation subagent's final report containing a raw
credential) is caught, and proves the guard's fail-safe posture -- block on
scan error, allow only when there is genuinely nothing to scan.

All synthetic values in this file are fabricated for the test and are not,
and never were, real credentials.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from unittest import mock

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from subagent_secret_leak_guard import (  # noqa: E402
    EnumSecretGuardVerdict,
    _hook_output,
    scan_stop_event,
)

pytestmark = pytest.mark.unit

# Synthetic-only credential shapes, fabricated for this test.
_SYNTHETIC_PG_PASSWORD = "xK9mP2vL8nQ4wR2ne"  # pragma: allowlist secret
_SYNTHETIC_GOOGLE_KEY = "AIza" + "Sy" + "D" + ("7" * 32)  # 39 chars total


class TestScanStopEventCatchesRealLeakShapes:
    """RED-first: reproduces the exact leak shapes from 2026-07-24."""

    def test_bare_postgres_password_prose_is_blocked(self) -> None:
        """The Postgres-severity-probe shape: prose, not key=value."""
        event = {
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "Severity: HIGH. The Postgres password is "
                        f"{_SYNTHETIC_PG_PASSWORD} and is exposed in 3 files."
                    ),
                }
            ]
        }
        result = scan_stop_event(event)
        assert result.verdict is EnumSecretGuardVerdict.BLOCK
        assert result.redacted_count >= 1

    def test_google_api_key_is_blocked(self) -> None:
        """The Google-key-verification-lane shape: AIza-prefixed key."""
        event = {
            "messages": [
                {
                    "role": "assistant",
                    "content": f"Verified working: {_SYNTHETIC_GOOGLE_KEY}",
                }
            ]
        }
        result = scan_stop_event(event)
        assert result.verdict is EnumSecretGuardVerdict.BLOCK
        assert result.redacted_count >= 1

    def test_clean_report_is_allowed(self) -> None:
        """A report that describes the finding without quoting the value passes."""
        event = {
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "Severity: HIGH. A Postgres credential was found "
                        "hardcoded in 3 files; value withheld, rotation "
                        "recommended."
                    ),
                }
            ]
        }
        result = scan_stop_event(event)
        assert result.verdict is EnumSecretGuardVerdict.ALLOW
        assert result.redacted_count == 0

    def test_no_extractable_message_is_allowed(self) -> None:
        """Nothing to scan -> allow, not a spurious block."""
        result = scan_stop_event({})
        assert result.verdict is EnumSecretGuardVerdict.ALLOW
        assert result.reason == "no_message_extracted"


class TestFailSafePosture:
    """Fail SAFE, not open: a scan error must block, never pass through raw text."""

    def test_scan_exception_blocks_not_allows(self) -> None:
        """If redact_secrets_with_count raises, the guard blocks (does not
        allow the unredacted message through)."""
        event = {
            "messages": [{"role": "assistant", "content": "some text with content"}]
        }
        with mock.patch(
            "subagent_secret_leak_guard.redact_secrets_with_count",
            side_effect=RuntimeError("boom"),
        ):
            result = scan_stop_event(event)
        assert result.verdict is EnumSecretGuardVerdict.BLOCK
        assert result.reason == "scan_error_fail_safe"

    def test_extraction_exception_does_not_crash(self) -> None:
        """If extraction itself raises, there is nothing in hand to have
        leaked via this guard -- allow, not a spurious infinite block."""
        with mock.patch(
            "subagent_secret_leak_guard._extract_last_assistant_message",
            side_effect=RuntimeError("boom"),
        ):
            result = scan_stop_event({"messages": []})
        assert result.verdict is EnumSecretGuardVerdict.ALLOW
        assert result.reason == "extraction_error_nothing_to_scan"


class TestHookOutputNeverLeaksTheSecret:
    """The hook's own additionalContext must never echo the matched secret,
    the redacted message, or the raw message -- it becomes part of the
    transcript itself."""

    def test_block_output_contains_no_secret_material(self) -> None:
        event = {
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        f"The Postgres password is {_SYNTHETIC_PG_PASSWORD} today."
                    ),
                }
            ]
        }
        result = scan_stop_event(event)
        output = json.dumps(_hook_output(result))
        assert _SYNTHETIC_PG_PASSWORD not in output
        assert "Postgres password is" not in output  # no message fragment echoed
        assert "decision" in output
        assert '"block"' in output


class TestCliEndToEnd:
    """Exercises the CLI entrypoint the shell wrapper invokes, as a
    subprocess, matching how Claude Code actually calls this hook."""

    def test_cli_blocks_on_leak_and_exits_2(self) -> None:
        event = {
            "messages": [
                {
                    "role": "assistant",
                    "content": (f"The Postgres password is {_SYNTHETIC_PG_PASSWORD}."),
                }
            ]
        }
        proc = subprocess.run(
            [sys.executable, str(_LIB_DIR / "subagent_secret_leak_guard.py")],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 2
        assert _SYNTHETIC_PG_PASSWORD not in proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["hookSpecificOutput"]["decision"] == "block"

    def test_cli_allows_clean_report_and_exits_0(self) -> None:
        event = {
            "messages": [
                {"role": "assistant", "content": "Nothing sensitive to report."}
            ]
        }
        proc = subprocess.run(
            [sys.executable, str(_LIB_DIR / "subagent_secret_leak_guard.py")],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["hookSpecificOutput"]["decision"] == "allow"

    def test_cli_handles_malformed_stdin_without_crashing(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(_LIB_DIR / "subagent_secret_leak_guard.py")],
            input="not json{{{",
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["hookSpecificOutput"]["decision"] == "allow"
