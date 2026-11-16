# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23413 AC39 (Amendment 14a): Claude Code delegation registers one hook.

Test that hooks-delegation.v1.json registers one Claude Code hook, the prompt
hook (UserPromptSubmit, pre_tool_use_delegation.sh labelled prompts), with its
history helper on the same event. Verify that re-running install-delegation.sh
--apply over an older six-row install leaves only those owned rows and keeps
unrelated hooks. Subagents always run on Claude: no PreToolUse row is owned.

Failure modes, enumerated before the change:
  T1. The hook set registers anything besides the prompt hook and its helper
      (the subagent hook, cost accounting, session start or session end).
  T2. An upgrade over an older install keeps an owned retired row.
  T3. The upgrade removes or edits a hook or setting onex did not write.
  T4. A second install changes settings.json again (not idempotent).

Delegation: drafted through `onex delegate` run 45bda61d-7562-4da3-a13f-84af540626e2
(Qwen3.8-27B); its two-hook docstring was revised to one hook after Amendment 14a.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_SET = _REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks-delegation.v1.json"
_INSTALLER = _REPO_ROOT / "scripts" / "install-delegation.sh"

_PROMPT_EVENT = "UserPromptSubmit"
_HOOK_SCRIPT = "pre_tool_use_delegation.sh"
# The prompt hook's history helper (Amendment 13, AC33 continuity) rides on the
# prompt event; operator 2026-11-17 (option A): part of the prompt hook.
_HISTORY_HELPER = "delegation_hook_runner.py --history-only"
_RETIRED = (
    "ONEX_DELEGATION_HOOK=subagents",
    "session-start.sh",
    "session-end.sh",
    "post_tool_use_cost_accounting.sh",
)
_EXPECTED_KINDS = [f"{_PROMPT_EVENT}:prompt-history", f"{_PROMPT_EVENT}:prompts"]

# A hook another tool wrote: the upgrade must leave it exactly as it is (T3).
_UNRELATED = {
    "matcher": "^Bash$",
    "hooks": [{"type": "command", "command": "/usr/local/bin/someone-elses-guard.sh"}],
}


def _hooks(data: dict) -> list[tuple[str, str, str]]:
    """(event, matcher, command) for every hook row in a hooks block."""
    return [
        (event, group.get("matcher", ""), hook["command"])
        for event, groups in data.get("hooks", {}).items()
        for group in groups
        for hook in group.get("hooks", [])
    ]


def _hook_kind(event: str, matcher: str, command: str) -> str:
    if _HISTORY_HELPER in command:
        return f"{event}:prompt-history"
    if "ONEX_DELEGATION_HOOK=prompts" in command and _HOOK_SCRIPT in command:
        return f"{event}:prompts"
    return f"{event}{matcher}:OTHER {command}"


def _owned(settings: dict, root: Path) -> list[tuple[str, str, str]]:
    return [row for row in _hooks(settings) if f"{root}/" in row[2]]


def _run_installer(home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(exist_ok=True)
    claude = stub_bin / "claude"
    claude.write_text('#!/usr/bin/env bash\necho "claude 1.0.0-stub"\n')
    claude.chmod(0o755)
    env = {
        "HOME": str(home),
        "PATH": f"{stub_bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "TMPDIR": str(tmp_path),
    }
    proc = subprocess.run(
        ["bash", str(_INSTALLER), "--apply", "--skip-pip", "--python", sys.executable],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _older_install(home: Path) -> dict:
    """Settings an older `onex delegation on` left: six owned rows plus one unrelated."""
    plugin = home / ".omninode" / "delegation" / "plugin" / "plugins" / "onex" / "hooks"
    scripts = plugin / "scripts"
    py = "PLUGIN_PYTHON_BIN=/usr/bin/python3"
    sub = "^(Agent|Task)$"
    return {
        "model": "keep-me",
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{py} ONEX_DELEGATION_HOOK=prompts {scripts}/{_HOOK_SCRIPT}",
                            "timeout": 300,
                        }
                    ]
                },
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"/usr/bin/python3 {plugin}/lib/{_HISTORY_HELPER} 2>/dev/null || true",
                            "timeout": 10,
                        }
                    ]
                },
            ],
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{py} {scripts}/session-start.sh",
                        }
                    ]
                }
            ],
            "SessionEnd": [
                {
                    "hooks": [
                        {"type": "command", "command": f"{py} {scripts}/session-end.sh"}
                    ]
                }
            ],
            "PreToolUse": [
                _UNRELATED,
                {
                    "matcher": sub,
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{py} ONEX_DELEGATION_HOOK=subagents {scripts}/{_HOOK_SCRIPT}",
                            "timeout": 300,
                        }
                    ],
                },
            ],
            "PostToolUse": [
                {
                    "matcher": sub,
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{py} {scripts}/post_tool_use_cost_accounting.sh",
                        }
                    ],
                }
            ],
        },
    }


@pytest.mark.unit
def test_hook_set_registers_only_the_prompt_hook() -> None:
    """T1: the hook set is the prompt hook and its history helper, nothing else."""
    rows = _hooks(json.loads(_HOOK_SET.read_text()))
    assert sorted(_hook_kind(*row) for row in rows) == _EXPECTED_KINDS, rows


@pytest.mark.unit
def test_upgrade_leaves_only_the_prompt_hook_and_keeps_unrelated(
    tmp_path: Path,
) -> None:
    """T2, T3: an upgrade drops every retired owned row and touches nothing else."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings_path = home / ".claude" / "settings.json"
    settings_path.write_text(json.dumps(_older_install(home), indent=2) + "\n")
    root = home / ".omninode" / "delegation"

    _run_installer(home, tmp_path)

    settings = json.loads(settings_path.read_text())
    owned = _owned(settings, root)
    assert sorted(_hook_kind(*row) for row in owned) == _EXPECTED_KINDS, owned
    assert not any(name in cmd for _, _, cmd in owned for name in _RETIRED), owned
    assert settings.get("model") == "keep-me"
    assert settings["hooks"].get("PreToolUse") == [_UNRELATED], settings["hooks"].get(
        "PreToolUse"
    )
    assert "PostToolUse" not in settings["hooks"]
    assert (
        "SessionStart" not in settings["hooks"]
        and "SessionEnd" not in settings["hooks"]
    )


@pytest.mark.unit
def test_second_install_changes_nothing(tmp_path: Path) -> None:
    """T4: a second install leaves settings.json byte for byte the same."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    _run_installer(home, tmp_path)
    settings_path = home / ".claude" / "settings.json"
    first = settings_path.read_bytes()
    _run_installer(home, tmp_path)
    assert settings_path.read_bytes() == first
