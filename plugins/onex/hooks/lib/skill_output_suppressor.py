# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Skill output suppression — reduce Claude context token usage.

Detects when a Bash tool call produces verbose output from skill-related
commands (pytest, mypy, ruff, pre-commit, docker logs, npm run build, etc.)
and produces a compact summary instead.

Token budget contract:
    Input:  full tool_response JSON from PostToolUse stdin
    Output: JSON with tool_response.output replaced by compact summary
            if the command matches a suppressible pattern AND the output
            exceeds the threshold. Otherwise, passes through unchanged.

    Errors are NEVER suppressed. If the command failed (non-zero exit),
    the full stderr/output is preserved for debugging.
"""

from __future__ import annotations

import json
import re
import sys
from enum import Enum

from pydantic import BaseModel, ConfigDict


class EnumSuppressionAction(str, Enum):
    suppressed = "suppressed"
    passthrough = "passthrough"
    error_preserved = "error_preserved"


class ModelSuppressionResult(BaseModel):
    """Result of output suppression evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: EnumSuppressionAction
    original_lines: int = 0
    summary_lines: int = 0
    command_type: str = ""
    summary: str = ""


# Commands whose output is safe to suppress when successful.
# Pattern -> human-readable label for the summary.
_SUPPRESSIBLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bpytest\b"), "pytest"),
    (re.compile(r"\bmypy\b"), "mypy"),
    (re.compile(r"\bruff\s+(check|format)\b"), "ruff"),
    (re.compile(r"\bpre-commit\s+run\b"), "pre-commit"),
    (re.compile(r"\bdocker\s+logs\b"), "docker-logs"),
    (re.compile(r"\bnpm\s+run\s+(build|test|lint)\b"), "npm"),
    (re.compile(r"\buv\s+run\s+(pytest|mypy|ruff)\b"), "uv-run"),
    (re.compile(r"\bbandit\b"), "bandit"),
    (re.compile(r"\bpyright\b"), "pyright"),
]

# Output shorter than this (in chars) is never suppressed — already compact.
_SUPPRESSION_THRESHOLD = 2000

# Maximum lines to include in the summary tail.
_SUMMARY_TAIL_LINES = 15


def detect_command_type(command: str) -> str | None:
    """Return the command type if it matches a suppressible pattern, else None."""
    for pattern, label in _SUPPRESSIBLE_PATTERNS:
        if pattern.search(command):
            return label
    return None


def _extract_pytest_summary(output: str) -> str:
    """Extract pytest's final summary line (e.g., '23 passed in 0.39s')."""
    lines = output.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        # pytest summary looks like: "====== N passed in X.XXs ======"
        if re.search(r"\d+\s+(passed|failed|error)", stripped):
            return stripped.strip("= ").strip()
    return ""


def _extract_mypy_summary(output: str) -> str:
    """Extract mypy's final status line."""
    lines = output.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if "Success:" in stripped or "Found" in stripped:
            return stripped
    return ""


def _extract_ruff_summary(output: str) -> str:
    """Extract ruff's summary."""
    lines = output.strip().splitlines()
    if not lines:
        return ""
    last = lines[-1].strip()
    if "All checks passed" in last or "Found" in last or "error" in last.lower():
        return last
    return f"{len(lines)} lines of output"


def summarize_output(
    command: str, output: str, exit_code: int | None
) -> ModelSuppressionResult:
    """Evaluate whether to suppress output and produce a summary if so.

    Returns a ModelSuppressionResult indicating the action taken.
    Errors (non-zero exit code) are NEVER suppressed.
    """
    command_type = detect_command_type(command)

    # Not a suppressible command — pass through
    if command_type is None:
        return ModelSuppressionResult(
            action=EnumSuppressionAction.passthrough,
            command_type="",
        )

    original_lines = output.count("\n") + 1 if output else 0

    # Error output is never suppressed
    if exit_code is not None and exit_code != 0:
        return ModelSuppressionResult(
            action=EnumSuppressionAction.error_preserved,
            original_lines=original_lines,
            summary_lines=original_lines,
            command_type=command_type,
            summary=f"[{command_type}] exited with code {exit_code} — full output preserved",
        )

    # Short output — not worth suppressing
    if len(output) < _SUPPRESSION_THRESHOLD:
        return ModelSuppressionResult(
            action=EnumSuppressionAction.passthrough,
            original_lines=original_lines,
            command_type=command_type,
        )

    # Extract tool-specific summary
    tool_summary = ""
    if command_type in ("pytest", "uv-run"):
        tool_summary = _extract_pytest_summary(output)
    elif command_type == "mypy":
        tool_summary = _extract_mypy_summary(output)
    elif command_type in ("ruff", "bandit", "pyright"):
        tool_summary = _extract_ruff_summary(output)

    # Build compact summary: tool-specific line + tail of output
    lines = output.strip().splitlines()
    tail = lines[-_SUMMARY_TAIL_LINES:] if len(lines) > _SUMMARY_TAIL_LINES else lines
    tail_text = "\n".join(tail)

    parts = []
    parts.append(
        f"[{command_type}] output suppressed ({original_lines} lines -> summary)"
    )
    if tool_summary:
        parts.append(f"Result: {tool_summary}")
    parts.append(f"--- last {len(tail)} lines ---")
    parts.append(tail_text)

    summary = "\n".join(parts)
    summary_lines = summary.count("\n") + 1

    return ModelSuppressionResult(
        action=EnumSuppressionAction.suppressed,
        original_lines=original_lines,
        summary_lines=summary_lines,
        command_type=command_type,
        summary=summary,
    )


def process_tool_info(tool_info: dict) -> dict:
    """Process PostToolUse JSON, suppressing output if appropriate.

    Modifies tool_response in-place if suppression applies.
    Returns the (possibly modified) tool_info dict.
    """
    tool_name = tool_info.get("tool_name", "")
    if tool_name != "Bash":
        return tool_info

    command = ""
    tool_input = tool_info.get("tool_input", {})
    if isinstance(tool_input, dict):
        command = tool_input.get("command", "")

    output = ""
    tool_response = tool_info.get("tool_response", {})
    if isinstance(tool_response, dict):
        output = tool_response.get("output", tool_response.get("stdout", ""))
    elif isinstance(tool_response, str):
        output = tool_response

    # Try to extract exit code
    exit_code = None
    if isinstance(tool_response, dict):
        ec = tool_response.get("exit_code", tool_response.get("exitCode"))
        if ec is not None:
            try:
                exit_code = int(ec)
            except (ValueError, TypeError):
                pass

    result = summarize_output(command, output, exit_code)

    if result.action == EnumSuppressionAction.suppressed:
        if isinstance(tool_response, dict):
            tool_response["output"] = result.summary
            tool_response["_suppressed"] = True
            tool_response["_original_lines"] = result.original_lines
        elif isinstance(tool_response, str):
            tool_info["tool_response"] = result.summary

    return tool_info


# CLI entry point: reads JSON from stdin, writes (possibly modified) JSON to stdout
if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        tool_info = json.loads(raw)
        modified = process_tool_info(tool_info)
        print(json.dumps(modified))
    except Exception as e:
        print(f"[skill_output_suppressor] error: {e}", file=sys.stderr)
        # On error, pass through unchanged
        if raw:
            print(raw)
        sys.exit(0)
