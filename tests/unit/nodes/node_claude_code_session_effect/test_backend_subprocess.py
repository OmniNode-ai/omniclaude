# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for SubprocessClaudeCodeSessionBackend (OMN-2800).

Test markers:
    @pytest.mark.unit  -- all tests here

Coverage:
    1. Success: stdout returned, exit code 0
    2. Non-zero exit -> ModelSkillResult(status=FAILED, error contains SUBPROCESS_ERROR)
    3. Timeout (asyncio.TimeoutError) -> error contains TIMEOUT
    4. Missing binary (probe failure) -> _available=False; calls return BACKEND_UNAVAILABLE
    5. Stdout truncated at 64 KB with truncation marker
    6. Stderr tail: only last 500 bytes included in FAILED result
    7. Semaphore blocks beyond MAX_CONCURRENT (test with 3 concurrent calls, cap=2)
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniclaude.nodes.node_claude_code_session_effect.backends.backend_subprocess import (
    _MAX_OUTPUT_BYTES,
    _STDERR_TAIL_BYTES,
    _TRUNCATION_MARKER,
    SubprocessClaudeCodeSessionBackend,
)
from omniclaude.nodes.node_claude_code_session_effect.models import (
    ClaudeCodeSessionOperation,
    ModelClaudeCodeSessionRequest,
)
from omniclaude.nodes.shared.models.model_skill_result import SkillResultStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORRELATION_ID = uuid.uuid4()


def _make_request(
    operation: ClaudeCodeSessionOperation = ClaudeCodeSessionOperation.SESSION_QUERY,
    prompt: str = "hello",
    working_directory: str = "/tmp",
) -> ModelClaudeCodeSessionRequest:
    return ModelClaudeCodeSessionRequest(
        operation=operation,
        prompt=prompt,
        working_directory=working_directory,
        correlation_id=_CORRELATION_ID,
    )


def _make_proc_mock(
    returncode: int = 0,
    stdout: bytes = b"response text",
    stderr: bytes = b"",
) -> AsyncMock:
    """Create a mock asyncio.Process returned by create_subprocess_exec."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


def _make_backend(available: bool = True) -> SubprocessClaudeCodeSessionBackend:
    """Create a backend instance with _available pre-set (skip probe)."""
    backend = SubprocessClaudeCodeSessionBackend()
    backend._available = available
    return backend


# ---------------------------------------------------------------------------
# Test 1: Success -- stdout returned, exit code 0
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_query_success() -> None:
    """session_query returns SUCCESS with stdout when exit code is 0."""
    backend = _make_backend(available=True)
    proc = _make_proc_mock(returncode=0, stdout=b"Hello from Claude")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await backend.session_query(_make_request(prompt="hi"))

    assert result.status == SkillResultStatus.SUCCESS
    assert result.output == "Hello from Claude"
    assert result.correlation_id == _CORRELATION_ID


# ---------------------------------------------------------------------------
# Test 2: Non-zero exit -> FAILED with SUBPROCESS_ERROR
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_query_nonzero_exit() -> None:
    """session_query returns FAILED with SUBPROCESS_ERROR on non-zero exit."""
    backend = _make_backend(available=True)
    proc = _make_proc_mock(returncode=1, stdout=b"", stderr=b"some error")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await backend.session_query(_make_request())

    assert result.status == SkillResultStatus.FAILED
    assert result.error is not None
    assert "SUBPROCESS_ERROR" in result.error
    assert "some error" in result.error


# ---------------------------------------------------------------------------
# Test 3: Timeout -> FAILED with TIMEOUT
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_query_timeout() -> None:
    """session_query returns FAILED with TIMEOUT on asyncio.TimeoutError."""
    backend = _make_backend(available=True)
    proc = _make_proc_mock()
    # Make wait_for raise TimeoutError
    proc.communicate = AsyncMock(side_effect=TimeoutError())

    with (
        patch("asyncio.create_subprocess_exec", return_value=proc),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        result = await backend.session_query(_make_request())

    assert result.status == SkillResultStatus.FAILED
    assert result.error is not None
    assert "TIMEOUT" in result.error


# ---------------------------------------------------------------------------
# Test 4: Missing binary (probe failure) -> BACKEND_UNAVAILABLE
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unavailable_backend_returns_error() -> None:
    """All methods return FAILED with BACKEND_UNAVAILABLE when _available=False."""
    backend = _make_backend(available=False)
    request = _make_request()

    for method_name in ("session_start", "session_query", "session_end"):
        method = getattr(backend, method_name)
        result = await method(request)
        assert result.status == SkillResultStatus.FAILED
        assert result.error is not None
        assert "BACKEND_UNAVAILABLE" in result.error


@pytest.mark.unit
def test_initialize_probe_failure_file_not_found() -> None:
    """initialize() sets _available=False when claude binary is not found."""
    backend = SubprocessClaudeCodeSessionBackend()

    with patch(
        "subprocess.run",
        side_effect=FileNotFoundError("claude not found"),
    ):
        backend.initialize()

    assert backend._available is False


@pytest.mark.unit
def test_initialize_probe_nonzero_version() -> None:
    """initialize() sets _available=False when claude --version returns non-zero."""
    backend = SubprocessClaudeCodeSessionBackend()

    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.returncode = 1
    mock_result.stdout = b""
    mock_result.stderr = b"error"

    with patch("subprocess.run", return_value=mock_result):
        backend.initialize()

    assert backend._available is False


@pytest.mark.unit
def test_initialize_probe_success() -> None:
    """initialize() sets _available=True when probe succeeds."""
    backend = SubprocessClaudeCodeSessionBackend()

    def _mock_run(args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        if args == ["claude", "--version"]:
            result.stdout = b"claude 1.0.0"
        elif args == ["claude", "--help"]:
            result.stdout = b"Usage: claude [options]\n  --print  --no-markdown  ..."
        result.stderr = b""
        return result

    with patch("subprocess.run", side_effect=_mock_run):
        backend.initialize()

    assert backend._available is True


# ---------------------------------------------------------------------------
# Test 5: Stdout truncated at 64 KB
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_query_stdout_truncated() -> None:
    """Output exceeding 64 KB is truncated with a marker."""
    backend = _make_backend(available=True)
    large_output = b"x" * (_MAX_OUTPUT_BYTES + 1000)
    proc = _make_proc_mock(returncode=0, stdout=large_output, stderr=b"")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await backend.session_query(_make_request())

    assert result.status == SkillResultStatus.SUCCESS
    assert result.output is not None
    assert result.output.endswith(_TRUNCATION_MARKER)
    # The decoded content before the marker should be exactly _MAX_OUTPUT_BYTES chars
    content_before_marker = result.output[: -len(_TRUNCATION_MARKER)]
    assert len(content_before_marker) == _MAX_OUTPUT_BYTES


# ---------------------------------------------------------------------------
# Test 6: Stderr tail -- only last 500 bytes included in FAILED result
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_query_stderr_tail() -> None:
    """Only the last 500 bytes of stderr appear in the error message."""
    backend = _make_backend(available=True)
    # Build stderr larger than _STDERR_TAIL_BYTES
    stderr_content = b"A" * 100 + b"B" * _STDERR_TAIL_BYTES
    proc = _make_proc_mock(returncode=1, stdout=b"", stderr=stderr_content)

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await backend.session_query(_make_request())

    assert result.status == SkillResultStatus.FAILED
    assert result.error is not None
    # Error should contain the tail of stderr (all B's)
    assert "B" * _STDERR_TAIL_BYTES in result.error
    # Should NOT contain the leading A's
    assert "A" * 100 not in result.error


# ---------------------------------------------------------------------------
# Test 7: Semaphore blocks beyond MAX_CONCURRENT
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semaphore_concurrency_cap() -> None:
    """Only MAX_CONCURRENT=2 calls run simultaneously; the 3rd waits."""
    backend = _make_backend(available=True)
    # Force cap to 2 for test determinism
    backend._semaphore = asyncio.Semaphore(2)

    entered_count = 0
    max_concurrent_observed = 0
    barrier = asyncio.Event()

    original_create = asyncio.create_subprocess_exec

    async def _slow_create(*args: Any, **kwargs: Any) -> AsyncMock:
        nonlocal entered_count, max_concurrent_observed
        entered_count += 1
        max_concurrent_observed = max(max_concurrent_observed, entered_count)
        # Wait for barrier to be set so all tasks hold the semaphore
        await barrier.wait()
        proc = _make_proc_mock(returncode=0, stdout=b"ok")
        entered_count -= 1
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=_slow_create):
        # Launch 3 concurrent queries
        tasks = [
            asyncio.create_task(backend.session_query(_make_request()))
            for _ in range(3)
        ]
        # Give the event loop time to start all tasks
        await asyncio.sleep(0.05)
        # Release the barrier so tasks can complete
        barrier.set()
        results = await asyncio.gather(*tasks)

    # All 3 should complete successfully
    assert all(r.status == SkillResultStatus.SUCCESS for r in results)
    # At most 2 should have been running at the same time
    assert max_concurrent_observed <= 2


# ---------------------------------------------------------------------------
# Test: session_start and session_end are no-ops returning SUCCESS
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_start_noop() -> None:
    """session_start returns SUCCESS without launching a subprocess."""
    backend = _make_backend(available=True)
    request = _make_request(operation=ClaudeCodeSessionOperation.SESSION_START)

    result = await backend.session_start(request)

    assert result.status == SkillResultStatus.SUCCESS
    assert result.output is not None
    assert "no-op" in result.output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_end_noop() -> None:
    """session_end returns SUCCESS without launching a subprocess."""
    backend = _make_backend(available=True)
    request = _make_request(operation=ClaudeCodeSessionOperation.SESSION_END)

    result = await backend.session_end(request)

    assert result.status == SkillResultStatus.SUCCESS
    assert result.output is not None
    assert "no-op" in result.output
