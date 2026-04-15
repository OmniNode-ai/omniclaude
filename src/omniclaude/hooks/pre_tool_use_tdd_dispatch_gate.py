# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse TDD dispatch gate (OMN-8846).

Fires on Agent() and Task() tool calls. Enforces TDD clause requirement based
on ONEX_DISPATCH_TYPE environment variable — NOT NLP string matching.

Dispatch types:
    research-only  → exit 0, no TDD required
    implementation → require "# failing-test:" AND "dod_evidence:" in prompt
    verification   → exit 0, no TDD required
    <unset/other>  → exit 2 with instructions to set ONEX_DISPATCH_TYPE

Exit codes:
    0  pass-through (original JSON on stdout)
    2  block        (block JSON on stdout)

CLI usage (invoked by pre_tool_use_tdd_dispatch_gate.sh):

    python3 -m omniclaude.hooks.pre_tool_use_tdd_dispatch_gate < tool_input.json
"""

from __future__ import annotations

import json
import os
import sys
from typing import Final

_GUARDED_TOOLS: Final[frozenset[str]] = frozenset({"Agent", "Task"})
_DISPATCH_TYPE_ENV: Final[str] = "ONEX_DISPATCH_TYPE"
_EXEMPT_TYPES: Final[frozenset[str]] = frozenset({"research-only", "verification"})

# Markers required in implementation prompts
_FAILING_TEST_MARKER: Final[str] = "# failing-test:"
_DOD_EVIDENCE_MARKER: Final[str] = "dod_evidence:"


def _extract_prompt(tool_input: dict[str, object]) -> str:
    for key in ("prompt", "message", "task", "description"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _block(reason: str) -> tuple[int, str]:
    return 2, json.dumps({"decision": "block", "reason": reason})


def run_gate(stdin_json: str) -> tuple[int, str]:
    """Evaluate the TDD dispatch gate.

    Returns (exit_code, output_json).
    """
    try:
        hook_data: dict[str, object] = json.loads(stdin_json)
    except json.JSONDecodeError:
        return 0, stdin_json

    tool_name = str(hook_data.get("tool_name", ""))
    if tool_name not in _GUARDED_TOOLS:
        return 0, stdin_json

    dispatch_type = os.environ.get(_DISPATCH_TYPE_ENV, "").strip().lower()

    if not dispatch_type:
        return _block(
            "[tdd-dispatch-gate] BLOCKED: ONEX_DISPATCH_TYPE not set. "
            "Set to 'research-only', 'implementation', or 'verification' before dispatch. "
            "Example: ONEX_DISPATCH_TYPE=implementation"
        )

    if dispatch_type in _EXEMPT_TYPES:
        return 0, stdin_json

    if dispatch_type == "implementation":
        raw_input = hook_data.get("tool_input", {})
        tool_input: dict[str, object] = raw_input if isinstance(raw_input, dict) else {}
        prompt = _extract_prompt(tool_input)

        has_failing_test = _FAILING_TEST_MARKER in prompt
        has_dod_evidence = _DOD_EVIDENCE_MARKER in prompt

        if not has_failing_test or not has_dod_evidence:
            missing = []
            if not has_failing_test:
                missing.append("'# failing-test: <path>::<test_name>'")
            if not has_dod_evidence:
                missing.append("'dod_evidence:' block")
            return _block(
                "[tdd-dispatch-gate] BLOCKED: implementation dispatch missing TDD clause. "
                f"Add to prompt: {', '.join(missing)}. "
                "TDD-first policy requires a failing test reference and DoD evidence "
                "before implementation work is dispatched."
            )

        return 0, stdin_json

    # Unknown type
    return _block(
        f"[tdd-dispatch-gate] BLOCKED: ONEX_DISPATCH_TYPE='{dispatch_type}' is not recognized. "
        "Valid values: 'research-only', 'implementation', 'verification'."
    )


def main(argv: list[str] | None = None) -> int:
    stdin_data = sys.stdin.read()
    exit_code, output = run_gate(stdin_data)
    print(output)  # noqa: T201
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
