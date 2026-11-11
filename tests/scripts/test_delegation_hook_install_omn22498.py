# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegation hook set installs once, idempotently (OMN-22498 AC2).

Two ``install-delegation.sh --apply`` runs over a scratch HOME whose
settings.json already holds the OMN-23413 gateway groups, an unrelated user
hook and an entry an earlier installer wrote.

Failure modes:
  F1. The second run changes settings.json at all.
  F2. More than one legacy delegation PreToolUse Agent|Task entry remains.
  F3. A gateway group (UserPromptSubmit with no matcher, or PreToolUse
      ^(Agent|Task)$, each one command running the omnimarket cli_gateway
      module) is dropped or altered by either run.
  F4. An entry an earlier installer wrote (the old hook-scripts/ copy, which
      could not run) survives beside the new one.
  F5. An unrelated user hook is dropped or moved.
"""

from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "scripts" / "install-delegation.sh"
_GATEWAY_MODULE = "omnimarket.nodes.node_claude_code_binding_install_effect.cli_gateway"


def _gateway_hook(python: str) -> dict[str, Any]:
    return {
        "type": "command",
        "command": shlex.join([python, "-m", _GATEWAY_MODULE, "hook"]),
        "timeout": 30,
        "onFailure": "block",
    }


def _seed_settings(home: Path) -> dict[str, Any]:
    python = "/opt/py with space/bin/python3"  # the gateway's python may hold spaces
    legacy = f"{home}/.omninode/delegation/hook-scripts/pre_tool_use_delegation.sh"
    settings = {
        "model": "opus",
        "hooks": {
            "UserPromptSubmit": [{"hooks": [_gateway_hook(python)]}],
            "PreToolUse": [
                {"matcher": "^(Agent|Task)$", "hooks": [_gateway_hook(python)]},
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "/usr/local/bin/my-own-guard"}
                    ],
                },
                {
                    "matcher": "^(Agent|Task)$",
                    "hooks": [{"type": "command", "command": legacy}],
                },
            ],
        },
    }
    path = home / ".claude" / "settings.json"
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return settings


def _apply(tmp_path: Path, home: Path) -> None:
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


def _is_gateway(hook: dict[str, Any]) -> bool:
    argv = shlex.split(hook.get("command", ""))
    return argv[1:] == ["-m", _GATEWAY_MODULE, "hook"]


def _gateway_groups(settings: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (event, group)
        for event, groups in settings.get("hooks", {}).items()
        for group in groups
        if any(_is_gateway(h) for h in group.get("hooks", []))
    ]


def _commands(settings: dict[str, Any], event: str) -> list[str]:
    return [
        h["command"]
        for g in settings.get("hooks", {}).get(event, [])
        for h in g.get("hooks", [])
    ]


@pytest.mark.unit
def test_delegation_hook_install_detector_sees_a_dropped_gateway_group() -> None:
    """Positive control: an installer that replaced hooks wholesale is caught."""
    seeded = _seed_settings_dict()
    wholesale = copy.deepcopy(seeded)
    wholesale["hooks"]["UserPromptSubmit"] = []
    assert len(_gateway_groups(seeded)) == 2
    assert len(_gateway_groups(wholesale)) == 1


def _seed_settings_dict() -> dict[str, Any]:
    python = "/opt/py with space/bin/python3"
    return {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [_gateway_hook(python)]}],
            "PreToolUse": [
                {"matcher": "^(Agent|Task)$", "hooks": [_gateway_hook(python)]}
            ],
        }
    }


@pytest.mark.unit
def test_delegation_hook_install_twice_is_byte_identical_and_keeps_other_rows(
    tmp_path: Path,
) -> None:
    """F1-F5 over two real installer runs."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    seeded = _seed_settings(home)
    path = home / ".claude" / "settings.json"

    _apply(tmp_path, home)
    first = path.read_bytes()
    _apply(tmp_path, home)
    second = path.read_bytes()
    assert second == first, "second --apply changed settings.json"  # F1

    settings = json.loads(second)
    pre = _commands(settings, "PreToolUse")
    delegation = [c for c in pre if "pre_tool_use_delegation.sh" in c]
    assert len(delegation) == 1, delegation  # F2
    assert "/hook-scripts/" not in delegation[0], delegation  # F4

    assert _gateway_groups(settings) == _gateway_groups(seeded)  # F3
    assert "/usr/local/bin/my-own-guard" in pre  # F5
    assert settings["model"] == "opus"
