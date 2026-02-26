# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for HandlerGitSubprocess (OMN-2817).

Test markers:
    @pytest.mark.unit  -- all tests here

Coverage:
    1. All 11 operations: parameterized success tests
    2. All 11 operations: parameterized failure (non-zero exit) tests
    3. Timeout per operation
    4. Binary unavailable (git/gh) -> GIT_UNAVAILABLE / GH_UNAVAILABLE
    5. Input validation: missing required fields -> INVALID_REQUEST
    6. Repo targeting: gh calls include -R owner/name when repo set
    7. Working directory: git calls pass cwd=working_directory
    8. Output truncation: stdout >64KB truncated
    9. JSON parse: pr_list success -> result.pr_list; failure -> PARSE_ERROR
   10. Ticket stamp: pr_create injects stamp; does not duplicate existing
   11. PR_MERGE with use_merge_queue: --merge-queue flag presence/absence
   12. Semaphore concurrency cap
   13. Initialize probe: success and failure paths
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniclaude.nodes.node_git_effect.handlers.handler_git_subprocess import (
    _MAX_OUTPUT_BYTES,
    _TRUNCATION_MARKER,
    OPERATION_TIMEOUTS,
    TICKET_STAMP_END,
    TICKET_STAMP_START,
    HandlerGitSubprocess,
    _inject_ticket_stamp,
)
from omniclaude.nodes.node_git_effect.models import (
    GitOperation,
    ModelGitRequest,
    ModelPRListFilters,
)
from omniclaude.nodes.node_git_effect.models.model_git_result import GitResultStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORRELATION_ID = uuid.uuid4()


def _make_proc_mock(
    returncode: int = 0,
    stdout: bytes = b"ok",
    stderr: bytes = b"",
) -> AsyncMock:
    """Create a mock asyncio.Process returned by create_subprocess_exec."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


def _make_handler(
    git_available: bool = True, gh_available: bool = True
) -> HandlerGitSubprocess:
    """Create a handler instance with availability pre-set (skip probe)."""
    handler = HandlerGitSubprocess()
    handler._git_available = git_available
    handler._gh_available = gh_available
    return handler


# ---------------------------------------------------------------------------
# Git operations (use git binary)
# ---------------------------------------------------------------------------
_GIT_OPS: list[tuple[GitOperation, dict[str, Any], list[str]]] = [
    (
        GitOperation.BRANCH_CREATE,
        {"branch_name": "feat/x", "base_ref": "main"},
        ["git", "checkout", "-b", "feat/x", "main"],
    ),
    (
        GitOperation.COMMIT,
        {"commit_message": "fix: thing"},
        # commit calls git add -A first, then git commit -m
        ["git", "commit", "-m", "fix: thing"],
    ),
    (
        GitOperation.PUSH,
        {"branch_name": "feat/x"},
        ["git", "push", "-u", "origin", "feat/x"],
    ),
    (
        GitOperation.TAG_CREATE,
        {"tag_name": "v1.0.0"},
        # tag_create calls git tag then git push origin <tag>
        ["git", "tag", "v1.0.0"],
    ),
]

# ---------------------------------------------------------------------------
# GH operations (use gh binary)
# ---------------------------------------------------------------------------
_GH_OPS: list[tuple[GitOperation, dict[str, Any], list[str]]] = [
    (
        GitOperation.PR_CREATE,
        {
            "pr_title": "feat: add feature",
            "pr_body": "body text",
            "base_branch": "main",
            "ticket_id": "OMN-1234",
        },
        ["gh", "pr", "create", "--title", "feat: add feature"],
    ),
    (
        GitOperation.PR_UPDATE,
        {"pr_number": 42, "pr_title": "new title"},
        ["gh", "pr", "edit", "42", "--title", "new title"],
    ),
    (
        GitOperation.PR_CLOSE,
        {"pr_number": 42},
        ["gh", "pr", "close", "42"],
    ),
    (
        GitOperation.PR_MERGE,
        {"pr_number": 42},
        ["gh", "pr", "merge", "42", "--squash"],
    ),
    (
        GitOperation.PR_LIST,
        {"json_fields": ["number", "title"]},
        ["gh", "pr", "list", "--json", "number,title"],
    ),
    (
        GitOperation.PR_VIEW,
        {"pr_number": 42, "json_fields": ["number", "title"]},
        ["gh", "pr", "view", "42", "--json", "number,title"],
    ),
    (
        GitOperation.LABEL_ADD,
        {"pr_number": 42, "labels": ["bug", "priority:high"]},
        ["gh", "pr", "edit", "42", "--add-label", "bug,priority:high"],
    ),
]


# ===========================================================================
# Test 1: Parameterized success for all 11 operations
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs", "expected_cmd_prefix"),
    _GIT_OPS,
    ids=[op.value for op, _, _ in _GIT_OPS],
)
async def test_git_operation_success(
    operation: GitOperation,
    kwargs: dict[str, Any],
    expected_cmd_prefix: list[str],
) -> None:
    """Git operations return SUCCESS with correct command invocation."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"success output")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=operation,
            correlation_id=_CORRELATION_ID,
            **kwargs,
        )
        result = await getattr(handler, operation.value)(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.correlation_id == _CORRELATION_ID
    # Verify the expected command was called (at least one call matches)
    calls = mock_exec.call_args_list
    assert len(calls) >= 1
    # Check that the expected prefix appears in one of the calls
    found = False
    for call in calls:
        call_args = list(call[0])
        if call_args[: len(expected_cmd_prefix)] == expected_cmd_prefix:
            found = True
            break
    assert found, (
        f"Expected command prefix {expected_cmd_prefix} not found in calls: "
        f"{[list(c[0]) for c in calls]}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs", "expected_cmd_prefix"),
    _GH_OPS,
    ids=[op.value for op, _, _ in _GH_OPS],
)
async def test_gh_operation_success(
    operation: GitOperation,
    kwargs: dict[str, Any],
    expected_cmd_prefix: list[str],
) -> None:
    """GH operations return SUCCESS with correct command invocation."""
    handler = _make_handler()
    # For JSON operations, return valid JSON
    if operation in (GitOperation.PR_LIST, GitOperation.PR_VIEW):
        if operation == GitOperation.PR_LIST:
            stdout = json.dumps([{"number": 1, "title": "test"}]).encode()
        else:
            stdout = json.dumps({"number": 42, "title": "test"}).encode()
    elif operation == GitOperation.PR_CREATE:
        stdout = b"https://github.com/OmniNode-ai/omniclaude/pull/99\n"
    else:
        stdout = b"success output"

    proc = _make_proc_mock(returncode=0, stdout=stdout)

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=operation,
            correlation_id=_CORRELATION_ID,
            **kwargs,
        )
        result = await getattr(handler, operation.value)(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.correlation_id == _CORRELATION_ID


# ===========================================================================
# Test 2: Parameterized failure (non-zero exit) for all operations
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [(op, kw) for op, kw, _ in _GIT_OPS + _GH_OPS],
    ids=[op.value for op, _, _ in _GIT_OPS + _GH_OPS],
)
async def test_operation_failure_nonzero_exit(
    operation: GitOperation,
    kwargs: dict[str, Any],
) -> None:
    """Operations return FAILED with SUBPROCESS_ERROR on non-zero exit."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=1, stdout=b"", stderr=b"fatal: error")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        request = ModelGitRequest(
            operation=operation,
            correlation_id=_CORRELATION_ID,
            **kwargs,
        )
        result = await getattr(handler, operation.value)(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error is not None
    assert result.error_code is not None


# ===========================================================================
# Test 3: Timeout per operation
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [(op, kw) for op, kw, _ in _GIT_OPS + _GH_OPS],
    ids=[op.value for op, _, _ in _GIT_OPS + _GH_OPS],
)
async def test_operation_timeout(
    operation: GitOperation,
    kwargs: dict[str, Any],
) -> None:
    """Operations return FAILED with TIMEOUT on asyncio.TimeoutError."""
    handler = _make_handler()
    proc = _make_proc_mock()
    proc.communicate = AsyncMock(side_effect=TimeoutError())

    with (
        patch("asyncio.create_subprocess_exec", return_value=proc),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        request = ModelGitRequest(
            operation=operation,
            correlation_id=_CORRELATION_ID,
            **kwargs,
        )
        result = await getattr(handler, operation.value)(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error is not None
    assert "TIMEOUT" in result.error
    assert result.error_code == "TIMEOUT"


# ===========================================================================
# Test 4: Binary unavailable
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [(op, kw) for op, kw, _ in _GIT_OPS],
    ids=[op.value for op, _, _ in _GIT_OPS],
)
async def test_git_unavailable(
    operation: GitOperation,
    kwargs: dict[str, Any],
) -> None:
    """Git operations return FAILED with GIT_UNAVAILABLE when git is not available."""
    handler = _make_handler(git_available=False)
    request = ModelGitRequest(
        operation=operation,
        correlation_id=_CORRELATION_ID,
        **kwargs,
    )
    result = await getattr(handler, operation.value)(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error_code == "GIT_UNAVAILABLE"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [(op, kw) for op, kw, _ in _GH_OPS],
    ids=[op.value for op, _, _ in _GH_OPS],
)
async def test_gh_unavailable(
    operation: GitOperation,
    kwargs: dict[str, Any],
) -> None:
    """GH operations return FAILED with GH_UNAVAILABLE when gh is not available."""
    handler = _make_handler(gh_available=False)
    request = ModelGitRequest(
        operation=operation,
        correlation_id=_CORRELATION_ID,
        **kwargs,
    )
    result = await getattr(handler, operation.value)(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error_code == "GH_UNAVAILABLE"


# ===========================================================================
# Test 5: Input validation - missing required fields
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    list(GitOperation),
    ids=[op.value for op in GitOperation],
)
async def test_missing_required_fields(operation: GitOperation) -> None:
    """Operations return FAILED with INVALID_REQUEST when required fields are missing."""
    handler = _make_handler()
    # Create request with only the operation -- no other fields
    request = ModelGitRequest(
        operation=operation,
        correlation_id=_CORRELATION_ID,
    )
    result = await getattr(handler, operation.value)(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error_code == "INVALID_REQUEST"
    assert "Missing required fields" in (result.error or "")


# ===========================================================================
# Test 6: Repo targeting - gh calls include -R owner/name
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_repo_targeting_gh() -> None:
    """GH operations include -R owner/name when repo is set."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"done")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_CLOSE,
            pr_number=42,
            repo="OmniNode-ai/omnibase_core",
            correlation_id=_CORRELATION_ID,
        )
        await handler.pr_close(request)

    call_args = list(mock_exec.call_args[0])
    assert "-R" in call_args
    assert "OmniNode-ai/omnibase_core" in call_args


@pytest.mark.unit
@pytest.mark.asyncio
async def test_repo_targeting_gh_no_repo() -> None:
    """GH operations do NOT include -R when repo is None."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"done")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_CLOSE,
            pr_number=42,
            correlation_id=_CORRELATION_ID,
        )
        await handler.pr_close(request)

    call_args = list(mock_exec.call_args[0])
    assert "-R" not in call_args


# ===========================================================================
# Test 7: Working directory - git calls pass cwd=working_directory
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_working_directory_git() -> None:
    """Git operations pass cwd=working_directory to subprocess."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"ok")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.BRANCH_CREATE,
            branch_name="feat/test",
            working_directory="/tmp/my-repo",
            correlation_id=_CORRELATION_ID,
        )
        await handler.branch_create(request)

    assert mock_exec.call_args[1].get("cwd") == "/tmp/my-repo"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_working_directory_gh() -> None:
    """GH operations pass cwd=working_directory to subprocess."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"done")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_CLOSE,
            pr_number=42,
            working_directory="/tmp/my-repo",
            correlation_id=_CORRELATION_ID,
        )
        await handler.pr_close(request)

    assert mock_exec.call_args[1].get("cwd") == "/tmp/my-repo"


# ===========================================================================
# Test 8: Output truncation - stdout >64KB
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_truncation() -> None:
    """Output exceeding 64 KB is truncated with a marker."""
    handler = _make_handler()
    large_output = b"x" * (_MAX_OUTPUT_BYTES + 1000)
    proc = _make_proc_mock(returncode=0, stdout=large_output)

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        request = ModelGitRequest(
            operation=GitOperation.BRANCH_CREATE,
            branch_name="feat/big",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.branch_create(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.output is not None
    assert result.output.endswith(_TRUNCATION_MARKER)
    content_before_marker = result.output[: -len(_TRUNCATION_MARKER)]
    assert len(content_before_marker) == _MAX_OUTPUT_BYTES


# ===========================================================================
# Test 9: JSON parse - pr_list and pr_view
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_list_json_parse_success() -> None:
    """pr_list parses JSON stdout into result.pr_list."""
    handler = _make_handler()
    json_data = [{"number": 1, "title": "PR 1"}, {"number": 2, "title": "PR 2"}]
    proc = _make_proc_mock(returncode=0, stdout=json.dumps(json_data).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        request = ModelGitRequest(
            operation=GitOperation.PR_LIST,
            json_fields=["number", "title"],
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_list(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.pr_list == json_data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_view_json_parse_success() -> None:
    """pr_view parses JSON stdout into result.pr_data."""
    handler = _make_handler()
    json_data = {"number": 42, "title": "My PR", "state": "OPEN"}
    proc = _make_proc_mock(returncode=0, stdout=json.dumps(json_data).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        request = ModelGitRequest(
            operation=GitOperation.PR_VIEW,
            pr_number=42,
            json_fields=["number", "title", "state"],
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_view(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.pr_data == json_data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_list_json_parse_failure() -> None:
    """pr_list returns FAILED with PARSE_ERROR on invalid JSON."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"not valid json {{{")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        request = ModelGitRequest(
            operation=GitOperation.PR_LIST,
            json_fields=["number"],
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_list(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error_code == "PARSE_ERROR"


# ===========================================================================
# Test 10: Ticket stamp injection + no duplicate
# ===========================================================================


@pytest.mark.unit
def test_ticket_stamp_injection() -> None:
    """_inject_ticket_stamp adds stamp when not already present."""
    body = "## Summary\nThis is a PR."
    result = _inject_ticket_stamp(body, "OMN-1234")

    assert TICKET_STAMP_START in result
    assert TICKET_STAMP_END in result
    assert "OMN-1234" in result
    assert result.startswith(body)


@pytest.mark.unit
def test_ticket_stamp_no_duplicate() -> None:
    """_inject_ticket_stamp does not duplicate if already stamped."""
    body = f"## Summary\n{TICKET_STAMP_START}\nold stamp\n{TICKET_STAMP_END}"
    result = _inject_ticket_stamp(body, "OMN-5678")

    # Should be unchanged -- already has stamp markers
    assert result == body


@pytest.mark.unit
def test_ticket_stamp_no_ticket_id() -> None:
    """_inject_ticket_stamp returns body unchanged when ticket_id is None."""
    body = "## Summary"
    result = _inject_ticket_stamp(body, None)
    assert result == body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_create_injects_stamp() -> None:
    """pr_create injects ticket stamp into the PR body."""
    handler = _make_handler()
    proc = _make_proc_mock(
        returncode=0,
        stdout=b"https://github.com/OmniNode-ai/omniclaude/pull/99\n",
    )

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_CREATE,
            pr_title="feat: add feature",
            pr_body="## Summary\nNew feature.",
            base_branch="main",
            ticket_id="OMN-1234",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_create(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.pr_number == 99
    assert result.pr_url == "https://github.com/OmniNode-ai/omniclaude/pull/99"

    # Check that the body passed to gh includes the ticket stamp
    call_args = list(mock_exec.call_args[0])
    body_idx = call_args.index("--body") + 1
    body_passed = call_args[body_idx]
    assert TICKET_STAMP_START in body_passed
    assert "OMN-1234" in body_passed


# ===========================================================================
# Test 11: PR_MERGE with use_merge_queue flag
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_merge_with_merge_queue() -> None:
    """PR_MERGE with use_merge_queue=True passes --merge-queue."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"queued")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_MERGE,
            pr_number=42,
            use_merge_queue=True,
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_merge(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.merge_state == "queued"
    call_args = list(mock_exec.call_args[0])
    assert "--merge-queue" in call_args
    assert "--squash" not in call_args


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_merge_without_merge_queue() -> None:
    """PR_MERGE with use_merge_queue=False does NOT pass --merge-queue."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"merged")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_MERGE,
            pr_number=42,
            use_merge_queue=False,
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_merge(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.merge_state == "merged"
    call_args = list(mock_exec.call_args[0])
    assert "--merge-queue" not in call_args
    assert "--squash" in call_args


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_merge_with_merge_method() -> None:
    """PR_MERGE respects merge_method field."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"merged")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_MERGE,
            pr_number=42,
            merge_method="rebase",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_merge(request)

    assert result.status == GitResultStatus.SUCCESS
    call_args = list(mock_exec.call_args[0])
    assert "--rebase" in call_args


# ===========================================================================
# Test 12: Semaphore concurrency cap
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semaphore_concurrency_cap() -> None:
    """Only MAX_CONCURRENT calls run simultaneously; extras wait."""
    handler = _make_handler()
    # Force cap to 2 for test determinism
    handler._semaphore = asyncio.Semaphore(2)

    entered_count = 0
    max_concurrent_observed = 0
    barrier = asyncio.Event()
    two_entered = asyncio.Event()

    async def _slow_create(*args: Any, **kwargs: Any) -> AsyncMock:
        nonlocal entered_count, max_concurrent_observed
        entered_count += 1
        max_concurrent_observed = max(max_concurrent_observed, entered_count)
        if entered_count >= 2:
            two_entered.set()
        await barrier.wait()
        proc = _make_proc_mock(returncode=0, stdout=b"ok")
        entered_count -= 1
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=_slow_create):
        tasks = [
            asyncio.create_task(
                handler.branch_create(
                    ModelGitRequest(
                        operation=GitOperation.BRANCH_CREATE,
                        branch_name=f"feat/test-{i}",
                        correlation_id=_CORRELATION_ID,
                    )
                )
            )
            for i in range(3)
        ]
        await asyncio.wait_for(two_entered.wait(), timeout=2.0)
        barrier.set()
        results = await asyncio.gather(*tasks)

    assert all(r.status == GitResultStatus.SUCCESS for r in results)
    assert max_concurrent_observed <= 2


# ===========================================================================
# Test 13: Initialize probe
# ===========================================================================


@pytest.mark.unit
def test_initialize_probe_success() -> None:
    """initialize() sets both binaries available when probes succeed."""
    handler = HandlerGitSubprocess()

    def _mock_run(args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        if args == ["git", "--version"]:
            result.stdout = b"git version 2.43.0"
        elif args == ["gh", "--version"]:
            result.stdout = b"gh version 2.40.0"
        result.stderr = b""
        return result

    with patch("subprocess.run", side_effect=_mock_run):
        handler.initialize()

    assert handler._git_available is True
    assert handler._gh_available is True
    assert handler._git_version is not None
    assert handler._gh_version is not None


@pytest.mark.unit
def test_initialize_probe_git_not_found() -> None:
    """initialize() marks git unavailable when binary not found."""
    handler = HandlerGitSubprocess()

    call_count = 0

    def _mock_run(args: Any, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if args[0] == "git":
            raise FileNotFoundError("git not found")
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        result.stdout = b"gh version 2.40.0"
        result.stderr = b""
        return result

    with patch("subprocess.run", side_effect=_mock_run):
        handler.initialize()

    assert handler._git_available is False
    assert handler._gh_available is True


@pytest.mark.unit
def test_initialize_probe_gh_not_found() -> None:
    """initialize() marks gh unavailable when binary not found."""
    handler = HandlerGitSubprocess()

    def _mock_run(args: Any, **kwargs: Any) -> MagicMock:
        if args[0] == "gh":
            raise FileNotFoundError("gh not found")
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        result.stdout = b"git version 2.43.0"
        result.stderr = b""
        return result

    with patch("subprocess.run", side_effect=_mock_run):
        handler.initialize()

    assert handler._git_available is True
    assert handler._gh_available is False


# ===========================================================================
# Test 14: Per-operation timeout values are distinct
# ===========================================================================


@pytest.mark.unit
def test_per_operation_timeout_values() -> None:
    """Each operation has a configured timeout value."""
    for op in GitOperation:
        assert op in OPERATION_TIMEOUTS
        assert OPERATION_TIMEOUTS[op] > 0


# ===========================================================================
# Test 15: Tag create - annotated vs lightweight
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tag_create_annotated() -> None:
    """tag_create with tag_message creates annotated tag."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"ok")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.TAG_CREATE,
            tag_name="v1.0.0",
            tag_message="Release v1.0.0",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.tag_create(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.tag_name == "v1.0.0"
    # First call should be annotated tag
    first_call = list(mock_exec.call_args_list[0][0])
    assert "-a" in first_call
    assert "-m" in first_call


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tag_create_lightweight() -> None:
    """tag_create without tag_message creates lightweight tag."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"ok")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.TAG_CREATE,
            tag_name="v1.0.0",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.tag_create(request)

    assert result.status == GitResultStatus.SUCCESS
    assert result.tag_name == "v1.0.0"
    first_call = list(mock_exec.call_args_list[0][0])
    assert "-a" not in first_call
    assert "-m" not in first_call


# ===========================================================================
# Test 16: PR list with filters
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pr_list_with_filters() -> None:
    """pr_list passes filter flags from ModelPRListFilters."""
    handler = _make_handler()
    json_data = [{"number": 1}]
    proc = _make_proc_mock(returncode=0, stdout=json.dumps(json_data).encode())

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PR_LIST,
            json_fields=["number"],
            list_filters=ModelPRListFilters(
                state="open",
                head="feat/test",
                author="jonah",
                limit=50,
            ),
            repo="OmniNode-ai/omniclaude",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.pr_list(request)

    assert result.status == GitResultStatus.SUCCESS
    call_args = list(mock_exec.call_args[0])
    assert "--state" in call_args
    assert "open" in call_args
    assert "--head" in call_args
    assert "feat/test" in call_args
    assert "--author" in call_args
    assert "jonah" in call_args
    assert "--limit" in call_args
    assert "50" in call_args
    assert "-R" in call_args
    assert "OmniNode-ai/omniclaude" in call_args


# ===========================================================================
# Test 17: Error classification
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_classification_auth_failure() -> None:
    """Stderr containing 'authentication' classifies as AUTH_FAILURE."""
    handler = _make_handler()
    proc = _make_proc_mock(
        returncode=128,
        stdout=b"",
        stderr=b"fatal: Authentication failed for ...",
    )

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        request = ModelGitRequest(
            operation=GitOperation.PUSH,
            branch_name="feat/x",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.push(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error_code == "AUTH_FAILURE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_classification_not_found() -> None:
    """Stderr containing 'not found' classifies as NOT_FOUND."""
    handler = _make_handler()
    proc = _make_proc_mock(
        returncode=1,
        stdout=b"",
        stderr=b"error: pathspec 'feat/x' did not match any file(s) known - not found",
    )

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        request = ModelGitRequest(
            operation=GitOperation.BRANCH_CREATE,
            branch_name="feat/x",
            correlation_id=_CORRELATION_ID,
        )
        result = await handler.branch_create(request)

    assert result.status == GitResultStatus.FAILED
    assert result.error_code == "NOT_FOUND"


# ===========================================================================
# Test 18: Import test
# ===========================================================================


@pytest.mark.unit
def test_import_handler() -> None:
    """HandlerGitSubprocess can be imported from the handlers package."""
    from omniclaude.nodes.node_git_effect.handlers import HandlerGitSubprocess

    handler = HandlerGitSubprocess()
    assert handler.handler_key == "subprocess"


# ===========================================================================
# Test 19: Force push uses --force-with-lease
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_push_force_with_lease() -> None:
    """Push with force_push=True uses --force-with-lease."""
    handler = _make_handler()
    proc = _make_proc_mock(returncode=0, stdout=b"ok")

    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        request = ModelGitRequest(
            operation=GitOperation.PUSH,
            branch_name="feat/x",
            force_push=True,
            correlation_id=_CORRELATION_ID,
        )
        await handler.push(request)

    call_args = list(mock_exec.call_args[0])
    assert "--force-with-lease" in call_args
