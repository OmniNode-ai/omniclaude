# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Bash handler for the skill bootstrapper runtime.

Provides shell execution operations (run_script, check_status, lint_files)
for skills that declare ``runtime: skill-bootstrapper``.

Rejects path traversal (``../``) with ``ValueError``.
"""

from __future__ import annotations

from typing import Any

HANDLER_BASH_ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {"run_script", "check_status", "lint_files"}
)


class HandlerBash:
    """Handler for bash operations within the skill bootstrapper.

    The bootstrapper owns schema normalization and result wrapping.
    This handler executes behavior only and returns ``dict[str, Any]``.
    """

    async def execute(self, operation: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute a bash operation.

        Args:
            operation: The operation to perform. Must be in the allowlist.
            inputs: Operation-specific inputs.

        Returns:
            Structured output dict (bootstrapper wraps into SkillResult).

        Raises:
            ValueError: If operation is not allowed or path traversal detected.
        """
        if operation not in HANDLER_BASH_ALLOWED_OPERATIONS:
            raise ValueError(
                f"Operation {operation!r} not allowed. "
                f"Allowed: {sorted(HANDLER_BASH_ALLOWED_OPERATIONS)}"
            )

        # Check all string inputs for path traversal
        for key, value in inputs.items():
            if isinstance(value, str) and "../" in value:
                raise ValueError(
                    f"Path traversal detected in input {key!r}: "
                    f"'../' is not allowed for security reasons."
                )

        return {"handler": "bash", "operation": operation, "status": "stub"}
