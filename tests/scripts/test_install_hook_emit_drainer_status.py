# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""`--status` must be able to see a broken agent. [OMN-17284]

Measured on the operator Mac 2026-09-15: the installed LaunchAgent plist had
been overwritten by a bare JSON array -- `plutil -lint` rejected it and it no
longer carried `KeepAlive`, so the one property that makes a wedged drainer
self-healing was gone. The service stayed loaded from launchd's in-memory copy
of the *previous* good plist, so nothing looked wrong. `--status` printed the
label, the plist path, `launchctl print` output and a journal count, exited 0,
and said nothing about any of it. The condition stood for two days.

Two blind spots, both exercised here:

1. `--status` never reads the plist it names. An unparseable plist, or one
   that has lost `KeepAlive`, reports exactly like a healthy one.
2. `--status` counts only the hook-emit journal. The `emit_spool` queue that
   `omnibase_infra`'s receipt-mode CLI writes when the emit daemon socket is
   unreachable is a *second* backlog under the same state root -- 736 records
   deep on that host -- and `--status` does not mention it, so the operator
   reads one queue's depth as the whole picture.

These tests deliberately do NOT need brew python3.13 or a real `launchctl`, so
unlike `test_install_hook_emit_drainer.py` (which drives the real installer and
therefore has no CI home on this fleet -- see the ignore list in ci.yml and
OMN-18357) this file runs on an ordinary runner. That is also the standing
proof that `--status` needs no brew interpreter: a Linux runner has neither
rule-11 literal, so every test here would fail if it did.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LABEL = "ai.omninode.hook-emit-drainer"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _prepare(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """Lay out an installer copy, a stub launchctl, and an empty HOME.

    Returns the installer path, the environment to run it under, and the
    LaunchAgents plist path `--status` will inspect.
    """
    repo_root = tmp_path / "omniclaude"
    installer = repo_root / "scripts" / "install-hook-emit-drainer.sh"
    installer.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_REPO_ROOT / "scripts" / "install-hook-emit-drainer.sh", installer)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # `launchctl print` succeeds: the service IS loaded. That is the whole
    # point -- on the measured host the agent was loaded and the plist on disk
    # was broken at the same time, which is why liveness proved nothing.
    _write_executable(
        fake_bin / "launchctl",
        "#!/usr/bin/env bash\nprintf 'state = running\\n'\nexit 0\n",
    )

    home = tmp_path / "home"
    state_root = tmp_path / "state" / ".onex_state"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    state_root.mkdir(parents=True)

    env = os.environ | {
        "HOME": str(home),
        # The script resolves its state dir from this first. Without it the
        # counts below are read off the operator's real machine.
        "ONEX_STATE_DIR": str(state_root),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    return installer, env, home / "Library" / "LaunchAgents" / f"{_LABEL}.plist"


def _healthy_plist() -> bytes:
    return plistlib.dumps(
        {
            "Label": _LABEL,
            "ProgramArguments": ["/usr/bin/python3", "/tmp/hook_emit_drainer.py"],
            "KeepAlive": True,
            "RunAtLoad": True,
            "Disabled": False,
        }
    )


def _run_status(
    installer: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(installer), "--status"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_status_passes_on_a_healthy_plist(tmp_path: Path) -> None:
    """Positive control: a well-formed plist with KeepAlive reports OK, exit 0.

    Without this, every assertion below would also pass against a `--status`
    that simply always failed.
    """
    installer, env, plist = _prepare(tmp_path)
    plist.write_bytes(_healthy_plist())

    result = _run_status(installer, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "KeepAlive" in result.stdout


def test_status_fails_on_an_unparseable_plist(tmp_path: Path) -> None:
    """The exact on-disk corruption measured: a bare JSON array, not a dict."""
    installer, env, plist = _prepare(tmp_path)
    plist.write_text(
        '["/x/python3","/x/hook_emit_drainer.py","--log-level","INFO"]',
        encoding="utf-8",
    )

    result = _run_status(installer, env)

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "install-hook-emit-drainer.sh" in combined, (
        "a failure must name the command that repairs it, or the operator is "
        "told something is wrong and not what to do"
    )


def test_status_fails_when_keepalive_is_absent(tmp_path: Path) -> None:
    """A parseable plist that has lost KeepAlive is the silent half of the bug.

    `plutil -lint` passes on it. The drainer stops being self-healing anyway:
    launchd will not restart it when it wedges or exits.
    """
    installer, env, plist = _prepare(tmp_path)
    payload = plistlib.loads(_healthy_plist())
    del payload["KeepAlive"]
    plist.write_bytes(plistlib.dumps(payload))

    result = _run_status(installer, env)

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "KeepAlive" in combined


def test_status_fails_when_the_plist_is_missing_entirely(tmp_path: Path) -> None:
    installer, env, _plist = _prepare(tmp_path)

    result = _run_status(installer, env)

    assert result.returncode != 0, result.stdout + result.stderr


def test_status_reports_the_emit_spool_backlog(tmp_path: Path) -> None:
    """The second queue must be visible, and distinguishable from the first.

    A journal count alone reads as the whole backlog. On the measured host the
    journal was full AND 736 records sat in `emit_spool` behind an absent emit
    daemon socket -- a different queue with a different cause and a different
    repair.
    """
    installer, env, plist = _prepare(tmp_path)
    plist.write_bytes(_healthy_plist())

    state = Path(env["ONEX_STATE_DIR"])
    journal = state / "hook_emit_journal"
    journal.mkdir()
    for index in range(3):
        (journal / f"{index}.json").write_text("{}", encoding="utf-8")
    spool = state / "emit_spool"
    spool.mkdir()
    for index in range(7):
        (spool / f"tool-output-captured-{index}.json").write_text(
            "{}", encoding="utf-8"
        )

    result = _run_status(installer, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3" in result.stdout and "7" in result.stdout
    assert "emit_spool" in result.stdout or "Spool" in result.stdout
