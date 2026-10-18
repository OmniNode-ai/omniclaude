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
the GitHub repository the quickstart names, and reads the command list from the
`init` record of `claude -p --output-format stream-json`. That record is emitted
before any authentication, so the scratch config needs no login and no network.
The built-ins are measured the same way on an empty scratch config, so the test
holds whatever built-in set the pinned Claude Code version ships.

What it proves, and what it does not
------------------------------------
* The commands the customer path runs are the public quickstart's, and the
  onboarding script's customer default is the same plugin from the same
  marketplace; the full developer tree needs its explicit --developer flag.
* After the install, the command list is the built-ins plus exactly
  `onex:delegate`, served by one plugin read from `plugins/onex-delegate`.
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
README = REPO_ROOT / "README.md"
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


def _init_record(config_dir: Path, cwd: Path) -> dict:
    """The session `init` record: slash commands, skills and plugins."""
    result = _run(
        [
            _claude(),
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            "1",
            "--strict-mcp-config",
            "--setting-sources",
            "user",
            "Reply with: ok",
        ],
        config_dir,
        cwd,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        record = json.loads(line)
        if record.get("type") == "system" and record.get("subtype") == "init":
            return record
    raise AssertionError(
        f"claude -p printed no init record (exit {result.returncode}); "
        f"stderr: {result.stderr[-2000:]}"
    )


def _quickstart_commands() -> list[list[str]]:
    """The `claude plugin ...` lines of the README's first-time install block."""
    text = README.read_text()
    block = (
        text.split("### Plugin Install", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
    )
    return [
        shlex.split(line)
        for line in block.splitlines()
        if line.strip().startswith("claude plugin ")
    ]


def test_quickstart_is_the_customer_install() -> None:
    assert _quickstart_commands() == [
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

    empty = tmp_path / "claude-empty"
    empty.mkdir()
    builtins = set(_init_record(empty, cwd)["slash_commands"])
    assert builtins, "an empty scratch config listed no built-in commands"
    assert DELEGATE_COMMAND not in builtins

    customer = tmp_path / "claude-customer"
    customer.mkdir()
    for argv in _quickstart_commands():
        # This checkout stands in for the GitHub repository the quickstart names.
        argv = [claude, *argv[1:]]
        if argv[2:4] == ["marketplace", "add"]:
            argv[4] = str(REPO_ROOT)
        done = _run(argv, customer, cwd)
        assert done.returncode == 0, (
            f"{shlex.join(argv)} failed: {done.stdout}{done.stderr}"
        )

    record = _init_record(customer, cwd)
    commands = set(record["slash_commands"])
    assert builtins <= commands
    assert commands - builtins == {DELEGATE_COMMAND}

    installed = [p for p in record["plugins"] if p.get("path") != "builtin"]
    assert [p["source"] for p in installed] == [CUSTOMER_PLUGIN]
    assert Path(installed[0]["path"]).resolve() == DELEGATE_PLUGIN_DIR.resolve()

    skills = [s for s in record.get("skills", []) if ":" in s]
    assert skills == [DELEGATE_COMMAND]
    skill_md = Path(installed[0]["path"]) / "skills" / "delegate" / "SKILL.md"
    assert 'onex delegate "<prompt>" --result-only' in skill_md.read_text()
