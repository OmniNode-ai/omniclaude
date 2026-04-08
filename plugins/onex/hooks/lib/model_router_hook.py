# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PreToolUse model router hook — advisory delegation to cheaper models (OMN-7810).

Classifies tool calls by estimated complexity and suggests delegation to cheaper
models for simple tasks. Runs in ADVISORY mode (warn only, does not block).

Complexity heuristics (no network calls, <50ms budget):
- Bash: long pipelines / multi-step commands → high; simple commands → low
- Edit/Write: large diffs or architecture files → high; small changes → low
- Read/Grep/Glob: always low (information gathering)

Exit codes:
    0 — allow (pass through, possibly with advisory on stderr)
    2 — block with delegation message (enforce mode only)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_FILENAME = "model_router_hook.yaml"


def _load_config(plugin_root: str) -> dict:
    """Load hook config from plugin config directory."""
    config_path = Path(plugin_root) / "hooks" / "config" / _CONFIG_FILENAME
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


# ---------------------------------------------------------------------------
# Complexity classification
# ---------------------------------------------------------------------------

# Patterns that indicate high complexity in Bash commands
_COMPLEX_BASH_PATTERNS = [
    "docker compose",
    "docker build",
    "kubectl",
    "terraform",
    "git rebase",
    "git merge",
    "uv run pytest",
    "make ",
    "cmake",
]

# Simple Bash command prefixes
_SIMPLE_BASH_PREFIXES = [
    "ls",
    "cat ",
    "echo ",
    "pwd",
    "cd ",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git show",
    "git rev-parse",
    "head ",
    "tail ",
    "wc ",
    "date",
    "which ",
    "whoami",
    "hostname",
    "env",
    "printenv",
    "mkdir ",
    "touch ",
    "rm ",
    "cp ",
    "mv ",
]

# Architecture-significant file patterns (higher complexity)
_ARCH_FILE_PATTERNS = [
    "handler_",
    "adapter_",
    "protocol_",
    "service_",
    "model_",
    "schema",
    "migration",
    "contract",
    "config",
]


def _classify_bash_complexity(command: str) -> float:
    """Return complexity score 0.0-1.0 for a Bash command."""
    if not command:
        return 0.0

    # Multi-command chains are complex
    if "&&" in command and command.count("&&") >= 2:
        return 0.8

    # Pipe chains with 3+ stages
    if command.count("|") >= 2:
        return 0.7

    # Check for known complex patterns
    cmd_lower = command.lower().strip()
    for pattern in _COMPLEX_BASH_PATTERNS:
        if pattern in cmd_lower:
            return 0.8

    # Check for simple commands
    for prefix in _SIMPLE_BASH_PREFIXES:
        if cmd_lower.startswith(prefix):
            return 0.2

    # Default: moderate
    return 0.5


def _classify_edit_complexity(tool_input: dict) -> float:
    """Return complexity score 0.0-1.0 for an Edit/Write call."""
    file_path = str(tool_input.get("file_path", ""))

    # Check for architecture-significant files
    filename = Path(file_path).name.lower() if file_path else ""
    for pattern in _ARCH_FILE_PATTERNS:
        if pattern in filename:
            return 0.8

    # Large content changes
    content = str(tool_input.get("content", ""))
    new_string = str(tool_input.get("new_string", ""))
    change_size = max(len(content), len(new_string))

    if change_size > 500:
        return 0.7
    if change_size > 100:
        return 0.5

    return 0.3


def classify_complexity(tool_name: str, tool_input: dict) -> float:
    """Classify tool call complexity. Returns 0.0 (trivial) to 1.0 (complex)."""
    if tool_name == "Bash":
        return _classify_bash_complexity(str(tool_input.get("command", "")))
    if tool_name in ("Edit", "Write"):
        return _classify_edit_complexity(tool_input)
    if tool_name in ("Read", "Grep", "Glob"):
        return 0.1  # Information gathering is always simple
    return 0.5


# ---------------------------------------------------------------------------
# Main hook logic
# ---------------------------------------------------------------------------


def run_model_router(stdin_json: str) -> tuple[int, str]:
    """Run model router hook.

    Returns:
        (exit_code, output) — 0 for allow, 2 for block (enforce mode only).
    """
    try:
        hook_data = json.loads(stdin_json)
    except json.JSONDecodeError:
        return 0, stdin_json

    tool_name = str(hook_data.get("tool_name", ""))
    raw_input = hook_data.get("tool_input", {})
    tool_input = raw_input if isinstance(raw_input, dict) else {}

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    config = _load_config(plugin_root)

    if not config.get("enabled", True):
        return 0, stdin_json

    mode = config.get("mode", "advisory")
    threshold = config.get("delegation_threshold", 0.7)
    delegation_model = config.get("delegation_model", "glm-4.7-flash")
    orchestration_tools = set(config.get("orchestration_tools", []))
    implementation_tools = set(config.get("implementation_tools", []))

    # Orchestration tools always pass through
    if tool_name in orchestration_tools:
        return 0, stdin_json

    # Only classify implementation tools
    if tool_name not in implementation_tools:
        return 0, stdin_json

    complexity = classify_complexity(tool_name, tool_input)

    if complexity < threshold:
        advisory = (
            f"[model-router] ADVISORY — Task complexity {complexity:.2f} "
            f"(threshold {threshold:.2f}). Consider delegating to "
            f"{delegation_model} via the delegation pipeline."
        )

        if mode == "enforce":
            return 2, json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        f"[model-router] Task complexity {complexity:.2f} is below "
                        f"threshold {threshold:.2f}. Delegate to {delegation_model} "
                        f"via the delegation pipeline instead of using Opus directly."
                    ),
                }
            )

        # Advisory mode: warn on stderr, pass through
        print(advisory, file=sys.stderr)
        return 0, stdin_json

    # Complex enough for Opus — pass through
    return 0, stdin_json


def main() -> int:
    """CLI entrypoint."""
    stdin_data = sys.stdin.read()
    exit_code, output = run_model_router(stdin_data)
    print(output)  # noqa: T201
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
