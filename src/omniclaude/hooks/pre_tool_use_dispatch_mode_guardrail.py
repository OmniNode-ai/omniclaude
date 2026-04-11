# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PreToolUse dispatch-mode guardrail (OMN-7257).

Advisory hook that fires when the ``Agent`` tool is invoked and inspects the
prompt for multi-scope signals suggesting a TeamCreate workflow would be more
appropriate than a single Agent dispatch.

Signals (any one triggers the advisory):

1. Three or more Linear ticket IDs (``OMN-\\d+``) referenced in the prompt
2. An explicit epic reference (``epic`` followed by an OMN id, or an
   ``OMN-\\d+`` tagged as an epic in the prompt)
3. Two or more distinct repo names from the OmniNode registry mentioned

Exceptions (hook passes through silently):

- The Agent call already specifies ``team_name`` (it is already part of a
  TeamCreate workflow)
- ``agent_type`` / ``subagent_type`` is ``Explore`` or a research agent
- The prompt matches a single-ticket scope (exactly one OMN id, no epic,
  single repo)

Every intervention is logged to
``$ONEX_STATE_DIR/dispatch-guardrail-log.ndjson`` with trigger signal,
response outcome (always ``proceeded`` since the advisory is non-blocking),
and a short task context summary.

The hook is disabled when ``DISPATCH_MODE_GUARDRAIL_DISABLED=1`` is set,
allowing per-session overrides.

Exit codes follow the established dispatch-guard protocol:
  0  pass-through (original JSON on stdout)
  1  warn          (advisory JSON on stdout; shell wrapper re-emits original)
  2  block         (unused here; the guardrail is advisory-only)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

# --- Signal configuration ---------------------------------------------------

_TICKET_PATTERN: Final[re.Pattern[str]] = re.compile(r"\bOMN-\d+\b")
_EPIC_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:epic\s+(?:id\s+)?OMN-\d+|OMN-\d+\s+epic|epic\s*[:=]\s*OMN-\d+)\b",
    re.IGNORECASE,
)

# Canonical repo names from the OmniNode registry (omni_home CLAUDE.md).
_REPO_NAMES: Final[frozenset[str]] = frozenset(
    {
        "omniclaude",
        "omnibase_core",
        "omnibase_infra",
        "omnibase_spi",
        "omnidash",
        "omnigemini",
        "omniintelligence",
        "omnimemory",
        "omninode_infra",
        "omnimarket",
        "omniweb",
        "onex_change_control",
        "omnibase_compat",
    }
)

# Agent types that represent exploration / research and should never trigger
# the guardrail regardless of prompt content.
_EXPLORATION_AGENTS: Final[frozenset[str]] = frozenset(
    {"explore", "research", "researcher", "general-purpose"}
)

_MULTI_TICKET_THRESHOLD: Final[int] = 3
_MULTI_REPO_THRESHOLD: Final[int] = 2

_TOOL_NAME: Final[str] = "Agent"
_DISABLE_ENV: Final[str] = "DISPATCH_MODE_GUARDRAIL_DISABLED"


# --- Signal detection ------------------------------------------------------


def _count_unique_tickets(prompt: str) -> int:
    return len({match.upper() for match in _TICKET_PATTERN.findall(prompt)})


def _has_epic_reference(prompt: str) -> bool:
    return bool(_EPIC_PATTERN.search(prompt))


def _count_repo_mentions(prompt: str) -> int:
    lowered = prompt.lower()
    return sum(
        1 for repo in _REPO_NAMES if re.search(rf"\b{re.escape(repo)}\b", lowered)
    )


def _is_exploration_agent(tool_input: dict[str, object]) -> bool:
    for key in ("agent_type", "subagent_type", "name"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip().lower() in _EXPLORATION_AGENTS:
            return True
    return False


def _detect_signals(prompt: str, tool_input: dict[str, object]) -> list[str]:
    """Return the list of fired signal names, empty if none."""
    signals: list[str] = []

    if _is_exploration_agent(tool_input):
        return signals

    ticket_count = _count_unique_tickets(prompt)
    if ticket_count >= _MULTI_TICKET_THRESHOLD:
        signals.append(f"multi_ticket:{ticket_count}")

    if _has_epic_reference(prompt):
        signals.append("epic_reference")

    repo_count = _count_repo_mentions(prompt)
    if repo_count >= _MULTI_REPO_THRESHOLD:
        signals.append(f"multi_repo:{repo_count}")

    return signals


def _already_team_dispatch(tool_input: dict[str, object]) -> bool:
    team_name = tool_input.get("team_name")
    return isinstance(team_name, str) and bool(team_name.strip())


# --- Logging ---------------------------------------------------------------


def _log_path() -> Path:
    state_dir = os.environ.get("ONEX_STATE_DIR")
    if state_dir:
        return Path(state_dir) / "dispatch-guardrail-log.ndjson"
    return Path.home() / ".onex_state" / "dispatch-guardrail-log.ndjson"


def _log_intervention(
    signals: list[str],
    prompt: str,
    tool_input: dict[str, object],
) -> None:
    try:
        log_file = _log_path()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "trigger_signals": signals,
            "agent_response": "proceeded",
            "task_context_summary": prompt[:200],
            "agent_name": tool_input.get("name") or tool_input.get("agent_name") or "",
            "team_name": tool_input.get("team_name") or "",
        }
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        # Logging must never block the hook; fail open.
        pass


# --- Core guard ------------------------------------------------------------


def _extract_prompt(tool_input: dict[str, object]) -> str:
    for key in ("prompt", "message", "task", "description"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def run_guardrail(stdin_json: str) -> tuple[int, str]:
    """Evaluate the dispatch-mode guardrail against a hook JSON payload.

    Returns ``(exit_code, output_json)``. ``exit_code == 1`` indicates a
    non-blocking advisory. ``exit_code == 0`` indicates pass-through.
    """
    if os.environ.get(_DISABLE_ENV) == "1":
        return 0, stdin_json

    try:
        hook_data: dict[str, object] = json.loads(stdin_json)
    except json.JSONDecodeError:
        return 0, stdin_json

    tool_name = str(hook_data.get("tool_name", ""))
    if tool_name != _TOOL_NAME:
        return 0, stdin_json

    raw_input = hook_data.get("tool_input", {})
    tool_input: dict[str, object] = raw_input if isinstance(raw_input, dict) else {}

    if _already_team_dispatch(tool_input):
        return 0, stdin_json

    prompt = _extract_prompt(tool_input)
    if not prompt:
        return 0, stdin_json

    signals = _detect_signals(prompt, tool_input)
    if not signals:
        return 0, stdin_json

    _log_intervention(signals, prompt, tool_input)

    advisory = {
        "decision": "warn",
        "reason": (
            "[dispatch-mode-guardrail] ADVISORY — This Agent call shows "
            f"multi-scope signals ({', '.join(signals)}). Consider using "
            "TeamCreate + Agent(team_name=...) to dispatch parallel workers "
            "instead of a single Agent for multi-ticket / multi-repo work. "
            "See ~/.claude/CLAUDE.md → Agent Dispatch Rules. Set "
            f"{_DISABLE_ENV}=1 to silence this advisory."
        ),
    }
    return 1, json.dumps(advisory)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — reads stdin, writes stdout, returns exit code."""
    stdin_data = sys.stdin.read()
    exit_code, output = run_guardrail(stdin_data)
    print(output)  # noqa: T201
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
