# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read-only tool definitions and dispatchers for the agentic delegation loop.

Provides eight named tools for local LLM agentic loops:
- read_file: Read file contents with optional offset/limit
- search_content: Search file contents using ripgrep
- find_files: Find files matching a glob pattern
- git_log: View git history with validated arguments
- git_diff: View git diffs with validated arguments
- git_show: View a specific git object
- list_dir: List directory contents
- line_count: Count lines in a file

All tools are read-only (v1). Write-capable tools are deferred to v2.

Tool safety doctrine: No generic ``run_command`` tool. Each allowed command is
a separate named tool with typed arguments and validated inputs.

Output truncation doctrine: All tool results are capped at 8KB with a stable
``[TRUNCATED -- N more lines]`` marker so the model can request narrower
follow-up reads.

Ticket: OMN-5723, OMN-6955
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default output cap per tool result (8KB per truncation doctrine).
_DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024

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

TOOL_GIT_LOG: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "git_log",
        "description": "View git commit history. Arguments are passed to 'git log'.",
        "parameters": {
            "type": "object",
            "properties": {
                "args": {
                    "type": "string",
                    "description": (
                        "Arguments for git log (e.g. '--oneline -20', "
                        "'--oneline --since=7.days'). Default: '--oneline -10'."
                    ),
                },
            },
        },
    },
}

TOOL_GIT_DIFF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "git_diff",
        "description": "View git diffs. Arguments are passed to 'git diff'.",
        "parameters": {
            "type": "object",
            "properties": {
                "args": {
                    "type": "string",
                    "description": (
                        "Arguments for git diff (e.g. 'HEAD~1', "
                        "'--stat', 'main...HEAD'). Default: ''."
                    ),
                },
            },
        },
    },
}

TOOL_GIT_SHOW: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "git_show",
        "description": "Show a git object (commit, tag, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Git ref to show (e.g. 'HEAD', 'abc1234', 'v1.0.0').",
                },
            },
            "required": ["ref"],
        },
    },
}

TOOL_LIST_DIR: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": "List the contents of a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory. Default: current directory.",
                },
            },
        },
    },
}

TOOL_LINE_COUNT: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "line_count",
        "description": "Count the number of lines in a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file.",
                },
            },
            "required": ["path"],
        },
    },
}

# All tool definitions for registration with the LLM.
ALL_TOOLS: list[dict[str, Any]] = [
    TOOL_READ_FILE,
    TOOL_SEARCH_CONTENT,
    TOOL_FIND_FILES,
    TOOL_GIT_LOG,
    TOOL_GIT_DIFF,
    TOOL_GIT_SHOW,
    TOOL_LIST_DIR,
    TOOL_LINE_COUNT,
]


# ---------------------------------------------------------------------------
# Output truncation (8KB default per doctrine)
# ---------------------------------------------------------------------------


def _truncate(output: str, max_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES) -> str:
    """Truncate output to a byte budget with a stable marker.

    The marker includes the number of remaining lines so the model can
    request a narrower follow-up read.
    """
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return output

    # Find the last newline within the budget so we don't cut mid-line.
    truncated_bytes = encoded[:max_bytes]
    last_nl = truncated_bytes.rfind(b"\n")
    if last_nl > 0:
        truncated_bytes = truncated_bytes[:last_nl]

    truncated_text = truncated_bytes.decode("utf-8", errors="replace")
    remaining_lines = output[len(truncated_text) :].count("\n")
    return truncated_text + f"\n[TRUNCATED -- {remaining_lines} more lines]"


# ---------------------------------------------------------------------------
# Git argument validation
# ---------------------------------------------------------------------------

# Characters that enable shell injection in git arguments.
_GIT_UNSAFE_CHARS = frozenset(";|&`$(){}!><\n\r")


def _validate_git_args(raw: str) -> list[str] | str:
    """Validate and split git arguments. Returns list of args or error string."""
    if any(c in _GIT_UNSAFE_CHARS for c in raw):
        return "Error: git arguments contain unsafe characters."
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        return f"Error: could not parse git arguments: {exc}"
    # Reject flags that could write or mutate state.
    _WRITE_FLAGS = {"--force", "-f", "--delete", "-D", "--hard", "--mixed"}
    for part in parts:
        if part in _WRITE_FLAGS:
            return f"Error: flag '{part}' is not allowed (read-only)."
    return parts


# ---------------------------------------------------------------------------
# Tool dispatchers
# ---------------------------------------------------------------------------


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

    total_lines = len(lines)
    selected = lines[offset : offset + limit]
    numbered = [f"{offset + i + 1:>6}\t{line}" for i, line in enumerate(selected)]
    result = "\n".join(numbered)
    if not result:
        return "(empty file or range out of bounds)"

    if offset + limit < total_lines:
        result += f"\n[{total_lines - offset - limit} more lines in file]"

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

    if len(matches) > 200:
        result_lines = matches[:200]
        result_lines.append(f"... and {len(matches) - 200} more files")
    else:
        result_lines = matches

    return _truncate("\n".join(result_lines))


def _dispatch_git_log(args: dict[str, Any]) -> str:
    """Execute git log with validated arguments."""
    raw_args = args.get("args", "--oneline -10")
    validated = _validate_git_args(raw_args)
    if isinstance(validated, str):
        return validated

    cmd = ["git", "log"] + validated
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "Error: git log timed out."

    output = result.stdout.strip()
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return (
            f"Error (exit {result.returncode}): {stderr}" if stderr else "(no output)"
        )
    return _truncate(output) if output else "(no output)"


def _dispatch_git_diff(args: dict[str, Any]) -> str:
    """Execute git diff with validated arguments."""
    raw_args = args.get("args", "")
    if raw_args:
        validated = _validate_git_args(raw_args)
        if isinstance(validated, str):
            return validated
        cmd = ["git", "diff"] + validated
    else:
        cmd = ["git", "diff"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "Error: git diff timed out."

    output = result.stdout.strip()
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return (
            f"Error (exit {result.returncode}): {stderr}" if stderr else "(no output)"
        )
    return _truncate(output) if output else "(no changes)"


def _dispatch_git_show(args: dict[str, Any]) -> str:
    """Execute git show for a specific ref."""
    ref = args.get("ref", "")
    if not ref:
        return "Error: 'ref' is required."

    validated = _validate_git_args(ref)
    if isinstance(validated, str):
        return validated

    cmd = ["git", "show"] + validated
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "Error: git show timed out."

    output = result.stdout.strip()
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return (
            f"Error (exit {result.returncode}): {stderr}" if stderr else "(no output)"
        )
    return _truncate(output) if output else "(no output)"


def _dispatch_list_dir(args: dict[str, Any]) -> str:
    """List directory contents."""
    path_str = args.get("path", ".")
    path = Path(path_str)

    if not path.exists():
        return f"Error: directory not found: {path_str}"
    if not path.is_dir():
        return f"Error: not a directory: {path_str}"

    try:
        entries = sorted(os.listdir(path))
    except OSError as exc:
        return f"Error listing directory: {exc}"

    if not entries:
        return "(empty directory)"

    lines: list[str] = []
    for entry in entries:
        full = path / entry
        suffix = "/" if full.is_dir() else ""
        lines.append(f"{entry}{suffix}")

    return _truncate("\n".join(lines))


def _dispatch_line_count(args: dict[str, Any]) -> str:
    """Count lines in a file."""
    path_str = args.get("path", "")
    if not path_str:
        return "Error: 'path' is required."

    path = Path(path_str)
    if not path.exists():
        return f"Error: file not found: {path_str}"
    if not path.is_file():
        return f"Error: not a file: {path_str}"

    try:
        count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError as exc:
        return f"Error: {exc}"

    return f"{count} lines"


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

_DISPATCH_TABLE: dict[str, Any] = {
    "read_file": _dispatch_read_file,
    "search_content": _dispatch_search_content,
    "find_files": _dispatch_find_files,
    "git_log": _dispatch_git_log,
    "git_diff": _dispatch_git_diff,
    "git_show": _dispatch_git_show,
    "list_dir": _dispatch_list_dir,
    "line_count": _dispatch_line_count,
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
    "TOOL_GIT_DIFF",
    "TOOL_GIT_LOG",
    "TOOL_GIT_SHOW",
    "TOOL_LINE_COUNT",
    "TOOL_LIST_DIR",
    "TOOL_READ_FILE",
    "TOOL_SEARCH_CONTENT",
    "dispatch_tool",
]
