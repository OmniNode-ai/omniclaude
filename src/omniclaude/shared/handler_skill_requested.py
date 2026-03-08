# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Shared handler for skill dispatch — routes any skill request to Polly.

Single canonical handler imported by all skill dispatch nodes. Constructs
the Polly prompt from a ModelSkillRequest, dispatches it via the injected
task_dispatcher callable, and parses the structured RESULT: block from the
output.

Lifecycle events (OMN-2773): when an optional ``event_emitter`` is provided,
the handler emits ``skill.started`` before dispatch and ``skill.completed``
after (on both success and exception paths). Events are best-effort — emission
failures are logged but never propagate to the caller.

Public API:
    handle_skill_requested(request, *, task_dispatcher, event_emitter=None) -> ModelSkillResult

Private helpers:
    _build_args_string(args) -> str
    _parse_result_block(output) -> tuple[SkillResultStatus, str | None]
    _emit_completed(...)  (module-private)
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from .models.model_skill_lifecycle_events import (
    ModelSkillCompletedEvent,
    ModelSkillStartedEvent,
)
from .models.model_skill_request import ModelSkillRequest
from .models.model_skill_result import ModelSkillResult, SkillResultStatus

__all__ = [
    "handle_skill_requested",
]

logger = logging.getLogger(__name__)

# Type alias for the task dispatcher dependency.
# The dispatcher receives a prompt string and returns the Polly output string.
TaskDispatcher = Callable[[str], Awaitable[str]]

# Type alias for the optional event emitter dependency.
# Accepts event_type (str) and payload (dict) — mirrors emit_client_wrapper.emit_event.
EventEmitter = Callable[[str, dict[str, object]], bool]

# Sentinel string that Polly must include in its output.
_RESULT_BLOCK_MARKER = "RESULT:"

# Keys within the RESULT block.
_STATUS_KEY = "status:"
_ERROR_KEY = "error:"

# Repo identifier — injected into lifecycle events to prevent cross-repo collisions.
_REPO_ID = "omniclaude"


def _build_args_string(args: dict[str, str]) -> str:
    """Serialize args dict to a canonical CLI-style flags string.

    Conversion rules:
    - Empty string value or the literal "true" → bare flag (``--key``)
    - Any other value → ``--key value`` pair

    Args:
        args: Argument key/value pairs from ModelSkillRequest.

    Returns:
        Space-joined CLI flags string, or empty string if args is empty.

    Examples:
        >>> _build_args_string({"verbose": "", "count": "5"})
        '--verbose --count 5'
        >>> _build_args_string({"dry-run": "true"})
        '--dry-run'
        >>> _build_args_string({})
        ''
    """
    if not args:
        return ""

    parts: list[str] = []
    for key, value in args.items():
        if value == "" or value == "true":
            parts.append(f"--{key}")
        else:
            parts.append(f"--{key} {value}")

    return " ".join(parts)


def _parse_result_block(output: str) -> tuple[SkillResultStatus, str | None]:
    """Extract status and error from a required RESULT: block in Polly's output.

    Polly is required to include a structured block of the form::

        RESULT:
        status: success
        error: <optional error detail>

    Parsing rules:
    - If no ``RESULT:`` marker is found → PARTIAL (block absent)
    - ``status: success`` → SUCCESS
    - ``status: failed`` → FAILED
    - Any other / missing status line → PARTIAL
    - ``error: <text>`` line → captured as error detail (stripped)
    - Missing or empty ``error:`` line → None

    Args:
        output: Raw text output from Polly.

    Returns:
        A tuple of (SkillResultStatus, error_detail | None).
    """
    # Locate the RESULT: block
    marker_idx = output.find(_RESULT_BLOCK_MARKER)
    if marker_idx == -1:
        logger.warning("No RESULT: block found in Polly output; returning PARTIAL")
        return SkillResultStatus.PARTIAL, "No RESULT: block in output"

    # Extract the text after the marker and scope to the first paragraph only.
    # Stop collecting lines as soon as we hit a blank line after at least one
    # non-blank line has been added — this prevents later status:/error: lines
    # (e.g. from verbose Polly output) from overwriting the values parsed from
    # the actual RESULT block.
    block_text = output[marker_idx + len(_RESULT_BLOCK_MARKER) :]
    block_lines: list[str] = []
    for line in block_text.splitlines():
        if block_lines and line.strip() == "":
            break
        block_lines.append(line)

    status: SkillResultStatus = SkillResultStatus.PARTIAL
    error: str | None = None

    for line in block_lines:
        stripped = line.strip().lower()

        if stripped.startswith(_STATUS_KEY):
            raw_status = line.strip()[len(_STATUS_KEY) :].strip().lower()
            if raw_status == "success":
                status = SkillResultStatus.SUCCESS
            elif raw_status == "failed":
                status = SkillResultStatus.FAILED
            else:
                status = SkillResultStatus.PARTIAL

        elif stripped.startswith(_ERROR_KEY):
            raw_error = line.strip()[len(_ERROR_KEY) :].strip()
            error = raw_error if raw_error else None

    return status, error


def _emit_completed(
    *,
    event_emitter: EventEmitter,
    run_id: UUID,
    request: ModelSkillRequest,
    status: SkillResultStatus,
    duration_ms: int,
    error_type: str | None,
    started_emit_failed: bool,
) -> None:
    """Emit the skill.completed lifecycle event (best-effort).

    Called from both the success and exception paths of handle_skill_requested.
    Any emission failure is logged but never propagated.

    Args:
        event_emitter: Callable matching emit_client_wrapper.emit_event signature.
        run_id: Shared run identifier (join key with skill.started).
        request: The original skill request.
        status: Final status of the invocation.
        duration_ms: Elapsed wall-clock time in milliseconds (from perf_counter).
        error_type: Exception class name if task_dispatcher raised, else None.
        started_emit_failed: Whether the skill.started emission failed.
    """
    completed_event = ModelSkillCompletedEvent(
        run_id=run_id,
        skill_name=request.skill_name,
        repo_id=_REPO_ID,
        correlation_id=request.correlation_id,
        status=status.value,
        duration_ms=duration_ms,
        error_type=error_type,
        started_emit_failed=started_emit_failed,
        emitted_at=datetime.now(UTC),
    )
    try:
        payload = completed_event.model_dump(mode="json")
        # run_id must be a string for the event registry partition key lookup
        payload["run_id"] = str(run_id)
        emitted = event_emitter("skill.completed", payload)
        if not emitted:
            logger.warning(
                "skill.completed emission returned False for skill %r (run_id=%s, correlation_id=%s)",
                request.skill_name,
                run_id,
                request.correlation_id,
            )
    except Exception:
        logger.exception(
            "Failed to emit skill.completed event for skill %r (run_id=%s, correlation_id=%s)",
            request.skill_name,
            run_id,
            request.correlation_id,
        )


async def handle_skill_requested(
    request: ModelSkillRequest,
    *,
    task_dispatcher: TaskDispatcher,
    event_emitter: EventEmitter | None = None,
) -> ModelSkillResult:
    """Dispatch a skill request to Polly and return a structured result.

    Constructs a prompt that includes the skill path and serialized args,
    dispatches it to the polymorphic agent (Polly) via ``task_dispatcher``,
    and parses the required RESULT: block from the output.

    On any exception from ``task_dispatcher`` the handler returns a FAILED
    result rather than propagating the exception.

    When ``event_emitter`` is provided, emits ``skill.started`` before dispatch
    and ``skill.completed`` after (both success and exception paths). Emission
    failures are logged but never propagate.

    Args:
        request: Fully validated skill request.
        task_dispatcher: Async callable that sends a prompt to Polly and
            returns the raw output string.
        event_emitter: Optional callable for emitting lifecycle events.
            Signature: (event_type: str, payload: dict[str, object]) -> bool.
            When None, no lifecycle events are emitted (default — zero impact
            on existing callers).

    Returns:
        ModelSkillResult with the parsed status, output, and optional error.
    """
    args_str = _build_args_string(request.args)
    args_clause = f" with args: {args_str}" if args_str else ""

    prompt = (
        f"Execute the skill defined at {request.skill_path!r}{args_clause}.\n"
        f"Read the skill definition from that path before executing.\n"
        f"After execution, you MUST include a structured RESULT: block in your "
        f"output with the following format:\n\n"
        f"RESULT:\n"
        f"status: <success|failed|partial>\n"
        f"error: <error detail or leave blank>\n"
    )

    logger.debug(
        "Dispatching skill %r to Polly (correlation_id=%s, skill_path=%r)",
        request.skill_name,
        request.correlation_id,
        request.skill_path,
    )

    # Generate run_id once — shared by started + completed events (join key).
    run_id: UUID = uuid.uuid4()

    # Derive a repo-relative skill_id from the skill_path.
    # skill_path may be absolute; strip everything up to "plugins/" if present.
    skill_path = request.skill_path
    skill_id_marker = "plugins/"
    marker_pos = skill_path.find(skill_id_marker)
    skill_id = skill_path[marker_pos:] if marker_pos != -1 else skill_path

    # Emit skill.started (best-effort, before dispatch).
    started_emit_failed = False
    if event_emitter is not None:
        started_event = ModelSkillStartedEvent(
            run_id=run_id,
            skill_name=request.skill_name,
            skill_id=skill_id,
            repo_id=_REPO_ID,
            correlation_id=request.correlation_id,
            args_count=len(request.args),
            emitted_at=datetime.now(UTC),
        )
        try:
            payload = started_event.model_dump(mode="json")
            payload["run_id"] = str(run_id)
            emitted = event_emitter("skill.started", payload)
            if not emitted:
                started_emit_failed = True
                logger.warning(
                    "skill.started emission returned False for skill %r (run_id=%s, correlation_id=%s)",
                    request.skill_name,
                    run_id,
                    request.correlation_id,
                )
        except Exception:
            started_emit_failed = True
            logger.exception(
                "Failed to emit skill.started event for skill %r (run_id=%s, correlation_id=%s)",
                request.skill_name,
                run_id,
                request.correlation_id,
            )

    # Record start time using monotonic counter (NTP-immune).
    t0 = time.perf_counter()

    try:
        raw_output: str = await task_dispatcher(prompt)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.exception(
            "task_dispatcher raised for skill %r (correlation_id=%s)",
            request.skill_name,
            request.correlation_id,
        )
        if event_emitter is not None:
            _emit_completed(
                event_emitter=event_emitter,
                run_id=run_id,
                request=request,
                status=SkillResultStatus.FAILED,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                started_emit_failed=started_emit_failed,
            )
        return ModelSkillResult(
            skill_name=request.skill_name,
            status=SkillResultStatus.FAILED,
            output=None,
            error="task_dispatcher raised an exception",
            correlation_id=request.correlation_id,
        )

    duration_ms = int((time.perf_counter() - t0) * 1000)
    output_str: str = str(raw_output) if raw_output is not None else ""
    status, error = _parse_result_block(output_str)

    logger.debug(
        "Skill %r completed with status=%s (correlation_id=%s)",
        request.skill_name,
        status,
        request.correlation_id,
    )

    if event_emitter is not None:
        _emit_completed(
            event_emitter=event_emitter,
            run_id=run_id,
            request=request,
            status=status,
            duration_ms=duration_ms,
            error_type=None,
            started_emit_failed=started_emit_failed,
        )

    return ModelSkillResult(
        skill_name=request.skill_name,
        status=status,
        output=output_str if output_str else None,
        error=error,
        correlation_id=request.correlation_id,
    )
