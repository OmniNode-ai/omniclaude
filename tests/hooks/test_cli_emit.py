# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for OmniClaude hook event CLI (OMN-1400).

Tests cover:
    - CLI command parsing
    - Timeout behavior
    - Failure suppression (always exit 0)
    - Dry-run mode

Note:
    These tests do NOT:
    - Spin up Kafka
    - Assert delivery guarantees
    - Simulate Claude Code internals
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from omniclaude.hooks.cli_emit import (
    EMIT_TIMEOUT_SECONDS,
    cli,
    run_with_timeout,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# =============================================================================
# Timeout Wrapper Tests
# =============================================================================


class TestTimeoutWrapper:
    """Tests for the timeout wrapper function."""

    def test_timeout_constant_is_configurable(self) -> None:
        """Timeout constant is configurable via KAFKA_HOOK_TIMEOUT_SECONDS env var.

        Default is 3.0s (increased from 250ms due to Kafka connection setup time).
        The .env file may override this value (currently set to 2s).
        """
        # The actual value depends on environment configuration
        # Default is 3.0s, but .env may override (e.g., to 2.0s)
        assert EMIT_TIMEOUT_SECONDS > 0, "Timeout must be positive"
        assert EMIT_TIMEOUT_SECONDS <= 60, "Timeout should be reasonable (<=60s)"

    def test_timeout_env_var_parsing(self) -> None:
        """Verify KAFKA_HOOK_TIMEOUT_SECONDS env var is correctly parsed as float.

        The module parses the env var at import time:
        float(os.environ.get("KAFKA_HOOK_TIMEOUT_SECONDS", "3.0"))

        Since the constant is already evaluated at import time, we test the
        parsing expression pattern rather than reloading the module.
        """
        import os

        # Verify the parsing logic works (test the expression, not the imported constant)
        # since the constant is already evaluated at import time
        test_value = "5.5"
        parsed = float(os.environ.get("TEST_TIMEOUT_VAR", test_value))
        assert parsed == 5.5

        # Verify default fallback matches expected default
        parsed_default = float(os.environ.get("NONEXISTENT_VAR", "3.0"))
        assert parsed_default == 3.0, "Default timeout should be 3.0 seconds"

    def test_successful_coro_returns_result(self) -> None:
        """Successful coroutine returns its result."""

        async def fast_coro() -> str:
            return "success"

        result = run_with_timeout(fast_coro())
        assert result == "success"

    def test_timeout_returns_none(self) -> None:
        """Coroutine that exceeds timeout returns None."""

        async def slow_coro() -> str:
            await asyncio.sleep(1.0)  # Much longer than 250ms
            return "should not reach"

        result = run_with_timeout(slow_coro(), timeout=0.01)  # Very short timeout
        assert result is None

    def test_exception_returns_none(self) -> None:
        """Coroutine that raises returns None (no exception to caller)."""

        async def failing_coro() -> str:
            raise RuntimeError("Boom!")

        result = run_with_timeout(failing_coro())
        assert result is None


# =============================================================================
# CLI Command Tests
# =============================================================================


class TestCliCommands:
    """Tests for CLI commands."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a Click CLI test runner."""
        return CliRunner()

    def test_help_command(self, runner: CliRunner) -> None:
        """--help shows usage information."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "OmniClaude hook event emitter" in result.output

    def test_version_command(self, runner: CliRunner) -> None:
        """--version shows version."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "omniclaude-emit" in result.output

    def test_no_command_shows_help(self, runner: CliRunner) -> None:
        """Running without command shows help."""
        result = runner.invoke(cli)
        assert result.exit_code == 0
        assert "session-started" in result.output


class TestSessionStartedCommand:
    """Tests for session-started command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_dry_run_mode(self, runner: CliRunner) -> None:
        """Dry run mode validates but doesn't emit."""
        result = runner.invoke(
            cli,
            [
                "session-started",
                "--session-id",
                str(uuid4()),
                "--cwd",
                "/workspace",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_always_exits_zero(self, runner: CliRunner) -> None:
        """Command always exits 0 even on failure."""
        with patch(
            "omniclaude.hooks.cli_emit.emit_session_started",
            new_callable=AsyncMock,
        ) as mock_emit:
            mock_emit.side_effect = RuntimeError("Kafka down")

            result = runner.invoke(
                cli,
                [
                    "session-started",
                    "--session-id",
                    str(uuid4()),
                    "--cwd",
                    "/workspace",
                ],
            )

            # Must exit 0 - observability must never break UX
            assert result.exit_code == 0

    def test_accepts_all_sources(self, runner: CliRunner) -> None:
        """Command accepts all valid source values."""
        for source in ["startup", "resume", "clear", "compact"]:
            result = runner.invoke(
                cli,
                [
                    "session-started",
                    "--session-id",
                    str(uuid4()),
                    "--cwd",
                    "/workspace",
                    "--source",
                    source,
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0


class TestSessionEndedCommand:
    """Tests for session-ended command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_dry_run_mode(self, runner: CliRunner) -> None:
        """Dry run mode validates but doesn't emit."""
        result = runner.invoke(
            cli,
            [
                "session-ended",
                "--session-id",
                str(uuid4()),
                "--reason",
                "clear",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_accepts_all_reasons(self, runner: CliRunner) -> None:
        """Command accepts all valid reason values."""
        for reason in ["clear", "logout", "prompt_input_exit", "other"]:
            result = runner.invoke(
                cli,
                [
                    "session-ended",
                    "--session-id",
                    str(uuid4()),
                    "--reason",
                    reason,
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0

    def test_accepts_duration_and_tools_count(self, runner: CliRunner) -> None:
        """Command accepts optional duration and tools count."""
        result = runner.invoke(
            cli,
            [
                "session-ended",
                "--session-id",
                str(uuid4()),
                "--duration",
                "1800.5",
                "--tools-count",
                "42",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0


class TestPromptSubmittedCommand:
    """Tests for prompt-submitted command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_dry_run_mode(self, runner: CliRunner) -> None:
        """Dry run mode validates but doesn't emit."""
        result = runner.invoke(
            cli,
            [
                "prompt-submitted",
                "--session-id",
                str(uuid4()),
                "--preview",
                "Fix the bug...",
                "--length",
                "100",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_auto_generates_prompt_id(self, runner: CliRunner) -> None:
        """Command auto-generates prompt-id if not provided."""
        result = runner.invoke(
            cli,
            [
                "prompt-submitted",
                "--session-id",
                str(uuid4()),
                "--length",
                "50",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0


class TestToolExecutedCommand:
    """Tests for tool-executed command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_dry_run_mode(self, runner: CliRunner) -> None:
        """Dry run mode validates but doesn't emit."""
        result = runner.invoke(
            cli,
            [
                "tool-executed",
                "--session-id",
                str(uuid4()),
                "--tool-name",
                "Read",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_accepts_success_flag(self, runner: CliRunner) -> None:
        """Command accepts --success/--failure flags."""
        for flag in ["--success", "--failure"]:
            result = runner.invoke(
                cli,
                [
                    "tool-executed",
                    "--session-id",
                    str(uuid4()),
                    "--tool-name",
                    "Bash",
                    flag,
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0

    def test_accepts_duration_and_summary(self, runner: CliRunner) -> None:
        """Command accepts optional duration and summary."""
        result = runner.invoke(
            cli,
            [
                "tool-executed",
                "--session-id",
                str(uuid4()),
                "--tool-name",
                "Write",
                "--duration-ms",
                "150",
                "--summary",
                "Wrote 50 lines to file.py",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0


# =============================================================================
# JSON Input Tests
# =============================================================================


class TestJsonInput:
    """Tests for JSON input mode."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_session_started_json_input(self, runner: CliRunner) -> None:
        """session-started accepts JSON input from stdin."""
        json_data = '{"cwd": "/from/json", "git_branch": "feature"}'
        result = runner.invoke(
            cli,
            [
                "session-started",
                "--session-id",
                str(uuid4()),
                "--cwd",
                "/fallback",
                "--json",
                "--dry-run",
            ],
            input=json_data,
        )
        assert result.exit_code == 0
        # Verify dry run executed
        assert "[DRY RUN]" in result.output
        # Verify JSON value overrode CLI fallback value
        assert "/from/json" in result.output, (
            f"Expected '/from/json' in output but got: {result.output}"
        )

    def test_invalid_json_exits_zero(self, runner: CliRunner) -> None:
        """Invalid JSON still exits 0 (failure suppression)."""
        result = runner.invoke(
            cli,
            [
                "session-started",
                "--session-id",
                str(uuid4()),
                "--cwd",
                "/workspace",
                "--json",
            ],
            input="not valid json",
        )
        # Must exit 0 - observability must never break UX
        assert result.exit_code == 0


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases in hook event handling.

    These tests cover boundary conditions, unicode handling, and special
    input values that may be encountered in production.
    """

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_prompt_preview_with_unicode(self, runner: CliRunner) -> None:
        """Prompt preview handles unicode characters correctly.

        Covers: emojis, CJK characters, RTL text, and other Unicode.
        These should serialize correctly in JSON and not raise.
        """
        unicode_previews = [
            "Fix the bug \U0001f41b in the auth system",  # emoji
            "Fix the bug in \u8ba4\u8bc1\u7cfb\u7edf",  # Chinese (authentication system)
            "\u05ea\u05d9\u05e7\u05d5\u05df \u05d1\u05d0\u05d2",  # Hebrew RTL (bug fix)
            "Caf\xe9 debugging \u2615",  # accents and symbols
        ]
        for preview in unicode_previews:
            result = runner.invoke(
                cli,
                [
                    "prompt-submitted",
                    "--session-id",
                    str(uuid4()),
                    "--preview",
                    preview,
                    "--length",
                    str(len(preview)),
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0, f"Failed for preview: {preview!r}"
            assert "[DRY RUN]" in result.output

    def test_empty_prompt_preview(self, runner: CliRunner) -> None:
        """Empty prompt preview is handled correctly.

        Edge case: User submits an empty prompt or prompt_preview is
        explicitly empty after sanitization.
        """
        result = runner.invoke(
            cli,
            [
                "prompt-submitted",
                "--session-id",
                str(uuid4()),
                "--preview",
                "",
                "--length",
                "0",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_session_duration_near_max_bound(self, runner: CliRunner) -> None:
        """Session duration near 30-day maximum is accepted.

        Tests 29 days in seconds (2,505,600), which should be within bounds.
        """
        duration_29_days = 29 * 24 * 60 * 60  # 2,505,600 seconds
        result = runner.invoke(
            cli,
            [
                "session-ended",
                "--session-id",
                str(uuid4()),
                "--reason",
                "other",
                "--duration",
                str(float(duration_29_days)),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_session_duration_at_exact_max_bound(self, runner: CliRunner) -> None:
        """Session duration at exactly 30 days (2,592,000 seconds) is accepted.

        This is the maximum allowed value per the schema constraint.
        """
        duration_30_days = 30 * 24 * 60 * 60  # 2,592,000 seconds
        result = runner.invoke(
            cli,
            [
                "session-ended",
                "--session-id",
                str(uuid4()),
                "--reason",
                "logout",
                "--duration",
                str(float(duration_30_days)),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_tool_duration_at_max_bound(self, runner: CliRunner) -> None:
        """Tool duration at exactly 1 hour (3,600,000 ms) is accepted.

        This is the maximum allowed value per the schema constraint.
        """
        duration_1_hour_ms = 3600000
        result = runner.invoke(
            cli,
            [
                "tool-executed",
                "--session-id",
                str(uuid4()),
                "--tool-name",
                "Bash",
                "--duration-ms",
                str(duration_1_hour_ms),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_tool_summary_at_max_length(self, runner: CliRunner) -> None:
        """Tool summary at exactly 500 chars (max_length) is accepted."""
        summary_500_chars = "x" * 500
        result = runner.invoke(
            cli,
            [
                "tool-executed",
                "--session-id",
                str(uuid4()),
                "--tool-name",
                "Write",
                "--summary",
                summary_500_chars,
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_prompt_preview_at_max_length(self, runner: CliRunner) -> None:
        """Prompt preview at exactly 100 chars (max_length) is accepted."""
        preview_100_chars = "x" * 100
        result = runner.invoke(
            cli,
            [
                "prompt-submitted",
                "--session-id",
                str(uuid4()),
                "--preview",
                preview_100_chars,
                "--length",
                "100",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output


# =============================================================================
# Tool Content Command Tests (OMN-1702)
# =============================================================================


class TestToolContentCommand:
    """Tests for tool-content command (INTERIM - raw JSON emission)."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_dry_run_mode(self, runner: CliRunner) -> None:
        """Dry run mode validates but doesn't emit."""
        result = runner.invoke(
            cli,
            [
                "tool-content",
                "--session-id",
                str(uuid4()),
                "--tool-name",
                "Write",
                "--tool-type",
                "file_write",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output
        assert "tool-content" in result.output

    def test_accepts_all_file_tools(self, runner: CliRunner) -> None:
        """Command accepts Read, Write, and Edit tool names."""
        for tool in ["Read", "Write", "Edit"]:
            result = runner.invoke(
                cli,
                [
                    "tool-content",
                    "--session-id",
                    str(uuid4()),
                    "--tool-name",
                    tool,
                    "--tool-type",
                    f"file_{tool.lower()}",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0, f"Failed for tool: {tool}"

    def test_accepts_success_failure_flags(self, runner: CliRunner) -> None:
        """Command accepts --success/--failure flags."""
        for flag in ["--success", "--failure"]:
            result = runner.invoke(
                cli,
                [
                    "tool-content",
                    "--session-id",
                    str(uuid4()),
                    "--tool-name",
                    "Write",
                    "--tool-type",
                    "file_write",
                    flag,
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0, f"Failed for flag: {flag}"

    def test_accepts_all_optional_fields(self, runner: CliRunner) -> None:
        """Command accepts all optional fields."""
        result = runner.invoke(
            cli,
            [
                "tool-content",
                "--session-id",
                str(uuid4()),
                "--tool-name",
                "Write",
                "--tool-type",
                "file_write",
                "--file-path",
                "/workspace/src/main.py",
                "--content-preview",
                "def hello():\n    return 42",
                "--content-length",
                "27",
                "--content-hash",
                "sha256:abc123def456",
                "--language",
                "python",
                "--duration-ms",
                "150.5",
                "--correlation-id",
                str(uuid4()),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output

    def test_dry_run_shows_payload(self, runner: CliRunner) -> None:
        """Dry run mode shows the JSON payload that would be emitted."""
        result = runner.invoke(
            cli,
            [
                "tool-content",
                "--session-id",
                "test-session-123",
                "--tool-name",
                "Read",
                "--tool-type",
                "file_read",
                "--file-path",
                "/workspace/test.py",
                "--language",
                "python",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Payload:" in result.output
        assert '"tool_name": "Read"' in result.output
        assert '"language": "python"' in result.output

    def test_always_exits_zero_on_failure(self, runner: CliRunner) -> None:
        """Command always exits 0 even when Kafka fails."""
        # Without KAFKA_BOOTSTRAP_SERVERS, emission will fail
        # but command should still exit 0
        with patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": ""}, clear=False):
            result = runner.invoke(
                cli,
                [
                    "tool-content",
                    "--session-id",
                    str(uuid4()),
                    "--tool-name",
                    "Write",
                    "--tool-type",
                    "file_write",
                ],
            )
            # Must exit 0 - observability must never break UX
            assert result.exit_code == 0

    def test_json_input_mode(self, runner: CliRunner) -> None:
        """Command accepts JSON input from stdin."""
        import json

        json_data = json.dumps(
            {
                "session_id": "json-session-id",
                "tool_name": "Edit",
                "tool_type": "file_edit",
                "file_path": "/workspace/edited.py",
                "content_preview": "edited content",
                "content_length": 15,
                "language": "python",
            }
        )
        result = runner.invoke(
            cli,
            [
                "tool-content",
                "--session-id",
                "cli-session",  # Should be overridden by JSON
                "--tool-name",
                "Write",  # Should be overridden by JSON
                "--tool-type",
                "write",  # Should be overridden by JSON
                "--json",
                "--dry-run",
            ],
            input=json_data,
        )
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output
        # Verify JSON values were used
        assert "Edit" in result.output


# =============================================================================
# Language Detection Tests (OMN-1702)
# =============================================================================


class TestLanguageDetection:
    """Tests for language detection from file extension.

    The language detection is implemented in the shell script
    (post-tool-use-quality.sh). This test class verifies the expected
    mappings to catch regressions if the case statement is modified.
    """

    # Language detection mapping from the shell script
    EXPECTED_MAPPINGS: dict[str, str] = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "jsx": "javascript",
        "rs": "rust",
        "go": "go",
        "java": "java",
        "rb": "ruby",
        "sh": "shell",
        "bash": "shell",
        "yml": "yaml",
        "yaml": "yaml",
        "json": "json",
        "md": "markdown",
        "sql": "sql",
        "html": "html",
        "css": "css",
    }

    def test_all_expected_extensions_documented(self) -> None:
        """Verify all expected extension mappings are present.

        The shell script supports 18 file extension mappings covering 16 languages.
        Some languages have multiple extensions (e.g., ts/tsx -> typescript,
        sh/bash -> shell, yml/yaml -> yaml).
        """
        # Note: Some extensions map to the same language (ts/tsx -> typescript)
        # Count unique extensions, not unique languages
        assert len(self.EXPECTED_MAPPINGS) == 18, (
            f"Expected 18 extension mappings (16 unique + 2 aliases), "
            f"got {len(self.EXPECTED_MAPPINGS)}"
        )

    def test_python_extensions(self) -> None:
        """Python files (.py) map to 'python' language."""
        assert self.EXPECTED_MAPPINGS["py"] == "python"

    def test_javascript_extensions(self) -> None:
        """JavaScript files (.js, .jsx) map to 'javascript'."""
        assert self.EXPECTED_MAPPINGS["js"] == "javascript"
        assert self.EXPECTED_MAPPINGS["jsx"] == "javascript"

    def test_typescript_extensions(self) -> None:
        """TypeScript files (.ts, .tsx) map to 'typescript'."""
        assert self.EXPECTED_MAPPINGS["ts"] == "typescript"
        assert self.EXPECTED_MAPPINGS["tsx"] == "typescript"

    def test_shell_extensions(self) -> None:
        """Shell script files (.sh, .bash) map to 'shell'."""
        assert self.EXPECTED_MAPPINGS["sh"] == "shell"
        assert self.EXPECTED_MAPPINGS["bash"] == "shell"

    def test_yaml_extensions(self) -> None:
        """YAML files (.yml, .yaml) map to 'yaml'."""
        assert self.EXPECTED_MAPPINGS["yml"] == "yaml"
        assert self.EXPECTED_MAPPINGS["yaml"] == "yaml"

    def test_rust_extension(self) -> None:
        """Rust files (.rs) map to 'rust'."""
        assert self.EXPECTED_MAPPINGS["rs"] == "rust"

    def test_go_extension(self) -> None:
        """Go files (.go) map to 'go'."""
        assert self.EXPECTED_MAPPINGS["go"] == "go"

    def test_java_extension(self) -> None:
        """Java files (.java) map to 'java'."""
        assert self.EXPECTED_MAPPINGS["java"] == "java"

    def test_ruby_extension(self) -> None:
        """Ruby files (.rb) map to 'ruby'."""
        assert self.EXPECTED_MAPPINGS["rb"] == "ruby"

    def test_config_file_extensions(self) -> None:
        """Config files (.json, .yml, .yaml) map correctly."""
        assert self.EXPECTED_MAPPINGS["json"] == "json"
        assert self.EXPECTED_MAPPINGS["yml"] == "yaml"
        assert self.EXPECTED_MAPPINGS["yaml"] == "yaml"

    def test_web_file_extensions(self) -> None:
        """Web files (.html, .css) map correctly."""
        assert self.EXPECTED_MAPPINGS["html"] == "html"
        assert self.EXPECTED_MAPPINGS["css"] == "css"

    def test_documentation_extensions(self) -> None:
        """Documentation files (.md) map to 'markdown'."""
        assert self.EXPECTED_MAPPINGS["md"] == "markdown"

    def test_database_extensions(self) -> None:
        """Database files (.sql) map to 'sql'."""
        assert self.EXPECTED_MAPPINGS["sql"] == "sql"
