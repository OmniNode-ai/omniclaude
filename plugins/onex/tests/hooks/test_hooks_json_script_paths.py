# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-8849: CI test that every command path in hooks.json resolves to an existing executable.

Prevents broken hook registrations from silently escaping into production.
"""

import json
import os
import re
from pathlib import Path

HOOKS_JSON_PATH = Path(__file__).parents[2] / "hooks" / "hooks.json"
PLUGIN_ROOT = Path(__file__).parents[2]

COMMAND_VAR = "${CLAUDE_PLUGIN_ROOT}"


def _resolve_path(command: str) -> Path | None:
    """Extract the script path from a hook command string.

    Handles:
    - "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/foo.sh"
    - "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/foo.sh"
    - absolute paths
    """
    # Strip leading 'bash ' or 'sh ' wrapper if present
    stripped = re.sub(r"^(bash|sh)\s+", "", command.strip())

    if COMMAND_VAR in stripped:
        relative = stripped.replace(COMMAND_VAR + "/", "")
        return PLUGIN_ROOT / relative

    path = Path(stripped)
    if path.is_absolute():
        return path

    # Relative path — resolve against plugin root
    return PLUGIN_ROOT / stripped


def _collect_hook_entries(hooks_data: dict) -> list[dict]:
    """Walk the hooks structure and yield (event, matcher, command) tuples."""
    entries = []
    for event_name, event_hooks in hooks_data.get("hooks", {}).items():
        for hook_group in event_hooks:
            matcher = hook_group.get("matcher", "<no-matcher>")
            for hook in hook_group.get("hooks", []):
                command = hook.get("command", "")
                if command:
                    entries.append(
                        {
                            "event": event_name,
                            "matcher": matcher,
                            "command": command,
                        }
                    )
    return entries


def test_hooks_json_valid_json() -> None:
    """hooks.json must be parseable JSON."""
    assert HOOKS_JSON_PATH.exists(), f"hooks.json not found at {HOOKS_JSON_PATH}"
    with open(HOOKS_JSON_PATH) as f:
        data = json.load(f)
    assert "hooks" in data, "hooks.json missing top-level 'hooks' key"


def test_hooks_json_script_paths() -> None:
    """Every command path in hooks.json must exist and be executable."""
    with open(HOOKS_JSON_PATH) as f:
        data = json.load(f)

    entries = _collect_hook_entries(data)
    assert entries, "No hook entries found — hooks.json may be empty"

    broken: list[str] = []
    report_lines: list[str] = []

    for entry in entries:
        event = entry["event"]
        matcher = entry["matcher"]
        command = entry["command"]
        resolved = _resolve_path(command)

        exists = resolved is not None and resolved.exists() and resolved.is_file()
        executable = exists and resolved is not None and os.access(resolved, os.X_OK)

        status = "OK" if (exists and executable) else "BROKEN"
        report_lines.append(
            f"  [{status}] event={event} matcher={matcher}\n"
            f"           command={command}\n"
            f"           resolved={resolved}\n"
            f"           exists={exists} executable={executable}"
        )

        if not (exists and executable):
            broken.append(
                f"event={event} matcher={matcher} command={command} resolved={resolved} "
                f"exists={exists} executable={executable}"
            )

    report = "\n".join(report_lines)
    assert not broken, (
        f"hooks.json has {len(broken)} broken registration(s):\n\n"
        + "\n".join(f"  - {b}" for b in broken)
        + f"\n\nFull report:\n{report}"
    )
