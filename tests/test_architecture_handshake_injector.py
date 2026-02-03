#!/usr/bin/env python3
"""Unit tests for architecture_handshake_injector.py module.

Tests the architecture handshake injection functionality used by SessionStart hooks
to inject repo-specific architecture constraints from .claude/architecture-handshake.md.

Part of OMN-1860: Architecture handshake injection.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Import the module under test
# conftest.py already adds plugins/onex/hooks/lib to sys.path
import architecture_handshake_injector
from architecture_handshake_injector import (
    find_handshake,
    read_handshake,
)


class TestFindHandshake:
    """Tests for find_handshake() function."""

    def test_find_handshake_no_directory(self, tmp_path: Path) -> None:
        """Returns None when project directory doesn't exist."""
        nonexistent_dir = tmp_path / "nonexistent" / "project"

        result = find_handshake(nonexistent_dir)

        assert result is None

    def test_find_handshake_no_claude_dir(self, tmp_path: Path) -> None:
        """Returns None when .claude directory doesn't exist."""
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True)

        result = find_handshake(project_dir)

        assert result is None

    def test_find_handshake_no_handshake_file(self, tmp_path: Path) -> None:
        """Returns None when .claude exists but no handshake file."""
        project_dir = tmp_path / "project"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        result = find_handshake(project_dir)

        assert result is None

    def test_find_handshake_found(self, tmp_path: Path) -> None:
        """Returns path when handshake file exists."""
        project_dir = tmp_path / "project"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        # Create handshake file
        handshake_path = claude_dir / "architecture-handshake.md"
        handshake_path.write_text("# Architecture Handshake\n\nConstraints here.")

        result = find_handshake(project_dir)

        assert result is not None
        assert result == handshake_path
        assert result.exists()

    def test_find_handshake_path_is_file_not_directory(self, tmp_path: Path) -> None:
        """Returns None when project path is a file, not a directory."""
        project_file = tmp_path / "project"
        project_file.touch()  # Create as file, not directory

        result = find_handshake(project_file)

        assert result is None

    def test_find_handshake_handshake_is_directory(self, tmp_path: Path) -> None:
        """Returns None when handshake path exists but is a directory."""
        project_dir = tmp_path / "project"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        # Create handshake as directory (should be ignored)
        handshake_dir = claude_dir / "architecture-handshake.md"
        handshake_dir.mkdir()

        result = find_handshake(project_dir)

        assert result is None

    def test_find_handshake_none_uses_cwd(self, tmp_path: Path) -> None:
        """When project_path is None, uses current working directory."""
        import os

        # Save current directory
        original_cwd = os.getcwd()

        try:
            # Set up a project with handshake in tmp_path
            claude_dir = tmp_path / ".claude"
            claude_dir.mkdir(parents=True)
            handshake_path = claude_dir / "architecture-handshake.md"
            handshake_path.write_text("# CWD Handshake")

            # Change to tmp_path
            os.chdir(tmp_path)

            result = find_handshake(None)

            assert result is not None
            assert result == handshake_path

        finally:
            # Restore original directory
            os.chdir(original_cwd)


class TestReadHandshake:
    """Tests for read_handshake() function."""

    def test_read_handshake_success(self, tmp_path: Path) -> None:
        """Returns content when file exists and is readable."""
        handshake_path = tmp_path / "architecture-handshake.md"
        expected_content = "# Architecture Handshake\n\n- Constraint 1\n- Constraint 2"
        handshake_path.write_text(expected_content)

        result = read_handshake(handshake_path)

        assert result == expected_content

    def test_read_handshake_nonexistent_file(self, tmp_path: Path) -> None:
        """Returns empty string when file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.md"

        result = read_handshake(nonexistent)

        assert result == ""

    def test_read_handshake_empty_file(self, tmp_path: Path) -> None:
        """Returns empty string for empty file."""
        handshake_path = tmp_path / "architecture-handshake.md"
        handshake_path.touch()  # Empty file

        result = read_handshake(handshake_path)

        assert result == ""

    def test_read_handshake_path_is_directory(self, tmp_path: Path) -> None:
        """Returns empty string when path is a directory."""
        dir_path = tmp_path / "somedir"
        dir_path.mkdir()

        result = read_handshake(dir_path)

        assert result == ""

    def test_read_handshake_unicode_content(self, tmp_path: Path) -> None:
        """Handles Unicode content correctly."""
        handshake_path = tmp_path / "architecture-handshake.md"
        expected_content = "# 架构握手\n\n- 约束条件 ñ é ü 🚀"
        handshake_path.write_text(expected_content, encoding="utf-8")

        result = read_handshake(handshake_path)

        assert result == expected_content

    def test_read_handshake_large_file(self, tmp_path: Path) -> None:
        """Handles large files correctly."""
        handshake_path = tmp_path / "architecture-handshake.md"
        # Create a ~100KB file
        expected_content = "# Large Handshake\n\n" + ("x" * 1000 + "\n") * 100
        handshake_path.write_text(expected_content)

        result = read_handshake(handshake_path)

        assert result == expected_content
        assert len(result) > 100000


class TestOutputHelpers:
    """Tests for output helper functions."""

    def test_create_empty_output_returns_success(self) -> None:
        """_create_empty_output returns success=True for hook compatibility."""
        result = architecture_handshake_injector._create_empty_output(retrieval_ms=100)

        # CRITICAL: Always success=True for hook compatibility
        assert result["success"] is True
        assert result["handshake_context"] == ""
        assert result["handshake_path"] is None
        assert result["retrieval_ms"] == 100

    def test_create_empty_output_tracks_retrieval_time(self) -> None:
        """_create_empty_output properly tracks retrieval_ms parameter."""
        result = architecture_handshake_injector._create_empty_output(retrieval_ms=42)
        assert result["retrieval_ms"] == 42

        result_zero = architecture_handshake_injector._create_empty_output(
            retrieval_ms=0
        )
        assert result_zero["retrieval_ms"] == 0


class TestCliMain:
    """Tests for CLI main() function via subprocess."""

    def _run_cli(self, input_json: str) -> dict:
        """Helper to run the CLI and parse output."""
        script_path = (
            Path(__file__).parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
            / "architecture_handshake_injector.py"
        )

        result = subprocess.run(
            [sys.executable, str(script_path)],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # We check returncode manually below
        )

        # Should always exit 0 for hook compatibility
        assert result.returncode == 0, (
            f"CLI returned {result.returncode}: {result.stderr}"
        )

        return json.loads(result.stdout)

    def test_cli_main_no_input(self) -> None:
        """CLI returns success with valid output for empty JSON input.

        Note: When no project_path is provided, CLI uses CWD which may have
        a handshake file. We only verify the output structure is valid.
        """
        output = self._run_cli("{}")

        assert output["success"] is True
        assert "handshake_context" in output
        assert isinstance(output["handshake_context"], str)
        assert "retrieval_ms" in output

    def test_cli_main_empty_string_input(self) -> None:
        """CLI handles completely empty input gracefully.

        Note: When no project_path is provided, CLI uses CWD which may have
        a handshake file. We only verify the output structure is valid.
        """
        output = self._run_cli("")

        assert output["success"] is True
        assert "handshake_context" in output
        assert isinstance(output["handshake_context"], str)

    def test_cli_main_invalid_json(self) -> None:
        """CLI handles invalid JSON input gracefully (exits 0)."""
        output = self._run_cli("this is not json {{{")

        # CRITICAL: Must still succeed for hook compatibility
        assert output["success"] is True
        assert output["handshake_context"] == ""

    def test_cli_main_with_project_path(self, tmp_path: Path) -> None:
        """CLI respects project_path parameter."""
        project_dir = tmp_path / "my_project"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        # Create handshake file
        expected_content = "# Test Architecture\n\n- Rule 1\n- Rule 2"
        handshake_path = claude_dir / "architecture-handshake.md"
        handshake_path.write_text(expected_content)

        input_json = json.dumps({"project_path": str(project_dir)})
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["handshake_context"] == expected_content
        assert output["handshake_path"] == str(handshake_path)

    def test_cli_main_with_cwd_parameter(self, tmp_path: Path) -> None:
        """CLI respects cwd parameter (alternative to project_path)."""
        project_dir = tmp_path / "cwd_project"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        expected_content = "# CWD Handshake"
        handshake_path = claude_dir / "architecture-handshake.md"
        handshake_path.write_text(expected_content)

        # Use 'cwd' instead of 'project_path'
        input_json = json.dumps({"cwd": str(project_dir)})
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["handshake_context"] == expected_content

    def test_cli_main_project_path_takes_precedence(self, tmp_path: Path) -> None:
        """project_path takes precedence over cwd when both provided."""
        # Create two projects
        project1 = tmp_path / "project1"
        (project1 / ".claude").mkdir(parents=True)
        (project1 / ".claude" / "architecture-handshake.md").write_text("Project 1")

        project2 = tmp_path / "project2"
        (project2 / ".claude").mkdir(parents=True)
        (project2 / ".claude" / "architecture-handshake.md").write_text("Project 2")

        # Provide both project_path and cwd
        input_json = json.dumps(
            {
                "project_path": str(project1),
                "cwd": str(project2),
            }
        )
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["handshake_context"] == "Project 1"

    def test_cli_main_nonexistent_project_path(self, tmp_path: Path) -> None:
        """CLI returns empty context when project_path doesn't exist."""
        nonexistent = tmp_path / "does_not_exist"

        input_json = json.dumps({"project_path": str(nonexistent)})
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["handshake_context"] == ""
        assert output["handshake_path"] is None

    def test_cli_main_no_handshake_in_project(self, tmp_path: Path) -> None:
        """CLI returns empty context when project has no handshake file."""
        project_dir = tmp_path / "no_handshake"
        project_dir.mkdir(parents=True)

        input_json = json.dumps({"project_path": str(project_dir)})
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["handshake_context"] == ""
        assert output["handshake_path"] is None

    def test_cli_main_retrieval_time_tracked(self) -> None:
        """CLI tracks retrieval time in milliseconds."""
        output = self._run_cli("{}")

        assert "retrieval_ms" in output
        assert isinstance(output["retrieval_ms"], int)
        assert output["retrieval_ms"] >= 0


class TestIntegrationScenarios:
    """Integration tests for realistic usage scenarios."""

    def test_full_workflow_find_and_read(self, tmp_path: Path) -> None:
        """Complete workflow: find handshake and read content."""
        project_dir = tmp_path / "my_repo"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        # Realistic handshake content
        handshake_content = """# Architecture Handshake - my_repo

## Repository Invariants

- All API responses must use JSON
- Database migrations must be reversible
- No backwards compatibility breaks without deprecation

## Testing Requirements

- Unit tests for all business logic
- Integration tests for API endpoints
- Minimum 80% code coverage

## Performance Constraints

- API response time < 200ms (p95)
- No N+1 queries
"""
        handshake_path = claude_dir / "architecture-handshake.md"
        handshake_path.write_text(handshake_content)

        # Step 1: Find handshake
        found_path = find_handshake(project_dir)
        assert found_path is not None
        assert found_path == handshake_path

        # Step 2: Read content
        content = read_handshake(found_path)
        assert "Repository Invariants" in content
        assert "Testing Requirements" in content
        assert "Performance Constraints" in content

    def test_cli_integration_with_real_handshake(self, tmp_path: Path) -> None:
        """CLI correctly processes a realistic handshake file."""
        project_dir = tmp_path / "production_repo"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        handshake_content = """# Architecture Handshake

## Key Constraints

1. Use dependency injection
2. Follow SOLID principles
3. Document all public APIs
"""
        handshake_path = claude_dir / "architecture-handshake.md"
        handshake_path.write_text(handshake_content)

        script_path = (
            Path(__file__).parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
            / "architecture_handshake_injector.py"
        )

        result = subprocess.run(
            [sys.executable, str(script_path)],
            input=json.dumps({"project_path": str(project_dir)}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["success"] is True
        assert "Key Constraints" in output["handshake_context"]
        assert "dependency injection" in output["handshake_context"]
        assert str(handshake_path) == output["handshake_path"]

    def test_graceful_degradation_no_handshake(self, tmp_path: Path) -> None:
        """System gracefully handles missing handshake (common case)."""
        # Most repos won't have a handshake file yet
        project_dir = tmp_path / "repo_without_handshake"
        project_dir.mkdir(parents=True)

        # No .claude directory at all
        found_path = find_handshake(project_dir)
        assert found_path is None

        # CLI also handles this gracefully
        script_path = (
            Path(__file__).parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
            / "architecture_handshake_injector.py"
        )

        result = subprocess.run(
            [sys.executable, str(script_path)],
            input=json.dumps({"project_path": str(project_dir)}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["success"] is True
        assert output["handshake_context"] == ""
        assert output["handshake_path"] is None

    def test_handles_special_characters_in_path(self, tmp_path: Path) -> None:
        """Handles project paths with special characters."""
        # Path with spaces and unicode
        project_dir = tmp_path / "my project (copy) ñ"
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(parents=True)

        handshake_path = claude_dir / "architecture-handshake.md"
        handshake_path.write_text("# Special Path Handshake")

        found_path = find_handshake(project_dir)
        assert found_path is not None

        content = read_handshake(found_path)
        assert content == "# Special Path Handshake"
