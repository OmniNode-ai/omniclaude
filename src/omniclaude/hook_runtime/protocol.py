# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook runtime daemon socket protocol models. [OMN-5304]

Defines the newline-delimited JSON request/response protocol used between
shell hook shims and the persistent hook runtime daemon.
"""

from __future__ import annotations

from pydantic import BaseModel


class HookRuntimeRequest(BaseModel, frozen=True):
    """Request sent from a shell hook shim to the hook runtime daemon.

    Actions:
    - classify_tool: classify and count a tool call, return pass/warn/block
    - reset_session: reset all counters for a session (UserPromptSubmit)
    - check_delegation_rule: return the delegation rule text for context injection
    - set_skill_loaded: mark that a skill was loaded without delegation
    - mark_delegated: mark that delegation occurred (Task tool)
    - ping: health check
    """

    action: str
    session_id: str
    payload: dict[str, object] = {}


class HookRuntimeResponse(BaseModel, frozen=True):
    """Response sent from the hook runtime daemon to a shell hook shim."""

    decision: str  # pass | warn | block | ack
    message: str | None = None
    counters: dict[str, int] = {}
    additional_context: str | None = None  # for hookSpecificOutput injection


def parse_hook_runtime_request(raw: dict[str, object]) -> HookRuntimeRequest:
    """Parse and validate a raw dict into a HookRuntimeRequest."""
    return HookRuntimeRequest.model_validate(raw)
