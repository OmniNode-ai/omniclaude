#!/usr/bin/env python3
"""
Async Exception Handling Tests for TemplateCache

Tests cleanup_async exception behavior with focus on:
- TimeoutError path during task cleanup
- Persistence close errors
- Exception propagation vs. suppression
- Single error log emission per failure
- Cleanup state indicators
"""

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.lib.template_cache import TemplateCache

# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def template_cache():
    """Create template cache with persistence disabled."""
    return TemplateCache(
        max_templates=10,
        max_size_mb=1,
        ttl_seconds=3600,
        enable_persistence=False,  # Disable to avoid DB dependencies
    )


@pytest.fixture
def template_cache_with_persistence():
    """Create template cache with persistence enabled (mocked)."""
    cache = TemplateCache(
        max_templates=10,
        max_size_mb=1,
        ttl_seconds=3600,
        enable_persistence=True,
    )
    # Mock persistence instance
    cache._persistence_instance = MagicMock()
    cache._persistence_instance.close = AsyncMock()
    cache._persistence_checked = True
    return cache


# -------------------------------------------------------------------------
# TimeoutError Path Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_async_timeout_error_during_task_wait(template_cache, caplog):
    """
    Test cleanup_async handles TimeoutError during task wait.

    Verifies:
    - TimeoutError is caught and logged
    - Remaining tasks are cancelled
    - Exactly one warning log for timeout
    - Cleanup indicators reflect timeout occurred
    """

    # Arrange - create slow background task
    async def slow_task():
        await asyncio.sleep(100)  # Never completes

    # Add background task to cache
    task = asyncio.create_task(slow_task())
    template_cache._background_tasks.add(task)

    # Capture logs
    with caplog.at_level(logging.WARNING):
        # Act - use very short timeout to trigger TimeoutError
        await template_cache.cleanup_async(timeout=0.1)

    # Assert: Exactly one warning log for timeout
    warning_logs = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "timeout" in record.message.lower()
    ]
    assert len(warning_logs) == 1, (
        f"Expected exactly 1 timeout warning, got {len(warning_logs)}: "
        f"{[r.message for r in warning_logs]}"
    )
    assert "Task cleanup timeout" in warning_logs[0].message

    # Assert: Task was cancelled
    assert task.cancelled() or task.done()

    # Assert: Background tasks set is cleared
    assert len(template_cache._background_tasks) == 0


@pytest.mark.asyncio
async def test_cleanup_async_cancels_all_pending_tasks_on_timeout(template_cache, caplog):
    """
    Test cleanup_async cancels ALL pending tasks on timeout.

    Verifies:
    - Multiple slow tasks are all cancelled
    - Single timeout warning log
    - All tasks cleared from tracking set
    """

    # Arrange - create multiple slow tasks
    async def slow_task(_task_id):
        await asyncio.sleep(100)

    tasks = [asyncio.create_task(slow_task(i)) for i in range(5)]
    template_cache._background_tasks.update(tasks)

    # Capture logs
    with caplog.at_level(logging.WARNING):
        # Act
        await template_cache.cleanup_async(timeout=0.1)

    # Assert: All tasks cancelled or done
    for task in tasks:
        assert task.cancelled() or task.done()

    # Assert: Exactly one timeout warning
    warning_logs = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "timeout" in record.message.lower()
    ]
    assert len(warning_logs) == 1

    # Assert: Tasks set cleared
    assert len(template_cache._background_tasks) == 0


@pytest.mark.asyncio
async def test_cleanup_async_successful_task_completion_no_timeout(template_cache, caplog):
    """
    Test cleanup_async successful task completion (no timeout).

    Verifies:
    - Fast tasks complete normally
    - No timeout warning logs
    - Debug log confirms success
    - Tasks cleared from tracking set
    """

    # Arrange - create fast task
    async def fast_task():
        await asyncio.sleep(0.01)  # Quick completion

    task = asyncio.create_task(fast_task())
    template_cache._background_tasks.add(task)

    # Capture logs
    with caplog.at_level(logging.DEBUG):
        # Act
        await template_cache.cleanup_async(timeout=1.0)

    # Assert: No warning logs
    warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warning_logs) == 0

    # Assert: Debug log confirms success
    debug_logs = [
        record
        for record in caplog.records
        if record.levelname == "DEBUG" and "complete" in record.message.lower()
    ]
    assert len(debug_logs) >= 1
    assert any("successfully" in log.message.lower() for log in debug_logs)

    # Assert: Tasks cleared
    assert len(template_cache._background_tasks) == 0


# -------------------------------------------------------------------------
# Persistence Close Error Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_async_persistence_close_error_is_logged(
    template_cache_with_persistence, caplog
):
    """
    Test cleanup_async logs persistence close errors but doesn't propagate.

    Verifies:
    - Persistence close error is caught and logged
    - Exception does NOT propagate
    - Exactly one debug log for error
    - Persistence instance is cleared
    """
    # Arrange
    close_error = RuntimeError("Database connection close failed")
    template_cache_with_persistence._persistence_instance.close.side_effect = close_error

    # Capture logs
    with caplog.at_level(logging.DEBUG):
        # Act - should NOT raise exception
        await template_cache_with_persistence.cleanup_async(timeout=1.0)

    # Assert: Exactly one debug log for close error
    debug_logs = [
        record
        for record in caplog.records
        if record.levelname == "DEBUG" and "closing persistence" in record.message.lower()
    ]
    assert len(debug_logs) == 1, (
        f"Expected exactly 1 persistence close error log, got {len(debug_logs)}"
    )

    # Assert: Persistence instance is cleared
    assert template_cache_with_persistence._persistence_instance is None


@pytest.mark.asyncio
async def test_cleanup_async_persistence_successful_close(template_cache_with_persistence, caplog):
    """
    Test cleanup_async successful persistence close.

    Verifies:
    - Persistence.close() is called
    - Debug log confirms closure
    - Persistence instance is cleared
    - No error logs
    """
    # Arrange - successful close
    template_cache_with_persistence._persistence_instance.close.return_value = None

    # Save reference to persistence instance before cleanup clears it
    persistence_mock = template_cache_with_persistence._persistence_instance

    # Capture logs
    with caplog.at_level(logging.DEBUG):
        # Act
        await template_cache_with_persistence.cleanup_async(timeout=1.0)

    # Assert: close() was called (check on saved reference)
    persistence_mock.close.assert_called_once()

    # Assert: Debug log confirms closure
    debug_logs = [
        record
        for record in caplog.records
        if record.levelname == "DEBUG" and "closed" in record.message.lower()
    ]
    assert any("persistence" in log.message.lower() for log in debug_logs)

    # Assert: Persistence instance cleared
    assert template_cache_with_persistence._persistence_instance is None

    # Assert: No error logs
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) == 0


@pytest.mark.asyncio
async def test_cleanup_async_without_persistence_instance(template_cache, caplog):
    """
    Test cleanup_async when persistence instance is None.

    Verifies:
    - No error when persistence is None
    - No attempt to close non-existent persistence
    - No error logs
    """
    # Arrange - ensure no persistence instance
    template_cache._persistence_instance = None

    # Capture logs
    with caplog.at_level(logging.ERROR):
        # Act
        await template_cache.cleanup_async(timeout=1.0)

    # Assert: No error logs
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) == 0


# -------------------------------------------------------------------------
# Combined Error Scenarios
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_async_both_timeout_and_persistence_errors(
    template_cache_with_persistence, caplog
):
    """
    Test cleanup_async handles both timeout AND persistence errors.

    Verifies:
    - Timeout error is logged (warning)
    - Persistence error is logged (debug)
    - Both errors handled independently
    - Total log count is 2 (one for each error)
    """

    # Arrange - slow task + persistence error
    async def slow_task():
        await asyncio.sleep(100)

    task = asyncio.create_task(slow_task())
    template_cache_with_persistence._background_tasks.add(task)

    close_error = ValueError("Persistence close failed")
    template_cache_with_persistence._persistence_instance.close.side_effect = close_error

    # Capture logs
    with caplog.at_level(logging.DEBUG):
        # Act
        await template_cache_with_persistence.cleanup_async(timeout=0.1)

    # Assert: One timeout warning
    timeout_logs = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "timeout" in record.message.lower()
    ]
    assert len(timeout_logs) == 1

    # Assert: One persistence error log
    persistence_logs = [
        record
        for record in caplog.records
        if record.levelname == "DEBUG" and "persistence" in record.message.lower()
    ]
    assert len(persistence_logs) >= 1  # At least one log about persistence


# -------------------------------------------------------------------------
# __aexit__ Exception Propagation Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aexit_returns_false_for_exception_propagation(template_cache):
    """
    Test __aexit__ returns False to allow exception propagation.

    Verifies:
    - __aexit__ calls cleanup_async
    - __aexit__ returns False (does not suppress exceptions)
    - External exceptions propagate through context manager
    """
    # Arrange
    test_error = RuntimeError("Cache operation failed")

    # Act & Assert: Exception propagates
    with pytest.raises(RuntimeError, match="Cache operation failed"):
        async with template_cache:
            raise test_error


@pytest.mark.asyncio
async def test_aexit_cleanup_successful_no_errors(template_cache, caplog):
    """
    Test __aexit__ successful cleanup path.

    Verifies:
    - Successful cleanup produces no error logs
    - cleanup_async is called
    - State is clean after exit
    """
    # Capture logs
    with caplog.at_level(logging.ERROR):
        # Act
        async with template_cache:
            pass  # Normal operation

    # Assert: No error logs
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) == 0

    # Assert: Background tasks cleared
    assert len(template_cache._background_tasks) == 0


# -------------------------------------------------------------------------
# Cleanup State Indicators
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_async_clears_background_tasks_set(template_cache):
    """
    Test cleanup_async clears _background_tasks set.

    Verifies:
    - Background tasks set is cleared after cleanup
    - Set is empty even if tasks were cancelled
    """

    # Arrange - add task
    async def dummy_task():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(dummy_task())
    template_cache._background_tasks.add(task)

    # Act
    await template_cache.cleanup_async(timeout=1.0)

    # Assert: Tasks set is empty
    assert len(template_cache._background_tasks) == 0


@pytest.mark.asyncio
async def test_cleanup_async_clears_persistence_instance(
    template_cache_with_persistence,
):
    """
    Test cleanup_async clears _persistence_instance.

    Verifies:
    - _persistence_instance is set to None after cleanup
    - Subsequent cleanup doesn't fail
    """
    # Act
    await template_cache_with_persistence.cleanup_async(timeout=1.0)

    # Assert: Persistence instance is None
    assert template_cache_with_persistence._persistence_instance is None

    # Act again - should not fail
    await template_cache_with_persistence.cleanup_async(timeout=1.0)


# -------------------------------------------------------------------------
# Edge Cases
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_async_with_empty_background_tasks(template_cache, caplog):
    """
    Test cleanup_async with no background tasks.

    Verifies:
    - No error with empty tasks set
    - No warning logs
    - Quick completion
    """
    # Arrange - ensure tasks set is empty
    template_cache._background_tasks.clear()

    # Capture logs
    with caplog.at_level(logging.WARNING):
        # Act
        await template_cache.cleanup_async(timeout=1.0)

    # Assert: No warning logs
    warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warning_logs) == 0


@pytest.mark.asyncio
async def test_cleanup_async_idempotent(template_cache):
    """
    Test cleanup_async can be called multiple times.

    Verifies:
    - Multiple calls don't cause errors
    - Idempotent behavior
    - State remains consistent
    """
    # Act - call multiple times
    await template_cache.cleanup_async(timeout=1.0)
    await template_cache.cleanup_async(timeout=1.0)
    await template_cache.cleanup_async(timeout=1.0)

    # Assert: State is consistent
    assert len(template_cache._background_tasks) == 0
    assert template_cache._persistence_instance is None


@pytest.mark.asyncio
async def test_cleanup_async_zero_timeout(template_cache, caplog):
    """
    Test cleanup_async with zero timeout.

    Verifies:
    - Zero timeout immediately triggers timeout path
    - Warning log is emitted
    - Tasks are cancelled
    """

    # Arrange - add slow task
    async def slow_task():
        await asyncio.sleep(1.0)

    task = asyncio.create_task(slow_task())
    template_cache._background_tasks.add(task)

    # Capture logs
    with caplog.at_level(logging.WARNING):
        # Act - zero timeout
        await template_cache.cleanup_async(timeout=0.0)

    # Assert: Timeout warning
    warning_logs = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "timeout" in record.message.lower()
    ]
    assert len(warning_logs) == 1

    # Assert: Task cancelled
    assert task.cancelled() or task.done()


# -------------------------------------------------------------------------
# Run Tests
# -------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
