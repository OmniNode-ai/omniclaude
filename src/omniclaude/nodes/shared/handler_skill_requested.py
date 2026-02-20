# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Shared handler for skill dispatch — routes any skill request to Polly.

Single canonical handler imported by all skill dispatch nodes. Constructs
the Polly prompt from a ModelSkillRequest, dispatches it via the injected
task_dispatcher callable, and parses the structured RESULT: block from the
output.

Public API:
    handle_skill_requested(request, *, task_dispatcher) -> ModelSkillResult

Private helpers:
    _build_args_string(args) -> str
    _parse_result_block(output) -> tuple[SkillResultStatus, str | None]
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from .models.model_skill_request import ModelSkillRequest
from .models.model_skill_result import ModelSkillResult, SkillResultStatus

__all__ = [
    "handle_skill_requested",
]

logger = logging.getLogger(__name__)

# Type alias for the task dispatcher dependency.
# The dispatcher receives a prompt string and returns the Polly output string.
TaskDispatcher = Callable[[str], Awaitable[str]]

# Sentinel string that Polly must include in its output.
_RESULT_BLOCK_MARKER = "RESULT:"

# Keys within the RESULT block.
_STATUS_KEY = "status:"
_ERROR_KEY = "error:"


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

    # Extract the text after the marker
    block_text = output[marker_idx + len(_RESULT_BLOCK_MARKER) :]

    status: SkillResultStatus = SkillResultStatus.PARTIAL
    error: str | None = None

    for line in block_text.splitlines():
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


async def handle_skill_requested(
    request: ModelSkillRequest,
    *,
    task_dispatcher: TaskDispatcher,
) -> ModelSkillResult:
    """Dispatch a skill request to Polly and return a structured result.

    Constructs a prompt that includes the skill path and serialized args,
    dispatches it to the polymorphic agent (Polly) via ``task_dispatcher``,
    and parses the required RESULT: block from the output.

    On any exception from ``task_dispatcher`` the handler returns a FAILED
    result rather than propagating the exception.

    Args:
        request: Fully validated skill request.
        task_dispatcher: Async callable that sends a prompt to Polly and
            returns the raw output string.

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

    try:
        raw_output: str = await task_dispatcher(prompt)
    except Exception:
        logger.exception(
            "task_dispatcher raised for skill %r (correlation_id=%s)",
            request.skill_name,
            request.correlation_id,
        )
        return ModelSkillResult(
            skill_name=request.skill_name,
            status=SkillResultStatus.FAILED,
            output=None,
            error="task_dispatcher raised an exception",
            correlation_id=request.correlation_id,
        )

    output_str: str = str(raw_output) if raw_output is not None else ""
    status, error = _parse_result_block(output_str)

    logger.debug(
        "Skill %r completed with status=%s (correlation_id=%s)",
        request.skill_name,
        status,
        request.correlation_id,
    )

    return ModelSkillResult(
        skill_name=request.skill_name,
        status=status,
        output=output_str if output_str else None,
        error=error,
        correlation_id=request.correlation_id,
    )
