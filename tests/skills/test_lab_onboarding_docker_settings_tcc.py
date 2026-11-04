# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22237: phase 4 on a Mac whose terminal has no Full Disk Access.

Docker Desktop keeps its settings in ``~/Library/Group Containers/group.com.docker``,
which macOS protects: from a terminal without Full Disk Access every read and write
there fails with "Operation not permitted". Phase 4 used to lose that distinction
(an unreadable file looked absent), failed with an empty ``Last error`` made of the
preceding log lines, and printed a remedy that could not clear it.

macOS is simulated by running the script's own sizing snippet under a Python that
raises the same ``PermissionError`` for paths in that folder, so the tests run
unchanged on any host.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins" / "onex" / "skills" / "_bin" / "lab-onboarding.sh"
ONBOARDING_MD = REPO / "plugins" / "onex" / "ONBOARDING.md"
FIXTURE = (
    REPO / "tests" / "fixtures" / "onboarding_docker_tcc_2026_11_03" / "incident.json"
)

pytestmark = pytest.mark.unit

_GROUP = "Library/Group Containers/group.com.docker"

# python3.13 as the script launches it, with the folder's macOS protection added.
_PYTHON_WRAPPER = """#!/bin/sh
shift  # the script runs `python3.13 - ARGS`; the code is on stdin either way
exec "{python}" -c '
import builtins, os, sys
mode = os.environ.get("FIXTURE_TCC", "")
prefix = os.environ["FIXTURE_PROTECTED"]
def guarded(real, deny_on):
    def inner(path, *a, **k):
        if isinstance(path, (str, bytes, os.PathLike)) and os.fspath(path).startswith(prefix) and deny_on(a, k):
            if mode == "unreadable":
                raise PermissionError(1, "Operation not permitted", os.fspath(path))
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real(path, *a, **k)
    return inner
def writes(a, k):
    m = a[0] if a else k.get("mode", "r")
    return any(c in m for c in "wax+")
if mode == "unreadable":
    os.stat = guarded(os.stat, lambda a, k: True)
    builtins.open = guarded(builtins.open, lambda a, k: True)
    os.makedirs = guarded(os.makedirs, lambda a, k: True)
    os.replace = guarded(os.replace, lambda a, k: True)
elif mode == "unwritable":
    builtins.open = guarded(builtins.open, writes)
    os.makedirs = guarded(os.makedirs, lambda a, k: True)
    os.replace = guarded(os.replace, lambda a, k: True)
sys.argv = ["-"] + sys.argv[1:]
exec(compile(sys.stdin.read(), "size_docker", "exec"))
' "$@"
"""


def _section(start: str, stop: str | None) -> str:
    lines: list[str] = []
    on = False
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        if line.startswith(start):
            on = True
        elif stop is not None and line.startswith(stop):
            on = False
        if on:
            lines.append(line)
    assert lines, f"the script has no section starting {start!r}"
    return "\n".join(lines) + "\n"


_PRELUDE = r"""
set -uo pipefail
log() { printf '%s\n' "$*" >>"$LOG"; }
say() { printf '%s\n' "$*"; log "$*"; }
hr() { :; }
notify() { :; }
mark_done() { :; }
is_done() { return 1; }
rerun_note() { :; }
sleep() { :; }
RETRIES=1
STATUS="$LOG.status"
"""

_PHASE4_STUBS = r"""
docker_installed() { return 0; }
docker_ready() { [ -n "${FIXTURE_DOCKER_UP:-}" ]; }
docker() { printf '%s\n' "${FIXTURE_DOCKER_INFO:-}"; }
restart_docker() { echo RESTARTED; }
open() { :; }
ram_gb() { printf '32\n'; }
wait_for_docker() { echo REACHED_DOCKER_START; exit 0; }
MODE2_OK=1
DOCKER_MEM_GB=10
DOCKER_CPUS=4
HOST_RESERVE_GB=6
"""


def _run_phase4(
    tmp_path: Path,
    *,
    tcc: str = "",
    settings: dict[str, int] | None = None,
    settings_raw: str | None = None,
    docker_up: bool = False,
    docker_info: str = "",
    before_phase4: str = "",
    seed_log: str = "",
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    group = home / _GROUP
    group.mkdir(parents=True)
    if settings is not None:
        (group / "settings-store.json").write_text(json.dumps(settings))
    if settings_raw is not None:
        (group / "settings-store.json").write_text(settings_raw)
    fake_brew = tmp_path / "bin"
    fake_brew.mkdir()
    py = fake_brew / "python3.13"
    py.write_text(_PYTHON_WRAPPER.format(python=sys.executable))
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "run.log"
    log.write_text(seed_log)
    snippet = (
        _PRELUDE
        + _section('PHASE_NO=""', "mark_done()")
        + _section("last_log_lines()", "# wait_until")
        + _section("# Phase 4: containers", "# Phase 5:")
        + _PHASE4_STUBS
        + f'brew_bin() {{ printf "%s/brew\\n" "{fake_brew}"; }}\n'
        + before_phase4
        + "\nphase4\n"
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "LOG": str(log),
        "FIXTURE_TCC": tcc,
        "FIXTURE_PROTECTED": str(group),
        "FIXTURE_DOCKER_INFO": docker_info,
    }
    if docker_up:
        env["FIXTURE_DOCKER_UP"] = "1"
    return subprocess.run(
        ["/bin/bash", "-c", snippet],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )


def _last_error(out: str) -> str:
    match = re.search(r"^  Last error: (.*)$", out, re.M)
    return match.group(1) if match else ""


# -- AC1 -------------------------------------------------------------------


def test_unreadable_names_cause(tmp_path: Path) -> None:
    result = _run_phase4(tmp_path, tcc="unreadable")
    out = result.stdout
    assert result.returncode == 1, out + result.stderr
    assert "FAILED" in out
    err = _last_error(out)
    assert "Operation not permitted" in err, out
    assert "group.com.docker" in err, out
    assert "Full Disk Access" in out, out
    assert "open Docker Desktop once" in out, out


def test_absent_settings_file_is_not_an_error(tmp_path: Path) -> None:
    """Positive control: a readable folder with no settings file is a fresh Docker, not a failure."""
    result = _run_phase4(tmp_path, settings=None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REACHED_DOCKER_START" in result.stdout
    written = tmp_path / "home" / _GROUP / "settings.json"
    assert json.loads(written.read_text()) == {"memoryMiB": 10240, "cpus": 4}


def test_unwritable_below_floor_names_cause(tmp_path: Path) -> None:
    result = _run_phase4(
        tmp_path, tcc="unwritable", settings={"MemoryMiB": 2048, "Cpus": 2}
    )
    out = result.stdout
    assert result.returncode == 1, out + result.stderr
    err = _last_error(out)
    assert "Permission denied" in err and "group.com.docker" in err, out
    assert "Full Disk Access" in out, out


# -- AC2 -------------------------------------------------------------------


def test_remedy_clears_on_rerun_when_settings_already_at_floor(tmp_path: Path) -> None:
    """The file is readable and big enough, but the folder cannot be written."""
    result = _run_phase4(
        tmp_path, tcc="unwritable", settings={"MemoryMiB": 12288, "Cpus": 8}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "already has at least" in result.stdout
    assert "REACHED_DOCKER_START" in result.stdout


def test_remedy_clears_on_rerun_when_running_engine_already_has_the_resources(
    tmp_path: Path,
) -> None:
    """Unreadable settings, Docker Desktop running at the floor: setting Resources
    by hand is a remedy that works, because the engine is asked instead."""
    mib = 10 * 1024 * 1024 * 1024
    result = _run_phase4(
        tmp_path, tcc="unreadable", docker_up=True, docker_info=f"{mib} 4"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REACHED_DOCKER_START" in result.stdout


def test_remedy_still_fails_when_running_engine_is_below_the_floor(
    tmp_path: Path,
) -> None:
    result = _run_phase4(
        tmp_path,
        tcc="unreadable",
        docker_up=True,
        docker_info=f"{2 * 1024**3} 2",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Full Disk Access" in result.stdout


# -- AC3 -------------------------------------------------------------------

_DECOY = "decoy-line-from-the-log"


def test_last_error_is_stderr_for_a_step(tmp_path: Path) -> None:
    result = _run_phase4(
        tmp_path,
        seed_log=f"{_DECOY} one\n{_DECOY} two\n{_DECOY} three\n",
        before_phase4=r"""
phase4() {
  phase_start 4 "demo"
  step "run the demo" sh -c 'echo "stdout-noise"; echo "the real cause" >&2; exit 7'
  phase_fail "fix it"
}
""",
    )
    err = _last_error(result.stdout)
    assert "the real cause" in err, result.stdout
    assert _DECOY not in err and "stdout-noise" not in err, result.stdout


def test_last_error_is_stderr_for_a_retried_step(tmp_path: Path) -> None:
    result = _run_phase4(
        tmp_path,
        seed_log=f"{_DECOY} one\n",
        before_phase4=r"""
phase4() {
  phase_start 4 "demo"
  retry "fetch the demo" sh -c 'echo "stdout-noise"; echo "connection refused" >&2; exit 7' || true
  phase_fail "fix it"
}
""",
    )
    err = _last_error(result.stdout)
    assert "connection refused" in err, result.stdout
    assert _DECOY not in err and "stdout-noise" not in err, result.stdout


def test_last_error_never_falls_back_to_log_lines(tmp_path: Path) -> None:
    result = _run_phase4(
        tmp_path,
        seed_log=f"{_DECOY} one\n{_DECOY} two\n",
        before_phase4=r"""
phase4() {
  phase_start 4 "demo"
  step "run the silent demo" sh -c 'echo "only stdout"; exit 9'
  phase_fail "fix it"
}
""",
    )
    err = _last_error(result.stdout)
    assert "status 9" in err, result.stdout
    assert _DECOY not in err and "only stdout" not in err, result.stdout


def test_sizing_failure_last_error_is_the_snippets_own_stderr(tmp_path: Path) -> None:
    result = _run_phase4(tmp_path, settings_raw="{not json", seed_log=f"{_DECOY} one\n")
    err = _last_error(result.stdout)
    assert "not valid JSON" in err, result.stdout
    assert _DECOY not in err, result.stdout


# -- AC4 -------------------------------------------------------------------


def test_onboarding_md_states_full_disk_access_beside_the_figures() -> None:
    lines = ONBOARDING_MD.read_text(encoding="utf-8").splitlines()
    table_at = next(i for i, ln in enumerate(lines) if ln.startswith("| Free disk"))
    near = "\n".join(lines[table_at : table_at + 12])
    assert "Full Disk Access" in near, near


# -- AC5 -------------------------------------------------------------------


def test_incident_fixture(tmp_path: Path) -> None:
    """The 2026-11-03 walk: Docker Desktop installed, Terminal without Full Disk Access."""
    incident = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert incident["phase_results"]["4"] == "FAIL"
    assert incident["last_error_as_recorded"] == ""
    result = _run_phase4(tmp_path, tcc="unreadable")
    out = result.stdout
    assert result.returncode == 1, out + result.stderr
    assert f"Step:      {incident['failed_step']}" in out or "Step:      read" in out
    err = _last_error(out)
    assert err, "Last error is empty, as in the recorded run"
    assert incident["os_error"] in err, out
    assert incident["settings_dir"].split("/")[-1] in err, out
    next_line = out.split("Next:")[1].split("\n")[0]
    assert next_line.strip() != incident["next_as_recorded"], next_line
    assert "Full Disk Access" in next_line, next_line
