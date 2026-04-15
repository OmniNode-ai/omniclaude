# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse gate: enforce agent disallowedTools rules (OMN-8842).

Reads the active agent from correlation state, loads its YAML, and blocks
any tool listed in `disallowedTools`. Exit 2 = hard block.

Usage (standalone):
    $ echo '{"tool_name":"CronCreate","tool_input":{}}' | python agent_tool_gate.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ToolCheckResult:
    blocked: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_disallowed_tools(agent_data: dict[str, Any]) -> list[str]:
    """Return the disallowedTools list from an agent YAML dict (default: [])."""
    value = agent_data.get("disallowedTools", [])
    if isinstance(value, list):
        return [str(t) for t in value]
    return []


def check_tool_allowed(tool_name: str, agent_data: dict[str, Any]) -> ToolCheckResult:
    """Return a ToolCheckResult for the given tool and agent data."""
    disallowed = get_disallowed_tools(agent_data)
    if tool_name in disallowed:
        agent_name = agent_data.get("agent_identity", {}).get("name", "unknown-agent")
        reason = (
            f"BLOCKED: agent {agent_name} has disallowedTools rule banning {tool_name}. "
            f"See agent YAML (disallowedTools field)."
        )
        return ToolCheckResult(blocked=True, reason=reason)
    return ToolCheckResult(blocked=False)


# ---------------------------------------------------------------------------
# Active agent resolution
# ---------------------------------------------------------------------------


def _resolve_agent_configs_dir() -> Path:
    """Resolve the agent configs directory (mirrors agent_router logic)."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        p = Path(plugin_root) / "agents" / "configs"
        if p.exists():
            return p

    script_dir = Path(__file__).parent
    candidate = script_dir.parent.parent / "agents" / "configs"
    if candidate.exists():
        return candidate

    state_dir = os.environ.get("ONEX_STATE_DIR", "")
    if state_dir:
        return Path(state_dir).expanduser() / "agents" / "omniclaude"
    raise RuntimeError("Cannot resolve agent configs directory")


def _get_active_agent_name() -> str | None:
    """Read the currently-selected agent name from correlation state."""
    try:
        # Try correlation_manager first (authoritative)
        _lib_dir = Path(__file__).parent
        if str(_lib_dir) not in sys.path:
            sys.path.insert(0, str(_lib_dir))
        import correlation_manager

        ctx = correlation_manager.get_correlation_context()
        if ctx:
            name = ctx.get("agent_name")
            if name and name not in ("", "NO_AGENT_DETECTED", "null"):
                return str(name)
    except Exception as e:
        logger.debug(f"correlation_manager unavailable: {e}")

    # Fallback: ONEX_ACTIVE_AGENT env var (set by some callers)
    env_agent = os.environ.get("ONEX_ACTIVE_AGENT", "").strip()
    if env_agent and env_agent not in ("", "NO_AGENT_DETECTED"):
        return env_agent

    return None


def _load_agent_yaml(agent_name: str) -> dict[str, Any] | None:
    """Load agent YAML by name from the configs directory."""
    try:
        configs_dir = _resolve_agent_configs_dir()
        # Try exact filename match first (strip leading "agent-" prefix)
        candidates = [
            configs_dir / f"{agent_name}.yaml",
            configs_dir / f"{agent_name.removeprefix('agent-')}.yaml",
        ]
        for path in candidates:
            if path.exists():
                with open(path) as f:
                    data = yaml.safe_load(f)
                return data or {}
    except Exception as e:
        logger.debug(f"Failed to load agent YAML for {agent_name}: {e}")
    return None


def _load_active_agent_yaml() -> dict[str, Any] | None:
    """Resolve + load the currently active agent's YAML. Returns None if unavailable."""
    agent_name = _get_active_agent_name()
    if not agent_name:
        return None
    return _load_agent_yaml(agent_name)


# ---------------------------------------------------------------------------
# Hook entry point
# ---------------------------------------------------------------------------


def main(stdin: Any = None) -> None:
    """PreToolUse hook entry point.

    Reads hook JSON from stdin, resolves the active agent, and blocks the tool
    if it appears in disallowedTools. Exits 2 on block, 0 on pass.
    """
    try:
        raw: str = (stdin or sys.stdin).read()
        data: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except Exception:
        # Malformed stdin — fail open, never freeze Claude Code
        print(raw if "raw" in dir() else "{}")
        return

    tool_name: str = data.get("tool_name", "")

    if not tool_name:
        print(json.dumps(data))
        return

    try:
        agent_data = _load_active_agent_yaml()
    except Exception as e:
        logger.warning(f"agent_tool_gate: failed to load agent YAML: {e}")
        agent_data = None

    if agent_data is None:
        # No active agent or YAML unresolvable — pass through
        print(json.dumps(data))
        return

    result = check_tool_allowed(tool_name, agent_data)

    if result.blocked:
        print(json.dumps({"decision": "block", "reason": result.reason}))
        sys.exit(2)
    else:
        print(json.dumps(data))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
