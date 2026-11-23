# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook-process canary appends over the bus through ``onex-ledger append-rows`` (OMN-26568).

The canary's ALERT row used to be written by opening the ledger file: the script required a
ledger path, checked the file, ran the test-write guard against it and appended with
``onex-ledger <ledger> --append``. Operator ruling 2026-11-05 (no file ledger ever again) and
RULING 2026-10-22T01:05:32Z (every ledger entry goes over the bus) retire that. The row now goes
on the stdin of ``onex-ledger append-rows --timeout <t> -``, with no ledger path argument, and the
script exits non-zero when that command does, so the canary counts the channel as not delivered.

The ``ONEX_LEDGER_APPEND_TOOL`` test seam takes the same stdin form. Every test runs with no
ledger path in the environment and no ledger file on disk.
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
CANARY = REPO / "scripts" / "hook_process_canary.py"
ROW = "2026-10-04T00:00:00Z | STATUS | lane=hook-process-canary | state=ALERT | a canary row"
LEDGER_PATH_VAR = "ONEX_LEDGER_PATH"


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
            LEDGER_PATH_VAR,
            "ONEX_LEDGER_APPEND_TOOL",
            "ONEX_LEDGER_LOCK_SCRIPT",
            "PYTEST_CURRENT_TEST",
        }
    }
    env["TMPDIR"] = str(tmp_path)
    env.update(extra)
    return env


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), ROW], env=env, capture_output=True, text=True, check=False
    )


def _fake_uv(tmp_path: Path, exit_code: int = 0) -> tuple[Path, Path, Path]:
    """A ``uv`` on PATH that records its argv (unit-separator joined) and its stdin."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "uv-argv.txt"
    stdin_log = tmp_path / "uv-stdin.txt"
    _executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        f"IFS=$'\\x1f'; printf '%s\\n' \"$*\" >> {argv_log}\n"
        f"cat >> {stdin_log}\n"
        f"exit {exit_code}\n",
    )
    return bin_dir, argv_log, stdin_log


def _internal(tmp_path: Path) -> Path:
    internal = tmp_path / "omnibase_internal"
    internal.mkdir()
    (internal / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n", encoding="utf-8"
    )
    return internal


def test_the_append_is_a_bus_append_of_the_row_on_stdin(tmp_path: Path) -> None:
    internal = _internal(tmp_path)
    bin_dir, argv_log, stdin_log = _fake_uv(tmp_path)
    done = _run(
        _env(
            tmp_path,
            OMNIBASE_INTERNAL_HOME=str(internal),
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        )
    )
    assert done.returncode == 0, done.stderr
    assert argv_log.read_text(encoding="utf-8").splitlines() == [
        "\x1f".join(
            [
                "run",
                "--quiet",
                "--project",
                str(internal),
                "onex-ledger",
                "append-rows",
                "--timeout",
                "30s",
                "-",
            ]
        )
    ]
    assert stdin_log.read_text(encoding="utf-8") == ROW + "\n"


def test_the_bus_append_exits_non_zero_when_the_command_does(tmp_path: Path) -> None:
    """A host that cannot reach the bus is a channel not delivered, never a silent success."""
    internal = _internal(tmp_path)
    bin_dir, _, _ = _fake_uv(tmp_path, exit_code=75)
    done = _run(
        _env(
            tmp_path,
            OMNIBASE_INTERNAL_HOME=str(internal),
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        )
    )
    assert done.returncode == 75


def test_the_bus_append_tool_seam_takes_the_same_stdin_form(tmp_path: Path) -> None:
    calls = tmp_path / "calls.txt"
    rows = tmp_path / "rows.txt"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(
        "import sys\n"
        f"open({str(calls)!r}, 'a').write('\\x1f'.join(sys.argv[1:]) + '\\n')\n"
        f"open({str(rows)!r}, 'a').write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    done = _run(_env(tmp_path, ONEX_LEDGER_APPEND_TOOL=str(recorder)))
    assert done.returncode == 0, done.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "\x1f".join(["append-rows", "--timeout", "30s", "-"])
    ]
    assert rows.read_text(encoding="utf-8") == ROW + "\n"


def test_the_bus_append_tool_seam_failure_is_the_script_failure(
    tmp_path: Path,
) -> None:
    failing = tmp_path / "failing.py"
    failing.write_text("import sys\nsys.stdin.read()\nsys.exit(3)\n", encoding="utf-8")
    done = _run(_env(tmp_path, ONEX_LEDGER_APPEND_TOOL=str(failing)))
    assert done.returncode == 3


def test_without_the_internal_project_the_append_fails_loudly(tmp_path: Path) -> None:
    done = _run(_env(tmp_path))
    assert done.returncode != 0
    assert "OMNIBASE_INTERNAL_HOME" in done.stderr


def test_the_lock_script_variable_is_ignored(tmp_path: Path) -> None:
    """The old variable alone no longer appends anything: the script must not fall back to it."""
    lock = tmp_path / "lock.py"
    lock.write_text(
        "import sys\nopen(sys.argv[1], 'a').write(sys.argv[-1] + '\\n')\n",
        encoding="utf-8",
    )
    done = _run(_env(tmp_path, ONEX_LEDGER_LOCK_SCRIPT=str(lock)))
    assert done.returncode != 0


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


def test_no_file_path_in_the_script_or_the_canary() -> None:
    """Neither file reads the ledger-path variable or opens a ledger file (OMN-26568 AC3)."""
    for path in (SCRIPT, CANARY):
        text = path.read_text(encoding="utf-8")
        assert LEDGER_PATH_VAR not in text, path.name
        assert "ROLLING_WORK_LEDGER" not in text, path.name
        assert "handler_ledger_write_guard" not in text, path.name
        assert '-f "${ledger}"' not in text, path.name


def test_no_file_path_the_append_runs_with_no_ledger_file_and_no_path_variable(
    tmp_path: Path,
) -> None:
    """With the path variable unset and no ledger on disk the append still runs, naming no path."""
    internal = _internal(tmp_path)
    bin_dir, argv_log, stdin_log = _fake_uv(tmp_path)
    env = _env(
        tmp_path,
        OMNIBASE_INTERNAL_HOME=str(internal),
        PATH=f"{bin_dir}:{os.environ['PATH']}",
    )
    assert LEDGER_PATH_VAR not in env
    done = _run(env)
    assert done.returncode == 0, done.stderr
    argv = argv_log.read_text(encoding="utf-8").strip().split("\x1f")
    assert argv[-4:] == ["append-rows", "--timeout", "30s", "-"]
    assert not any(part.endswith(".md") for part in argv)
    assert stdin_log.read_text(encoding="utf-8") == ROW + "\n"
    assert [p.name for p in tmp_path.glob("*.md")] == []
