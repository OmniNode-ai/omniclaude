# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse guard that blocks foreground drift while an overseer contract is active.

OMN-8376 — when `.onex_state/overseer-active.flag` exists, foreground Bash/Edit/Write
tools targeting repo paths under ``$OMNI_HOME`` are blocked so the lead agent cannot
drift into manual fixes while an overseer (OMN-8375 HandlerOvernight) is driving.

Read-only tools (Read, Grep, Glob, TaskList, SendMessage, ...) are not routed to this
guard via the hooks.json matcher — they remain allowed unconditionally.

Flag schema (YAML)::

    contract_path: /abs/path/to/contract.yaml
    active_phase: <phase-name>
    started_at: 2026-04-11T07:00:00Z

Flag location: ``$ONEX_STATE_DIR/overseer-active.flag`` (falls back to
``$OMNI_HOME/.onex_state/overseer-active.flag`` for scratch/test sessions).

Exit codes:
    0 — allow (flag absent, tool not targeting repo path, or non-matching tool)
    2 — block (flag present AND tool targets a path under $OMNI_HOME)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BLOCK_TOOLS = frozenset({"Bash", "Edit", "Write", "NotebookEdit", "MultiEdit"})


def _flag_path() -> Path:
    state_dir = os.environ.get("ONEX_STATE_DIR")
    if state_dir:
        return Path(state_dir) / "overseer-active.flag"
    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        return Path(omni_home) / ".onex_state" / "overseer-active.flag"
    return Path.home() / ".onex_state" / "overseer-active.flag"


def _omni_home_roots() -> list[Path]:
    roots: list[Path] = []
    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        roots.append(Path(omni_home).resolve())
    # Also cover the canonical worktrees root so foreground edits to active
    # worktrees are blocked while an overseer contract drives.
    worktrees_root = Path("/Volumes/PRO-G40/Code/omni_worktrees")  # local-path-ok
    if worktrees_root.exists():
        roots.append(worktrees_root.resolve())
    return roots


def _parse_flag(flag: Path) -> tuple[str, str]:
    """Parse minimal YAML flag without requiring PyYAML.

    Returns ``(contract_path, active_phase)`` with best-effort defaults.
    """
    contract_path = "<unknown>"
    active_phase = "<unknown>"
    try:
        text = flag.read_text(encoding="utf-8")
    except OSError:
        return contract_path, active_phase
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "contract_path" and value:
            contract_path = value
        elif key == "active_phase" and value:
            active_phase = value
    return contract_path, active_phase


def _targets_repo_path(tool_name: str, tool_input: dict, roots: list[Path]) -> bool:
    """Return True if the tool call touches anything under an OMNI_HOME root.

    Conservative: if we can't tell (no roots configured), return True so the
    guard fails closed when an overseer contract is active. The only way to
    get past the guard is to remove the flag.
    """
    if not roots:
        return True

    candidates: list[str] = []

    if tool_name in {"Edit", "Write", "NotebookEdit", "MultiEdit"}:
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if isinstance(file_path, str) and file_path:
            candidates.append(file_path)
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if not isinstance(command, str):
            return True
        # Any absolute path token under an OMNI_HOME root trips the guard.
        # Also trips on common mutating git/gh commands regardless of cwd —
        # `gh pr merge`, `git push`, `git commit`, etc. — because those operate
        # on whatever repo the session cwd is in, which is almost always under
        # OMNI_HOME during a drift incident.
        cwd = tool_input.get("cwd") or os.getcwd()
        if isinstance(cwd, str) and cwd:
            candidates.append(cwd)
        # Absolute path tokens in the command.
        for match in re.finditer(r"(/[\w./\-]+)", command):
            candidates.append(match.group(1))
        # Mutating gh / git operations on any repo are blocked unconditionally.
        mutating_patterns = (
            r"\bgh\s+pr\s+(merge|create|edit|close|reopen|review)\b",
            r"\bgh\s+issue\s+(create|edit|close|reopen|comment)\b",
            r"\bgit\s+(push|commit|merge|rebase|reset|checkout|tag|cherry-pick)\b",
        )
        for pat in mutating_patterns:
            if re.search(pat, command):
                return True

    for cand in candidates:
        try:
            resolved = Path(cand).expanduser().resolve()
        except (OSError, ValueError):
            continue
        for root in roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Fail open on bad input — other guards will handle malformed payloads.
        print("{}")
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name not in BLOCK_TOOLS:
        print("{}")
        return 0

    flag = _flag_path()
    if not flag.exists():
        print("{}")
        return 0

    roots = _omni_home_roots()
    if not _targets_repo_path(tool_name, tool_input, roots):
        print("{}")
        return 0

    contract_path, active_phase = _parse_flag(flag)
    reason = (
        f"Overseer contract {contract_path} is active on phase {active_phase}. "
        "Foreground tool blocked. Escalate via contract halt condition or kill "
        f"overseer with: rm {flag}"
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
