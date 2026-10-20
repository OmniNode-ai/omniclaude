# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The selected broker overlay must survive launchd's isolated environment."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LABEL = "ai.omninode.hook-emit-drainer"


@pytest.fixture
def installer(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "omniclaude"
    script = repo / "scripts/install-hook-emit-drainer.sh"
    template = repo / f"scripts/launchd/{LABEL}.plist"
    template.parent.mkdir(parents=True)
    shutil.copy2(ROOT / f"scripts/launchd/{LABEL}.plist", template)
    # Relocate only the literal Brew probes in the fixture. Production still
    # requires the grant-bearing binary; this exercises rendering on Linux CI.
    source = (ROOT / "scripts/install-hook-emit-drainer.sh").read_text()
    for literal in re.findall(r'\[\[ -x "([^"]*python3\.13)" \]\]', source):
        source = source.replace(f'"{literal}"', f'"{sys.executable}"')
    script.write_text(source)
    commands = tmp_path / "bin"
    commands.mkdir()
    for name in ("launchctl", "plutil"):
        command = commands / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    env = os.environ | {
        "HOME": str(tmp_path / "home"),
        "OMNI_HOME": str(tmp_path / "workspace"),
        "PATH": f"{commands}:{os.environ['PATH']}",
    }
    env.pop("ONEX_WORKSPACE_CONFIG_ROOT", None)
    env.pop("ONEX_HOOK_EMIT_PRESERVE_BACKLOG", None)
    return script, env


def run(
    script: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_overlay_survives_supervisor_environment_and_resolves_broker(
    installer: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    script, env = installer
    owner = tmp_path / 'private & "config"'
    overlay = owner / "config/lab/hook_edge_lane.yaml"
    overlay.parent.mkdir(parents=True)
    overlay.write_text(
        'known_lanes:\n  dev:\n    bootstrap_servers: "broker.example:19092"\n'
    )
    alias = tmp_path / "config-alias"
    alias.symlink_to(owner, target_is_directory=True)
    env["ONEX_WORKSPACE_CONFIG_ROOT"] = str(alias)
    env["ONEX_HOOK_EMIT_PRESERVE_BACKLOG"] = "1"

    result = run(script, env, "--dry-run")

    assert result.returncode == 0, result.stderr
    rendered = plistlib.loads(result.stdout[result.stdout.index("<?xml") :].encode())
    daemon_env = rendered["EnvironmentVariables"]
    assert "--preserve-backlog" in rendered["ProgramArguments"]
    assert daemon_env["ONEX_WORKSPACE_CONFIG_ROOT"] == str(owner.resolve())
    # Reproduce launchd: only the rendered environment reaches the resolver,
    # and the workspace's sibling configuration clone has no broker overlay.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
            "import hook_edge_lane as h; "
            "print(h.resolve_bootstrap_servers(h.load_contract(Path(sys.argv[2]))))",
            str(ROOT / "plugins/onex/hooks/lib"),
            str(ROOT / "plugins/onex/hooks/contracts/hook_edge_lane.yaml"),
        ],
        env=daemon_env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "broker.example:19092"
    assert not (Path(env["HOME"]) / "Library/LaunchAgents").exists()


def test_missing_overlay_preserves_previous_agent_before_build(
    installer: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    script, env = installer
    destination = Path(env["HOME"]) / f"Library/LaunchAgents/{LABEL}.plist"
    destination.parent.mkdir(parents=True)
    destination.write_text("previous-plist")
    env["ONEX_WORKSPACE_CONFIG_ROOT"] = str(tmp_path / "missing-config")

    result = run(script, env)

    assert result.returncode != 0
    assert "lacks config/lab/hook_edge_lane.yaml" in result.stderr
    assert destination.read_text() == "previous-plist"


def test_unselected_root_retains_resolver_autodiscovery(
    installer: tuple[Path, dict[str, str]],
) -> None:
    script, env = installer

    result = run(script, env, "--dry-run")

    assert result.returncode == 0, result.stderr
    rendered = plistlib.loads(result.stdout[result.stdout.index("<?xml") :].encode())
    assert "ONEX_WORKSPACE_CONFIG_ROOT" not in rendered["EnvironmentVariables"]
    assert "--preserve-backlog" not in rendered["ProgramArguments"]


def test_invalid_recovery_setting_refuses_install(
    installer: tuple[Path, dict[str, str]],
) -> None:
    script, env = installer
    env["ONEX_HOOK_EMIT_PRESERVE_BACKLOG"] = "yes"

    result = run(script, env)

    assert result.returncode != 0
    assert "must be 0 or 1" in result.stderr


def test_explicit_state_root_is_shared_by_hooks_and_launchd(
    installer: tuple[Path, dict[str, str]],
    tmp_path: Path,
) -> None:
    script, env = installer
    state_root = tmp_path / 'contractor state & "journal"'
    env["ONEX_STATE_DIR"] = str(state_root)
    result = run(script, env, "--dry-run")
    assert result.returncode == 0, result.stderr
    rendered = plistlib.loads(result.stdout[result.stdout.index("<?xml") :].encode())
    assert rendered["EnvironmentVariables"]["ONEX_STATE_DIR"] == str(state_root)
    hook = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; printf "%s" "$ONEX_STATE_DIR"',
            "bash",
            str(ROOT / "plugins/onex/hooks/scripts/onex-paths.sh"),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert hook.returncode == 0, hook.stderr
    assert hook.stdout == rendered["EnvironmentVariables"]["ONEX_STATE_DIR"]
    assert not (Path(env["HOME"]) / "Library/LaunchAgents").exists()


def test_fresh_profile_hook_default_differs_from_drainer_without_explicit_state(
    installer: tuple[Path, dict[str, str]],
) -> None:
    """Onboarding exports OMNIBASE_PATH, so the documented state step is needed."""
    script, env = installer
    env.pop("ONEX_STATE_DIR", None)
    env.pop("XDG_STATE_HOME", None)
    env["OMNIBASE_PATH"] = env.pop("OMNI_HOME")
    result = run(script, env, "--dry-run")
    assert result.returncode == 0, result.stderr
    rendered = plistlib.loads(result.stdout[result.stdout.index("<?xml") :].encode())
    hook = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; printf "%s" "$ONEX_STATE_DIR"',
            "bash",
            str(ROOT / "plugins/onex/hooks/scripts/onex-paths.sh"),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert hook.returncode == 0, hook.stderr
    assert hook.stdout == str(Path(env["HOME"]) / ".local/state/omniclaude")
    # The installer derives its workspace from its checkout, not OMNIBASE_PATH.
    assert rendered["EnvironmentVariables"]["ONEX_STATE_DIR"] == str(
        script.parents[2] / ".onex_state"
    )
