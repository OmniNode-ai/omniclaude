# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the PostToolUse Bash-output secret-redaction guard [OMN-16277].

RED-first coverage: reproduces the exact two failure shapes from
2026-08-19 (a kubectl jsonpath/json dump echoing an Infisical
machine-identity `clientSecret`, and an `env | grep -i POSTGRES` output
whose Postgres password lived inside a `postgresql://user:pass@host` URL
rather than a `PASSWORD=` key) unredacted before this hook existed, and
proves they are masked via the `hookSpecificOutput.updatedToolOutput`
protocol after. Also proves the mechanism does NOT mass-redact ordinary,
credential-free Bash output (git log, pytest, docs with ref-pins).

All synthetic values in this file are fabricated for the test and are not,
and never were, real credentials.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from post_tool_use_secret_redact_guard import (  # noqa: E402
    EnumRedactionDecision,
    build_redaction_output,
    evaluate_and_redact,
)

pytestmark = pytest.mark.unit

_GUARD_SCRIPT = _LIB_DIR / "post_tool_use_secret_redact_guard.py"

# Synthetic-only credential shapes, fabricated for this test.
_SYNTHETIC_CLIENT_SECRET = (
    "zQ8mNc2VbTf6RkP1xYh4LwEj9Dst0Auo"  # pragma: allowlist secret
)
_SYNTHETIC_PG_PASSWORD = "Sup3rSecr3tPW9xyz"  # pragma: allowlist secret


def _bash_payload(
    stdout: str, *, stderr: str = "", interrupted: bool = False, exit_code: int = 0
) -> dict:
    return {
        "session_id": "test-session",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo test"},
        "tool_response": {
            "stdout": stdout,
            "stderr": stderr,
            "interrupted": interrupted,
            "isImage": False,
            "exit_code": exit_code,
        },
        "tool_use_id": "toolu_test_0001",
    }


class TestCatchesRealLeakShapes:
    """RED-first: reproduces the exact leak shapes from 2026-08-19."""

    def test_kubectl_jsonpath_clientsecret_dump_is_redacted(self) -> None:
        """Morning incident: over-broad kubectl -o json/jsonpath dump of an
        Infisical machine-identity Secret, echoing clientSecret verbatim."""
        stdout = (
            '{"clientId":"universal-auth-machine-id","clientSecret":'
            f'"{_SYNTHETIC_CLIENT_SECRET}"}}\n'
        )
        payload = _bash_payload(stdout)
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.redacted
        assert replacement is not None
        redacted_stdout = replacement["hookSpecificOutput"]["updatedToolOutput"][
            "stdout"
        ]
        assert _SYNTHETIC_CLIENT_SECRET not in redacted_stdout
        assert "REDACTED" in redacted_stdout
        # Non-secret sibling field survives.
        assert "universal-auth-machine-id" in redacted_stdout

    def test_env_grep_postgres_url_embedded_password_is_redacted(self) -> None:
        """Evening incident: env | grep -i POSTGRES output where the
        password lives inside a connection-string URL, not a PASSWORD= key
        -- the exact shape the agent's own ad-hoc sed redaction missed."""
        stdout = (
            "POSTGRES_HOST=db.internal\n"
            "POSTGRES_PORT=5432\n"
            f"DATABASE_URL=postgresql://appuser:{_SYNTHETIC_PG_PASSWORD}@db.internal:5432/appdb\n"
        )
        payload = _bash_payload(stdout)
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.redacted
        assert replacement is not None
        redacted_stdout = replacement["hookSpecificOutput"]["updatedToolOutput"][
            "stdout"
        ]
        assert _SYNTHETIC_PG_PASSWORD not in redacted_stdout
        assert "REDACTED" in redacted_stdout
        # Non-secret lines survive.
        assert "POSTGRES_HOST=db.internal" in redacted_stdout

    def test_secret_in_stderr_is_also_redacted(self) -> None:
        """A credential can leak on an error path too -- stderr must be
        scanned, not just stdout."""
        payload = _bash_payload(
            "",
            stderr=f'connection refused: clientSecret="{_SYNTHETIC_CLIENT_SECRET}"',
            exit_code=1,
        )
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.redacted
        assert replacement is not None
        redacted_stderr = replacement["hookSpecificOutput"]["updatedToolOutput"][
            "stderr"
        ]
        assert _SYNTHETIC_CLIENT_SECRET not in redacted_stderr


class TestPassthroughOnCleanOutput:
    """Silence (no hookSpecificOutput emission) whenever nothing matched."""

    def test_non_bash_tool_passes_through(self) -> None:
        payload = {"tool_name": "Read", "tool_response": {"content": "hello"}}
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.passthrough_not_bash
        assert replacement is None

    def test_clean_bash_output_passes_through(self) -> None:
        payload = _bash_payload(
            "On branch dev\nnothing to commit, working tree clean\n"
        )
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.passthrough_clean
        assert replacement is None

    def test_empty_output_passes_through(self) -> None:
        payload = _bash_payload("")
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.passthrough_clean
        assert replacement is None

    def test_small_output_below_no_threshold_still_scanned(self) -> None:
        """Unlike the verbose-output suppressor, this guard has NO size
        floor -- a credential can leak in 40 characters."""
        payload = _bash_payload(f"secret={_SYNTHETIC_PG_PASSWORD}")
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.redacted
        assert replacement is not None


class TestDoesNotMassRedactLegitimateOutput:
    """GREEN-preserve: ordinary Bash output must survive intact."""

    def test_git_log_with_author_emails_and_urls_untouched(self) -> None:
        stdout = (
            "remote: https://github.com/OmniNode-ai/omniclaude.git\n"
            "commit 4ac599abbf00\n"
            "Author: Jane Doe <jane.doe@example.com>\n"
            "Date:   Wed Aug 19 10:00:00 2026 -0700\n\n"
            "    docs: fix broken links\n"
        )
        payload = _bash_payload(stdout)
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.passthrough_clean
        assert replacement is None

    def test_report_prose_with_ref_pins_untouched(self) -> None:
        stdout = (
            "ticketed as [OMN-15460](https://linear.app/omninode/issue/OMN-15460)"
            " (High, bug).\nRoot cause: contracts exist on OCC @dev but 404 on"
            " omnimarket@dev.\n"
        )
        payload = _bash_payload(stdout)
        evaluation, replacement = evaluate_and_redact(payload)
        assert evaluation.decision is EnumRedactionDecision.passthrough_clean
        assert replacement is None


class TestReplacementProtocolShape:
    """Pins the exact hookSpecificOutput envelope shape (mirrors the
    OMN-13090 probe protocol already used by skill_output_suppressor.py)."""

    def test_build_redaction_output_shape(self) -> None:
        out = build_redaction_output(
            stdout="clean stdout",
            stderr="clean stderr",
            original={"interrupted": False, "isImage": False},
        )
        assert out == {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": {
                    "stdout": "clean stdout",
                    "stderr": "clean stderr",
                    "interrupted": False,
                    "isImage": False,
                },
            }
        }

    def test_build_redaction_output_preserves_interrupted_flag(self) -> None:
        """A redacted secret on an interrupted/errored command must not
        silently clear the interrupted flag -- that would hide a real
        failure from the caller."""
        out = build_redaction_output(
            stdout="",
            stderr="redacted",
            original={"interrupted": True, "isImage": False},
        )
        assert out["hookSpecificOutput"]["updatedToolOutput"]["interrupted"] is True


class TestCliEndToEnd:
    """Subprocess-level: exercises the real entrypoint, not just the
    library function."""

    def test_cli_emits_replacement_json_on_leak(self) -> None:
        payload = _bash_payload(f'{{"clientSecret":"{_SYNTHETIC_CLIENT_SECRET}"}}')
        result = subprocess.run(
            [sys.executable, str(_GUARD_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout.strip(), "expected a hookSpecificOutput emission"
        emitted = json.loads(result.stdout)
        redacted_stdout = emitted["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        assert _SYNTHETIC_CLIENT_SECRET not in redacted_stdout

    def test_cli_emits_nothing_on_clean_output(self) -> None:
        payload = _bash_payload("On branch dev\nnothing to commit\n")
        result = subprocess.run(
            [sys.executable, str(_GUARD_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_cli_never_crashes_on_malformed_stdin(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_GUARD_SCRIPT)],
            input="not json{{{",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == ""
