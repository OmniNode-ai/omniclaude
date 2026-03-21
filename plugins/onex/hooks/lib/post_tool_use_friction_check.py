# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PostToolUse friction check — detect skill failures from tool responses.

Called from post-tool-use hooks. Checks if a tool response indicates a skill
failure (FAILED/ERROR/BLOCKED) and delegates to friction_observer_adapter.

V1 is schema-conservative: malformed or partial Skill responses that do not
clearly expose a failure status are ignored rather than guessed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FAILURE_STATUSES = frozenset({"failed", "error", "blocked"})


def check_tool_for_friction(
    tool_info: dict[str, Any],
    *,
    session_id: str,
    ticket_id: str | None = None,
    registry_path: Path | None = None,
) -> None:
    """Check a tool response for skill failures and record friction if found.

    Only processes Skill tool responses with failure statuses.
    """
    try:
        tool_name = tool_info.get("tool_name", "")
        if tool_name != "Skill":
            return

        response = tool_info.get("tool_response", {})
        if not isinstance(response, dict):
            return

        status = response.get("status", "")
        if status not in _FAILURE_STATUSES:
            return

        from friction_observer_adapter import observe_friction  # noqa: E402

        observe_friction(
            event_type="skill.completed",
            payload={
                "status": status,
                "skill_name": response.get("skill_name", tool_name),
                "error": response.get("error", ""),
                "blocked_reason": response.get("blocked_reason", ""),
            },
            session_id=session_id,
            source="claude_code_hook",
            ticket_id=ticket_id,
            registry_path=registry_path,
        )
    except Exception:
        logger.debug("PostToolUse friction check failed", exc_info=True)
