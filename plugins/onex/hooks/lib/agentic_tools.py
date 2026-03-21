# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read-only tool definitions and dispatchers for the agentic delegation loop.

Provides four tools for local LLM agentic loops:
- read_file: Read file contents with optional offset/limit
- search_content: Search file contents using ripgrep
- find_files: Find files matching a glob pattern
- run_command: Execute allowlisted read-only commands

All tools are read-only (v1). Write-capable tools are deferred to v2.

Ticket: OMN-5723
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Maximum output size to prevent overwhelming LLM context.
_MAX_OUTPUT_CHARS = 50_000

# Allowlisted command prefixes for run_command.
_COMMAND_ALLOWLIST: list[str] = [
    "git log",
    "git diff",
    "git status",
    "git show",
    "ls",
    "wc",
    "cat",
]

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling JSON Schema format)
# ---------------------------------------------------------------------------

TOOL_READ_FILE: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read the contents of a file. Use offset and limit to read "
            "specific portions of large files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-based). Default: 0.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read. Default: 200.",
                },
            },
            "required": ["path"],
        },
    },
}

TOOL_SEARCH_CONTENT: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_content",
        "description": (
            "Search file contents for a regex pattern using ripgrep. "
            "Returns matching lines with file paths and line numbers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in. Default: current directory.",
                },
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g. '*.py'). Optional.",
                },
            },
            "required": ["pattern"],
        },
    },
}

TOOL_FIND_FILES: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "find_files",
        "description": (
            "Find files matching a glob pattern. Returns a list of matching file paths."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match (e.g. '**/*.py', 'src/**/*.ts').",
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from. Default: current directory.",
                },
            },
            "required": ["pattern"],
        },
    },
}

TOOL_RUN_COMMAND: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Execute a read-only shell command. Only allowlisted commands are "
            "permitted: git log/diff/status/show, ls, wc, cat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
            },
            "required": ["command"],
        },
    },
}

# All tool definitions for registration with the LLM.
ALL_TOOLS: list[dict[str, Any]] = [
    TOOL_READ_FILE,
    TOOL_SEARCH_CONTENT,
    TOOL_FIND_FILES,
    TOOL_RUN_COMMAND,
]


# ---------------------------------------------------------------------------
# Tool dispatchers
# ---------------------------------------------------------------------------


def _truncate(output: str) -> str:
    """Truncate output to prevent overwhelming LLM context."""
    if len(output) > _MAX_OUTPUT_CHARS:
        return (
            output[:_MAX_OUTPUT_CHARS]
            + f"\n... [truncated at {_MAX_OUTPUT_CHARS} chars]"
        )
    return output


def _dispatch_read_file(args: dict[str, Any]) -> str:
    """Read file contents with optional offset/limit."""
    path_str = args.get("path", "")
    if not path_str:
        return "Error: 'path' is required."

    path = Path(path_str)
    if not path.exists():
        return f"Error: file not found: {path_str}"
    if not path.is_file():
        return f"Error: not a file: {path_str}"

    offset = max(0, int(args.get("offset", 0)))
    limit = max(1, int(args.get("limit", 200)))

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"Error reading file: {exc}"

    selected = lines[offset : offset + limit]
    numbered = [f"{offset + i + 1:>6}\t{line}" for i, line in enumerate(selected)]
    result = "\n".join(numbered)
    if not result:
        return "(empty file or range out of bounds)"
    return _truncate(result)


def _dispatch_search_content(args: dict[str, Any]) -> str:
    """Search file contents using ripgrep."""
    pattern = args.get("pattern", "")
    if not pattern:
        return "Error: 'pattern' is required."

    cmd = ["rg", "--no-heading", "--line-number", "--max-count", "50", pattern]

    search_path = args.get("path", ".")
    glob_filter = args.get("glob")
    if glob_filter:
        cmd.extend(["--glob", glob_filter])

    cmd.append(search_path)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except FileNotFoundError:
        return "Error: ripgrep (rg) is not installed."
    except subprocess.TimeoutExpired:
        return "Error: search timed out after 15 seconds."

    output = result.stdout.strip()
    if not output:
        return "(no matches found)"
    return _truncate(output)


def _dispatch_find_files(args: dict[str, Any]) -> str:
    """Find files matching a glob pattern."""
    pattern = args.get("pattern", "")
    if not pattern:
        return "Error: 'pattern' is required."

    base_path = Path(args.get("path", "."))

    try:
        matches = sorted(str(p) for p in base_path.glob(pattern))
    except OSError as exc:
        return f"Error: {exc}"

    if not matches:
        return "(no files found)"

    # Cap at 200 results to avoid flooding context.
    if len(matches) > 200:
        result_lines = matches[:200]
        result_lines.append(f"... and {len(matches) - 200} more files")
    else:
        result_lines = matches

    return _truncate("\n".join(result_lines))


# Shell metacharacters that enable command chaining/injection.
_SHELL_METACHAR_PATTERN = re.compile(r"[;|&`$()<>\n]")


def _is_command_allowed(command: str) -> bool:
    """Check if a command matches the allowlist.

    Rejects commands containing shell metacharacters to prevent injection
    via chaining operators (e.g. ``cat /etc/passwd; rm -rf /``).
    """
    stripped = command.strip()
    if _SHELL_METACHAR_PATTERN.search(stripped):
        return False
    return any(stripped.startswith(prefix) for prefix in _COMMAND_ALLOWLIST)


def _dispatch_run_command(args: dict[str, Any]) -> str:
    """Execute an allowlisted read-only command."""
    command = args.get("command", "")
    if not command:
        return "Error: 'command' is required."

    if not _is_command_allowed(command):
        return (
            f"Error: command not allowed. Only these prefixes are permitted: "
            f"{', '.join(_COMMAND_ALLOWLIST)}"
        )

    try:
        cmd_args = shlex.split(command)
    except ValueError as exc:
        return f"Error: could not parse command: {exc}"

    try:
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds."

    output = result.stdout.strip()
    if result.returncode != 0 and result.stderr.strip():
        output += f"\n[stderr]: {result.stderr.strip()}"
    if not output:
        return "(no output)"
    return _truncate(output)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

_DISPATCH_TABLE: dict[str, Any] = {
    "read_file": _dispatch_read_file,
    "search_content": _dispatch_search_content,
    "find_files": _dispatch_find_files,
    "run_command": _dispatch_run_command,
}


def dispatch_tool(tool_name: str, arguments_json: str) -> str:
    """Dispatch a tool call by name with JSON-encoded arguments.

    Args:
        tool_name: Name of the tool to invoke.
        arguments_json: JSON string of arguments.

    Returns:
        String result of the tool invocation, or an error message.
    """
    handler = _DISPATCH_TABLE.get(tool_name)
    if handler is None:
        return f"Error: unknown tool '{tool_name}'. Available: {', '.join(_DISPATCH_TABLE.keys())}"

    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON arguments: {exc}"

    if not isinstance(args, dict):
        return "Error: arguments must be a JSON object."

    try:
        return handler(args)
    except Exception as exc:
        logger.exception("Tool dispatch error for %s", tool_name)
        return f"Error: tool execution failed: {exc}"


__all__ = [
    "ALL_TOOLS",
    "TOOL_FIND_FILES",
    "TOOL_READ_FILE",
    "TOOL_RUN_COMMAND",
    "TOOL_SEARCH_CONTENT",
    "dispatch_tool",
]
