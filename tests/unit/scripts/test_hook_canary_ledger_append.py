# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook-process canary appends through ``onex-ledger`` (OMN-19513 cutover plan, task C1).

The canary's ALERT row was the one ledger writer that bypassed the dual write: it appended through
the registry's lock script, which has no bus emit, so its rows never reached the database ledger.
These tests pin the append command: the packaged ``onex-ledger`` of the omnibase_internal project,
run by ``uv``, or the ``ONEX_LEDGER_APPEND_TOOL`` test seam that the omnibase_internal worktree
tools already honour. No file under ``scripts/`` may name the lock-script variable again.

Every ledger these tests touch is under ``tmp_path``, which is the subprocess's ``TMPDIR``, so the
ledger test-write guard judges it a test's own ledger.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "hook_canary_ledger_append.sh"
ROW = "2026-10-04T00:00:00Z | STATUS | lane=hook-process-canary | state=ALERT | a canary row"
HEADER = "## Work ledger\n"


def _executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "OMNI_HOME",
            "OMNIBASE_INTERNAL_HOME",
            "ONEX_LEDGER_APPEND_TOOL",
            "ONEX_LEDGER_LOCK_SCRIPT",
            "PYTEST_CURRENT_TEST",
        }
    }
    env["TMPDIR"] = str(tmp_path)
    env.update(extra)
    return env


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "ROLLING_WORK_LEDGER.md"
    path.write_text(HEADER, encoding="utf-8")
    return path


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), ROW], env=env, capture_output=True, text=True, check=False
    )


def test_the_append_goes_through_the_append_tool_seam(
    tmp_path: Path, ledger: Path
) -> None:
    calls = tmp_path / "calls.txt"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(
        "import sys\n"
        f"open({str(calls)!r}, 'a').write('\\x1f'.join(sys.argv[1:]) + '\\n')\n"
        "open(sys.argv[1], 'a').write(sys.argv[-1] + '\\n')\n",
        encoding="utf-8",
    )
    done = _run(
        _env(
            tmp_path,
            ONEX_LEDGER_PATH=str(ledger),
            ONEX_LEDGER_APPEND_TOOL=str(recorder),
        )
    )
    assert done.returncode == 0, done.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "\x1f".join([str(ledger), "--timeout", "30s", "--append", ROW])
    ]
    assert ledger.read_text(encoding="utf-8") == HEADER + ROW + "\n"


def test_the_default_append_command_is_the_packaged_onex_ledger(
    tmp_path: Path, ledger: Path
) -> None:
    internal = tmp_path / "omnibase_internal"
    internal.mkdir()
    (internal / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n", encoding="utf-8"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "uv-calls.txt"
    _executable(
        bin_dir / "uv",
        f"#!/usr/bin/env bash\nIFS=$'\\x1f'; printf '%s\\n' \"$*\" >> {calls}\n",
    )
    done = _run(
        _env(
            tmp_path,
            ONEX_LEDGER_PATH=str(ledger),
            OMNIBASE_INTERNAL_HOME=str(internal),
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        )
    )
    assert done.returncode == 0, done.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "\x1f".join(
            [
                "run",
                "--quiet",
                "--project",
                str(internal),
                "onex-ledger",
                str(ledger),
                "--timeout",
                "30s",
                "--append",
                ROW,
            ]
        )
    ]


def test_without_the_internal_project_the_append_fails_loudly(
    tmp_path: Path, ledger: Path
) -> None:
    done = _run(_env(tmp_path, ONEX_LEDGER_PATH=str(ledger)))
    assert done.returncode != 0
    assert "OMNIBASE_INTERNAL_HOME" in done.stderr
    assert ledger.read_text(encoding="utf-8") == HEADER


def test_the_lock_script_variable_is_ignored(tmp_path: Path, ledger: Path) -> None:
    """The old variable alone no longer appends anything: the script must not fall back to it."""
    lock = tmp_path / "lock.py"
    lock.write_text(
        "import sys\nopen(sys.argv[1], 'a').write(sys.argv[-1] + '\\n')\n",
        encoding="utf-8",
    )
    done = _run(
        _env(tmp_path, ONEX_LEDGER_PATH=str(ledger), ONEX_LEDGER_LOCK_SCRIPT=str(lock))
    )
    assert done.returncode != 0
    assert ledger.read_text(encoding="utf-8") == HEADER


def test_no_script_names_the_lock_script_variable() -> None:
    """The plan's falsifier, ``git grep -n ONEX_LEDGER_LOCK_SCRIPT -- scripts/``, as a file scan."""
    hits = [
        str(path.relative_to(REPO))
        for path in sorted((REPO / "scripts").rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and "ONEX_LEDGER_LOCK_SCRIPT"
        in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == []
