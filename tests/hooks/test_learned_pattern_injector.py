# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for learned pattern injector module.

Tests the CLI interface for the learned pattern injector used by
hooks to inject learned patterns into Claude Code sessions.

The injector always exits with code 0 for hook compatibility,
returning success=False in the JSON output for error cases.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# Path to the injector script
INJECTOR_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "learned_pattern_injector.py"
)


# =============================================================================
# Basic Existence Tests
# =============================================================================


class TestInjectorExists:
    """Tests for injector script existence."""

    def test_injector_exists(self) -> None:
        """Verify injector script exists."""
        assert INJECTOR_PATH.exists(), f"Injector not found at {INJECTOR_PATH}"

    def test_injector_is_file(self) -> None:
        """Verify injector is a file, not a directory."""
        assert INJECTOR_PATH.is_file(), f"Injector is not a file: {INJECTOR_PATH}"

    def test_injector_is_python(self) -> None:
        """Verify injector has .py extension."""
        assert INJECTOR_PATH.suffix == ".py", (
            f"Injector is not a Python file: {INJECTOR_PATH}"
        )


# =============================================================================
# Exit Code Tests
# =============================================================================


class TestExitCodes:
    """Tests for injector exit code behavior."""

    def test_always_exits_zero_with_valid_input(self) -> None:
        """Test injector exits 0 with valid JSON input."""
        input_data = json.dumps(
            {
                "agent_name": "test-agent",
                "domain": "",
                "max_patterns": 5,
                "min_confidence": 0.7,
            }
        )

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0, f"Injector failed: {result.stderr}"

    def test_always_exits_zero_with_invalid_json(self) -> None:
        """Test injector exits 0 even with invalid JSON input."""
        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0, "Injector should always exit 0"

    def test_always_exits_zero_with_empty_input(self) -> None:
        """Test injector exits 0 with empty input."""
        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0, "Injector should always exit 0 for empty input"

    def test_always_exits_zero_with_partial_input(self) -> None:
        """Test injector exits 0 with partial JSON input."""
        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input='{"agent_name": "test"',  # Missing closing brace
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0, (
            "Injector should always exit 0 for malformed JSON"
        )


# =============================================================================
# Output Structure Tests
# =============================================================================


class TestOutputStructure:
    """Tests for injector output JSON structure."""

    def test_output_has_required_fields(self) -> None:
        """Test output has all required fields."""
        input_data = json.dumps({"agent_name": "test"})

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        assert "success" in output
        assert "patterns_context" in output
        assert "pattern_count" in output
        assert "source" in output
        assert "retrieval_ms" in output

    def test_output_is_valid_json(self) -> None:
        """Test output is valid JSON."""
        input_data = json.dumps({"agent_name": "test"})

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        # Should not raise JSONDecodeError
        output = json.loads(result.stdout)
        assert isinstance(output, dict)

    def test_output_types_correct(self) -> None:
        """Test output field types are correct."""
        input_data = json.dumps({"agent_name": "test"})

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        assert isinstance(output["success"], bool)
        assert isinstance(output["patterns_context"], str)
        assert isinstance(output["pattern_count"], int)
        assert isinstance(output["source"], str)
        assert isinstance(output["retrieval_ms"], int)


# =============================================================================
# Empty/None Pattern Tests
# =============================================================================


class TestEmptyPatterns:
    """Tests for behavior when no patterns are available."""

    def test_empty_input_returns_success(self) -> None:
        """Test with minimal input returns success with empty patterns."""
        input_data = json.dumps(
            {
                "agent_name": "test-agent",
                "domain": "",
                "max_patterns": 5,
                "min_confidence": 0.7,
            }
        )

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True
        assert output["pattern_count"] == 0
        assert output["source"] == "none"

    def test_no_pattern_files_returns_empty(self) -> None:
        """Test returns empty patterns when no pattern files exist."""
        # Use a non-existent project path
        input_data = json.dumps(
            {
                "agent_name": "test",
                "project": "/nonexistent/path/to/project",
                "domain": "",
                "max_patterns": 10,
                "min_confidence": 0.5,
            }
        )

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        assert output["success"] is True
        assert output["pattern_count"] == 0


# =============================================================================
# Retrieval Timing Tests
# =============================================================================


class TestRetrievalTiming:
    """Tests for retrieval_ms field."""

    def test_retrieval_ms_is_numeric(self) -> None:
        """Test retrieval_ms is a non-negative integer."""
        input_data = json.dumps({"agent_name": "test"})

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        assert isinstance(output["retrieval_ms"], int)
        assert output["retrieval_ms"] >= 0

    def test_retrieval_ms_reasonable_range(self) -> None:
        """Test retrieval_ms is in reasonable range (< 10 seconds)."""
        input_data = json.dumps({"agent_name": "test"})

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        # Should be very fast when no patterns exist
        assert output["retrieval_ms"] < 10000  # Less than 10 seconds


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling behavior."""

    def test_invalid_json_returns_error_output(self) -> None:
        """Test invalid JSON input returns error output (not exception)."""
        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        # success is True for hook compatibility, but source indicates error
        assert output["success"] is True
        assert output["source"] == "error"
        assert output["pattern_count"] == 0

    def test_empty_string_input_handled(self) -> None:
        """Test empty string input is handled gracefully."""
        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        assert output["success"] is True
        assert output["pattern_count"] == 0

    def test_whitespace_only_input_handled(self) -> None:
        """Test whitespace-only input is handled gracefully."""
        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input="   \n\t  ",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = json.loads(result.stdout)
        assert output["success"] is True
        assert output["pattern_count"] == 0


# =============================================================================
# Input Parameter Tests
# =============================================================================


class TestInputParameters:
    """Tests for various input parameters."""

    def test_max_patterns_parameter(self) -> None:
        """Test max_patterns parameter is accepted."""
        input_data = json.dumps(
            {
                "agent_name": "test",
                "max_patterns": 10,
            }
        )

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True

    def test_min_confidence_parameter(self) -> None:
        """Test min_confidence parameter is accepted."""
        input_data = json.dumps(
            {
                "agent_name": "test",
                "min_confidence": 0.9,
            }
        )

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True

    def test_domain_parameter(self) -> None:
        """Test domain parameter is accepted."""
        input_data = json.dumps(
            {
                "agent_name": "test",
                "domain": "code_review",
            }
        )

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True

    def test_project_parameter(self) -> None:
        """Test project parameter is accepted."""
        input_data = json.dumps(
            {
                "agent_name": "test",
                "project": "/tmp",
            }
        )

        result = subprocess.run(
            [sys.executable, str(INJECTOR_PATH)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True


# =============================================================================
# Pattern File Loading Tests
# =============================================================================


class TestPatternFileLoading:
    """Tests for pattern file loading functionality."""

    def test_loads_patterns_from_project_directory(self) -> None:
        """Test loads patterns from project .claude directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pattern file in project
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "last_updated": "2025-01-20T00:00:00Z",
                        "patterns": [
                            {
                                "pattern_id": "test-pattern-1",
                                "domain": "testing",
                                "title": "Test Pattern",
                                "description": "A test pattern for unit testing.",
                                "confidence": 0.9,
                                "usage_count": 5,
                                "success_rate": 0.8,
                            }
                        ],
                    }
                )
            )

            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                    "domain": "",
                    "max_patterns": 10,
                    "min_confidence": 0.5,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output = json.loads(result.stdout)
            assert output["success"] is True
            assert output["pattern_count"] == 1
            assert str(pattern_file) in output["source"]
            assert "Test Pattern" in output["patterns_context"]

    def test_filters_by_domain(self) -> None:
        """Test patterns are filtered by domain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pattern file with multiple domains
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "last_updated": "2025-01-20T00:00:00Z",
                        "patterns": [
                            {
                                "pattern_id": "pattern-1",
                                "domain": "testing",
                                "title": "Testing Pattern",
                                "description": "For testing domain.",
                                "confidence": 0.9,
                                "usage_count": 5,
                                "success_rate": 0.8,
                            },
                            {
                                "pattern_id": "pattern-2",
                                "domain": "code_review",
                                "title": "Review Pattern",
                                "description": "For code review domain.",
                                "confidence": 0.85,
                                "usage_count": 3,
                                "success_rate": 0.7,
                            },
                        ],
                    }
                )
            )

            # Request only testing domain
            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                    "domain": "testing",
                    "max_patterns": 10,
                    "min_confidence": 0.5,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output = json.loads(result.stdout)
            assert output["success"] is True
            assert output["pattern_count"] == 1
            assert "Testing Pattern" in output["patterns_context"]
            assert "Review Pattern" not in output["patterns_context"]

    def test_filters_by_confidence(self) -> None:
        """Test patterns are filtered by minimum confidence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pattern file with varying confidence
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "last_updated": "2025-01-20T00:00:00Z",
                        "patterns": [
                            {
                                "pattern_id": "high-conf",
                                "domain": "testing",
                                "title": "High Confidence",
                                "description": "High confidence pattern.",
                                "confidence": 0.95,
                                "usage_count": 10,
                                "success_rate": 0.9,
                            },
                            {
                                "pattern_id": "low-conf",
                                "domain": "testing",
                                "title": "Low Confidence",
                                "description": "Low confidence pattern.",
                                "confidence": 0.5,
                                "usage_count": 2,
                                "success_rate": 0.6,
                            },
                        ],
                    }
                )
            )

            # Request only high confidence patterns
            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                    "domain": "",
                    "max_patterns": 10,
                    "min_confidence": 0.8,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output = json.loads(result.stdout)
            assert output["success"] is True
            assert output["pattern_count"] == 1
            assert "High Confidence" in output["patterns_context"]
            assert "Low Confidence" not in output["patterns_context"]

    def test_respects_max_patterns(self) -> None:
        """Test max_patterns limit is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pattern file with many patterns
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            patterns = [
                {
                    "pattern_id": f"pattern-{i}",
                    "domain": "testing",
                    "title": f"Pattern {i}",
                    "description": f"Description for pattern {i}.",
                    "confidence": 0.9 - (i * 0.01),  # Decreasing confidence
                    "usage_count": 5,
                    "success_rate": 0.8,
                }
                for i in range(10)
            ]
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "last_updated": "2025-01-20T00:00:00Z",
                        "patterns": patterns,
                    }
                )
            )

            # Request only 3 patterns
            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                    "domain": "",
                    "max_patterns": 3,
                    "min_confidence": 0.5,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output = json.loads(result.stdout)
            assert output["success"] is True
            assert output["pattern_count"] == 3


# =============================================================================
# Markdown Output Format Tests
# =============================================================================


class TestMarkdownOutput:
    """Tests for markdown output formatting."""

    def test_markdown_has_header(self) -> None:
        """Test markdown output has appropriate header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "last_updated": "2025-01-20T00:00:00Z",
                        "patterns": [
                            {
                                "pattern_id": "test-1",
                                "domain": "testing",
                                "title": "Test Pattern",
                                "description": "Test description.",
                                "confidence": 0.9,
                                "usage_count": 5,
                                "success_rate": 0.8,
                            }
                        ],
                    }
                )
            )

            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output = json.loads(result.stdout)
            assert "## Learned Patterns" in output["patterns_context"]

    def test_markdown_contains_pattern_title(self) -> None:
        """Test markdown output contains pattern titles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "last_updated": "2025-01-20T00:00:00Z",
                        "patterns": [
                            {
                                "pattern_id": "test-1",
                                "domain": "testing",
                                "title": "My Unique Pattern Title",
                                "description": "Test description.",
                                "confidence": 0.9,
                                "usage_count": 5,
                                "success_rate": 0.8,
                            }
                        ],
                    }
                )
            )

            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output = json.loads(result.stdout)
            assert "My Unique Pattern Title" in output["patterns_context"]

    def test_markdown_contains_domain_and_confidence(self) -> None:
        """Test markdown output contains domain and confidence info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "last_updated": "2025-01-20T00:00:00Z",
                        "patterns": [
                            {
                                "pattern_id": "test-1",
                                "domain": "code_review",
                                "title": "Test Pattern",
                                "description": "Test description.",
                                "confidence": 0.85,
                                "usage_count": 10,
                                "success_rate": 0.9,
                            }
                        ],
                    }
                )
            )

            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output = json.loads(result.stdout)
            context = output["patterns_context"]
            assert "code_review" in context
            assert "85%" in context  # Confidence as percentage
            assert "90%" in context  # Success rate as percentage


# =============================================================================
# Invalid Pattern File Tests
# =============================================================================


class TestInvalidPatternFiles:
    """Tests for handling invalid pattern files."""

    def test_handles_malformed_json_file(self) -> None:
        """Test handles malformed JSON in pattern file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text("not valid json {{{")

            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert output["success"] is True
            assert output["pattern_count"] == 0

    def test_handles_missing_pattern_fields(self) -> None:
        """Test handles pattern entries with missing required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            pattern_file = claude_dir / "learned_patterns.json"
            pattern_file.write_text(
                json.dumps(
                    {
                        "version": "1.0.0",
                        "patterns": [
                            {
                                "pattern_id": "incomplete",
                                # Missing required fields
                            }
                        ],
                    }
                )
            )

            input_data = json.dumps(
                {
                    "agent_name": "test",
                    "project": tmpdir,
                }
            )

            result = subprocess.run(
                [sys.executable, str(INJECTOR_PATH)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert output["success"] is True
            # Invalid pattern should be skipped
            assert output["pattern_count"] == 0
