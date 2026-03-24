# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PreToolUse workflow guard for triage-first and ticket-first enforcement (OMN-6231).

Enforces two workflow preconditions via proxy signals:

1. Triage-first: Before any Linear epic creation (mcp__linear-server__save_issue
   with a parent-less issue that resembles an epic), check that
   .onex_state/triage_complete marker file exists. The marker is written by
   the linear_triage skill when a triage session completes.

2. Ticket-first: Before any git commit via the Bash tool, check that the
   current branch name contains an OMN-\\d+ pattern OR the commit message
   (if extractable from the command string) contains one.

IMPORTANT — scope limitations (honest about what this enforces):
- This enforces proxy signals only. A human can bypass both checks trivially
  by touching the marker file or naming a branch with OMN-1. This is
  intentional: the goal is blocking accidental/automatic bypasses, not
  preventing deliberate overrides.
- The triage_complete marker is session-scoped: if a worktree has no marker,
  the guard warns but does NOT hard-block epic creation (too many false
  positives for worktrees that legitimately start fresh).
- The OMN-\\d+ check is branch-name-first. If the branch name matches, no
  commit-message scan is performed.

CLI usage (invoked by pre_tool_use_workflow_guard.sh):

    python3 -m omniclaude.hooks.pre_tool_use_workflow_guard < tool_input.json

Reads JSON from stdin (Claude Code PreToolUse hook format).
Exits 0 (allow/pass-through), 1 (warn — allow but emit advisory), or 2 (block).

Related:
    - OMN-6231: Enforce Triage-First and Ticket-First Workflow at the Hook Layer
    - OMN-6233: Task 4 — integration pass that extends this module
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Marker file location
# ---------------------------------------------------------------------------

_TRIAGE_COMPLETE_MARKER = ".onex_state/triage_complete"
_ONEX_STATE_DIR = ".onex_state"

# ---------------------------------------------------------------------------
# Ticket ID pattern
# ---------------------------------------------------------------------------

_TICKET_PATTERN = re.compile(r"OMN-\d+", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Git commit detection — matches `git commit` in a Bash command string
# ---------------------------------------------------------------------------

_GIT_COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b")

# ---------------------------------------------------------------------------
# Epic creation detection — mcp__linear-server__save_issue without parentId
# ---------------------------------------------------------------------------

_EPIC_CREATION_TOOL = "mcp__linear-server__save_issue"


# ---------------------------------------------------------------------------
# Helper: resolve project root from env or cwd
# ---------------------------------------------------------------------------


def _resolve_project_root() -> Path:
    """Return the project root directory.

    Uses CLAUDE_PROJECT_DIR env var if set, otherwise falls back to cwd.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        return Path(project_dir)
    return Path.cwd()


# ---------------------------------------------------------------------------
# Helper: get current git branch
# ---------------------------------------------------------------------------


def _get_current_branch(cwd: Path) -> str | None:
    """Return the current git branch name, or None if not in a git repo."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:  # noqa: BLE001
        return None
    return None


# ---------------------------------------------------------------------------
# Triage-first check
# ---------------------------------------------------------------------------


def _check_triage_complete(project_root: Path) -> tuple[bool, str]:
    """Check if the triage_complete marker file exists.

    Returns:
        (marker_present, message) — message is empty when marker is present.
    """
    marker_path = project_root / _TRIAGE_COMPLETE_MARKER
    if marker_path.exists():
        return True, ""
    return False, (
        f"[workflow-guard] ADVISORY — Epic creation attempted without a completed "
        f"triage pass.\n"
        f"Expected marker: {marker_path}\n"
        f"Run /linear_triage (or the triage skill) first. The skill writes "
        f"'{_TRIAGE_COMPLETE_MARKER}' when triage is complete.\n"
        f"If triage was completed in a different session, touch the marker manually: "
        f"`mkdir -p {_ONEX_STATE_DIR} && touch {_TRIAGE_COMPLETE_MARKER}`"
    )


# ---------------------------------------------------------------------------
# Ticket-first check
# ---------------------------------------------------------------------------


def _check_ticket_id_in_context(
    bash_command: str, project_root: Path
) -> tuple[bool, str]:
    """Check for OMN-\\d+ in branch name or commit message.

    Returns:
        (ticket_present, message) — message is empty when ticket ID is found.
    """
    # Check branch name first
    branch = _get_current_branch(project_root)
    if branch and _TICKET_PATTERN.search(branch):
        return True, ""

    # Check commit message extracted from the command string
    # Patterns: -m "OMN-1234: ..." or --message="..." or -F <file>
    msg_match = re.search(r'-m\s+["\']([^"\']+)["\']', bash_command)
    if msg_match:
        commit_msg = msg_match.group(1)
        if _TICKET_PATTERN.search(commit_msg):
            return True, ""

    branch_hint = f" (current branch: {branch!r})" if branch else ""
    return False, (
        f"[workflow-guard] ADVISORY — git commit attempted without a Linear ticket ID"
        f"{branch_hint}.\n"
        f"Expected: OMN-\\d+ in branch name or commit message.\n"
        f"Fix: ensure you are on a branch named like "
        f"jonah/omn-1234-description, or include OMN-1234 in your commit message."
    )


# ---------------------------------------------------------------------------
# Core guard logic
# ---------------------------------------------------------------------------


def run_guard(stdin_json: str) -> tuple[int, str]:
    """Run the workflow guard against hook JSON from stdin.

    Args:
        stdin_json: Raw JSON string from Claude Code PreToolUse hook.

    Returns:
        Tuple of (exit_code, output_string).
        exit_code 0: allow (output is original JSON).
        exit_code 1: warn (output is advisory JSON).
        exit_code 2: block (output is block JSON).
    """
    try:
        hook_data: dict[str, object] = json.loads(stdin_json)
    except json.JSONDecodeError:
        return 0, stdin_json

    tool_name: str = str(hook_data.get("tool_name", ""))
    raw_input = hook_data.get("tool_input", {})
    tool_input: dict[str, object] = raw_input if isinstance(raw_input, dict) else {}

    project_root = _resolve_project_root()

    # --- Check 1: Triage-first (epic creation via Linear MCP) ---
    if tool_name == _EPIC_CREATION_TOOL:
        # Heuristic: if parentId is absent or None, treat as potential epic creation
        parent_id = tool_input.get("parentId") or tool_input.get("parent_id")
        if not parent_id:
            marker_present, advisory = _check_triage_complete(project_root)
            if not marker_present:
                # Warn only — do not hard-block (high false positive risk)
                return 1, json.dumps({"decision": "warn", "reason": advisory})

    # --- Check 2: Ticket-first (git commit via Bash) ---
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if _GIT_COMMIT_PATTERN.search(command):
            ticket_present, advisory = _check_ticket_id_in_context(
                command, project_root
            )
            if not ticket_present:
                # Warn only — hard-blocking git commits has too many false positives
                # (e.g. initial commits, chore commits during repo setup)
                return 1, json.dumps({"decision": "warn", "reason": advisory})

    # --- Pass through ---
    return 0, stdin_json


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the workflow guard."""
    stdin_data = sys.stdin.read()
    exit_code, output = run_guard(stdin_data)
    print(output)  # noqa: T201
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
