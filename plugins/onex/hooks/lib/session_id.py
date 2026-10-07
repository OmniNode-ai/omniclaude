# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Canonical session-ID resolver for omniclaude hooks and skills.

Resolves the active Claude Code session ID. Order:
    1. CLAUDE_CODE_SESSION_ID  (canonical, native env var from Claude Code)
    2. CLAUDE_SESSION_ID       (legacy alias -- still honored during migration)
    3. ONEX_SESSION_ID         (legacy alias -- still honored during migration)
    4. SESSION_ID              (legacy alias -- still honored during migration)
    5. provided default (default: "unknown")

Empty-string values fall through to the next entry in the chain so that a
caller setting CLAUDE_CODE_SESSION_ID="" does not mask legacy fallbacks
during transition.

This is the ONLY place in the repo permitted to read the legacy aliases.
The session-id-canonical lint rejects all other reads.
"""

from __future__ import annotations

import os
from typing import overload

_LOOKUP_ORDER: tuple[str, ...] = (
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "ONEX_SESSION_ID",
    "SESSION_ID",
)


@overload
def resolve_session_id(*, env: dict[str, str] | None = None) -> str: ...
@overload
def resolve_session_id(*, default: str, env: dict[str, str] | None = None) -> str: ...
@overload
def resolve_session_id(
    *, default: None, env: dict[str, str] | None = None
) -> str | None: ...


def resolve_session_id(
    *, default: str | None = "unknown", env: dict[str, str] | None = None
) -> str | None:
    """Return the canonical Claude Code session ID, or `default` if none is set."""
    environment = os.environ if env is None else env
    for name in _LOOKUP_ORDER:
        value = environment.get(name, "").strip()
        if value:
            return value
    return default


__all__ = ["resolve_session_id"]
