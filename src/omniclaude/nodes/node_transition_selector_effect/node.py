# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Transition Selector Effect — local model as constrained transition selector.

This effect node wires the local model (Qwen3-14B at LLM_CODER_FAST_URL) into
the agent graph navigation loop as a constrained transition selector. The model
is given a bounded typed action set and selects exactly one transition.

Design constraints (from OMN-2569 spec):
- The model classifies over a CLOSED set — it never invents new actions.
- Prompt construction uses ONLY data from current_state, goal, action_set, context.
- Malformed output and out-of-set selections return structured errors; no crashes.
- Selection timeout is 10 seconds; returns SelectionErrorKind.SELECTION_TIMEOUT.
- Prompt template is versioned via contract.yaml, not hardcoded here.

Capability: navigation.transition_selection
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import TYPE_CHECKING

import httpx
from omnibase_core.nodes.node_effect import NodeEffect

from omniclaude.nodes.node_transition_selector_effect.models.model_contract_state import (
    ModelContractState,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_goal_condition import (
    ModelGoalCondition,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_navigation_context import (
    ModelNavigationContext,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_request import (
    ModelTransitionSelectorRequest,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_result import (
    ModelTransitionSelectorResult,
    SelectionErrorKind,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_typed_action import (
    ModelTypedAction,
)

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer

logger = logging.getLogger(__name__)

# Prompt template version — must match contract.yaml prompt_template.version
_PROMPT_TEMPLATE_VERSION = "1.0.0"

# Default model endpoint from environment, falling back to contract default
_DEFAULT_LLM_ENDPOINT = os.environ.get(
    "LLM_CODER_FAST_URL",
    "http://192.168.86.201:8001",  # onex-allow-internal-ip
)

# Selection timeout in seconds (matches contract.yaml error_handling.selection_timeout_seconds).
# asyncio.wait_for is the authoritative timeout; httpx timeout is set slightly higher so that
# asyncio cancellation fires first and produces a clean SELECTION_TIMEOUT error rather than
# an httpx.ReadTimeout that would surface as MODEL_UNAVAILABLE.
_SELECTION_TIMEOUT_SECONDS = 10.0
_HTTP_TIMEOUT_SECONDS = _SELECTION_TIMEOUT_SECONDS + 2.0


class NodeTransitionSelectorEffect(NodeEffect):
    """Effect node: local model as constrained transition selector.

    Implements TransitionSelector.select() per OMN-2569 spec. Presents the
    bounded action_set to Qwen3-14B as a numbered classification problem.

    Invariants:
    - Prompt contains ONLY data from current_state, goal, action_set, context.
    - Model output is validated against action_set before returning.
    - All failures are structured ModelTransitionSelectorResult with error_kind.
    - Never raises; always returns a result object.

    Capability: navigation.transition_selection
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the transition selector effect node.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)
        self._llm_endpoint = _DEFAULT_LLM_ENDPOINT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def select(
        self,
        request: ModelTransitionSelectorRequest,
    ) -> ModelTransitionSelectorResult:
        """Select a typed action from the bounded action set.

        Builds a structured classification prompt, calls the local model,
        parses the response, and validates the selection against action_set.

        Args:
            request: Full selection request with current_state, goal,
                action_set (non-empty), and navigation context.

        Returns:
            ModelTransitionSelectorResult with:
                - selected_action populated on success
                - error_kind + error_detail populated on any failure

        Never raises. All errors are returned as structured results.
        """
        start_ms = time.monotonic() * 1000.0
        correlation_id = request.correlation_id

        # Build the prompt
        try:
            prompt = self._build_prompt(request)
        except Exception as exc:
            logger.warning(
                "transition_selector.prompt_build_error",
                extra={"correlation_id": str(correlation_id), "error": str(exc)},
            )
            return ModelTransitionSelectorResult(
                error_kind=SelectionErrorKind.PROMPT_BUILD_ERROR,
                error_detail=f"Prompt construction failed: {exc}",
                duration_ms=time.monotonic() * 1000.0 - start_ms,
                correlation_id=correlation_id,
            )

        # Call the model with timeout
        try:
            raw_output = await asyncio.wait_for(
                self._call_model(prompt),
                timeout=_SELECTION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "transition_selector.timeout",
                extra={
                    "correlation_id": str(correlation_id),
                    "timeout_s": _SELECTION_TIMEOUT_SECONDS,
                },
            )
            return ModelTransitionSelectorResult(
                error_kind=SelectionErrorKind.SELECTION_TIMEOUT,
                error_detail=(
                    f"Model did not respond within {_SELECTION_TIMEOUT_SECONDS}s"
                ),
                duration_ms=time.monotonic() * 1000.0 - start_ms,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            logger.warning(
                "transition_selector.model_unavailable",
                extra={"correlation_id": str(correlation_id), "error": str(exc)},
            )
            return ModelTransitionSelectorResult(
                error_kind=SelectionErrorKind.MODEL_UNAVAILABLE,
                error_detail=f"Model call failed: {exc}",
                duration_ms=time.monotonic() * 1000.0 - start_ms,
                correlation_id=correlation_id,
            )

        # Parse model output
        selected_index = self._parse_selection(raw_output)
        if selected_index is None:
            logger.warning(
                "transition_selector.malformed_output",
                extra={
                    "correlation_id": str(correlation_id),
                    "raw_output": raw_output[:200],
                },
            )
            return ModelTransitionSelectorResult(
                error_kind=SelectionErrorKind.MALFORMED_OUTPUT,
                error_detail=(
                    "Model output could not be parsed as a valid selection. "
                    f"Raw output (truncated): {raw_output[:200]}"
                ),
                model_raw_output=raw_output,
                duration_ms=time.monotonic() * 1000.0 - start_ms,
                correlation_id=correlation_id,
            )

        # Validate index against action_set (1-indexed in prompt)
        action_list = request.action_set
        if selected_index < 1 or selected_index > len(action_list):
            logger.warning(
                "transition_selector.out_of_set",
                extra={
                    "correlation_id": str(correlation_id),
                    "selected_index": selected_index,
                    "action_set_size": len(action_list),
                },
            )
            return ModelTransitionSelectorResult(
                error_kind=SelectionErrorKind.OUT_OF_SET,
                error_detail=(
                    f"Model selected index {selected_index} but action_set "
                    f"has {len(action_list)} entries (1-indexed)"
                ),
                model_raw_output=raw_output,
                duration_ms=time.monotonic() * 1000.0 - start_ms,
                correlation_id=correlation_id,
            )

        selected_action = action_list[selected_index - 1]
        duration_ms = time.monotonic() * 1000.0 - start_ms

        logger.info(
            "transition_selector.selected",
            extra={
                "correlation_id": str(correlation_id),
                "selected_action_id": selected_action.action_id,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return ModelTransitionSelectorResult(
            selected_action=selected_action,
            model_raw_output=raw_output,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Prompt Construction (versioned via contract.yaml)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_action_list(action_set: tuple[ModelTypedAction, ...]) -> str:
        """Format the action set as a numbered list for the prompt.

        Args:
            action_set: Non-empty tuple of typed actions.

        Returns:
            Numbered string with one action per line.
        """
        lines: list[str] = []
        for idx, action in enumerate(action_set, start=1):
            lines.append(
                f"{idx}. [{action.action_type}] {action.description}"
                f" (target: {action.target_state_id or 'n/a'})"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_prior_paths(
        prior_paths: tuple[tuple[str, ...], ...],
    ) -> str:
        """Format prior paths for prompt inclusion.

        Args:
            prior_paths: Tuple of action_id sequences from OmniMemory.

        Returns:
            Formatted string or "None available" if empty.
        """
        if not prior_paths:
            return "None available"
        formatted = []
        for i, path in enumerate(prior_paths[:3], start=1):  # cap at 3 for brevity
            formatted.append(f"  Path {i}: {' -> '.join(path)}")
        return "\n".join(formatted)

    def _build_prompt(self, request: ModelTransitionSelectorRequest) -> str:
        """Build the versioned classification prompt.

        Prompt template version: 1.0.0 (matches contract.yaml).
        Only uses data from current_state, goal, action_set, context.

        Args:
            request: The selection request.

        Returns:
            Fully-rendered prompt string ready for the model.
        """
        state = request.current_state
        goal = request.goal
        context = request.context
        action_set = request.action_set

        state_fields_str = (
            json.dumps(dict(state.fields), indent=2) if state.fields else "{}"
        )
        prior_paths_str = self._format_prior_paths(context.prior_paths)
        action_list_str = self._build_action_list(action_set)
        target_state_str = goal.target_state_id or "not specified"

        # Template v1.0.0 — matches contract.yaml prompt_template.template
        prompt = (
            "You are a graph navigation classifier. Your task is to select the single\n"
            "best transition from a bounded set of typed options.\n"
            "\n"
            "## Current State\n"
            f"State ID: {state.state_id}\n"
            f"Node Type: {state.node_type}\n"
            f"Fields: {state_fields_str}\n"
            "\n"
            "## Goal\n"
            f"Goal: {goal.summary}\n"
            f"Target State: {target_state_str}\n"
            "\n"
            "## Navigation Context\n"
            f"Session: {context.session_id}\n"
            f"Step: {context.step_number}\n"
            f"Prior Successful Paths:\n{prior_paths_str}\n"
            "\n"
            "## Available Transitions\n"
            "Select exactly ONE of the following transitions by responding with its number.\n"
            "Do NOT invent new transitions or describe actions outside this list.\n"
            "\n"
            f"{action_list_str}\n"
            "\n"
            "## Response Format\n"
            "Respond with a JSON object containing only:\n"
            '{"selected": <number>}\n'
            "\n"
            "Where <number> is the integer index of your chosen transition (starting from 1).\n"
            "Do not include any other text."
        )
        return prompt

    # ------------------------------------------------------------------
    # Model Call
    # ------------------------------------------------------------------

    # Retry policy (matches contract.yaml error_handling.retry_policy)
    _MAX_RETRIES = 1
    _RETRY_DELAY_SECONDS = 0.5  # initial_delay_ms: 500

    async def _call_model(self, prompt: str) -> str:
        """Call the local model with retry on model_unavailable.

        Implements the retry_policy from contract.yaml:
          max_retries: 1, initial_delay_ms: 500, retry_on: [model_unavailable]

        Uses LLM_CODER_FAST_URL (Qwen3-14B, port 8001). Requests JSON mode
        if available for structured output.

        Args:
            prompt: The fully-rendered classification prompt.

        Returns:
            Raw model response text.

        Raises:
            Exception: After all retries are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                return await self._call_model_once(prompt)
            except Exception as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    logger.warning(
                        "transition_selector.model_retry",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self._MAX_RETRIES,
                            "error": str(exc),
                        },
                    )
                    await asyncio.sleep(self._RETRY_DELAY_SECONDS)
        raise last_exc  # type: ignore[misc]

    async def _call_model_once(self, prompt: str) -> str:
        """Single model call via OpenAI-compatible chat completions API.

        Args:
            prompt: The fully-rendered classification prompt.

        Returns:
            Raw model response text.

        Raises:
            httpx.HTTPError: On network or HTTP errors.
            ValueError: If model returns no choices.
        """
        endpoint = self._llm_endpoint.rstrip("/")
        url = f"{endpoint}/v1/chat/completions"

        payload = {
            "model": "qwen3-14b",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "max_tokens": 64,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        # Extract content from OpenAI-compatible response
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("Model returned no choices in response")

        content: str = choices[0].get("message", {}).get("content", "")
        return content

    # ------------------------------------------------------------------
    # Output Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_selection(raw_output: str) -> int | None:
        """Parse the model's JSON response into a 1-based selection index.

        Expects: {"selected": <integer>}

        Args:
            raw_output: Raw text from the model.

        Returns:
            1-based integer index, or None if parsing fails for any reason.
        """
        if not raw_output or not raw_output.strip():
            return None

        try:
            data = json.loads(raw_output.strip())
        except json.JSONDecodeError:
            # Try to extract JSON from surrounding text
            try:
                start = raw_output.index("{")
                end = raw_output.rindex("}") + 1
                data = json.loads(raw_output[start:end])
            except (ValueError, json.JSONDecodeError):
                return None

        if not isinstance(data, dict):
            return None

        selected = data.get("selected")
        # Reject bool explicitly: isinstance(True, int) is True, but bool is not
        # a valid index — True would map to index 1 silently.
        if isinstance(selected, bool):
            return None
        if not isinstance(selected, int):
            # Try coercing string integer
            try:
                selected = int(selected)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        return selected

    # ------------------------------------------------------------------
    # Class-level helpers for external callers (TransitionSelector API)
    # ------------------------------------------------------------------

    @staticmethod
    def build_request(
        current_state: ModelContractState,
        goal: ModelGoalCondition,
        action_set: list[ModelTypedAction],
        context: ModelNavigationContext,
    ) -> ModelTransitionSelectorRequest:
        """Convenience factory matching the TransitionSelector.select() signature.

        Args:
            current_state: Current contract state in the navigation graph.
            goal: Goal condition this session is working toward.
            action_set: Bounded list of typed actions to select from.
            context: Navigation session context.

        Returns:
            ModelTransitionSelectorRequest ready for NodeTransitionSelectorEffect.select().
        """
        import uuid

        return ModelTransitionSelectorRequest(
            current_state=current_state,
            goal=goal,
            action_set=tuple(action_set),
            context=context,
            correlation_id=uuid.uuid4(),
        )


__all__ = ["NodeTransitionSelectorEffect"]
