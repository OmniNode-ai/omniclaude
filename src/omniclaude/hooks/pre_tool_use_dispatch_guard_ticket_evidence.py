# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse dispatch guard: require Linear ticket + DoD evidence (OMN-8490).

Fires on Agent() and Task() tool calls. Blocks dispatch unless the prompt
contains an OMN-XXXX ticket reference AND a matching `.evidence/OMN-XXXX/`
directory exists under the project root.

Exemptions:
- Prompt contains the literal ``# research-only`` marker.
- Env var ``DISPATCH_TICKET_GUARD_DISABLED=1`` disables the guard entirely.

Exit codes:
    0  pass-through (original JSON on stdout)
    2  block        (block JSON on stdout)

CLI usage (invoked by pre_tool_use_dispatch_guard_ticket_evidence.sh):

    python3 -m omniclaude.hooks.pre_tool_use_dispatch_guard_ticket_evidence < tool_input.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Final

_TICKET_PATTERN: Final[re.Pattern[str]] = re.compile(r"\bOMN-\d+\b", re.IGNORECASE)
_RESEARCH_ONLY_MARKER: Final[str] = "# research-only"
_GUARDED_TOOLS: Final[frozenset[str]] = frozenset({"Agent", "Task"})
_DISABLE_ENV: Final[str] = "DISPATCH_TICKET_GUARD_DISABLED"


def _project_dir() -> Path:
    raw = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if raw:
        return Path(raw)
    return Path.cwd()


def _extract_prompt(tool_input: dict[str, object]) -> str:
    for key in ("prompt", "message", "task", "description"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _find_tickets(prompt: str) -> list[str]:
    return list({m.upper() for m in _TICKET_PATTERN.findall(prompt)})


def _evidence_exists(ticket: str, project_dir: Path) -> bool:
    return (project_dir / ".evidence" / ticket).is_dir()


def run_guard(stdin_json: str) -> tuple[int, str]:
    """Evaluate the ticket-evidence dispatch guard.

    Returns (exit_code, output_json).
    """
    if os.environ.get(_DISABLE_ENV) == "1":
        return 0, stdin_json

    try:
        hook_data: dict[str, object] = json.loads(stdin_json)
    except json.JSONDecodeError:
        return 0, stdin_json

    tool_name = str(hook_data.get("tool_name", ""))
    if tool_name not in _GUARDED_TOOLS:
        return 0, stdin_json

    raw_input = hook_data.get("tool_input", {})
    tool_input: dict[str, object] = raw_input if isinstance(raw_input, dict) else {}
    prompt = _extract_prompt(tool_input)

    if _RESEARCH_ONLY_MARKER in prompt:
        return 0, stdin_json

    tickets = _find_tickets(prompt)
    if not tickets:
        block = json.dumps(
            {
                "decision": "block",
                "reason": (
                    "[dispatch-ticket-guard] BLOCKED — No OMN-XXXX ticket reference "
                    "found in the prompt. All Agent/Task dispatches must reference a "
                    "Linear ticket. Add an OMN-XXXX reference and ensure "
                    ".evidence/OMN-XXXX/ exists, or add '# research-only' to exempt."
                ),
            }
        )
        return 2, block

    project_dir = _project_dir()
    matched = [t for t in tickets if _evidence_exists(t, project_dir)]
    if not matched:
        missing = ", ".join(sorted(tickets))
        block = json.dumps(
            {
                "decision": "block",
                "reason": (
                    f"[dispatch-ticket-guard] BLOCKED — Ticket(s) {missing} referenced "
                    f"but no matching .evidence/OMN-XXXX/ directory found under "
                    f"{project_dir}. Create the evidence directory (e.g. "
                    f".evidence/{tickets[0]}/) or add '# research-only' to exempt."
                ),
            }
        )
        return 2, block

    return 0, stdin_json


def main(argv: list[str] | None = None) -> int:
    stdin_data = sys.stdin.read()
    exit_code, output = run_guard(stdin_data)
    print(output)  # noqa: T201
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
