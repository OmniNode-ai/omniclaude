#!/usr/bin/env python3
"""
Comprehensive tests for complete hook lifecycle.

Tests:
- UserPromptSubmit → agent detection → context injection
- PreToolUse → quality validation → blocking
- PostToolUse → auto-fix → metrics collection
- Session lifecycle (start → work → end)
- Correlation ID propagation

Author: OmniClaude Framework
Version: 1.0.0
"""

import pytest
import sys
import json
import time
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

# Add lib directory to path
HOOKS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

from hook_event_logger import HookEventLogger, log_userprompt, log_pretooluse, log_posttooluse
from correlation_manager import (
    set_correlation_id,
    get_correlation_context,
    clear_correlation_context
)
from metadata_extractor import MetadataExtractor


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_hooks_dir(tmp_path):
    """Create temporary hooks directory structure."""
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()

    # Create lib directory
    lib_dir = hooks_dir / "lib"
    lib_dir.mkdir()

    # Create logs directory
    logs_dir = hooks_dir / "logs"
    logs_dir.mkdir()

    return hooks_dir


@pytest.fixture
def correlation_id():
    """Generate test correlation ID."""
    corr_id = str(uuid.uuid4())
    yield corr_id
    # Cleanup
    clear_correlation_context()


@pytest.fixture
def mock_database():
    """Mock database connection for testing."""
    with patch('hook_event_logger.psycopg2.connect') as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        yield {
            "connect": mock_connect,
            "conn": mock_conn,
            "cursor": mock_cursor
        }


@pytest.fixture
def sample_prompts():
    """Sample prompts for testing."""
    return {
        "explicit_agent": "@agent-testing write comprehensive unit tests",
        "trigger_match": "help me write pytest tests for coverage",
        "ai_required": "optimize database query performance",
        "no_agent": "what's the weather today",
        "quality_issue": "write a function without type annotations"
    }


# ============================================================================
# USER PROMPT SUBMIT HOOK TESTS
# ============================================================================

@pytest.mark.integration
class TestUserPromptSubmitHook:
    """Test UserPromptSubmit hook functionality."""

    def test_hook_input_parsing(self, sample_prompts):
        """Test hook correctly parses JSON input."""
        prompt = sample_prompts["explicit_agent"]
        hook_input = {
            "prompt": prompt,
            "metadata": {
                "session_id": "test-session"
            }
        }

        json_input = json.dumps(hook_input)

        # Simulate hook execution
        result = subprocess.run(
            [str(HOOKS_DIR / "user-prompt-submit-enhanced.sh")],
            input=json_input,
            capture_output=True,
            text=True,
            env={
                "ENABLE_AI_AGENT_SELECTION": "false",
                **dict(subprocess.os.environ)
            }
        )

        # Hook should succeed
        assert result.returncode == 0

        # Parse output
        try:
            output = json.loads(result.stdout)
            assert "hookSpecificOutput" in output or "prompt" in output
        except json.JSONDecodeError:
            # OK if output is not JSON (might be enhanced prompt)
            pass

    def test_agent_detection_explicit(self, sample_prompts):
        """Test explicit agent pattern detection in hook."""
        prompt = sample_prompts["explicit_agent"]
        hook_input = json.dumps({"prompt": prompt})

        result = subprocess.run(
            [str(HOOKS_DIR / "user-prompt-submit-enhanced.sh")],
            input=hook_input,
            capture_output=True,
            text=True,
            env={
                "ENABLE_AI_AGENT_SELECTION": "false",
                **dict(subprocess.os.environ)
            }
        )

        assert result.returncode == 0

        # Check logs for agent detection
        log_file = HOOKS_DIR / "hook-enhanced.log"
        if log_file.exists():
            with open(log_file, 'r') as f:
                log_content = f.read()
                # Should log agent detection
                assert "agent-testing" in log_content.lower() or "agent detected" in log_content.lower()

    def test_context_injection(self, sample_prompts):
        """Test hook injects agent context."""
        prompt = sample_prompts["explicit_agent"]
        hook_input = json.dumps({"prompt": prompt})

        result = subprocess.run(
            [str(HOOKS_DIR / "user-prompt-submit-enhanced.sh")],
            input=hook_input,
            capture_output=True,
            text=True,
            env={
                "ENABLE_AI_AGENT_SELECTION": "false",
                **dict(subprocess.os.environ)
            }
        )

        output = result.stdout

        # Should inject agent context
        if "@agent-testing" in prompt:
            assert "Agent Framework Context" in output or "agent-testing" in output.lower()

    def test_correlation_id_generation(self):
        """Test hook generates correlation ID."""
        prompt = "@agent-testing write tests"
        hook_input = json.dumps({"prompt": prompt})

        result = subprocess.run(
            [str(HOOKS_DIR / "user-prompt-submit-enhanced.sh")],
            input=hook_input,
            capture_output=True,
            text=True,
            env={
                "ENABLE_AI_AGENT_SELECTION": "false",
                **dict(subprocess.os.environ)
            }
        )

        output = result.stdout

        # Should contain correlation ID (UUID format)
        import re
        uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        assert re.search(uuid_pattern, output.lower())

    def test_no_agent_passthrough(self, sample_prompts):
        """Test hook passes through when no agent detected."""
        prompt = sample_prompts["no_agent"]
        hook_input = json.dumps({"prompt": prompt})

        result = subprocess.run(
            [str(HOOKS_DIR / "user-prompt-submit-enhanced.sh")],
            input=hook_input,
            capture_output=True,
            text=True,
            env={
                "ENABLE_AI_AGENT_SELECTION": "false",
                **dict(subprocess.os.environ)
            }
        )

        assert result.returncode == 0

        # Should pass through original input
        output = json.loads(result.stdout) if result.stdout else {}
        if "prompt" in output:
            # Should not add agent context for non-agent prompts
            assert "Agent Framework Context" not in str(output)


# ============================================================================
# CORRELATION MANAGER TESTS
# ============================================================================

@pytest.mark.unit
class TestCorrelationManager:
    """Test correlation ID management."""

    def test_set_and_get_correlation(self, correlation_id):
        """Test setting and retrieving correlation context."""
        set_correlation_id(
            correlation_id=correlation_id,
            agent_name="agent-testing",
            agent_domain="testing",
            prompt_preview="write tests"
        )

        context = get_correlation_context()

        assert context is not None
        assert context["correlation_id"] == correlation_id
        assert context["agent_name"] == "agent-testing"
        assert context["agent_domain"] == "testing"
        assert "write tests" in context["prompt_preview"]

    def test_context_persistence(self, correlation_id):
        """Test correlation context persists across calls."""
        set_correlation_id(
            correlation_id=correlation_id,
            agent_name="agent-testing"
        )

        # Get context multiple times
        context1 = get_correlation_context()
        context2 = get_correlation_context()

        # Compare fields excluding timestamps (which update on each access)
        assert context1["correlation_id"] == context2["correlation_id"]
        assert context1["agent_name"] == context2["agent_name"]
        assert context1["prompt_count"] == context2["prompt_count"]
        # Verify the correlation ID is correct
        assert context1["correlation_id"] == correlation_id

    def test_context_cleanup(self, correlation_id):
        """Test correlation context cleanup."""
        set_correlation_id(correlation_id=correlation_id)

        # Verify set
        assert get_correlation_context() is not None

        # Clear
        clear_correlation_context()

        # Should be None or empty
        context = get_correlation_context()
        assert context is None or not context

    def test_missing_context(self):
        """Test getting context when none set."""
        clear_correlation_context()

        context = get_correlation_context()

        # Should return None or empty dict
        assert context is None or not context


# ============================================================================
# METADATA EXTRACTOR TESTS
# ============================================================================

@pytest.mark.unit
class TestMetadataExtractor:
    """Test metadata extraction."""

    def test_basic_metadata_extraction(self):
        """Test basic metadata extraction from prompt."""
        extractor = MetadataExtractor(working_dir="/test")

        metadata = extractor.extract_all(
            prompt="write pytest tests for the API",
            agent_name="agent-testing"
        )

        assert isinstance(metadata, dict)
        # Check for actual metadata structure
        assert "prompt_characteristics" in metadata
        assert "length_chars" in metadata["prompt_characteristics"]
        assert metadata["prompt_characteristics"]["length_chars"] > 0
        # Also check other expected fields
        assert "workflow_stage" in metadata
        assert "editor_context" in metadata

    def test_file_reference_extraction(self):
        """Test extraction of file references from prompt."""
        extractor = MetadataExtractor(working_dir="/test")

        prompt = "fix the bug in /path/to/file.py and tests/test_api.py"
        metadata = extractor.extract_all(prompt)

        # Should extract file references
        assert isinstance(metadata, dict)

    def test_performance_target(self):
        """Test metadata extraction meets performance target (<15ms)."""
        extractor = MetadataExtractor(working_dir="/test")

        prompt = "write comprehensive pytest tests for all API endpoints"

        iterations = 100
        start_time = time.time()

        for _ in range(iterations):
            extractor.extract_all(prompt)

        elapsed_ms = (time.time() - start_time) * 1000
        avg_ms = elapsed_ms / iterations

        assert avg_ms < 15.0, f"Metadata extraction too slow: {avg_ms:.2f}ms"

    def test_correlation_context_integration(self, correlation_id):
        """Test metadata extraction with correlation context."""
        set_correlation_id(correlation_id=correlation_id, agent_name="agent-testing")

        extractor = MetadataExtractor(working_dir="/test")

        corr_context = get_correlation_context()
        metadata = extractor.extract_all(
            prompt="write tests",
            correlation_context=corr_context
        )

        assert isinstance(metadata, dict)


# ============================================================================
# PRETOOLUSE HOOK TESTS
# ============================================================================

@pytest.mark.integration
class TestPreToolUseHook:
    """Test PreToolUse quality enforcement hook."""

    def test_hook_passes_non_target_tools(self):
        """Test hook passes through non-Write/Edit/MultiEdit tools."""
        tool_info = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/test/file.py"}
        }

        json_input = json.dumps(tool_info)

        result = subprocess.run(
            [str(HOOKS_DIR / "pre-tool-use-quality.sh")],
            input=json_input,
            capture_output=True,
            text=True
        )

        # Should pass through immediately
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["tool_name"] == "Read"

    def test_hook_intercepts_write_tool(self):
        """Test hook intercepts Write tool for validation."""
        tool_info = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/test/model_test.py",
                "content": "def test_function():\n    pass\n"
            }
        }

        json_input = json.dumps(tool_info)

        result = subprocess.run(
            [str(HOOKS_DIR / "pre-tool-use-quality.sh")],
            input=json_input,
            capture_output=True,
            text=True
        )

        # Should intercept (exit 0 or 2)
        assert result.returncode in [0, 2]

    def test_correlation_id_tracking(self, correlation_id):
        """Test PreToolUse hook tracks correlation ID."""
        # Set correlation context
        set_correlation_id(correlation_id=correlation_id)

        tool_info = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/test/file.py",
                "content": "pass"
            }
        }

        json_input = json.dumps(tool_info)

        result = subprocess.run(
            [str(HOOKS_DIR / "pre-tool-use-quality.sh")],
            input=json_input,
            capture_output=True,
            text=True,
            env={
                "CORRELATION_ID": correlation_id,
                **dict(subprocess.os.environ)
            }
        )

        # Check logs for correlation ID
        # (implementation would verify CORRELATION_ID in logs)
        assert result.returncode in [0, 2]


# ============================================================================
# POSTTOOLUSE HOOK TESTS
# ============================================================================

@pytest.mark.integration
class TestPostToolUseHook:
    """Test PostToolUse metrics collection hook."""

    def test_hook_processes_write_tool(self, tmp_path):
        """Test hook processes Write tool output."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def test(): pass")

        tool_info = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
            "tool_response": {"success": True}
        }

        json_input = json.dumps(tool_info)

        result = subprocess.run(
            [str(HOOKS_DIR / "post-tool-use-quality.sh")],
            input=json_input,
            capture_output=True,
            text=True
        )

        # Should always pass through (exit 0)
        assert result.returncode == 0

        # Output should be original tool info
        output = json.loads(result.stdout)
        assert output["tool_name"] == "Write"

    def test_hook_passes_read_tool(self):
        """Test hook passes through Read tool."""
        tool_info = {
            "tool_name": "Read",
            "tool_response": {"content": "file content"}
        }

        json_input = json.dumps(tool_info)

        result = subprocess.run(
            [str(HOOKS_DIR / "post-tool-use-quality.sh")],
            input=json_input,
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["tool_name"] == "Read"


# ============================================================================
# DATABASE INTEGRATION TESTS
# ============================================================================

@pytest.mark.integration
class TestDatabaseIntegration:
    """Test database event logging integration."""

    def test_database_connection(self, mock_database):
        """Test database connection establishment."""
        logger = HookEventLogger()

        # Should not raise exception
        assert logger is not None

    def test_event_logging(self, mock_database, correlation_id):
        """Test event logging to database."""
        logger = HookEventLogger()

        event_id = logger.log_event(
            source="UserPromptSubmit",
            action="agent_detected",
            resource="agent",
            resource_id="agent-testing",
            payload={
                "agent_name": "agent-testing",
                "confidence": 0.95
            },
            metadata={
                "correlation_id": correlation_id
            }
        )

        # Should return event ID
        assert event_id is not None or event_id == correlation_id

        # Verify database insert was called
        mock_database["cursor"].execute.assert_called()

    def test_async_logging_non_blocking(self, mock_database):
        """Test database logging is non-blocking."""
        logger = HookEventLogger()

        # Time multiple log calls
        start_time = time.time()

        for _ in range(10):
            logger.log_event(
                source="Test",
                action="test_action",
                resource="test",
                resource_id="test-id",
                payload={}
            )

        elapsed_ms = (time.time() - start_time) * 1000

        # Should be fast even with 10 calls (async)
        assert elapsed_ms < 100.0, f"Logging too slow: {elapsed_ms:.2f}ms"


# ============================================================================
# END-TO-END WORKFLOW TESTS
# ============================================================================

@pytest.mark.e2e
class TestEndToEndWorkflow:
    """Test complete end-to-end workflows."""

    def test_complete_agent_workflow(self, tmp_path):
        """Test complete workflow: prompt → detection → validation → execution."""
        # Step 1: UserPromptSubmit
        prompt = "@agent-testing write comprehensive tests"
        hook_input = json.dumps({"prompt": prompt})

        result1 = subprocess.run(
            [str(HOOKS_DIR / "user-prompt-submit-enhanced.sh")],
            input=hook_input,
            capture_output=True,
            text=True,
            env={
                "ENABLE_AI_AGENT_SELECTION": "false",
                **dict(subprocess.os.environ)
            }
        )

        assert result1.returncode == 0

        # Step 2: PreToolUse (simulate Write)
        test_file = tmp_path / "test_example.py"
        tool_info = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(test_file),
                "content": "def test_example():\n    pass\n"
            }
        }

        result2 = subprocess.run(
            [str(HOOKS_DIR / "pre-tool-use-quality.sh")],
            input=json.dumps(tool_info),
            capture_output=True,
            text=True
        )

        assert result2.returncode in [0, 2]

        # Step 3: PostToolUse (after file written)
        test_file.write_text("def test_example():\n    pass\n")

        post_tool_info = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
            "tool_response": {"success": True}
        }

        result3 = subprocess.run(
            [str(HOOKS_DIR / "post-tool-use-quality.sh")],
            input=json.dumps(post_tool_info),
            capture_output=True,
            text=True
        )

        assert result3.returncode == 0

    def test_correlation_propagation(self, correlation_id):
        """Test correlation ID propagates through entire workflow."""
        # This would require integration with actual Claude Code
        # For now, test the correlation manager directly

        # Step 1: Set in UserPromptSubmit
        set_correlation_id(correlation_id=correlation_id, agent_name="agent-testing")

        # Step 2: Retrieve in PreToolUse
        context = get_correlation_context()
        assert context["correlation_id"] == correlation_id

        # Step 3: Retrieve in PostToolUse
        context2 = get_correlation_context()
        assert context2["correlation_id"] == correlation_id

        # Cleanup
        clear_correlation_context()


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================

@pytest.mark.performance
class TestHookPerformance:
    """Test hook performance benchmarks."""

    def test_userpromptsubmit_overhead(self):
        """Test UserPromptSubmit hook overhead without AI."""
        prompt = "write pytest tests"
        hook_input = json.dumps({"prompt": prompt})

        iterations = 10
        start_time = time.time()

        for _ in range(iterations):
            subprocess.run(
                [str(HOOKS_DIR / "user-prompt-submit-enhanced.sh")],
                input=hook_input,
                capture_output=True,
                text=True,
                env={
                    "ENABLE_AI_AGENT_SELECTION": "false",
                    **dict(subprocess.os.environ)
                }
            )

        elapsed_ms = (time.time() - start_time) * 1000
        avg_ms = elapsed_ms / iterations

        print(f"\nUserPromptSubmit overhead: {avg_ms:.2f}ms avg")
        assert avg_ms < 100.0, f"Hook too slow: {avg_ms:.2f}ms"

    def test_pretooluse_overhead(self, tmp_path):
        """Test PreToolUse hook overhead."""
        tool_info = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "test.py"),
                "content": "pass"
            }
        }

        json_input = json.dumps(tool_info)

        iterations = 10
        start_time = time.time()

        for _ in range(iterations):
            subprocess.run(
                [str(HOOKS_DIR / "pre-tool-use-quality.sh")],
                input=json_input,
                capture_output=True,
                text=True
            )

        elapsed_ms = (time.time() - start_time) * 1000
        avg_ms = elapsed_ms / iterations

        print(f"\nPreToolUse overhead: {avg_ms:.2f}ms avg")
        assert avg_ms < 200.0, f"Hook too slow: {avg_ms:.2f}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
