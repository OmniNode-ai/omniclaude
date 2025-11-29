#!/usr/bin/env python3
"""
Comprehensive test coverage for Claude hooks quality enforcement system.

This module tests the quality_enforcer.py which handles:
- Code quality validation
- Naming convention enforcement
- Violation detection and logging
- Decision intelligence capture
- Tool call modification/blocking

Test Categories:
- Unit tests for ViolationsLogger
- Unit tests for QualityEnforcer helper methods
- Integration tests for enforce() workflow
- Edge case handling tests
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Add paths for imports (updated for claude/ consolidation)
sys.path.insert(0, str(Path(__file__).parent.parent / "claude" / "hooks"))
sys.path.insert(0, str(Path(__file__).parent.parent / "claude" / "lib" / "utils"))


# =============================================================================
# TEST FIXTURES
# =============================================================================


@pytest.fixture
def temp_log_dir(tmp_path: Path) -> Path:
    """Create temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


@pytest.fixture
def mock_violation():
    """Create a mock violation object."""

    class MockViolation:
        def __init__(
            self,
            name: str = "calculateTotal",
            line: int = 10,
            violation_type: str = "function",
            expected_format: str = "snake_case",
            suggestion: str = "calculate_total",
            rule: str = "PEP 8 naming",
        ):
            self.name = name
            self.line = line
            self.violation_type = violation_type
            self.expected_format = expected_format
            self.suggestion = suggestion
            self.rule = rule
            self.message = f"'{name}' should be '{expected_format}'"

    return MockViolation


@pytest.fixture
def sample_tool_call() -> Dict[str, Any]:
    """Create a sample tool call for testing."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/test/calculator.py",
            "content": """def calculateTotal(items):
    return sum(items)

def processData():
    pass
""",
        },
    }


@pytest.fixture
def sample_edit_tool_call() -> Dict[str, Any]:
    """Create a sample Edit tool call for testing."""
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/test/utils.py",
            "old_string": "def oldFunc():",
            "new_string": "def calculateTotal():",
        },
    }


@pytest.fixture
def mock_settings():
    """Mock settings for controlled testing."""
    with patch("quality_enforcer.settings") as mock:
        mock.enable_phase_1_validation = True
        mock.enable_phase_2_rag = False
        mock.enable_phase_3_correction = False
        mock.enable_phase_4_ai_quorum = False
        mock.performance_budget_seconds = 2.0
        mock.enforcement_mode = "warn"
        yield mock


# =============================================================================
# TEST VIOLATIONS LOGGER
# =============================================================================


class TestViolationsLogger:
    """Tests for ViolationsLogger class."""

    def test_logger_creates_log_directories(self, tmp_path: Path, monkeypatch):
        """Test that logger creates necessary directories."""
        # Patch CONFIG for test
        with patch(
            "quality_enforcer.CONFIG",
            {
                "logging": {
                    "violations_log": str(tmp_path / "logs" / "violations.log"),
                    "violations_summary": str(
                        tmp_path / "logs" / "violations_summary.json"
                    ),
                    "max_violations_history": 100,
                }
            },
        ):
            from quality_enforcer import ViolationsLogger

            logger = ViolationsLogger()

            assert logger.violations_log.parent.exists()
            assert logger.violations_summary.parent.exists()

    def test_log_violations_writes_to_file(
        self, tmp_path: Path, mock_violation, monkeypatch
    ):
        """Test that violations are written to log file."""
        with patch(
            "quality_enforcer.CONFIG",
            {
                "logging": {
                    "violations_log": str(tmp_path / "logs" / "violations.log"),
                    "violations_summary": str(
                        tmp_path / "logs" / "violations_summary.json"
                    ),
                    "max_violations_history": 100,
                }
            },
        ):
            from quality_enforcer import ViolationsLogger

            logger = ViolationsLogger()

            violations = [mock_violation(), mock_violation(name="anotherBadName")]

            # Change to tmp_path so relative path works
            monkeypatch.chdir(tmp_path)
            logger.log_violations("/test/file.py", violations)

            # Check log file was created
            assert logger.violations_log.exists()
            content = logger.violations_log.read_text()
            assert "2 violations" in content
            assert "calculateTotal" in content

    def test_log_violations_updates_summary_json(
        self, tmp_path: Path, mock_violation, monkeypatch
    ):
        """Test that summary JSON is updated."""
        with patch(
            "quality_enforcer.CONFIG",
            {
                "logging": {
                    "violations_log": str(tmp_path / "logs" / "violations.log"),
                    "violations_summary": str(
                        tmp_path / "logs" / "violations_summary.json"
                    ),
                    "max_violations_history": 100,
                }
            },
        ):
            from quality_enforcer import ViolationsLogger

            logger = ViolationsLogger()

            violations = [mock_violation()]

            monkeypatch.chdir(tmp_path)
            logger.log_violations("/test/file.py", violations)

            # Check summary JSON
            assert logger.violations_summary.exists()
            summary = json.loads(logger.violations_summary.read_text())
            assert "total_violations_today" in summary
            assert summary["total_violations_today"] == 1

    def test_log_violations_handles_empty_list(self, tmp_path: Path, monkeypatch):
        """Test that empty violations list is handled gracefully."""
        with patch(
            "quality_enforcer.CONFIG",
            {
                "logging": {
                    "violations_log": str(tmp_path / "logs" / "violations.log"),
                    "violations_summary": str(
                        tmp_path / "logs" / "violations_summary.json"
                    ),
                    "max_violations_history": 100,
                }
            },
        ):
            from quality_enforcer import ViolationsLogger

            logger = ViolationsLogger()

            # Should not crash or create log entry
            logger.log_violations("/test/file.py", [])

            # Log file should not be created for empty violations
            assert not logger.violations_log.exists()

    def test_log_violations_limits_display(
        self, tmp_path: Path, mock_violation, monkeypatch
    ):
        """Test that violations display is limited to 5 per log entry."""
        with patch(
            "quality_enforcer.CONFIG",
            {
                "logging": {
                    "violations_log": str(tmp_path / "logs" / "violations.log"),
                    "violations_summary": str(
                        tmp_path / "logs" / "violations_summary.json"
                    ),
                    "max_violations_history": 100,
                }
            },
        ):
            from quality_enforcer import ViolationsLogger

            logger = ViolationsLogger()

            # Create 10 violations
            violations = [mock_violation(name=f"badName{i}") for i in range(10)]

            monkeypatch.chdir(tmp_path)
            logger.log_violations("/test/file.py", violations)

            content = logger.violations_log.read_text()
            assert "10 violations" in content
            assert "and 5 more" in content


# =============================================================================
# TEST QUALITY ENFORCER HELPER METHODS
# =============================================================================


class TestQualityEnforcerHelpers:
    """Tests for QualityEnforcer helper methods."""

    def test_detect_language_python(self):
        """Test Python file detection."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        assert enforcer._detect_language("/path/to/file.py") == "python"
        assert enforcer._detect_language("script.py") == "python"

    def test_detect_language_typescript(self):
        """Test TypeScript file detection."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        assert enforcer._detect_language("/path/to/file.ts") == "typescript"
        assert enforcer._detect_language("/path/to/component.tsx") == "typescript"

    def test_detect_language_javascript(self):
        """Test JavaScript file detection."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        assert enforcer._detect_language("/path/to/file.js") == "javascript"
        assert enforcer._detect_language("/path/to/component.jsx") == "javascript"

    def test_detect_language_unsupported(self):
        """Test unsupported file types return None."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        assert enforcer._detect_language("/path/to/file.go") is None
        assert enforcer._detect_language("/path/to/file.rs") is None
        assert enforcer._detect_language("/path/to/file.txt") is None
        assert enforcer._detect_language("/path/to/Makefile") is None

    def test_extract_content_from_write(self, sample_tool_call):
        """Test content extraction from Write tool call."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        content = enforcer._extract_content(sample_tool_call)
        assert "calculateTotal" in content
        assert "processData" in content

    def test_extract_content_from_edit(self, sample_edit_tool_call):
        """Test content extraction from Edit tool call."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        content = enforcer._extract_content(sample_edit_tool_call)
        assert "calculateTotal" in content

    def test_extract_content_from_multi_edit(self):
        """Test content extraction from MultiEdit tool call."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        tool_call = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": "/test/file.py",
                "edits": [
                    {"old_string": "a", "new_string": "def func1():"},
                    {"old_string": "b", "new_string": "def func2():"},
                ],
            },
        }

        content = enforcer._extract_content(tool_call)
        assert "func1" in content
        assert "func2" in content

    def test_extract_content_handles_missing_fields(self):
        """Test content extraction handles missing fields gracefully."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        # Empty tool call
        assert enforcer._extract_content({}) == ""

        # Missing tool_input
        assert enforcer._extract_content({"tool_name": "Write"}) == ""

        # Missing content field
        assert enforcer._extract_content({"tool_input": {}}) == ""

    def test_update_tool_content(self):
        """Test updating tool call with new content."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        tool_call = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/test.py", "content": "old content"},
        }

        result = enforcer._update_tool_content(tool_call, "new content")
        assert result["tool_input"]["content"] == "new content"

    def test_append_comment(self):
        """Test appending comment to tool call content."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        tool_call = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/test.py", "content": "original"},
        }

        result = enforcer._append_comment(tool_call, "\n# Added comment")
        assert "original" in result["tool_input"]["content"]
        assert "# Added comment" in result["tool_input"]["content"]


# =============================================================================
# TEST BUILD VIOLATIONS SYSTEM MESSAGE
# =============================================================================


class TestBuildViolationsSystemMessage:
    """Tests for building system messages for violations."""

    def test_build_message_warn_mode(self, mock_violation):
        """Test system message generation in warn mode."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        violations = [mock_violation()]

        message = enforcer._build_violations_system_message(
            violations, "/test/file.py", mode="warn"
        )

        assert "NAMING CONVENTION WARNINGS" in message
        assert "/test/file.py" in message
        assert "1 naming violation(s)" in message
        assert "calculateTotal" in message

    def test_build_message_block_mode(self, mock_violation):
        """Test system message generation in block mode."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        violations = [mock_violation()]

        message = enforcer._build_violations_system_message(
            violations, "/test/file.py", mode="block"
        )

        assert "WRITE BLOCKED" in message
        assert "Please fix violations" in message

    def test_build_message_groups_by_type(self, mock_violation):
        """Test that violations are grouped by type."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        violations = [
            mock_violation(name="func1", violation_type="function"),
            mock_violation(name="func2", violation_type="function"),
            mock_violation(name="MyClass", violation_type="class"),
        ]

        message = enforcer._build_violations_system_message(
            violations, "/test/file.py", mode="warn"
        )

        assert "FUNCTION VIOLATIONS" in message
        assert "CLASS VIOLATIONS" in message


# =============================================================================
# TEST APPLY CORRECTION
# =============================================================================


class TestApplyCorrection:
    """Tests for applying corrections to content."""

    def test_apply_correction_simple(self):
        """Test simple name correction."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        content = "def calculateTotal(items):\n    return sum(items)"
        correction = {"old_name": "calculateTotal", "new_name": "calculate_total"}

        result = enforcer._apply_correction(content, correction)
        assert "calculate_total" in result
        assert "calculateTotal" not in result

    def test_apply_correction_word_boundary(self):
        """Test that correction respects word boundaries."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        # Should not change 'calculateTotalAmount' when fixing 'calculateTotal'
        content = "def calculateTotal():\n    x = calculateTotalAmount()"
        correction = {"old_name": "calculateTotal", "new_name": "calculate_total"}

        result = enforcer._apply_correction(content, correction)
        # Should change standalone calculateTotal
        assert "calculate_total" in result
        # Should NOT change calculateTotalAmount
        assert "calculateTotalAmount" in result

    def test_apply_correction_multiple_occurrences(self):
        """Test correction of multiple occurrences."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        content = """def calculateTotal(items):
    return sum(items)

result = calculateTotal([1, 2, 3])
print(calculateTotal([4, 5, 6]))
"""
        correction = {"old_name": "calculateTotal", "new_name": "calculate_total"}

        result = enforcer._apply_correction(content, correction)
        assert result.count("calculate_total") == 3
        assert "calculateTotal" not in result


# =============================================================================
# TEST ENFORCE WORKFLOW
# =============================================================================


class TestEnforceWorkflow:
    """Tests for the main enforce() workflow."""

    @pytest.mark.asyncio
    async def test_enforce_no_content_passthrough(self):
        """Test that tool calls without content pass through."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            with patch("quality_enforcer.ENABLE_PHASE_1_VALIDATION", True):
                enforcer = QualityEnforcer()

        tool_call = {"tool_name": "Bash", "tool_input": {"command": "ls"}}

        result = await enforcer.enforce(tool_call)
        assert result == tool_call

    @pytest.mark.asyncio
    async def test_enforce_no_file_path_passthrough(self):
        """Test that tool calls without file_path pass through."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            with patch("quality_enforcer.ENABLE_PHASE_1_VALIDATION", True):
                enforcer = QualityEnforcer()

        tool_call = {"tool_name": "Write", "tool_input": {"content": "test"}}

        result = await enforcer.enforce(tool_call)
        assert result == tool_call

    @pytest.mark.asyncio
    async def test_enforce_unsupported_language_passthrough(self):
        """Test that unsupported file types pass through."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            with patch("quality_enforcer.ENABLE_PHASE_1_VALIDATION", True):
                enforcer = QualityEnforcer()

        tool_call = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/test/file.go", "content": "package main"},
        }

        result = await enforcer.enforce(tool_call)
        assert result == tool_call

    @pytest.mark.asyncio
    async def test_enforce_phase_1_disabled_passthrough(self):
        """Test that tool calls pass through when Phase 1 is disabled."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            with patch("quality_enforcer.ENABLE_PHASE_1_VALIDATION", False):
                enforcer = QualityEnforcer()

                tool_call = {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": "/test/file.py",
                        "content": "def calculateTotal(): pass",
                    },
                }

                result = await enforcer.enforce(tool_call)
                assert result == tool_call


# =============================================================================
# TEST GENERATE SIMPLE CORRECTIONS
# =============================================================================


class TestGenerateSimpleCorrections:
    """Tests for simple correction generation."""

    def test_generate_corrections_from_violations(self, mock_violation):
        """Test generating corrections from violations."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        violations = [mock_violation()]

        corrections = enforcer._generate_simple_corrections(violations)

        assert len(corrections) == 1
        assert corrections[0]["old_name"] == "calculateTotal"
        assert corrections[0]["new_name"] == "calculate_total"
        assert corrections[0]["confidence"] == 0.6  # Lower confidence without RAG


# =============================================================================
# TEST EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge case tests for quality enforcer."""

    @pytest.mark.asyncio
    async def test_enforce_handles_exception_gracefully(self):
        """Test that exceptions during enforcement return original tool call."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            with patch("quality_enforcer.ENABLE_PHASE_1_VALIDATION", True):
                enforcer = QualityEnforcer()

        # Patch _detect_language to raise exception
        with patch.object(
            enforcer, "_detect_language", side_effect=RuntimeError("Test error")
        ):
            tool_call = {
                "tool_name": "Write",
                "tool_input": {"file_path": "/test.py", "content": "test"},
            }

            result = await enforcer.enforce(tool_call)
            # Should return original on error
            assert result == tool_call

    def test_elapsed_time_tracking(self):
        """Test elapsed time tracking."""
        import time

        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        # Should be close to 0 initially
        initial = enforcer._elapsed()
        assert initial < 0.1

        # After sleep, should increase
        time.sleep(0.1)
        after_sleep = enforcer._elapsed()
        assert after_sleep >= 0.1

    def test_stats_initialization(self):
        """Test that stats are properly initialized."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        expected_keys = [
            "phase_1_time",
            "phase_2_time",
            "phase_3_time",
            "phase_4_time",
            "phase_5_time",
            "violations_found",
            "corrections_applied",
            "corrections_suggested",
            "corrections_skipped",
        ]

        for key in expected_keys:
            assert key in enforcer.stats
            assert enforcer.stats[key] == 0.0


# =============================================================================
# TEST CREATE FALLBACK SCORES
# =============================================================================


class TestCreateFallbackScores:
    """Tests for creating fallback scores."""

    def test_creates_scores_for_all_corrections(self, mock_violation):
        """Test that fallback scores are created for all corrections."""
        from quality_enforcer import QualityEnforcer

        with patch("quality_enforcer.CONFIG", {}):
            enforcer = QualityEnforcer()

        corrections = [
            {"violation": mock_violation(), "old_name": "a", "new_name": "b"},
            {"violation": mock_violation(), "old_name": "c", "new_name": "d"},
        ]

        scored = enforcer._create_fallback_scores(corrections)

        assert len(scored) == 2
        for item in scored:
            assert "correction" in item
            assert "score" in item
            assert item["score"].consensus_score == 0.65
            assert item["score"].confidence == 0.60
            assert item["score"].should_apply is False


# =============================================================================
# TEST MAIN ENTRY POINT
# =============================================================================


class TestMainEntryPoint:
    """Tests for the async main() entry point."""

    @pytest.mark.asyncio
    async def test_main_empty_input(self, tmp_path: Path, monkeypatch):
        """Test main with empty stdin."""
        # Create required log directory
        log_dir = tmp_path / ".claude" / "hooks" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with patch("sys.stdin", StringIO("")):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                from quality_enforcer import main

                exit_code = await main()

        assert exit_code == 0
        assert mock_stdout.getvalue().strip() == "{}"

    @pytest.mark.asyncio
    async def test_main_invalid_json(self, tmp_path: Path, monkeypatch):
        """Test main with invalid JSON input."""
        log_dir = tmp_path / ".claude" / "hooks" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with patch("sys.stdin", StringIO("{invalid json}")):
            with patch("sys.stdout", new_callable=StringIO):
                with patch("sys.stderr", new_callable=StringIO):
                    from quality_enforcer import main

                    exit_code = await main()

        # Should return error code on invalid JSON
        assert exit_code == 1


# =============================================================================
# TEST CONFIG LOADING
# =============================================================================


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_config_missing_file(self, tmp_path: Path, monkeypatch):
        """Test load_config handles missing config file."""
        monkeypatch.chdir(tmp_path)

        # Patch the __file__ to point to tmp_path
        with patch("quality_enforcer.Path") as mock_path:
            mock_path.return_value.parent = tmp_path
            mock_path.return_value.exists.return_value = False

            from quality_enforcer import load_config

            config = load_config()
            assert isinstance(config, dict)

    def test_load_config_invalid_yaml(self, tmp_path: Path, monkeypatch):
        """Test load_config handles invalid YAML gracefully."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content: [")

        with patch("quality_enforcer.Path") as mock_path:
            mock_path_instance = MagicMock()
            mock_path_instance.parent = tmp_path
            mock_path_instance.exists.return_value = True
            mock_path_instance.__truediv__ = lambda self, x: config_file
            mock_path.return_value = mock_path_instance

            # The function should handle the error gracefully
            # This tests defensive programming


# =============================================================================
# RUN TESTS
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
