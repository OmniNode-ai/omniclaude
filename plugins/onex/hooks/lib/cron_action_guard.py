# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Cron-loop action enforcement hook (PostToolUse on CronCreate).

Reads the Claude Code PostToolUse hook input JSON from stdin, inspects the
``prompt`` field of the CronCreate tool input, and emits a warning when the
scheduled cron appears to be a passive status reporter rather than an action
trigger.

Both-side keyword logic
-----------------------
A cron loop is flagged as passive ONLY when:

  - Passive keywords are present: "status", "report", "check", "list"
  AND
  - Action keywords are absent: "dispatch", "merge", "fix", "sweep", "create"

Single-direction matching produces false positives. ``/onex:system_status``
contains "status" but is an action trigger — it must NOT produce a warning.

Warning message emitted
-----------------------
"Cron loop appears passive — loops must trigger actions (dispatch agents,
merge PRs), not just report status."

Exit codes
----------
0 — always (non-blocking advisory; hooks must never freeze Claude Code UI)

Usage (standalone)
------------------
    $ echo '{"tool_name":"CronCreate","tool_input":{"prompt":"/onex:system_status"}}' \\
          | python cron_action_guard.py
"""

from __future__ import annotations

import json
import sys

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

PASSIVE_KEYWORDS: frozenset[str] = frozenset({"status", "report", "check", "list"})
ACTION_KEYWORDS: frozenset[str] = frozenset(
    {"dispatch", "merge", "fix", "sweep", "create"}
)

WARNING_MESSAGE = (
    "Cron loop appears passive — loops must trigger actions "
    "(dispatch agents, merge PRs), not just report status."
)


def _tokenize(prompt: str) -> frozenset[str]:
    """Return a set of lowercase word tokens extracted from *prompt*.

    Non-alphabetic characters (slashes, colons, underscores, hyphens) are
    treated as delimiters so that ``/onex:system_status`` produces the tokens
    ``{"onex", "system", "status"}`` rather than matching "status" as a
    substring of the entire string.
    """
    import re

    return frozenset(re.findall(r"[a-z]+", prompt.lower()))


def is_passive_cron(prompt: str) -> bool:
    """Return True when the prompt looks passive (no action keywords present).

    Both conditions must hold:
    1. At least one passive keyword found as a whole word token.
    2. No action keyword found as a whole word token.

    Word-boundary tokenization prevents false positives: ``/onex:system_status``
    produces the tokens ``{"onex", "system", "status"}``. The token "status" IS
    present, so this would still flag. However, the intent from the spec is that
    a skill name used as the full prompt is an action trigger. The guard uses
    an additional heuristic: a prompt that starts with "/" followed by a skill
    name without any surrounding context is treated as a skill invocation and
    not flagged as passive.
    """

    # If the prompt looks like a bare skill invocation (starts with '/'), treat
    # it as an action trigger regardless of keyword content. Skill names are
    # action triggers — they dispatch work even when their name contains passive
    # keywords like "status" or "check".
    stripped = prompt.strip()
    if stripped.startswith("/"):
        return False

    tokens = _tokenize(prompt)
    has_passive = bool(tokens & PASSIVE_KEYWORDS)
    has_action = bool(tokens & ACTION_KEYWORDS)
    return has_passive and not has_action


def main(stdin: object = None) -> None:
    """Entry point for PostToolUse hook.

    Reads hook JSON from stdin (or the provided ``stdin`` object for testing),
    checks if CronCreate was called with a passive prompt, and emits a warning
    if so. Always exits 0.
    """
    try:
        raw: str = (stdin or sys.stdin).read()
        data: dict = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        # Malformed stdin — pass through silently, never block
        print("{}")
        return

    if data.get("tool_name") != "CronCreate":
        print("{}")
        return

    tool_input = data.get("tool_input", {})
    prompt: str = tool_input.get("prompt", "") or ""

    if is_passive_cron(prompt):
        print(json.dumps({"hookSpecificOutput": WARNING_MESSAGE}))
    else:
        print("{}")


if __name__ == "__main__":
    main()
