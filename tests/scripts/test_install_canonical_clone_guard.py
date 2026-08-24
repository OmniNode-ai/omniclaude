# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for ``scripts/install-canonical-clone-guard.sh`` (OMN-16496).

The installer is the only sanctioned way the tracked guard source
(``scripts/user-hooks/canonical-clone-guard.py``) reaches its live location
(``~/.claude/hooks/canonical-clone-guard.py``). It is dry-run by default,
byte-copies on ``--apply``, is idempotent, and verifies that the hook is
registered in ``~/.claude/settings.json`` (it never edits that file).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "install-canonical-clone-guard.sh"
SOURCE = REPO_ROOT / "scripts" / "user-hooks" / "canonical-clone-guard.py"

EXIT_OK = 0
EXIT_PENDING = 3


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _register(home: Path, command: str) -> None:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write|NotebookEdit|MultiEdit|Bash",
                            "hooks": [
                                {"type": "command", "command": command, "timeout": 10}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.mark.unit
def test_dry_run_writes_nothing_and_reports_pending(home: Path) -> None:
    proc = _run(home)
    assert proc.returncode == EXIT_PENDING, proc.stdout + proc.stderr
    assert "installed: missing" in proc.stdout
    assert "registered: no" in proc.stdout
    assert "--apply" in proc.stdout
    assert not (home / ".claude").exists()


@pytest.mark.unit
def test_apply_installs_byte_identical_executable_copy(home: Path) -> None:
    _register(home, str(home / ".claude" / "hooks" / "canonical-clone-guard.py"))
    proc = _run(home, "--apply")
    assert proc.returncode == EXIT_OK, proc.stdout + proc.stderr
    installed = home / ".claude" / "hooks" / "canonical-clone-guard.py"
    assert installed.is_file()
    assert _sha(installed) == _sha(SOURCE)
    assert os.access(installed, os.X_OK)
    assert "installed: identical" in proc.stdout
    assert "registered: yes" in proc.stdout
    assert not list((home / ".claude" / "hooks").glob("*.bak.*"))

    again = _run(home, "--apply")
    assert again.returncode == EXIT_OK
    assert "installed: identical" in again.stdout
    assert not list((home / ".claude" / "hooks").glob("*.bak.*"))


@pytest.mark.unit
def test_drift_is_detected_backed_up_and_replaced(home: Path) -> None:
    _register(home, str(home / ".claude" / "hooks" / "canonical-clone-guard.py"))
    installed = home / ".claude" / "hooks" / "canonical-clone-guard.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("#!/usr/bin/env python3\n# stale copy\n", encoding="utf-8")

    check = _run(home)
    assert check.returncode == EXIT_PENDING
    assert "installed: DRIFT" in check.stdout
    assert installed.read_text(encoding="utf-8").startswith(
        "#!/usr/bin/env python3\n# stale copy"
    )

    apply = _run(home, "--apply")
    assert apply.returncode == EXIT_OK, apply.stdout + apply.stderr
    assert _sha(installed) == _sha(SOURCE)
    backups = list(installed.parent.glob("canonical-clone-guard.py.bak.*"))
    assert len(backups) == 1
    assert "stale copy" in backups[0].read_text(encoding="utf-8")


@pytest.mark.unit
def test_apply_without_registration_installs_but_stays_pending(home: Path) -> None:
    proc = _run(home, "--apply")
    assert proc.returncode == EXIT_PENDING, proc.stdout + proc.stderr
    installed = home / ".claude" / "hooks" / "canonical-clone-guard.py"
    assert _sha(installed) == _sha(SOURCE)
    assert "registered: no" in proc.stdout
    assert '"PreToolUse"' in proc.stdout
    assert "canonical-clone-guard.py" in proc.stdout


@pytest.mark.unit
def test_registration_check_matches_command_suffix_only(home: Path) -> None:
    _register(home, "some-other-hook.py")
    proc = _run(home, "--apply")
    assert proc.returncode == EXIT_PENDING
    assert "registered: no" in proc.stdout

    _register(home, "~/.claude/hooks/canonical-clone-guard.py")
    proc = _run(home)
    assert proc.returncode == EXIT_OK, proc.stdout + proc.stderr
    assert "registered: yes" in proc.stdout


@pytest.mark.unit
def test_tracked_source_is_a_valid_hook_and_installer_is_portable() -> None:
    assert SOURCE.is_file()
    assert SOURCE.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")
    assert os.access(SOURCE, os.X_OK)
    text = SCRIPT.read_text(encoding="utf-8")
    for needle in ("/Users" + "/", "/Volumes" + "/"):
        assert needle not in text
    assert "set -euo pipefail" in text
