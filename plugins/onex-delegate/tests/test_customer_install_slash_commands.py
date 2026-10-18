# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The customer install adds exactly one slash command: /onex:delegate (OMN-17427).

Why this file exists
--------------------
`test_delegate_only_surface.py` reads the manifests and the plugin tree. It
cannot see what Claude Code itself puts in a customer's command list once the
install has run, and that list is what the customer sees. On 2026-10-17 the
onboarding script installed the full developer tree (about 120 /onex: skills,
most of which need the lab) on a customer-shaped laptop, while every manifest
test stayed green.

This module runs the customer install with the real `claude` binary into a
scratch Claude config (`CLAUDE_CONFIG_DIR`), with this checkout standing in for
the GitHub repository the customer install names, and reads back what Claude Code's
own loader installed: `claude plugin list --json` for the installed plugins and
`claude plugin details` for each plugin's component inventory. A plugin's
slash commands are its skills, named `<plugin>:<skill>`; everything else on the
list is Claude Code's own. Neither read starts a session or calls a model, so
the scratch config needs no login. On the full developer tree the same read
reports 114 skills and 30 hooks.

What it proves, and what it does not
------------------------------------
* The commands the customer path runs are the two below, and the
  onboarding script's customer default is the same plugin from the same
  marketplace; the full developer tree needs its explicit --developer flag.
* After the install, one plugin is installed, read from `plugins/onex-delegate`,
  and its inventory is one skill, `delegate`, and nothing else, so the command
  list is Claude Code's built-ins plus exactly `onex:delegate`.
* `/onex:delegate` resolves to this plugin's delegate skill, whose one command
  is `onex delegate ... --result-only`.

Answering a delegation needs a signed-in Claude Code session and a model; a
scratch config has neither. `test_install_works.py` proves the command the
skill runs works on the declared pins.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
DELEGATE_PLUGIN_DIR = REPO_ROOT / "plugins" / "onex-delegate"
ONBOARDING_SCRIPT = (
    REPO_ROOT / "plugins" / "onex" / "skills" / "_bin" / "lab-onboarding.sh"
)

CUSTOMER_MARKETPLACE = "OmniNode-ai/omniclaude"
CUSTOMER_PLUGIN = "onex@omninode-tools"
DEVELOPER_PLUGIN = "onex@omninode-tools-dev"
DELEGATE_COMMAND = "onex:delegate"

_CLI_TIMEOUT_SECONDS = 180


def _claude() -> str:
    resolved = shutil.which("claude")
    assert resolved is not None, (
        "the claude binary is not on PATH; the plugin-compat-gate CI job installs "
        "the pinned CLAUDE_CODE_VERSION before it runs this file"
    )
    return resolved


def _env(config_dir: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE", "ANTHROPIC")) and k != "PYTHONPATH"
    }
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


def _run(
    argv: list[str], config_dir: Path, cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=_env(config_dir),
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT_SECONDS,
        check=False,
    )


def _installed(config_dir: Path, cwd: Path) -> list[dict]:
    done = _run([_claude(), "plugin", "list", "--json"], config_dir, cwd)
    assert done.returncode == 0, (
        f"claude plugin list failed: {done.stdout}{done.stderr}"
    )
    return json.loads(done.stdout)


_INVENTORY_ROW = re.compile(
    r"^\s+(?P<kind>[A-Za-z][A-Za-z ]*?) \((?P<count>\d+)\)(?:\s+(?P<items>.*))?$"
)


def _inventory(
    plugin_id: str, config_dir: Path, cwd: Path
) -> dict[str, tuple[int, str]]:
    """`claude plugin details` component inventory: kind -> (count, listed names)."""
    done = _run([_claude(), "plugin", "details", plugin_id], config_dir, cwd)
    assert done.returncode == 0, (
        f"claude plugin details failed: {done.stdout}{done.stderr}"
    )
    block = (
        done.stdout.split("Component inventory", 1)[1].strip("\n").split("\n\n", 1)[0]
    )
    inventory: dict[str, tuple[int, str]] = {}
    for line in block.splitlines():
        row = _INVENTORY_ROW.match(line)
        assert row is not None, f"unreadable inventory row {line!r} in:\n{done.stdout}"
        inventory[row["kind"]] = (int(row["count"]), (row["items"] or "").strip())
    return inventory


def _quickstart_commands() -> list[list[str]]:
    """The `claude plugin ...` lines of the customer's first-time install."""
    return [
        ["claude", "plugin", "marketplace", "add", CUSTOMER_MARKETPLACE],
        ["claude", "plugin", "install", CUSTOMER_PLUGIN],
    ]


def test_onboarding_script_defaults_to_the_customer_plugin() -> None:
    text = ONBOARDING_SCRIPT.read_text()
    assert f'CUSTOMER_MARKETPLACE="{CUSTOMER_MARKETPLACE}"' in text
    assert re.search(
        rf"^CUSTOMER_MARKETPLACE=.*WANT_PLUGIN={re.escape(CUSTOMER_PLUGIN)};",
        text,
        re.M,
    )
    assert re.search(
        rf'^\[ "\$DEVELOPER" -eq 1 \] && \{{ WANT_PLUGIN={re.escape(DEVELOPER_PLUGIN)};',
        text,
        re.M,
    ), "the developer plugin tree must be installed only under --developer"
    assert "--developer) DEVELOPER=1 ;;" in text
    assert re.search(r"^RESTART=0; DEVELOPER=0$", text, re.M)


def test_customer_install_adds_only_the_delegate_command(tmp_path: Path) -> None:
    claude = _claude()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    config = tmp_path / "claude-customer"
    config.mkdir()
    assert _installed(config, cwd) == [], "a scratch config must start with no plugins"

    for argv in _quickstart_commands():
        # This checkout stands in for the GitHub repository the customer install names.
        argv = [claude, *argv[1:]]
        if argv[2:4] == ["marketplace", "add"]:
            argv[4] = str(REPO_ROOT)
        done = _run(argv, config, cwd)
        assert done.returncode == 0, (
            f"{shlex.join(argv)} failed: {done.stdout}{done.stderr}"
        )

    installed = _installed(config, cwd)
    assert [(p["id"], p["enabled"]) for p in installed] == [(CUSTOMER_PLUGIN, True)]
    assert (
        Path(installed[0]["readFromFolder"]).resolve() == DELEGATE_PLUGIN_DIR.resolve()
    )

    inventory = _inventory(CUSTOMER_PLUGIN, config, cwd)
    assert inventory.pop("Skills") == (1, "delegate")
    assert inventory and all(count == 0 for count, _ in inventory.values()), inventory
    plugin_name = CUSTOMER_PLUGIN.split("@", 1)[0]
    assert f"{plugin_name}:delegate" == DELEGATE_COMMAND

    skill_md = Path(installed[0]["installPath"]) / "skills" / "delegate" / "SKILL.md"
    assert 'onex delegate "<prompt>" --result-only' in skill_md.read_text()
