# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Agentic ReAct loop for local LLM delegation.

Implements a ReAct-style (Reason + Act) tool-calling loop that allows local
LLMs to iteratively read files, search code, and run read-only commands to
produce informed work products.

The loop:
1. Sends messages + tool definitions to the LLM via chat_completion_sync()
2. Parses tool_calls from the response
3. Dispatches tools via the provided dispatch function
4. Appends tool results as ``role: "tool"`` messages
5. Loops until: final text response, max iterations, timeout, or error

Designed to run synchronously in a daemon background thread (not asyncio).

Ticket: OMN-5724
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path setup (module-level, idempotent) — mirrors other hooks/lib modules
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
_SRC_PATH = _SCRIPT_DIR.parent.parent.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# ---------------------------------------------------------------------------
# Lazy backend import — avoids import-time failure if omniclaude not on path
# ---------------------------------------------------------------------------
_backend_instance: Any = None


def _get_backend() -> Any:
    """Return a cached VllmInferenceBackend instance.

    Lazily imports and constructs the backend to avoid import-time failures
    when omniclaude is not on sys.path (e.g. in unit tests with mocking).
    """
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance

    try:
        from omniclaude.config.model_local_llm_config import LocalLlmEndpointRegistry
        from omniclaude.nodes.node_local_llm_inference_effect.backends.backend_vllm import (
            VllmInferenceBackend,
        )

        registry = LocalLlmEndpointRegistry()
        _backend_instance = VllmInferenceBackend(registry)
        return _backend_instance
    except ImportError:
        logger.warning("VllmInferenceBackend not available; agentic loop disabled")
        return None


# Type alias for untyped dicts at the OpenAI API boundary.
_JsonDict = dict[str, Any]  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class AgenticStatus(Enum):
    """Terminal status of an agentic loop execution."""

    SUCCESS = "success"
    MAX_ITERATIONS = "max_iterations"
    TIMEOUT = "timeout"
    LLM_ERROR = "llm_error"
    NO_BACKEND = "no_backend"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class AgenticResult:
    """Result of an agentic loop execution.

    Attributes:
        content: Final text output from the LLM (the work product).
        iterations: Number of loop iterations executed.
        tool_calls_count: Total number of tool calls dispatched.
        status: Terminal status indicating how/why the loop ended.
        tool_names_used: Set of unique tool names that were called.
        error: Error message if status is not SUCCESS.
    """

    content: str | None = None
    iterations: int = 0
    tool_calls_count: int = 0
    status: AgenticStatus = AgenticStatus.SUCCESS
    tool_names_used: set[str] = field(default_factory=set)
    error: str | None = None
    total_message_bytes: int = 0


# ---------------------------------------------------------------------------
# Core ReAct loop
# ---------------------------------------------------------------------------


def _estimate_message_bytes(messages: list[_JsonDict]) -> int:
    """Estimate the total byte size of the messages list."""
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += len(content.encode("utf-8", errors="replace"))
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                total += len(
                    str(func.get("name", "")).encode("utf-8", errors="replace")
                )
                total += len(
                    str(func.get("arguments", "")).encode("utf-8", errors="replace")
                )
    return total


_DEFAULT_CONTEXT_BUDGET_BYTES = 128 * 1024


def run_agentic_loop(
    prompt: str,
    system_prompt: str,
    endpoint_url: str,
    tools: list[_JsonDict],
    dispatch_fn: Callable[[str, str], str],
    max_iterations: int = 10,
    timeout_s: float = 60.0,
    model: str | None = None,
    backend: Any | None = None,
    context_budget_bytes: int = _DEFAULT_CONTEXT_BUDGET_BYTES,
) -> AgenticResult:
    """Execute a ReAct-style agentic loop with tool calling.

    Sends the prompt + tools to the LLM, dispatches any tool_calls, appends
    results, and loops until the LLM returns a final text response (no
    tool_calls), or a termination condition is reached.

    Args:
        prompt: The user's task prompt.
        system_prompt: System prompt guiding the LLM's behavior.
        endpoint_url: Base URL of the LLM endpoint.
        tools: OpenAI function-calling format tool definitions.
        dispatch_fn: Callable(tool_name, arguments_json) -> result string.
        max_iterations: Maximum number of loop iterations (default 10).
        timeout_s: Wall-clock timeout in seconds (default 60).
        model: Optional model name override for the endpoint.
        backend: Optional pre-constructed backend (for testing). If None,
            uses the lazily-initialized global backend.

    Returns:
        AgenticResult with the final content and execution metadata.
    """
    if backend is None:
        backend = _get_backend()
    if backend is None:
        return AgenticResult(
            status=AgenticStatus.NO_BACKEND,
            error="VllmInferenceBackend not available",
        )

    # Build initial messages
    messages: list[_JsonDict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    start_time = time.monotonic()
    iterations = 0
    total_tool_calls = 0
    tool_names_used: set[str] = set()

    for iteration in range(max_iterations):
        # Check timeout
        elapsed = time.monotonic() - start_time
        if elapsed >= timeout_s:
            logger.info(
                "Agentic loop timed out after %.1fs (%d iterations, %d tool calls)",
                elapsed,
                iterations,
                total_tool_calls,
            )
            return AgenticResult(
                content=_extract_last_assistant_content(messages),
                iterations=iterations,
                tool_calls_count=total_tool_calls,
                status=AgenticStatus.TIMEOUT,
                tool_names_used=tool_names_used,
                error=f"Timed out after {elapsed:.1f}s",
            )

        iterations += 1

        # Call LLM
        result = backend.chat_completion_sync(
            messages=messages,
            endpoint_url=endpoint_url,
            model=model,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            temperature=0.1,
        )

        # Check for LLM errors
        if result.error:
            logger.warning("LLM error on iteration %d: %s", iteration + 1, result.error)
            return AgenticResult(
                content=_extract_last_assistant_content(messages),
                iterations=iterations,
                tool_calls_count=total_tool_calls,
                status=AgenticStatus.LLM_ERROR,
                tool_names_used=tool_names_used,
                error=result.error,
            )

        # No tool calls -> final answer
        if not result.tool_calls:
            logger.info(
                "Agentic loop completed: %d iterations, %d tool calls, %.1fs",
                iterations,
                total_tool_calls,
                time.monotonic() - start_time,
            )
            return AgenticResult(
                content=result.content or "",
                iterations=iterations,
                tool_calls_count=total_tool_calls,
                status=AgenticStatus.SUCCESS,
                tool_names_used=tool_names_used,
            )

        # Append assistant message with tool_calls
        assistant_msg: _JsonDict = {
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": result.tool_calls,
        }
        messages.append(assistant_msg)

        # Dispatch each tool call and append results
        for tool_call in result.tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "unknown")
            tool_args = tool_call.get("function", {}).get("arguments", "{}")
            call_id = tool_call.get("id", f"call_{total_tool_calls}")

            tool_names_used.add(tool_name)
            total_tool_calls += 1

            try:
                tool_result = dispatch_fn(tool_name, tool_args)
            except Exception as exc:
                logger.warning("Tool dispatch error for %s: %s", tool_name, exc)
                tool_result = f"Error executing tool {tool_name}: {exc}"

            # Append tool result message
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_result,
                }
            )

            logger.debug(
                "Tool %s returned %d chars (iteration %d)",
                tool_name,
                len(tool_result),
                iteration + 1,
            )

        # Check context budget after all tool results appended
        current_bytes = _estimate_message_bytes(messages)
        if current_bytes >= context_budget_bytes:
            logger.info(
                "Agentic loop hit context budget (%d >= %d bytes)",
                current_bytes,
                context_budget_bytes,
            )
            return AgenticResult(
                content=_extract_last_assistant_content(messages),
                iterations=iterations,
                tool_calls_count=total_tool_calls,
                status=AgenticStatus.BUDGET_EXHAUSTED,
                tool_names_used=tool_names_used,
                error=f"Context budget exhausted ({current_bytes} >= {context_budget_bytes} bytes)",
                total_message_bytes=current_bytes,
            )

    # Exhausted max iterations
    logger.info(
        "Agentic loop hit max iterations (%d), %d tool calls, %.1fs",
        max_iterations,
        total_tool_calls,
        time.monotonic() - start_time,
    )
    return AgenticResult(
        content=_extract_last_assistant_content(messages),
        iterations=iterations,
        tool_calls_count=total_tool_calls,
        status=AgenticStatus.MAX_ITERATIONS,
        tool_names_used=tool_names_used,
        error=f"Reached max iterations ({max_iterations})",
        total_message_bytes=_estimate_message_bytes(messages),
    )


def _extract_last_assistant_content(messages: list[_JsonDict]) -> str | None:
    """Extract content from the last assistant message in the history."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return None


# ---------------------------------------------------------------------------
# Convenience wrapper with default tools
# ---------------------------------------------------------------------------


def run_agentic_task(
    prompt: str,
    system_prompt: str,
    endpoint_url: str,
    max_iterations: int = 10,
    timeout_s: float = 60.0,
    model: str | None = None,
    working_dir: str | None = None,
) -> AgenticResult:
    """Run an agentic task using the default tool set.

    Convenience wrapper around ``run_agentic_loop()`` that automatically
    provides the standard read-only tools from ``agentic_tools``.

    Args:
        prompt: The user's task prompt.
        system_prompt: System prompt guiding the LLM's behavior.
        endpoint_url: Base URL of the LLM endpoint.
        max_iterations: Maximum loop iterations (default 10).
        timeout_s: Wall-clock timeout in seconds (default 60).
        model: Optional model name override.
        working_dir: Optional working directory context to prepend to prompt.

    Returns:
        AgenticResult with the final content and execution metadata.
    """
    # Import tools lazily to avoid circular imports
    try:
        from agentic_tools import (  # type: ignore[import-not-found]
            ALL_TOOLS,
            dispatch_tool,
        )
    except ImportError:
        try:
            from lib.agentic_tools import (  # type: ignore[import-not-found]
                ALL_TOOLS,
                dispatch_tool,
            )
        except ImportError:
            return AgenticResult(
                status=AgenticStatus.NO_BACKEND,
                error="agentic_tools module not available",
            )

    # Augment prompt with working directory context
    full_prompt = prompt
    if working_dir:
        full_prompt = f"Working directory: {working_dir}\n\n{prompt}"

    return run_agentic_loop(
        prompt=full_prompt,
        system_prompt=system_prompt,
        endpoint_url=endpoint_url,
        tools=ALL_TOOLS,
        dispatch_fn=dispatch_tool,
        max_iterations=max_iterations,
        timeout_s=timeout_s,
        model=model,
    )


__all__ = [
    "AgenticResult",
    "AgenticStatus",
    "run_agentic_loop",
    "run_agentic_task",
]
