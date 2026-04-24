# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse guard that blocks foreground work when background workers are active.

OMN-7843 — when the current session is the team lead of a team with one or more
*non-lead* members (i.e., real workers), foreground tool calls (Read, Edit,
Write, Bash, Glob, Grep) are blocked so the lead delegates via SendMessage /
Agent / TaskCreate instead of doing the work itself.

Design decisions (per DoD + `feedback_delegation_enforcer_risk.md`):

* **Opt-in enable via `TEAM_LEAD_FOREGROUND_BLOCK=true`.** Default is OFF. The
  guard is effectively a no-op unless the user explicitly enables it. This is
  the #1 defense against recursive-block incidents.

* **Hard kill-switch via `ONEX_TEAM_LEAD_GUARD_DISABLE=1`.** If set, the guard
  short-circuits before any logic runs. This must be respected regardless of
  any other signal. Also honored: a file marker at
  ``~/.claude/omniclaude-team-lead-guard-disabled``.

* **Subagent exemption.** If ``CLAUDE_AGENT_ID`` is set (i.e., we are running
  inside a spawned subagent — not the session that owns the team), bypass
  unconditionally. Subagents must never be blocked because they have no way to
  satisfy "delegate via SendMessage" — they're the delegation target.

* **Generous defaults.** If team config is missing / unreadable / unparseable,
  or the member list only contains the lead itself, allow the call (fail
  open). Only block when we can *positively* identify a worker team where this
  session is the lead.

* **Team identification.** Walk ``~/.claude/teams/*/config.json`` looking for a
  file whose ``leadSessionId`` matches the current ``CLAUDE_SESSION_ID``. This
  is the authoritative signal — no brittle "active team" flag file that can
  drift.

Exit codes::

    0 — allow (guard disabled, no team, subagent, missing session, etc.)
    2 — block (lead session with ≥1 worker AND matcher-tool invoked)

Performance: kill-switch + subagent + session-missing paths exit in <1ms with
no filesystem access beyond the kill-switch file marker check. The team lookup
is at most one ``glob('*')`` + small JSON reads — well under the 10ms budget
called out in the DoD.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Tools this guard blocks when a worker team is active.
# Glob/Grep are read-only but the DoD explicitly lists them as blocked to keep
# the lead from doing exploration work that a worker should own.
BLOCK_TOOLS = frozenset({"Read", "Edit", "Write", "Bash", "Glob", "Grep"})

# Env var names
ENV_ENABLE = "TEAM_LEAD_FOREGROUND_BLOCK"
ENV_KILL_SWITCH = "ONEX_TEAM_LEAD_GUARD_DISABLE"
ENV_AGENT_ID = "CLAUDE_AGENT_ID"
ENV_SESSION_ID = "CLAUDE_SESSION_ID"


def _kill_switch_file() -> Path:
    """Return the file-marker kill-switch path (resolved at call time).

    Resolved lazily so test harnesses that override ``HOME`` via monkeypatch
    see the overridden value.
    """
    return Path.home() / ".claude" / "omniclaude-team-lead-guard-disabled"


def _kill_switch_active() -> bool:
    """Return True if the guard should short-circuit (fail open)."""
    if os.environ.get(ENV_KILL_SWITCH, "").strip() in {"1", "true", "TRUE", "yes"}:
        return True
    try:
        return _kill_switch_file().exists()
    except OSError:
        return False


def _guard_enabled() -> bool:
    """Return True if the opt-in enable flag is set.

    Accepts ``true``/``1``/``yes`` (case-insensitive). Anything else — including
    unset — means the guard is OFF.
    """
    raw = os.environ.get(ENV_ENABLE, "").strip().lower()
    return raw in {"true", "1", "yes"}


def _is_subagent() -> bool:
    """Return True if this process is a spawned subagent (not the main session)."""
    return bool(os.environ.get(ENV_AGENT_ID, "").strip())


def _teams_root() -> Path:
    """Return the directory holding per-team config files."""
    override = os.environ.get("CLAUDE_TEAMS_ROOT", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".claude" / "teams"


def _find_lead_team(session_id: str) -> tuple[str, int] | None:
    """Return ``(team_name, worker_count)`` if the current session leads a team.

    Walks ``CLAUDE_TEAMS_ROOT`` (default ``~/.claude/teams``) looking for a
    ``config.json`` whose ``leadSessionId`` matches ``session_id``. Worker count
    excludes the lead itself — a team whose only member is the lead has zero
    workers and does not trigger the guard.

    Returns ``None`` on any error (teams dir missing, no matching team, parse
    failure). Fails open — we only return a positive result when we can read,
    parse, and match with high confidence.
    """
    if not session_id:
        return None
    root = _teams_root()
    if not root.is_dir():
        return None
    try:
        candidates = sorted(root.glob("*/config.json"))
    except OSError:
        return None

    for cfg_path in candidates:
        try:
            with cfg_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("leadSessionId") != session_id:
            continue

        team_name = data.get("name") or cfg_path.parent.name
        members = data.get("members")
        if not isinstance(members, list):
            # Config exists but has no member list — treat as "no workers"
            return None

        lead_agent_id = data.get("leadAgentId", "")
        worker_count = 0
        for member in members:
            if not isinstance(member, dict):
                continue
            agent_id = member.get("agentId", "")
            agent_type = str(member.get("agentType", "")).strip().lower()
            # A member is a worker if they are neither the team lead agent nor
            # tagged as agentType=team-lead. This handles lead entries added to
            # the member list as well as separate worker rows.
            if agent_id and agent_id == lead_agent_id:
                continue
            if agent_type == "team-lead":
                continue
            worker_count += 1

        if worker_count <= 0:
            return None
        return (str(team_name), worker_count)

    return None


def main() -> int:
    # Fast paths — these must be first, before any filesystem or parse work.

    # 1. Hard kill-switch. Always wins. No logs, no processing.
    if _kill_switch_active():
        print("{}")
        return 0

    # 2. Opt-in gate. Default OFF. If not enabled, the guard is a no-op.
    if not _guard_enabled():
        print("{}")
        return 0

    # 3. Subagent exemption. Subagents have no way to satisfy "delegate" and
    # must never be blocked.
    if _is_subagent():
        print("{}")
        return 0

    # 4. Parse payload. Fail open on bad input — other guards handle malformed.
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print("{}")
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in BLOCK_TOOLS:
        print("{}")
        return 0

    # 5. Identify the team this session is leading, if any. Fail open when no
    # session ID is present (common in ad-hoc CLI invocations / tests).
    session_id = os.environ.get(ENV_SESSION_ID, "").strip()
    if not session_id:
        print("{}")
        return 0

    team = _find_lead_team(session_id)
    if team is None:
        print("{}")
        return 0

    team_name, worker_count = team
    reason = (
        f"Team lead foreground guard: team '{team_name}' has {worker_count} "
        f"active worker(s). Delegate this work via SendMessage, Agent, or "
        "TaskCreate instead of running the tool yourself. To bypass "
        f"temporarily, set {ENV_KILL_SWITCH}=1 or unset {ENV_ENABLE}."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
