# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22237: phase 4 sizes Docker Desktop through a macOS-protected folder.

Docker Desktop keeps ``MemoryMiB``/``Cpus`` in
``$HOME/Library/Group Containers/group.com.docker``, which macOS protects: a
terminal without Full Disk Access gets ``EPERM`` for every call on it. The
recorded run (2026-11-03T01:01:33Z, a fresh macOS account on the operator's
Mac, omniclaude ``ee8797af``) failed phase 4 in 0s at ``size Docker Desktop``
with an EMPTY ``Last error`` and a ``Next:`` line that asked for Settings >
Resources by hand -- a remedy that could not clear it, because the re-run still
could not READ the file to find the floor already met.

Three facts the earlier version could not tell apart, each with its own remedy:
absent (write it), unreadable (grant access, or read the engine), unwritable
(same). ``os.path.exists`` answers False for a refusal exactly as it does for
an absent file, so the protected file was read as ``{}``, judged too small, and
rewritten -- which is the call that died.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_bin"
    / "lab-onboarding.sh"
)
GUIDE = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "ONBOARDING.md"

#: The floors the script declares (DOCKER_MEM_GB, DOCKER_CPUS).
MEM_MIB = 10 * 1024
CPUS = 4

#: Verbatim from the recorded run's phase-4 block (OMN-22237). The empty
#: ``Last error`` is the defect this file holds a control for.
INCIDENT_PHASE_4 = (
    'phase=4 name="Docker (optional: the local stack, on your key)" '
    'result=FAILED elapsed="0s" step="size Docker Desktop" last_error=""'
)

EXIT_CHANGED, EXIT_ERROR, EXIT_ENOUGH, EXIT_UNREADABLE, EXIT_UNWRITABLE = 0, 1, 2, 3, 4

pytestmark = pytest.mark.unit


def _fragment(tmp_path: Path) -> Path:
    """The Docker-sizing functions alone, so no test runs bare ``main``."""
    extracted = subprocess.run(
        [
            "awk",
            r"""
            /^(docker_settings_file|size_docker|docker_engine_resources_ok)\(\)/ { fn = 1 }
            fn { print }
            fn && /^}/ { fn = 0 }
            """,
            str(SCRIPT),
        ],
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    assert "size_docker()" in extracted, "the awk extraction found no size_docker"
    fragment = tmp_path / "fragment.sh"
    fragment.write_text(extracted, encoding="utf-8")
    return fragment


def _brew_shim(tmp_path: Path) -> Path:
    """A ``brew_bin``-shaped directory holding this interpreter as python3.13."""
    bin_dir = tmp_path / "brewbin"
    bin_dir.mkdir()
    (bin_dir / "brew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "brew").chmod(0o755)
    shim = bin_dir / "python3.13"
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return bin_dir


def _settings_dir(home: Path) -> Path:
    directory = home / "Library" / "Group Containers" / "group.com.docker"
    directory.mkdir(parents=True)
    return directory


def _run_size_docker(
    tmp_path: Path, home: Path, *, mem: int = MEM_MIB, cpus: int = CPUS
) -> subprocess.CompletedProcess[str]:
    """Call ``size_docker`` with the real script's text and a stubbed brew."""
    bin_dir = _brew_shim(tmp_path)
    fragment = _fragment(tmp_path)
    script = (
        f'set -u\n. "{fragment}"\n'
        f'brew_bin() {{ printf %s "{bin_dir}/brew"; }}\n'
        f"size_docker {mem} {cpus}\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "HOME": str(home)},
    )


def _unreadable(home: Path) -> Path:
    """A settings file inside a directory this user may not open (the TCC shape)."""
    directory = _settings_dir(home)
    settings = directory / "settings-store.json"
    settings.write_text(json.dumps({"MemoryMiB": 2048, "Cpus": 2}), encoding="utf-8")
    directory.chmod(0o000)
    return settings


@pytest.fixture(autouse=True)
def _not_root() -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses the permission bits this file is about")


def test_unreadable_names_cause(tmp_path: Path) -> None:
    """AC1: an unreadable settings path stops with a named cause, not an empty one."""
    home = tmp_path / "home"
    home.mkdir()
    directory = _unreadable(home)
    try:
        result = _run_size_docker(tmp_path, home)
    finally:
        directory.parent.chmod(0o755)

    assert result.returncode == EXIT_UNREADABLE, (
        "an unreadable settings file must report its own exit code, not a "
        f"generic error: rc={result.returncode} stderr={result.stderr!r}"
    )
    assert "cannot read Docker Desktop's settings" in result.stderr
    assert "Full Disk Access" in result.stderr
    assert "Traceback" not in result.stderr, (
        "the cause must be stated, never left as a traceback: " + result.stderr
    )


def test_unreadable_is_distinct_from_absent(tmp_path: Path) -> None:
    """AC1: absent is a different fact, and it is still written."""
    home = tmp_path / "home"
    home.mkdir()
    _settings_dir(home)

    result = _run_size_docker(tmp_path, home)

    assert result.returncode == EXIT_CHANGED, result.stderr
    written = json.loads(
        (
            home / "Library" / "Group Containers" / "group.com.docker" / "settings.json"
        ).read_text(encoding="utf-8")
    )
    assert written["memoryMiB"] >= MEM_MIB
    assert written["cpus"] >= CPUS


def test_remedy_clears_on_rerun(tmp_path: Path) -> None:
    """AC2: at or above the floor, nothing is written, so the hand remedy works.

    The recorded failure's remedy ("set Settings > Resources by hand, then run
    this again") could never clear it: the re-run reached the write path again.
    A readable file at the floor must now return "already enough" and leave the
    protected path untouched.
    """
    home = tmp_path / "home"
    home.mkdir()
    directory = _settings_dir(home)
    settings = directory / "settings-store.json"
    settings.write_text(
        json.dumps({"MemoryMiB": MEM_MIB, "Cpus": CPUS}), encoding="utf-8"
    )
    before = settings.read_bytes()
    # Writable by its owner, as a real Mac's is; the point is that no write happens.
    result = _run_size_docker(tmp_path, home)

    assert result.returncode == EXIT_ENOUGH, result.stderr
    assert settings.read_bytes() == before, "the settings file was rewritten"
    assert not (directory / "settings-store.json.pre-onboarding").exists()


def test_remedy_clears_on_rerun_through_the_engine(tmp_path: Path) -> None:
    """AC2: with the file unreadable, the engine's own figures are accepted.

    This is what makes "open Docker Desktop and set Resources" a remedy on a
    Mac that will never grant the terminal Full Disk Access.
    """
    fragment = _fragment(tmp_path)
    assert "docker_engine_resources_ok" in fragment.read_text(encoding="utf-8"), (
        "phase 4 must have a way to measure Docker without reading the "
        "protected settings file"
    )
    bin_dir = tmp_path / "dockerbin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\nprintf '%s %s\\n' \"$FAKE_MEM_BYTES\" \"$FAKE_NCPU\"\n",
        encoding="utf-8",
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)

    def _engine(mem_bytes: int, ncpu: int) -> int:
        return subprocess.run(
            [
                "bash",
                "-c",
                f'set -u\n. "{fragment}"\ndocker_engine_resources_ok {MEM_MIB} {CPUS}\n',
            ],
            text=True,
            capture_output=True,
            timeout=30,
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_MEM_BYTES": str(mem_bytes),
                "FAKE_NCPU": str(ncpu),
            },
        ).returncode

    assert _engine(MEM_MIB * 1024 * 1024, CPUS) == 0, (
        "an engine already at the floor must be accepted"
    )
    assert _engine(2048 * 1024 * 1024, CPUS) != 0, "too little memory must not pass"
    assert _engine(MEM_MIB * 1024 * 1024, 2) != 0, "too few CPUs must not pass"


def test_last_error_is_stderr(tmp_path: Path) -> None:
    """AC3: the field carries the step's own stderr, never the log's tail."""
    text = SCRIPT.read_text(encoding="utf-8")
    sizing = text.split('size_docker "$mem" "$DOCKER_CPUS"', 1)[1].split("esac", 1)[0]
    assert "last_log_lines" not in sizing.split("*)", 1)[0], (
        "the named failure paths must not reach for the log's last lines"
    )
    assert 'size_err="$(size_docker' in text, (
        "the step's stderr must be captured where the field can carry it"
    )

    home = tmp_path / "home"
    home.mkdir()
    directory = _unreadable(home)
    bin_dir = _brew_shim(tmp_path)
    fragment = _fragment(tmp_path)
    log = tmp_path / "run.log"
    log.write_text("a preceding line\nanother preceding line\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'set -u\n. "{fragment}"\n'
                f'brew_bin() {{ printf %s "{bin_dir}/brew"; }}\n'
                f'LOG="{log}"\n'
                f'size_err="$(size_docker {MEM_MIB} {CPUS} 2>&1 >>"$LOG")"\n'
                'printf %s "$size_err"\n',
            ],
            text=True,
            capture_output=True,
            timeout=60,
            env={**os.environ, "HOME": str(home)},
        )
    finally:
        directory.parent.chmod(0o755)

    assert "Full Disk Access" in result.stdout, (
        "the captured value must be the step's cause: " + result.stdout
    )
    assert "preceding line" not in result.stdout


def test_incident_fixture(tmp_path: Path) -> None:
    """AC5: the recorded failure's shape, replayed against the script.

    The run log the ticket cites (``run-20261102-190022.log``) was not among
    the files copied off the walked account, so the control is built from the
    status line it recorded, which is preserved verbatim above: a 0s FAILED
    phase 4 at ``size Docker Desktop`` carrying an empty ``last_error``. The
    replay asserts the two properties that line proves were wrong -- no cause,
    and a remedy that says nothing about why.
    """
    assert 'last_error=""' in INCIDENT_PHASE_4

    home = tmp_path / "home"
    home.mkdir()
    directory = _unreadable(home)
    try:
        result = _run_size_docker(tmp_path, home)
    finally:
        directory.parent.chmod(0o755)

    assert result.returncode == EXIT_UNREADABLE
    assert result.stderr.strip(), "the incident's empty last_error must not recur"

    text = SCRIPT.read_text(encoding="utf-8")
    remedy = text.split("3|4)", 1)[1].split("esac", 1)[0]
    assert "Full Disk Access" in remedy, (
        "the remedy printed for a protected path must name what blocks it"
    )
    assert "Full Disk Access" in GUIDE.read_text(encoding="utf-8"), (
        "AC4: the guide must state the requirement beside the memory figures"
    )


def test_the_guide_states_full_disk_access_in_the_docker_section() -> None:
    """AC4: the figures and the access requirement sit together."""
    guide = GUIDE.read_text(encoding="utf-8")
    assert "Full Disk Access" in guide
    before, _, after = guide.partition("Full Disk Access")
    assert "Free disk" in before, "the requirement belongs with the resource table"
    assert "group.com.docker" in after, "name the folder macOS protects"


def test_the_awk_extraction_is_not_silently_empty(tmp_path: Path) -> None:
    """A negative control for this file's own harness."""
    assert shutil.which("awk"), "awk is needed to extract the functions under test"
    fragment = _fragment(tmp_path)
    body = fragment.read_text(encoding="utf-8")
    for name in ("docker_settings_file", "size_docker", "docker_engine_resources_ok"):
        assert f"{name}()" in body
