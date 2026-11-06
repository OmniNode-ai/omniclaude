# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The capture-only settings file a headless lab worker loads (OMN-19998).

A landing worker on a lab host runs ``claude -p`` with the omni plugin and none of the onex
plugin's hooks, so none of its tool calls reached the hook-event table: h051 0 of 279 and
h053 0 of 262 tool calls in one measured hour, against 99.6 percent on the operator Mac. Loading
the whole onex plugin would add its guards and mirrors to workers by accident. This file is the
smallest route: ``--settings plugins/onex/hooks/capture_only_settings.json`` registers only the
capture hook, on the same events and matchers ``hooks.json`` gives it, and runs it from the
registry root the worker already exports.

The file is derived from ``hooks.json``, never maintained beside it. These tests rebuild it from
``hooks.json`` and compare, so a capture event added to the plugin without the file is a red test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_HOOKS_DIR = Path(__file__).parents[3] / "plugins" / "onex" / "hooks"
_SETTINGS = _HOOKS_DIR / "capture_only_settings.json"
_CAPTURE_SCRIPT = "claude_hook_capture.sh"
_SCRIPT_UNDER_ROOT = f"omniclaude/plugins/onex/hooks/scripts/{_CAPTURE_SCRIPT}"

# One command for every event. The script is looked up under the worker's registry root; a root
# without the clone, or an unset root, makes the hook drain stdin and exit 0. The session is put
# in the "full" mode explicitly because a worker's working directory is not under the registry
# root, which the mode resolver reads as "lite" and journals nothing.
_COMMAND = (
    'bash -c \'[ -n "$0" ] && [ -f "$0" ] && OMNICLAUDE_MODE=full exec bash "$0" '
    "|| { cat >/dev/null; exit 0; }' \"${OMNI_HOME:-/nonexistent}/"
    + _SCRIPT_UNDER_ROOT
    + '"'
)


def build_capture_only_settings(hooks_json: dict) -> dict:
    """The capture registrations of ``hooks.json``, as a Claude Code settings file."""
    out: dict[str, list[dict]] = {}
    for event, groups in hooks_json["hooks"].items():
        for group in groups:
            if not any(
                str(hook.get("command", "")).endswith(_CAPTURE_SCRIPT)
                for hook in group["hooks"]
            ):
                continue
            entry: dict = {k: v for k, v in group.items() if k != "hooks"}
            entry["hooks"] = [{"type": "command", "command": _COMMAND}]
            out.setdefault(event, []).append(entry)
    return {"hooks": out}


def _hooks_json() -> dict:
    return json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))


def test_the_committed_file_is_what_hooks_json_derives() -> None:
    assert json.loads(
        _SETTINGS.read_text(encoding="utf-8")
    ) == build_capture_only_settings(_hooks_json()), (
        "regenerate plugins/onex/hooks/capture_only_settings.json from hooks.json"
    )


def test_it_registers_only_the_capture_hook() -> None:
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    commands = {
        hook["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    }
    assert commands == {_COMMAND}
    assert set(settings) == {"hooks"}, (
        "the file carries hooks only: no env, no permissions"
    )


def test_every_capture_event_of_the_plugin_is_in_the_file() -> None:
    plugin_events = {
        event
        for event, groups in _hooks_json()["hooks"].items()
        for group in groups
        for hook in group["hooks"]
        if str(hook.get("command", "")).endswith(_CAPTURE_SCRIPT)
    }
    assert plugin_events
    assert plugin_events == set(
        json.loads(_SETTINGS.read_text(encoding="utf-8"))["hooks"]
    )


def test_a_capture_registration_the_file_lacks_is_caught() -> None:
    """The failing control: a capture event added to the plugin makes the derivation differ."""
    hooks_json = _hooks_json()
    hooks_json["hooks"]["BrandNewEvent"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/" + _CAPTURE_SCRIPT,
                }
            ]
        }
    ]
    assert build_capture_only_settings(hooks_json) != json.loads(
        _SETTINGS.read_text(encoding="utf-8")
    )
