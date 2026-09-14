# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression coverage for the hook-drainer launch environment."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _prepare_installer(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    """The resident drainer must not fall back to stale Brew site packages."""
    repo_root = tmp_path / "omniclaude"
    installer = repo_root / "scripts" / "install-hook-emit-drainer.sh"
    plist = repo_root / "scripts" / "launchd" / "ai.omninode.hook-emit-drainer.plist"
    builder = (
        repo_root / "plugins" / "onex" / "hooks" / "scripts" / "ensure-plugin-venv.sh"
    )
    for source, destination in (
        (_REPO_ROOT / "scripts" / "install-hook-emit-drainer.sh", installer),
        (
            _REPO_ROOT / "scripts" / "launchd" / "ai.omninode.hook-emit-drainer.plist",
            plist,
        ),
    ):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "launchctl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$*" >> "${FAKE_LAUNCHCTL_LOG}"\n'
        'command="${1:-}"\n'
        'if [[ "$command" == print && "${FAKE_WAS_LOADED:-0}" != 1 ]]; then exit 1; fi\n'
        'if [[ "$command" == bootstrap || "$command" == enable ]]; then\n'
        '  count_file="${FAKE_STATE}/${command}"\n'
        '  count=0; [[ -f "$count_file" ]] && count="$(<"$count_file")"\n'
        '  count=$((count + 1)); printf "%s" "$count" > "$count_file"\n'
        '  if [[ "${FAKE_FAIL:-}" == "$command" && "$count" == 1 ]]; then exit 1; fi\n'
        "fi\n",
    )
    _write_executable(
        fake_bin / "cp",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${FAKE_FAIL_CP_DEST:-}" == "${2:-}" ]]; then exit 1; fi\n'
        '/bin/cp "$@"\n',
    )
    _write_executable(fake_bin / "plutil", "#!/usr/bin/env bash\nexit 0\n")

    home = tmp_path / "home"
    plugin_data = tmp_path / "plugin-data"
    env = os.environ | {
        "CLAUDE_PLUGIN_DATA": str(plugin_data),
        "HOME": str(home),
        "OMNI_HOME": str(tmp_path / "omni-home"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_LAUNCHCTL_LOG": str(tmp_path / "launchctl.log"),
        "FAKE_STATE": str(tmp_path / "state"),
    }
    Path(env["FAKE_STATE"]).mkdir()
    return installer, env, builder, home


def _write_builder(builder: Path, *, verify_exit: int = 0) -> None:
    _write_executable(
        builder,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'mkdir -p "${CLAUDE_PLUGIN_DATA}"\n'
        'printf "%s:%s\\n" "${1:-build}" "${ONEX_BREW_PYTHON:-}" '
        '>> "${CLAUDE_PLUGIN_DATA}/builder-ran"\n'
        f'[[ "${{1:-}}" == --verify ]] && exit {verify_exit}\n'
        'mkdir -p "${CLAUDE_PLUGIN_DATA}/.venv/bin"\n',
    )


def _run(
    installer: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(installer), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installer_renders_only_a_builder_verified_venv(tmp_path: Path) -> None:
    """Installer relies on the builder's exact lock/Brew freshness check."""
    installer, env, builder, home = _prepare_installer(tmp_path)
    _write_builder(builder)

    result = _run(installer, env)

    assert result.returncode == 0, result.stderr
    plugin_data = Path(env["CLAUDE_PLUGIN_DATA"])
    build_lines = (plugin_data / "builder-ran").read_text(encoding="utf-8").splitlines()
    assert build_lines[0].startswith("build:")
    assert build_lines[1] == "--verify:" + build_lines[0].removeprefix("build:")

    rendered = (
        home / "Library" / "LaunchAgents" / "ai.omninode.hook-emit-drainer.plist"
    ).read_text(encoding="utf-8")
    assert str(plugin_data / ".venv" / "bin" / "python3") in rendered


def test_installer_rejects_unverified_or_in_progress_builder_result(
    tmp_path: Path,
) -> None:
    """A concurrent or stale builder result may never replace the loaded agent."""
    installer, env, builder, home = _prepare_installer(tmp_path)
    _write_builder(builder, verify_exit=75)
    destination = (
        home / "Library" / "LaunchAgents" / "ai.omninode.hook-emit-drainer.plist"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text("previous-plist", encoding="utf-8")

    result = _run(installer, env)

    assert result.returncode != 0
    assert destination.read_text(encoding="utf-8") == "previous-plist"
    assert not Path(env["FAKE_LAUNCHCTL_LOG"]).exists()


@pytest.mark.parametrize("failure", ["bootstrap", "enable"])
def test_installer_restores_previous_loaded_service_after_activation_failure(
    tmp_path: Path, failure: str
) -> None:
    """A failed activation restores both the prior plist and loaded service."""
    installer, env, builder, home = _prepare_installer(tmp_path)
    _write_builder(builder)
    env |= {"FAKE_WAS_LOADED": "1", "FAKE_FAIL": failure}
    destination = (
        home / "Library" / "LaunchAgents" / "ai.omninode.hook-emit-drainer.plist"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text("previous-plist", encoding="utf-8")

    result = _run(installer, env)

    assert result.returncode != 0
    assert destination.read_text(encoding="utf-8") == "previous-plist"
    calls = Path(env["FAKE_LAUNCHCTL_LOG"]).read_text(encoding="utf-8").splitlines()
    gui_domain = f"gui/{os.getuid()}"
    assert calls.count("bootstrap " + gui_domain + " " + str(destination)) == 2
    expected_enable_calls = 1 if failure == "bootstrap" else 2
    assert (
        calls.count("enable " + gui_domain + "/ai.omninode.hook-emit-drainer")
        == expected_enable_calls
    )


def test_installer_restores_previous_plist_when_copy_fails(tmp_path: Path) -> None:
    """A partial plist copy does not disturb the resident service."""
    installer, env, builder, home = _prepare_installer(tmp_path)
    _write_builder(builder)
    destination = (
        home / "Library" / "LaunchAgents" / "ai.omninode.hook-emit-drainer.plist"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text("previous-plist", encoding="utf-8")
    env |= {"FAKE_WAS_LOADED": "1", "FAKE_FAIL_CP_DEST": str(destination)}

    result = _run(installer, env)

    assert result.returncode != 0
    assert destination.read_text(encoding="utf-8") == "previous-plist"
    calls = Path(env["FAKE_LAUNCHCTL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert calls == [f"print gui/{os.getuid()}/ai.omninode.hook-emit-drainer"]


def test_dry_run_does_not_build_or_mutate_launch_agent(tmp_path: Path) -> None:
    installer, env, builder, home = _prepare_installer(tmp_path)
    _write_builder(builder)

    result = _run(installer, env, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert not (Path(env["CLAUDE_PLUGIN_DATA"]) / "builder-ran").exists()
    assert not (home / "Library" / "LaunchAgents").exists()
    assert not Path(env["FAKE_LAUNCHCTL_LOG"]).exists()


def test_builder_failed_sync_preserves_previous_usable_venv(tmp_path: Path) -> None:
    """A failed candidate build restores the original venv in its final path."""
    workspace_root = tmp_path / "workspace"
    project = workspace_root / "omniclaude"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'test'\n", encoding="utf-8"
    )
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    plugin_root = tmp_path / "plugin"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(
        '{"version": "test"}\n', encoding="utf-8"
    )
    builder = plugin_root / "ensure-plugin-venv.sh"
    shutil.copy2(
        _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "ensure-plugin-venv.sh",
        builder,
    )
    builder.chmod(builder.stat().st_mode | stat.S_IXUSR)
    plugin_data = tmp_path / "plugin-data"
    previous_python = plugin_data / ".venv" / "bin" / "python3"
    _write_executable(previous_python, "#!/usr/bin/env bash\necho previous\n")
    previous_marker = plugin_data / ".venv" / ".built-from"
    previous_marker.write_text("stale-marker", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "uv",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "$1" == venv ]]; then\n'
        '  destination="${@: -1}"; mkdir -p "${destination}/bin"\n'
        '  printf candidate > "${destination}/bin/python3"; exit 0\n'
        "fi\n"
        '[[ "$1" == sync ]] && exit 2\n'
        "exit 1\n",
    )
    env = os.environ | {
        "OMNI_HOME": str(workspace_root),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PLUGIN_DATA": str(plugin_data),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash", str(builder)], env=env, capture_output=True, text=True, check=False
    )

    assert result.returncode != 0
    assert (
        previous_python.read_text(encoding="utf-8")
        == "#!/usr/bin/env bash\necho previous\n"
    )
    assert previous_marker.read_text(encoding="utf-8") == "stale-marker"

    spoofed = env | {
        "ONEX_PLUGIN_VENV_LOCK_HELD": "1",
        "ONEX_PLUGIN_VENV_LOCK_FD": "0",
    }
    spoofed_result = subprocess.run(
        ["bash", str(builder)], env=spoofed, capture_output=True, text=True, check=False
    )
    assert spoofed_result.returncode == 1
    assert "requires the inherited advisory lock" in spoofed_result.stderr


def test_builder_lock_survives_killed_wrapper_until_child_stops(tmp_path: Path) -> None:
    """A child build retains the advisory lock after its wrapper is killed."""
    workspace_root = tmp_path / "workspace"
    project = workspace_root / "omniclaude"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'test'\n", encoding="utf-8"
    )
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    plugin_root = tmp_path / "plugin"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(
        '{"version": "test"}\n', encoding="utf-8"
    )
    builder = plugin_root / "ensure-plugin-venv.sh"
    shutil.copy2(
        _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "ensure-plugin-venv.sh",
        builder,
    )
    builder.chmod(builder.stat().st_mode | stat.S_IXUSR)
    plugin_data = tmp_path / "plugin-data"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    started = tmp_path / "build-started"
    release = tmp_path / "release-build"
    _write_executable(
        fake_bin / "uv",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "$1" == venv ]]; then\n'
        '  : > "${BUILD_STARTED}"\n'
        '  while [[ ! -e "${BUILD_RELEASE}" ]]; do sleep 0.02; done\n'
        '  destination="${@: -1}"; mkdir -p "${destination}/bin"; exit 0\n'
        "fi\n"
        '[[ "$1" == sync ]] && exit 2\n'
        "exit 1\n",
    )
    env = os.environ | {
        "OMNI_HOME": str(workspace_root),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PLUGIN_DATA": str(plugin_data),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "BUILD_STARTED": str(started),
        "BUILD_RELEASE": str(release),
    }

    lock_parent = subprocess.Popen(
        ["bash", str(builder)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert started.exists(), "builder child did not reach the mutation barrier"
    lock_parent.kill()
    lock_parent.wait(timeout=5)

    competitor = subprocess.run(
        ["bash", str(builder)], env=env, capture_output=True, text=True, check=False
    )
    assert competitor.returncode == 75

    release.touch()
    deadline = time.monotonic() + 5
    replacement: subprocess.CompletedProcess[str] | None = None
    while time.monotonic() < deadline:
        replacement = subprocess.run(
            ["bash", str(builder)], env=env, capture_output=True, text=True, check=False
        )
        if replacement.returncode != 75:
            break
        time.sleep(0.02)

    assert replacement is not None
    assert replacement.returncode != 75


def test_builder_and_installer_share_both_literal_brew_paths() -> None:
    """Intel and Apple Silicon use the selected Brew interpreter contract."""
    builder = (
        _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "ensure-plugin-venv.sh"
    ).read_text(encoding="utf-8")
    installer = (_REPO_ROOT / "scripts" / "install-hook-emit-drainer.sh").read_text(
        encoding="utf-8"
    )
    assert 'export ONEX_BREW_PYTHON="${BREW_PYTHON}"' in installer
