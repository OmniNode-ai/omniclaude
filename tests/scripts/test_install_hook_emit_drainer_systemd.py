# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The installer has a Linux branch: a systemd --user unit. [OMN-20309]

The hook-emit drainer shipped only as a launchd plist. On the Linux lab host
nothing drained the journal: 1,064 records were queued when
the alert fired at 09:20 ET and the drainer reported no state, because no
drainer existed there to report one.

The supervisor is chosen by what the host has: ``launchctl`` on PATH means
launchd, otherwise ``systemctl`` means systemd. These tests put a stub
``systemctl`` on PATH and no ``launchctl``, so they drive the real installer
without a real systemd, root, or brew python, and run on an ordinary Linux
runner.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UNIT = "ai.omninode.hook-emit-drainer.service"
_SYSTEMD_TEMPLATE = _REPO_ROOT / "scripts" / "systemd" / _UNIT

pytestmark = pytest.mark.skipif(
    shutil.which("launchctl") is not None,
    reason="a host with launchctl takes the launchd branch",
)


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _prepare(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    """Installer copy, a stub systemctl that logs its argv, and a fake OMNI_HOME.

    Returns the installer, the environment, the systemctl call log, and the
    per-user unit path the installer must write.
    """
    workspace = tmp_path / "workspace"
    repo_root = workspace / "omniclaude"
    installer = repo_root / "scripts" / "install-hook-emit-drainer.sh"
    installer.parent.mkdir(parents=True)
    shutil.copy2(_REPO_ROOT / "scripts" / "install-hook-emit-drainer.sh", installer)
    template = repo_root / "scripts" / "systemd" / _UNIT
    template.parent.mkdir(parents=True)
    shutil.copy2(_SYSTEMD_TEMPLATE, template)

    # The omniclaude project venv is the Linux interpreter. The stub accepts
    # the installer's import probe so no real omnibase_infra is needed.
    _write_executable(
        repo_root / ".venv" / "bin" / "python3", "#!/usr/bin/env bash\nexit 0\n"
    )

    calls = tmp_path / "systemctl.calls"
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "systemctl",
        f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\nexit 0\n',
    )
    # No loginctl or systemd-analyze stub: the installer must tolerate a host
    # without them rather than fail the install.

    home = tmp_path / "home"
    home.mkdir()
    state = workspace / ".onex_state"
    (state / "hook_emit_journal").mkdir(parents=True)
    env = {
        "HOME": str(home),
        "OMNI_HOME": str(workspace),
        "ONEX_STATE_DIR": str(state),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
    }
    return installer, env, calls, home / ".config" / "systemd" / "user" / _UNIT


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


def test_template_is_a_user_unit_that_restarts_forever() -> None:
    text = _SYSTEMD_TEMPLATE.read_text(encoding="utf-8")
    assert "Restart=always" in text, "a drainer that exits must come back (KeepAlive)"
    assert "StartLimitIntervalSec=0" in text, (
        "a fast-failing drainer must never be abandoned"
    )
    assert "WantedBy=default.target" in text, "a user unit hangs off default.target"
    assert "multi-user.target" not in text, "multi-user.target is a system unit"
    assert "\nUser=" not in text, "a user unit runs as the user; User= needs root"
    for token in ("__OMNI_HOME__", "__PYTHON__"):
        assert token in text


def test_dry_run_renders_without_touching_the_host(tmp_path: Path) -> None:
    installer, env, calls, unit = _prepare(tmp_path)

    result = _run(installer, env, "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "__OMNI_HOME__" not in result.stdout and "__PYTHON__" not in result.stdout
    workspace = env["OMNI_HOME"]
    assert (
        f"ExecStart={workspace}/omniclaude/.venv/bin/python3 "
        f"{workspace}/omniclaude/plugins/onex/hooks/lib/hook_emit_drainer.py"
    ) in result.stdout
    assert not unit.exists(), "--dry-run must not install"
    assert not calls.exists(), "--dry-run must not call systemctl"


def test_install_writes_a_user_unit_and_starts_it_without_root(tmp_path: Path) -> None:
    installer, env, calls, unit = _prepare(tmp_path)

    result = _run(installer, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert unit.is_file()
    assert "__OMNI_HOME__" not in unit.read_text(encoding="utf-8")
    argv = calls.read_text(encoding="utf-8").splitlines()
    assert "--user daemon-reload" in argv
    assert f"--user enable --now {_UNIT}" in argv
    assert all(line.startswith("--user ") for line in argv), (
        f"every systemctl call must be --user, so no root is needed: {argv}"
    )


def test_install_refuses_when_the_interpreter_is_missing(tmp_path: Path) -> None:
    installer, env, calls, unit = _prepare(tmp_path)
    (Path(env["OMNI_HOME"]) / "omniclaude" / ".venv" / "bin" / "python3").unlink()

    result = _run(installer, env)

    assert result.returncode != 0
    assert "uv sync" in result.stdout + result.stderr, "name the repair"
    assert not unit.exists()
    assert not calls.exists()


def test_uninstall_stops_and_removes_the_unit(tmp_path: Path) -> None:
    installer, env, calls, unit = _prepare(tmp_path)
    assert _run(installer, env).returncode == 0
    calls.unlink()

    result = _run(installer, env, "--uninstall")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not unit.exists()
    argv = calls.read_text(encoding="utf-8").splitlines()
    assert f"--user disable --now {_UNIT}" in argv


def test_status_reports_the_queue_depth_and_the_unit_state(tmp_path: Path) -> None:
    installer, env, _calls, _unit = _prepare(tmp_path)
    assert _run(installer, env).returncode == 0
    journal = Path(env["ONEX_STATE_DIR"]) / "hook_emit_journal"
    for index in range(3):
        (journal / f"{index:020d}_x.json").write_text("{}", encoding="utf-8")
    spool = Path(env["ONEX_STATE_DIR"]) / "emit_spool"
    spool.mkdir()
    (spool / "a.json").write_text("{}", encoding="utf-8")

    result = _run(installer, env, "--status")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Pending: 3" in result.stdout
    assert "Spooled: 1" in result.stdout
    assert _UNIT in result.stdout


def test_status_fails_when_the_unit_was_never_installed(tmp_path: Path) -> None:
    """A missing unit is a red status naming the repair, never a quiet zero."""
    installer, env, _calls, _unit = _prepare(tmp_path)

    result = _run(installer, env, "--status")

    assert result.returncode != 0
    assert "install-hook-emit-drainer.sh" in result.stdout + result.stderr
