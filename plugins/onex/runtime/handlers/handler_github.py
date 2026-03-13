# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""GitHub handler for the skill bootstrapper runtime.

Provides GitHub-related operations (PR creation, branch management, etc.)
for skills that declare ``runtime: skill-bootstrapper``.

Fails fast at construction time if ``CLAUDE_PLUGIN_ROOT`` is not set.
"""

from __future__ import annotations

import os
from typing import Any


class HandlerGitHub:
    """Handler for GitHub operations within the skill bootstrapper.

    The bootstrapper owns schema normalization and result wrapping.
    This handler executes behavior only and returns ``dict[str, Any]``.
    """

    def __init__(self) -> None:
        self._plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if not self._plugin_root:
            raise RuntimeError(
                "CLAUDE_PLUGIN_ROOT not set. "
                "Deploy the omniclaude plugin or set the env var explicitly."
            )

    @property
    def plugin_root(self) -> str:
        """Return the plugin root path."""
        return self._plugin_root  # type: ignore[return-value]

    async def execute(self, operation: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute a GitHub operation.

        Args:
            operation: The operation to perform.
            inputs: Operation-specific inputs.

        Returns:
            Structured output dict (bootstrapper wraps into SkillResult).
        """
        return {"handler": "github", "operation": operation, "status": "stub"}
