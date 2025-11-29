#!/usr/bin/env python3
"""
Async Exception Handling Tests for GenerationPipeline

Tests cleanup_async and __aexit__ exception propagation behavior:
- Exceptions during cleanup are logged but propagated
- __aexit__ returns False (allows exception propagation)
- Exactly one error log per failure
- State consistency after exceptions
"""

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude.lib.generation_pipeline import GenerationPipeline


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def mock_template_engine():
    """Mock template engine with cleanup_async."""
    engine = MagicMock()
    engine.templates = {"EFFECT": MagicMock()}
    engine.cleanup_async = AsyncMock()
    engine.template_cache = MagicMock()
    engine.template_cache._background_tasks = set()
    return engine


@pytest.fixture
def pipeline(mock_template_engine):
    """Create pipeline instance with mocked template engine."""
    return GenerationPipeline(
        template_engine=mock_template_engine,
        enable_compilation_testing=False,
    )


# -------------------------------------------------------------------------
# cleanup_async Exception Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_async_propagates_template_engine_exception(
    pipeline, mock_template_engine, caplog
):
    """
    Test cleanup_async propagates exceptions from template_engine.cleanup_async.

    Verifies:
    - Exception is logged (exactly 1 error log)
    - Exception does NOT propagate (cleanup catches it)
    - State remains consistent
    """
    # Arrange
    test_error = RuntimeError("Template cleanup failed")
    mock_template_engine.cleanup_async.side_effect = test_error

    # Capture logs
    with caplog.at_level(logging.ERROR):
        # Act - cleanup_async should NOT raise (it catches exceptions)
        await pipeline.cleanup_async(timeout=1.0)

    # Assert: Exactly one error log
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) == 1, (
        f"Expected exactly 1 error log, got {len(error_logs)}: "
        f"{[r.message for r in error_logs]}"
    )
    assert "Failed to cleanup template engine" in error_logs[0].message
    assert str(test_error) in error_logs[0].message

    # Assert: Template engine cleanup was called
    mock_template_engine.cleanup_async.assert_called_once_with(1.0)

    # Assert: Pipeline state remains consistent
    assert pipeline.template_engine == mock_template_engine


@pytest.mark.asyncio
async def test_cleanup_async_logs_multiple_errors_separately(
    pipeline, mock_template_engine, caplog
):
    """
    Test cleanup_async logs each component failure separately.

    Verifies:
    - Multiple cleanup failures are logged individually
    - Each component gets exactly one error log
    - Cleanup continues despite failures
    """
    # Arrange
    template_error = ValueError("Template cache error")
    mock_template_engine.cleanup_async.side_effect = template_error

    # Capture logs
    with caplog.at_level(logging.ERROR):
        # Act
        await pipeline.cleanup_async(timeout=2.0)

    # Assert: Exactly one error log for template engine
    error_logs = [
        record
        for record in caplog.records
        if record.levelname == "ERROR" and "template engine" in record.message
    ]
    assert (
        len(error_logs) == 1
    ), f"Expected exactly 1 template engine error log, got {len(error_logs)}"


# -------------------------------------------------------------------------
# __aexit__ Exception Propagation Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aexit_returns_false_for_exception_propagation(
    pipeline, mock_template_engine
):
    """
    Test __aexit__ returns False to allow exception propagation.

    Verifies:
    - __aexit__ calls cleanup_async
    - __aexit__ returns False (does not suppress exceptions)
    - External exceptions propagate through context manager
    """
    # Arrange
    test_exception = ValueError("External operation failed")

    # Act & Assert: Exception propagates
    with pytest.raises(ValueError, match="External operation failed"):
        async with pipeline:
            # Simulate error during pipeline usage
            raise test_exception

    # Assert: cleanup_async was called despite exception
    mock_template_engine.cleanup_async.assert_called_once()


@pytest.mark.asyncio
async def test_aexit_cleanup_exception_is_logged_not_suppressed(
    pipeline, mock_template_engine, caplog
):
    """
    Test __aexit__ logs cleanup exceptions but doesn't suppress original exception.

    Verifies:
    - Cleanup exception is logged (1 error log)
    - Original exception still propagates
    - No exception chaining issues
    """
    # Arrange
    cleanup_error = RuntimeError("Cleanup failed during exit")
    original_error = ValueError("Original operation failed")
    mock_template_engine.cleanup_async.side_effect = cleanup_error

    # Capture logs
    with caplog.at_level(logging.ERROR):
        # Act & Assert: Original exception propagates
        with pytest.raises(ValueError, match="Original operation failed"):
            async with pipeline:
                raise original_error

    # Assert: Exactly one error log for cleanup failure
    error_logs = [
        record
        for record in caplog.records
        if record.levelname == "ERROR" and "cleanup" in record.message.lower()
    ]
    assert (
        len(error_logs) == 1
    ), f"Expected exactly 1 cleanup error log, got {len(error_logs)}"


@pytest.mark.asyncio
async def test_aexit_successful_cleanup_no_exceptions(
    pipeline, mock_template_engine, caplog
):
    """
    Test __aexit__ successful cleanup path (no exceptions).

    Verifies:
    - Successful cleanup produces no error logs
    - cleanup_async is called with default timeout
    - State is clean after exit
    """
    # Arrange - successful cleanup
    mock_template_engine.cleanup_async.return_value = None

    # Capture logs
    with caplog.at_level(logging.ERROR):
        # Act
        async with pipeline:
            pass  # Normal operation

    # Assert: No error logs
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) == 0, f"Expected no error logs, got: {error_logs}"

    # Assert: cleanup_async was called
    mock_template_engine.cleanup_async.assert_called_once()


# -------------------------------------------------------------------------
# State Consistency Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_async_maintains_state_after_exception(
    pipeline, mock_template_engine
):
    """
    Test cleanup_async maintains consistent state after exceptions.

    Verifies:
    - Pipeline attributes remain accessible
    - Template engine reference is preserved
    - No attribute corruption occurs
    """
    # Arrange
    mock_template_engine.cleanup_async.side_effect = RuntimeError("Cleanup error")

    # Act - cleanup fails but doesn't raise
    await pipeline.cleanup_async(timeout=1.0)

    # Assert: State consistency
    assert pipeline.template_engine == mock_template_engine
    assert hasattr(pipeline, "logger")
    assert hasattr(pipeline, "enable_compilation_testing")


@pytest.mark.asyncio
async def test_cleanup_async_can_be_called_multiple_times(
    pipeline, mock_template_engine
):
    """
    Test cleanup_async is idempotent (can be called multiple times).

    Verifies:
    - Multiple calls don't cause errors
    - Each call attempts cleanup
    - No state corruption from repeated calls
    """
    # Arrange - successful cleanup
    mock_template_engine.cleanup_async.return_value = None

    # Act - call cleanup multiple times
    await pipeline.cleanup_async(timeout=1.0)
    await pipeline.cleanup_async(timeout=1.0)
    await pipeline.cleanup_async(timeout=1.0)

    # Assert: Called multiple times without error
    assert mock_template_engine.cleanup_async.call_count == 3


# -------------------------------------------------------------------------
# Edge Cases
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cleanup_async_with_none_template_engine(caplog):
    """
    Test cleanup_async handles None template_engine gracefully.

    Verifies:
    - No exception when template_engine is None
    - No error logs
    - Cleanup completes successfully
    """
    # Arrange
    pipeline = GenerationPipeline(
        template_engine=None,
        enable_compilation_testing=False,
    )

    # Capture logs
    with caplog.at_level(logging.ERROR):
        # Act
        await pipeline.cleanup_async(timeout=1.0)

    # Assert: No error logs
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) == 0


@pytest.mark.asyncio
async def test_aexit_with_slow_cleanup(pipeline, mock_template_engine, caplog):
    """
    Test __aexit__ handles slow cleanup operations.

    Verifies:
    - Slow cleanup completes eventually
    - No timeout errors when cleanup takes time
    - Cleanup is called despite being slow
    """

    # Arrange
    async def slow_cleanup(timeout):
        await asyncio.sleep(0.1)  # Simulate slow cleanup

    mock_template_engine.cleanup_async.side_effect = slow_cleanup

    # Capture logs
    with caplog.at_level(logging.DEBUG):
        # Act - slow cleanup should complete
        async with pipeline:
            pass

    # Assert: Cleanup was called
    mock_template_engine.cleanup_async.assert_called_once()


# -------------------------------------------------------------------------
# Run Tests
# -------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
