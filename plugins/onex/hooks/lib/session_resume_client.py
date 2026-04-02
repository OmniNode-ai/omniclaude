# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Session resume context formatter.

Formats a session projector snapshot into injectable markdown context
for the SESSION_RESUME context source. Used by context injection
at session start when an agent is logged in (ONEX_AGENT_ID set).
"""

from __future__ import annotations


def format_resume_context(
    snapshot: dict[str, object] | None,
    agent_id: str,
) -> str:
    """Format a session snapshot as injectable markdown context.

    Returns empty string if snapshot is None or empty.
    """
    if not snapshot:
        return ""

    lines = [f"## Resumed Session Context ({agent_id})", ""]

    ticket = snapshot.get("current_ticket")
    branch = snapshot.get("git_branch")
    workdir = snapshot.get("working_directory", "")
    outcome = snapshot.get("session_outcome")

    if ticket:
        lines.append(f"- **Ticket:** {ticket}")
    if branch:
        lines.append(f"- **Branch:** {branch}")
    if workdir:
        repo = str(workdir).rstrip("/").split("/")[-1] if workdir else "unknown"
        lines.append(f"- **Repo:** {repo}")

    files = snapshot.get("files_touched", [])
    if files and isinstance(files, list):
        lines.append(f"- **Files touched:** {', '.join(str(f) for f in files[:10])}")

    errors = snapshot.get("errors_hit", [])
    if errors and isinstance(errors, list):
        lines.append(f"- **Errors hit:** {len(errors)}")
        for err in errors[-3:]:
            lines.append(f"  - `{str(err)[:100]}`")

    last_tool = snapshot.get("last_tool_name")
    last_success = snapshot.get("last_tool_success")
    last_summary = snapshot.get("last_tool_summary")
    if last_tool:
        status = "succeeded" if last_success else "failed"
        lines.append(f"- **Last action:** {last_tool} ({status})")
        if last_summary:
            lines.append(f"  - {str(last_summary)[:200]}")

    if outcome:
        lines.append(f"- **Session outcome:** {outcome}")

    started = snapshot.get("session_started_at")
    ended = snapshot.get("session_ended_at")
    if ended:
        lines.append(f"- **Session ended at:** {ended}")
    elif started:
        lines.append(f"- **Session started at:** {started}")

    return "\n".join(lines)
