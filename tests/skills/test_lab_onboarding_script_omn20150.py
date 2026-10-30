# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20150: the lab onboarding script's preflight contract.

Preflight reads the machine and changes nothing. A machine below the minimum
exits 3 having written nothing under $HOME, and a VM is never given containers.
Readings are overridden through the script's ONBOARD_TEST_* seams, so these run
on Linux and macOS hosts and install nothing. The script must also parse under the
stock macOS /bin/bash 3.2 (the D4 failure class).
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import pty
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_bin"
    / "lab-onboarding.sh"
)
SKILL = SCRIPT.parents[1] / "omninode_dev_setup" / "SKILL.md"
HANDLER = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "omniclaude"
    / "nodes"
    / "node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
UNBRACED_MULTIBYTE_EXPANSION = re.compile(rb"\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]")

pytestmark = pytest.mark.unit


def _drive_tty(
    argv: list[str],
    env: dict[str, str],
    steps: list[tuple[str, str]],
    timeout: float = 120,
) -> tuple[str, int]:
    """Answer prompts on a controlling terminal and reap the child even on failure."""
    fd, slave = pty.openpty()
    proc = subprocess.Popen(
        argv,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)

    output = bytearray()
    deadline = time.monotonic() + timeout
    eof = False

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError(
                f"Terminal driver timed out: {output.decode(errors='replace')}"
            )
        return seconds

    def read_output() -> None:
        nonlocal eof
        if not select.select([fd], [], [], remaining())[0]:
            raise TimeoutError(
                f"Terminal driver timed out: {output.decode(errors='replace')}"
            )
        try:
            chunk = os.read(fd, 65536)
        except OSError as exc:
            if exc.errno != errno.EIO:
                raise
            # Linux reports EIO when the slave closes; BSD returns an empty read.
            chunk = b""
        if chunk:
            output.extend(chunk)
        else:
            eof = True

    try:
        cursor = 0
        for prompt, answer in steps:
            expected = prompt.encode()
            while (position := output.find(expected, cursor)) < 0:
                if eof:
                    raise AssertionError(
                        f"Child exited before prompt {prompt!r}: {output.decode(errors='replace')}"
                    )
                read_output()
            cursor = position + len(expected)
            # Give the shell time to enter read (and read -s to disable echo).
            time.sleep(min(0.05, remaining()))
            os.write(fd, (answer + "\r").encode())
        while not eof:
            read_output()
        returncode = proc.wait(timeout=remaining())
        return output.decode(errors="replace").replace("\r", ""), returncode
    finally:
        if proc.poll() is None:
            # start_new_session made the child a group leader: kill its subprocesses too.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        os.close(fd)


def _run(tmp_path: Path, *args: str, **seams: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(tmp_path / "run") + "/",
        "ONBOARD_NOTIFY": "0",
        "ONBOARD_TEST_OS": "Darwin",
        "ONBOARD_TEST_MACOS": "14.5",
        "ONBOARD_TEST_PORTS_BUSY": "",
        "ONBOARD_TEST_DISK_GB": "100",
        "ONBOARD_TEST_RAM_GB": "32",
        "ONBOARD_TEST_CPUS": "10",
        "ONBOARD_TEST_VM": "0",
        "ONBOARD_TEST_ADMIN": "1",
        "ONBOARD_TEST_NEEDS_ADMIN": "0",
        **seams,
    }
    (tmp_path / "run").mkdir(exist_ok=True)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _home_files(tmp_path: Path) -> list[Path]:
    return sorted(p for p in (tmp_path / "home").rglob("*"))


def test_the_script_parses_under_the_stock_bash() -> None:
    bash = "/bin/bash" if os.path.exists("/bin/bash") else "bash"
    result = subprocess.run(
        [bash, "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_no_unbraced_expansion_touches_a_multibyte_character() -> None:
    """A bare $name before a multibyte byte is an unbound variable on bash 3.2.

    `bash -n` cannot catch this: the script parses, then dies at expansion time.
    Stock /bin/bash 3.2 absorbs the leading byte of a UTF-8 character into the
    variable name, so `$f\u2026` expands as `$f` plus 0xE2 -- unbound, and
    `set -u` ends the run. Braces settle it. Found by the OMN-20224 bare-Mac
    walk, where it killed phase 1 right after Homebrew installed.
    """
    offenders = [
        (i, line.decode("utf-8", "replace").strip())
        for i, line in enumerate(SCRIPT.read_bytes().split(b"\n"), 1)
        if UNBRACED_MULTIBYTE_EXPANSION.search(line)
    ]
    assert not offenders, (
        "brace these expansions; on bash 3.2 the multibyte character joins the "
        f"variable name: {offenders}"
    )


def test_the_multibyte_expansion_guard_would_catch_the_regression() -> None:
    """Prove the guard catches the regression and accepts the braced form."""
    assert UNBRACED_MULTIBYTE_EXPANSION.search(b'echo "Installing $f\xe2\x80\xa6"')
    assert not UNBRACED_MULTIBYTE_EXPANSION.search(
        b'echo "Installing ${f}\xe2\x80\xa6"'
    )


def test_phase_2_declares_the_workspace_runtime_config() -> None:
    """OMN-20371: a bound workspace root with no tier-1 config is REFUSED.

    Phase 2 exports OMNIBASE_PATH, which makes the workspace a registry
    workspace, and `resolve_embedded_runtime_config` then refuses a bound root
    that declares no `config/onex/runtime/runtime_config.yaml` rather than
    answering with the shipped in-memory default (OMN-19193). Before this, a
    freshly onboarded machine could not run a bare `onex delegate` at all, and
    `/onex:delegate` in Claude Code failed on its first attempt.
    """
    text = SCRIPT.read_text()
    assert "config/onex/runtime/runtime_config.yaml" in text, (
        "phase 2 must declare the workspace's tier-1 runtime config; a bound "
        "root without it is refused"
    )
    assert "write_workspace_runtime_config" in text
    # Written in phase 2, and a resumed run repairs a workspace that lacks it.
    assert "workspace_runtime_config_present || return 1" in text, (
        "phase2_verified must require the config, so a re-run on a workspace "
        "set up before this change writes it"
    )


def test_the_declared_transport_names_no_lab_address() -> None:
    """The config is generated, never vendored from the canonical tree.

    The canonical workspace's own tier-1 config declares the lab's dev lane.
    Copying it here
    would put a lab address on a developer machine, which AC5 of OMN-20150
    forbids, so the generated file declares the in-memory bus instead.
    """
    text = SCRIPT.read_text()
    start = text.index("write_workspace_runtime_config()")
    body = text[start : text.index("workspace_runtime_config_present()")]
    assert 'type: "inmemory"' in body
    assert 'profile: "local"' in body
    # No dotted-quad address, no tailnet name, no lane: built from parts so this
    # assertion does not itself become the hardcoded-address it forbids.
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", body)
    assert "ts" + ".net" not in body
    assert "lane:" not in body


def test_the_scripts_own_delegation_uses_the_developers_command() -> None:
    """The phase-3 check must not pass through a flag a developer never types.

    It used to run `onex delegate --bus inmemory`, which succeeded on machines
    where the bare command a developer runs was refused -- so phase 6 reported
    a delegation row while `/onex:delegate` failed. The check now runs the bare
    command, against the transport phase 2 declared.
    """
    text = SCRIPT.read_text()
    start = text.index("delegate_hello() {")
    whole = text[start : text.index("\n}", start)]
    # Comments may name the flag to explain its absence; only code counts.
    body = "\n".join(
        line for line in whole.splitlines() if not line.lstrip().startswith("#")
    )
    assert "--bus" not in body, (
        "delegate_hello must not select a transport: the declared workspace "
        "config is what a developer's own command resolves"
    )
    assert (
        'env -u PYTHONPATH "$WORKSPACE/.onex-dispatch-venv/bin/onex" '
        'delegate --json "Reply with exactly one word: hello"'
    ) in body


def test_the_script_names_no_lab_host() -> None:
    """The plugin is public: lab addresses come from the workspace, never the script."""
    text = SCRIPT.read_text()
    # Assembled, so this test does not itself put a lab address in the tree.
    needles = (
        ".ts" + ".net",
        "192" + ".168.",
        "100" + ".64.",
        "omninode" + "-pc",
        "omni" + "pc2",
    )
    for needle in needles:
        assert needle not in text, needle


def test_below_minimum_exits_3_and_writes_nothing_under_home(tmp_path: Path) -> None:
    result = _run(tmp_path, ONBOARD_TEST_RAM_GB="4")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "below the minimum requirements" in result.stdout
    assert "Nothing was installed" in result.stdout
    assert "VM" in result.stdout
    assert _home_files(tmp_path) == []


def test_preflight_only_changes_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, "--preflight-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Preflight only: nothing was changed." in result.stdout
    assert _home_files(tmp_path) == []


def test_a_vm_is_never_given_containers(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--preflight-only",
        ONBOARD_TEST_VM="1",
        ONBOARD_TEST_RAM_GB="64",
        ONBOARD_TEST_CPUS="16",
    )
    assert result.returncode == 0
    assert "No local Docker" in result.stdout
    assert "Docker Desktop cannot run inside a macOS guest" in result.stdout


def test_containers_are_offered_not_imposed(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--preflight-only",
        ONBOARD_TEST_VM="0",
        ONBOARD_TEST_RAM_GB="32",
        ONBOARD_TEST_CPUS="10",
    )
    assert result.returncode == 0
    if "ports in use" not in result.stdout:
        assert "Docker can be added (you will be asked)" in result.stdout


def test_containers_when_asked_for(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--preflight-only",
        "--containers",
        ONBOARD_TEST_VM="0",
        ONBOARD_TEST_RAM_GB="32",
        ONBOARD_TEST_CPUS="10",
    )
    assert result.returncode == 0
    if "ports in use" not in result.stdout:
        assert "and the stack locally in Docker" in result.stdout


def test_no_containers_is_honoured(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--preflight-only",
        "--no-containers",
        ONBOARD_TEST_RAM_GB="32",
        ONBOARD_TEST_CPUS="10",
    )
    assert "No local Docker: --no-containers was passed" in result.stdout


def test_containers_asked_for_on_a_mac_that_cannot_run_them_continue_without(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        "--preflight-only",
        "--containers",
        ONBOARD_TEST_RAM_GB="8",
        ONBOARD_TEST_CPUS="4",
    )
    assert result.returncode == 0
    assert "Docker is not offered on this Mac" in result.stdout
    assert "onex runs your delegations natively on this Mac" in result.stdout


@pytest.mark.parametrize(
    ("docker", "floor"),
    [("not installed", "30 GB"), ("installed, not running", "20 GB")],
)
def test_disk_floor_depends_on_whether_docker_is_installed(
    tmp_path: Path, docker: str, floor: str
) -> None:
    result = _run(
        tmp_path,
        "--preflight-only",
        ONBOARD_TEST_DOCKER=docker,
        ONBOARD_TEST_DISK_GB="25",
    )
    line = next(ln for ln in result.stdout.splitlines() if "Free disk" in ln)
    assert line.rstrip().endswith(floor)
    assert f"Docker Desktop         {docker}" in result.stdout


def test_status_file_records_each_phase(tmp_path: Path) -> None:
    _run(tmp_path, "--preflight-only")
    status = (tmp_path / "run" / "omninode-onboarding" / "status").read_text()
    assert 'phase=0 name="Preflight' in status
    assert "result=PASS" in status


def test_each_phase_reports_when_it_finishes_with_its_elapsed_time(
    tmp_path: Path,
) -> None:
    """AC7: the developer learns a phase's result when it ends, not at the end.

    The run prints the phase's start, then PASS or FAIL with elapsed time. A
    preflight-only run is the whole of phase 0, so its own output carries both.
    """
    result = _run(tmp_path, "--preflight-only")
    out = result.stdout + result.stderr
    assert "Phase 0/6: Preflight" in out, out
    # PASS and an elapsed time on the same line, the time in the script's own
    # `elapsed` spelling (seconds, or minutes and seconds).
    assert re.search(r"Phase 0/6 PASSED: Preflight[^\n]*\((?:\d+m )?\d+s\)", out), out


def test_the_log_file_path_is_printed_before_any_work(tmp_path: Path) -> None:
    """AC7: the log file's path is printed first.

    A developer who has to ask where the log is has already lost the failure
    they wanted it for, so the path precedes the first requirement line.
    """
    result = _run(tmp_path, "--preflight-only")
    out = result.stdout + result.stderr
    log_at = out.find("Log file:")
    assert log_at != -1, out
    for later in ("Requirement", "Phase 0/6 PASSED"):
        assert out.find(later) > log_at, f"{later!r} precedes the log path\n{out}"


def test_a_failure_names_the_step_the_attempts_the_error_and_what_to_do() -> None:
    """AC7: a failure names the step, the attempt count, the last error and the
    next thing to do -- at the moment it happens, not only in a final summary.

    Asserted against `phase_fail`, which is the one place every phase failure is
    reported. The OMN-20224 walk observed all four live: an injected network
    failure printed `Step: download the Homebrew installer (after 3 attempt(s))`,
    the curl error, and the next action, before the run ended.
    """
    text = SCRIPT.read_text()
    start = text.index("phase_fail() {")
    body = text[start : text.index("\n}", start)]
    assert "FAILED: $PHASE_NAME" in body
    assert "after $FAILED_ATTEMPTS attempt(s)" in body
    assert "Step:" in body and "Last error:" in body and "Next:" in body
    assert "Log:" in body
    # Reported by `say`, which writes to the terminal as well as the log, so the
    # failure is visible when it happens rather than in a summary.
    assert "say " in body


def test_retries_are_at_least_three_and_wait_five_to_ten_seconds() -> None:
    text = SCRIPT.read_text()
    assert '[ "$RETRIES" -lt 3 ] && RETRIES=3' in text
    assert "wait=$(( (RANDOM % 6) + 5 ))" in text


def test_skill_starts_the_run_in_a_terminal_and_keeps_secrets_out_of_the_session() -> (
    None
):
    text = SKILL.read_text()
    assert "--preflight-only" in text
    assert 'tell application \\"Terminal\\"' in text
    assert "Never ask the developer to paste a password or API key into this" in text


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [("y", "and the stack locally in Docker"), ("n", "No local Docker: you said no")],
)
def test_one_question_after_preflight_decides_docker(
    tmp_path: Path, answer: str, outcome: str
) -> None:
    """No flag: the developer is asked once, on a terminal, and the answer decides Docker."""
    phase0_only = tmp_path / "phase0.sh"
    phase0_only.write_text(SCRIPT.read_text().replace("\nmain\n", "\nphase0\n"))
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "run").mkdir()
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(tmp_path / "run") + "/",
        "TERM": "dumb",
        "ONBOARD_NOTIFY": "0",
        "ONBOARD_TEST_OS": "Darwin",
        "ONBOARD_TEST_MACOS": "14.5",
        "ONBOARD_TEST_PORTS_BUSY": "",
        "ONBOARD_TEST_DISK_GB": "100",
        "ONBOARD_TEST_RAM_GB": "32",
        "ONBOARD_TEST_CPUS": "10",
        "ONBOARD_TEST_VM": "0",
        "ONBOARD_TEST_ADMIN": "1",
        "ONBOARD_TEST_NEEDS_ADMIN": "0",
        "ONBOARD_TEST_NO_GUI": "1",
        # Docker present, so a yes asks no licence question (CI runners have none).
        "ONBOARD_TEST_DOCKER": "running",
        "ONBOARD_TEST_CATALOGUE": _catalogue(tmp_path, _default_lists()),
    }
    out, _returncode = _drive_tty(
        ["/bin/bash", str(phase0_only), "--provider", "gemini"],
        env,
        [
            ("(input is hidden):", "AIza-not-a-real-key"),
            ("Choose your Gemini models", "1"),
            ("Continue?", "y"),
            ("Set up the local stack in Docker too?", answer),
        ],
    )
    assert "You're already covered" in out
    assert outcome in out


# ---------------------------------------------------------------------------
# OMN-17099: the containers run the developer's model and key, not a template's.
# ---------------------------------------------------------------------------


def _function_body(name: str, source: Path | None = None) -> str:
    """The text of one top-level shell function, from its first line to its `}`,
    from ``source`` or else the script and its bootstrap handler."""
    lines = (
        source.read_text(encoding="utf-8")
        if source
        else SCRIPT.read_text(encoding="utf-8") + HANDLER.read_text(encoding="utf-8")
    ).splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() "))
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def test_the_key_reaches_the_stack_by_pipe_and_never_as_an_argument_or_variable() -> (
    None
):
    body = _function_body("register_key_in_stack")
    assert "| make -s" in body
    assert "secret-local PROVIDER=" in body
    # The value is read and written inside the python heredoc only.
    assert "sys.stdout.write(value)" in body
    for forbidden in ("KEY=", "VALUE=", "export ", "SECRET="):
        assert forbidden not in body


def _boot_resources(free: int, disk: int) -> tuple[int, str, str]:
    """Run the boot-threshold check with the two readings stubbed."""
    program = "\n".join(
        [
            "set -u",
            f"BOOT_FREE_MEM_GB={BOOT_FREE_MEM_GB}",
            f"BOOT_FREE_DISK_GB={BOOT_FREE_DISK_GB}",
            f"avail_mem_gb() {{ echo {free}; }}",
            f"disk_free_gb() {{ echo {disk}; }}",
            _functions("boot_resources_ok"),
            "boot_resources_ok; rc=$?",
            'printf "%s\\n%s\\n" "$BOOT_SHORT" "$BOOT_REMEDY"',
            "exit $rc",
        ]
    )
    done = subprocess.run(
        ["/bin/bash", "-c", program],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    short, remedy = (done.stdout.split("\n") + ["", ""])[:2]
    return done.returncode, short, remedy


def _constant(name: str) -> int:
    match = re.search(rf"^{name}=(\d+)", SCRIPT.read_text(), re.M)
    assert match, name
    return int(match.group(1))


BOOT_FREE_MEM_GB = _constant("BOOT_FREE_MEM_GB")
BOOT_FREE_DISK_GB = _constant("BOOT_FREE_DISK_GB")
M2_DISK_GB_DOCKER_PRESENT = _constant("M2_DISK_GB_DOCKER_PRESENT")

# The figures OMN-20150 AC9 states for the moment the stack boots. Written out
# rather than read from the script, because the whole point of AC2 is that the
# criterion and the constant are one number: reading both from the same place
# would pass however far apart they drift.
AC9_BOOT_MEM_GB = 4
AC9_BOOT_DISK_GB = 15


def test_ample_resources_let_the_stack_boot() -> None:
    """AC1 (OMN-20394): both readings above their floors is not a shortfall."""
    rc, short, remedy = _boot_resources(BOOT_FREE_MEM_GB + 1, BOOT_FREE_DISK_GB + 300)
    assert rc == 0
    assert short == ""
    assert remedy == ""


def test_a_memory_shortfall_never_names_the_disk() -> None:
    """AC1 (OMN-20394): the passing reading is not reported as a cause."""
    rc, short, remedy = _boot_resources(BOOT_FREE_MEM_GB - 1, BOOT_FREE_DISK_GB + 261)
    assert rc != 0
    assert "memory available" in short
    assert "disk" not in short, short
    assert remedy == "close other apps"


def test_a_disk_shortfall_never_names_the_memory() -> None:
    """AC1 (OMN-20394): and the same the other way round."""
    rc, short, remedy = _boot_resources(BOOT_FREE_MEM_GB + 8, BOOT_FREE_DISK_GB - 1)
    assert rc != 0
    assert "disk free" in short
    assert "memory" not in short, short
    assert remedy == "free disk space"


def test_both_short_names_both_and_both_remedies() -> None:
    """AC1 (OMN-20394): when both fail, both are named -- the AND was only wrong
    when one of them passed."""
    rc, short, remedy = _boot_resources(BOOT_FREE_MEM_GB - 1, BOOT_FREE_DISK_GB - 1)
    assert rc != 0
    assert "memory available" in short and "disk free" in short
    assert remedy == "close other apps and free disk space"


def test_the_failure_message_is_built_only_from_the_failing_clause() -> None:
    """AC1 (OMN-20394): phase 4 reports the helper's text, not both thresholds."""
    phase_4 = _function_body("phase4")
    assert "boot_resources_ok" in phase_4
    assert "$BOOT_SHORT" in phase_4
    assert "needs $BOOT_FREE_DISK_GB" not in phase_4


def test_the_boot_floors_are_the_figures_ac9_states() -> None:
    """AC2 (OMN-20394): the enforced boot floor and the figure the criterion
    states are the same number. AC9 said 30 GB until 2026-10-05, which was the
    Mode 2 PREFLIGHT floor written into a clause about boot time -- the script
    enforced 15 and the criterion could not be walked as written."""
    assert BOOT_FREE_MEM_GB == AC9_BOOT_MEM_GB
    assert BOOT_FREE_DISK_GB == AC9_BOOT_DISK_GB


def test_no_boot_floor_exceeds_what_preflight_already_admitted() -> None:
    """AC2 (OMN-20394): why 15 is the side that moved, not 30. Preflight admits
    Mode 2 at 20 GB once Docker Desktop is installed, so a boot floor above
    that admits a Mac and then refuses it in phase 4 -- the admit-then-refuse
    shape this ticket exists to remove. Any future raise has to move the
    preflight floor with it."""
    assert BOOT_FREE_DISK_GB <= M2_DISK_GB_DOCKER_PRESENT


def _phase0_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (tmp_path / "run").mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(tmp_path / "run") + "/",
        "TERM": "dumb",
        "ONBOARD_NOTIFY": "0",
        "ONBOARD_TEST_OS": "Darwin",
        "ONBOARD_TEST_MACOS": "14.5",
        "ONBOARD_TEST_PORTS_BUSY": "",
        "ONBOARD_TEST_NO_GUI": "1",
        "ONBOARD_TEST_DISK_GB": "100",
        "ONBOARD_TEST_RAM_GB": "32",
        "ONBOARD_TEST_CPUS": "10",
        "ONBOARD_TEST_VM": "0",
        "ONBOARD_TEST_ADMIN": "1",
        "ONBOARD_TEST_NEEDS_ADMIN": "0",
        # OMN-21058: no test reaches a real provider's model list or omnimarket.
        "ONBOARD_TEST_CATALOGUE": _catalogue(tmp_path, _default_lists()),
        **extra,
    }


def _phase0_only(tmp_path: Path) -> Path:
    p = tmp_path / "phase0.sh"
    p.write_text(SCRIPT.read_text().replace("\nmain\n", "\nphase0\n"))
    return p


# OMN-21058: a stand-in for each provider's model list, so no test that enters a
# key reaches a real provider. ``routes`` maps a provider to (status, body); the
# rest serve _DEFAULT_LISTS. Each request's Authorization lands in ``auth``.
_DEFAULT_LISTS: dict[str, object] = {
    "gemini": {
        "data": [
            {"id": "models/gemini-3-flash-lite"},
            {"id": "models/gemini-3-flash"},
        ]
    },
    "openrouter": {"data": [{"id": "fx/free-a:free"}, {"id": "fx/free-b:free"}]},
    "openai": {"data": [{"id": "gpt-4.1-nano"}, {"id": "gpt-4.1-mini"}]},
}


def _start_models_server(
    routes: dict[str, tuple[int, object]] | None = None,
) -> tuple[ThreadingHTTPServer, dict[str, Any]]:
    served: dict[str, Any] = {"auth": {}}
    table = {p: (200, body) for p, body in _DEFAULT_LISTS.items()} | (routes or {})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            provider = self.path.strip("/")
            served["auth"].setdefault(provider, []).append(
                self.headers.get("Authorization")
            )
            status, body = table.get(provider, (404, {"error": {"message": "no"}}))
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    served["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    return server, served


@contextmanager
def _models_server(
    routes: dict[str, tuple[int, object]] | None = None,
) -> Iterator[dict[str, Any]]:
    server, served = _start_models_server(routes)
    try:
        yield served
    finally:
        server.shutdown()
        server.server_close()


# One server for every test that does not serve its own lists. It is never shut
# down: its thread is a daemon and ends with the test process, and a shutdown
# at interpreter exit would wait on a thread that no longer runs.
_DEFAULT_URL: list[str] = []


def _default_lists() -> str:
    if not _DEFAULT_URL:
        _DEFAULT_URL.append(_start_models_server()[1]["url"])
    return _DEFAULT_URL[0]


def _catalogue(tmp_path: Path, base: str) -> str:
    """A provider catalogue shaped like omnimarket's, its lists served at ``base``."""
    path = tmp_path / f"catalogue-{abs(hash(base))}.yaml"
    path.write_text(
        "providers:\n"
        "  - provider: openrouter\n"
        "    plan: free_tier\n"
        f'    models_url: "{base}/openrouter"\n'
        "    model_preference:\n"
        "      - pattern: 'fx/fam-(?P<generation>[0-9]+)-it:free'\n"
        "        tags: [free]\n"
        "  - provider: gemini\n"
        f'    models_url: "{base}/gemini"\n'
        "    model_preference:\n"
        "      - pattern: 'gemini-(?P<generation>[0-9]+(?:\\.[0-9]+)?)-flash-lite'\n"
        "      - pattern: 'gemini-(?P<generation>[0-9]+(?:\\.[0-9]+)?)-flash'\n"
        "  - provider: openai\n"
        f'    models_url: "{base}/openai"\n'
        "    model_preference:\n"
        "      - pattern: 'gpt-4\\.(?P<generation>[0-9]+)-nano'\n"
        "  - provider: anthropic\n"
        f'    models_url: "{base}/not-this-one"\n' + _LOCAL_BLOCK
    )
    return str(path)


# The catalogue's `local` row: one Ollama model per memory class (OMN-21215),
# which onboarding lists for Ollama, the one sized to this Mac recommended.
_LOCAL_BLOCK = (
    "local:\n"
    "  default_models: [fixture-ollama-small, fixture-ollama-mid, fixture-ollama-huge]\n"
    "  memory_classes:\n"
    '    - memory_class: "8gb"\n'
    "      min_memory_gb: 8\n"
    "      model: fixture-ollama-small\n"
    "      server: ollama\n"
    "      download_gb: 1\n"
    '    - memory_class: "16gb"\n'
    "      min_memory_gb: 16\n"
    "      model: fixture-ollama-mid\n"
    "      server: ollama\n"
    "      download_gb: 5\n"
    '    - memory_class: "64gb_plus"\n'
    "      min_memory_gb: 64\n"
    '      model: "fixture-ollama-huge"\n'
    "      server: ollama\n"
    "      download_gb: 40\n"
    "recommended_order:\n"
    "  onboarding: baseline\n"
    "  orders:\n"
    "    baseline:\n"
    "      models: default_models\n"
    '      basis: "OMN-21215"\n'
    "  classes:\n"
    "    code_generation: baseline\n"
    "not_offered: []\n"
)


def _listed(out: str, heading: str) -> list[str]:
    """The model ids numbered under ``heading``, in the order shown."""
    listing = out.split(heading, 1)[1].split("Pick one or more", 1)[0]
    return [
        ln.split(") ", 1)[1].split("  (recommended)")[0]
        for ln in listing.splitlines()
        if re.match(r"^ +[0-9]+\) ", ln)
    ]


@pytest.mark.parametrize("provider", ["none", "glm"])
def test_only_the_beta_providers_are_accepted(tmp_path: Path, provider: str) -> None:
    """No lab-model fallback, and GLM is out of the beta: gemini, openrouter, openai,
    ollama or a local model server by URL (OMN-21163)."""
    result = _run(tmp_path, "--provider", provider)
    assert result.returncode == 2
    assert "must be gemini, openrouter, openai, ollama or local" in result.stderr


def test_no_key_and_nobody_to_ask_stops_before_installing(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        env=_phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 1, result.stdout
    assert "Nothing was installed" in result.stdout
    assert sorted((tmp_path / "home").rglob("*")) == []


def _stored_keys(tmp_path: Path, *providers: str) -> None:
    """A fake `onex` whose `secret list` reports keys an earlier run stored."""
    bindir = tmp_path / "home" / ".local" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"    llm.{p}.api_key  (updated 2026-10-02)\n" for p in providers)
    onex = bindir / "onex"
    onex.write_text(f'#!/bin/sh\n[ "$1" = secret ] || exit 1\ncat <<EOF\n{rows}EOF\n')
    onex.chmod(0o755)


def _functions(*names: str, source: Path | None = None) -> str:
    """The named top-level functions of ``source``, or of the script and its
    bootstrap handler, as bash source."""
    # The public retry wrappers depend on the shared engine after consolidation.
    if "retry" in names or "retry_capture" in names:
        names = (*names, "retry_command")
    text = source.read_text() if source else SCRIPT.read_text() + HANDLER.read_text()
    out, keep = [], False
    for line in text.splitlines():
        if any(line.startswith(f"{n}() {{") for n in names):
            keep = True
        if keep:
            out.append(line)
            if line == "}":
                keep = False
    return "\n".join(out)


def test_phase5_installs_the_full_onex_tree_and_omni_only_with_developer() -> None:
    """The customer default is the delegate-only plugin (OMN-17427)."""
    text = SCRIPT.read_text()
    assert '[ "$DEVELOPER" -eq 1 ] && { WANT_PLUGIN=onex@omninode-tools-dev;' in text
    assert 'plugin install "$want"' in text
    assert 'if [ "$DEVELOPER" -eq 0 ]; then' in text
    assert (
        'plugin marketplace add "$WORKSPACE/omniclaude/plugins/"*-dev-marketplace'
        in text
    )
    assert "for p in omni onex-overlays" in text
    assert "internal_plugins_reachable" in text


def test_nothing_connects_to_the_lab() -> None:
    """Developers run onex locally only: no tailnet, no lab bus identity, no lab model."""
    text = SCRIPT.read_text()
    for gone in (
        "tailscale",
        "lane-login",
        "principal_issuer_url",
        "lab_model_url",
        "developer-onboarding.yaml",
        "--bus kafka",
        "--reissue-identity",
    ):
        assert gone not in text.lower(), gone
    assert "TOTAL_PHASES=6" in text
    assert 'DONE_FILE="$STATE_DIR/phases.v2.done"' in text


def test_a_resumed_run_finds_the_tools_phase_1_installed(tmp_path: Path) -> None:
    """Phase 1 skipped on a re-run must not leave uv and onex off PATH for later phases."""
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    probe = SCRIPT.read_text().split("\nIS_TTY=0\n", 1)[0] + '\necho "PATH=$PATH"\n'
    script = tmp_path / "head.sh"
    script.write_text(probe)
    out = subprocess.run(
        ["/bin/bash", str(script)],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path) + "/"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    ).stdout
    assert f"{home}/.local/bin" in out.split("PATH=", 1)[1].split(":")


# ---------------------------------------------------------------------------
# Ollama: a model on this Mac, no key.
# ---------------------------------------------------------------------------


def _shell(snippet: str, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "-c", snippet],
        env={
            "HOME": str(home),
            "STAMP": "t",
            "PATH": "/usr/bin:/bin",
            "LOG": "/dev/null",
        },
        capture_output=True,
        text=True,
        check=True,
    )


_TEMPLATE_OVERLAY = (
    'backends:\n  - backend_id: local-coder\n    endpoint_url: &model_endpoint "http://host.docker.internal:8000/v1/chat/completions"\n'
    '    served_model_id: "a-placeholder-model"\n'
    '  - backend_id: local-heavy-reasoning\n    endpoint_url: *model_endpoint\n    served_model_id: "a-placeholder-model"\n'
)


@pytest.mark.parametrize("theirs", [False, True])
def test_docker_with_ollama_points_only_the_untouched_template_at_it(
    tmp_path: Path, theirs: bool
) -> None:
    home = tmp_path / "home"
    (home / ".omnibase").mkdir(parents=True)
    overlay = home / ".omnibase" / "local.bifrost.yaml"
    original = (
        _TEMPLATE_OVERLAY.replace("host.docker.internal:8000", "my-box:9000")
        if theirs
        else _TEMPLATE_OVERLAY
    )
    overlay.write_text(original)
    _shell(
        _functions("sed_inplace", "point_bundle_model")
        + '\npoint_bundle_model "http://host.docker.internal:11434/v1/chat/completions" "qwen2.5-coder:7b"\n',
        home,
    )
    text = overlay.read_text()
    if theirs:
        assert text == original
    else:
        assert (
            '&model_endpoint "http://host.docker.internal:11434/v1/chat/completions"'
            in text
        )
        assert text.count('served_model_id: "qwen2.5-coder:7b"') == 2
        assert "a-placeholder-model" not in text


def test_ollama_in_a_vm_is_warned_it_will_be_slow(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--provider", "ollama"],
        env=_phase0_env(
            tmp_path,
            ONBOARD_TEST_VM="1",
            ONBOARD_TEST_RAM_GB="32",
            ONBOARD_TEST_CPUS="10",
        ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "This is a virtual machine: Ollama gets little or no GPU in a VM"
        in result.stdout
    )
    assert (
        "Gemini, OpenRouter or OpenAI (a key) is the better choice here."
        in result.stdout
    )


def test_the_run_ends_by_saying_to_sign_in_to_claude_code() -> None:
    text = SCRIPT.read_text()
    assert (
        "Open Claude Code (run 'claude') and sign in with your Anthropic account"
        in text
    )


def test_ollama_asks_for_no_key_and_chooses_the_model_later(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "/bin/bash",
            str(_phase0_only(tmp_path)),
            "--provider",
            "ollama",
            "--no-containers",
        ],
        env=_phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "Model: Ollama on this Mac, no key. The model is chosen for this Mac's 32 GB"
        in result.stdout
    )
    assert "API key" not in result.stdout
    assert sorted((tmp_path / "home").rglob("*")) == []


_OLLAMA_BLOCK = """\
backends: []
ollama:
  port: 11434
  chat_path: /v1/chat/completions
  models:
    - min_memory_gb: 16
      model: big-model:7b
      download_gb: 5
    - min_memory_gb: 0
      model: small-model:1b
      download_gb: 1
"""


def _workspace_with_config(tmp_path: Path, block: str) -> Path:
    ws = tmp_path / "ws"
    cfg = (
        ws / "omnimarket" / "src" / "omnimarket" / "configs" / "bifrost_delegation.yaml"
    )
    cfg.parent.mkdir(parents=True)
    cfg.write_text(block)
    venv_bin = ws / ".onex-dispatch-venv" / "bin"
    venv_bin.mkdir(parents=True)
    shim = venv_bin / "python"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    return ws


def _ollama_config(
    ws: Path, ram: str, model: str = ""
) -> subprocess.CompletedProcess[str]:
    consts = "\n".join(
        line
        for line in SCRIPT.read_text().splitlines()
        if line.startswith("OLLAMA_CONFIG_REL=")
    )
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            f"WORKSPACE={ws}\n{consts}\n"
            + _functions("ollama_config")
            + f'\nollama_config {ram} "{model}"\n',
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    ("ram", "model", "expected"),
    [
        ("32", "", "11434 /v1/chat/completions big-model:7b 5"),
        ("16", "", "11434 /v1/chat/completions big-model:7b 5"),
        ("8", "", "11434 /v1/chat/completions small-model:1b 1"),
        ("8", "big-model:7b", "11434 /v1/chat/completions big-model:7b 5"),
        ("8", "unlisted:3b", "11434 /v1/chat/completions unlisted:3b 5"),
    ],
)
def test_the_ollama_model_comes_from_the_model_config_by_memory(
    tmp_path: Path, ram: str, model: str, expected: str
) -> None:
    result = _ollama_config(_workspace_with_config(tmp_path, _OLLAMA_BLOCK), ram, model)
    assert result.stdout.strip() == expected, result.stderr


def test_a_model_config_without_the_ollama_block_is_refused(tmp_path: Path) -> None:
    result = _ollama_config(_workspace_with_config(tmp_path, "backends: []\n"), "32")
    assert result.returncode != 0
    assert "no complete ollama block" in result.stderr


def test_the_script_holds_no_model_name_port_or_model_path() -> None:
    """The hardcoded-model-config gate's rule: those live in the model config, and
    the OpenRouter default lives in the onex-overlays overlay (OMN-20844, AC3), so
    the script names no model at all."""
    text = SCRIPT.read_text()
    assert not re.search(r"qwen|llama[0-9]|11434", text)
    assert "/v1/chat/completions" not in text
    assert not re.search(r"^OPENROUTER_MODEL=.+", text.replace('=""', "="), re.M)


def test_ollama_routes_are_written_and_a_foreign_file_is_kept(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = home / ".omninode" / "delegation" / "bifrost_overrides.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("# mine\nbackends: []\n")
    consts = "\n".join(
        line
        for line in SCRIPT.read_text().splitlines()
        if line.startswith(("OVERRIDES_FILE_REL=", "OLLAMA_MARK="))
    )
    _shell(
        consts
        + '\nOLLAMA_URL="http://127.0.0.1:11434"; OLLAMA_CHAT_PATH="/v1/chat/completions"'
        + "\nsay() { :; }\n"
        + _functions("ollama_overrides_ours", "write_ollama_overrides")
        + '\nwrite_ollama_overrides "big-model:7b"\n',
        home,
    )
    text = target.read_text()
    assert text.startswith("# Written by omninode-dev-setup: Ollama on this Mac.")
    assert text.count('endpoint_url: "http://127.0.0.1:11434/v1/chat/completions"') == 2
    assert text.count('model_name: "big-model:7b"') == 2
    assert (
        target.parent / "bifrost_overrides.yaml.pre-onboarding.t"
    ).read_text() == "# mine\nbackends: []\n"


def test_a_vm_is_told_before_any_question(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--provider", "ollama"],
        env=_phase0_env(
            tmp_path,
            ONBOARD_TEST_VM="1",
            ONBOARD_TEST_RAM_GB="32",
            ONBOARD_TEST_CPUS="10",
        ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = result.stdout
    assert "We detected that this Mac is a virtual machine." in out
    assert "Docker can't run inside a macOS VM" in out
    assert out.index("We detected that this Mac is a virtual machine.") < out.index(
        "Model: Ollama on this Mac"
    )


def test_the_docker_question_leads_with_what_was_found() -> None:
    text = SCRIPT.read_text()
    for found in (
        "We found Docker Desktop on this Mac, and it's running.",
        "We found Docker Desktop on this Mac, but it isn't running.",
        "Docker Desktop isn't installed on this Mac.",
    ):
        assert found in text


def test_workspace_config_is_written_to_declared_owner(tmp_path: Path) -> None:
    text = SCRIPT.read_text()
    start = text.index("write_workspace_runtime_config()")
    functions = text[start : text.index("phase2_verified()", start)]
    root = tmp_path / "workspace"
    owner = root / ".onex/workspace-config"
    env = {
        **os.environ,
        "WORKSPACE": str(root),
        "WORKSPACE_CONFIG_ROOT": str(owner),
        "WORKSPACE_RUNTIME_CONFIG_REL": "config/onex/runtime/runtime_config.yaml",
        "WORKSPACE_RUNTIME_CONFIG_MARK": "# Written by omninode-dev-setup.",
    }
    subprocess.run(
        [
            "bash",
            "-c",
            functions
            + "\nwrite_workspace_runtime_config; workspace_runtime_config_present",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    target = owner / "config/onex/runtime/runtime_config.yaml"
    assert target.is_file()
    assert 'type: "inmemory"' in target.read_text()
    assert not (root / "config").exists()


# ---------------------------------------------------------------------------
# OMN-20818: several models in one pass, every question in the terminal and up
# front. Any combination of Gemini, OpenRouter, OpenAI and Ollama, at least one;
# each key asked for one at a time, naming its provider.
# ---------------------------------------------------------------------------

_MENU = "Choose one or more, e.g. 1,3,4:"
_HIDDEN = "(input is hidden):"


def _preflight(
    tmp_path: Path,
    steps: list[tuple[str, str]],
    *args: str,
    timeout: float = 120,
    **extra: str,
) -> tuple[str, int]:
    return _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers", *args],
        _phase0_env(tmp_path, **extra),
        steps,
        timeout=timeout,
    )


def test_no_question_is_a_dialog() -> None:
    """AC1: model choice, keys, Docker, its terms and the password are all asked
    in the terminal; the only osascript left is the notification and quitting
    Docker for a restart."""
    text = SCRIPT.read_text()
    assert not re.search(r"display dialog|choose from list|SUDO_ASKPASS", text)
    assert "PROMPT_TTY=$IS_TTY" in text


@pytest.mark.parametrize("answer", ["1,3,4", "1 3 4", "134", "4,1,3", "1,1,3,4"])
def test_several_models_are_chosen_by_number(tmp_path: Path, answer: str) -> None:
    """AC3: every spelling of the same picks chooses the same models, in menu order."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, answer),
            (_HIDDEN, "AIza-g"),
            ("Choose your Gemini models", "1"),
            (_HIDDEN, "sk-proj-o"),
            ("Choose your OpenAI models", "1"),
            ("Choose your Ollama models", "1"),
            ("Continue?", "q"),
        ],
    )
    assert "You chose: Gemini, OpenAI, Ollama" in out


@pytest.mark.parametrize("answer", ["", "6", "0", "x"])
def test_an_empty_or_out_of_range_choice_asks_again(
    tmp_path: Path, answer: str
) -> None:
    out, _ = _preflight(
        tmp_path, [(_MENU, answer), ("Choose at least one, 1 to 5", "q")]
    )
    assert out.count(_MENU) == 2


def test_each_key_is_asked_one_at_a_time_naming_its_provider(tmp_path: Path) -> None:
    """AC4: one hidden prompt per keyed model, "n of m"; Ollama gets none."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "1,2,4"),
            ("Gemini key (1 of 2)", "AIza-g"),
            ("Choose your Gemini models", "1"),
            ("OpenRouter key (2 of 2)", "sk-or-v1-r"),
            ("Choose your OpenRouter models", "1"),
            ("Choose your Ollama models", "1"),
            ("Continue?", "q"),
        ],
    )
    assert "paste it from aistudio.google.com/apikey" in out
    assert "paste it from openrouter.ai/keys" in out
    assert "Ollama key" not in out
    assert "AIza-g" not in out and "sk-or-v1-r" not in out  # never echoed


@pytest.mark.parametrize(
    ("chosen", "key", "named"),
    [
        ("3", "sk-or-v1-abc", "an OpenRouter key, not an OpenAI key"),
        ("1", "sk-proj-abc", "an OpenAI key, not a Gemini key"),
        ("2", "sk-ant-abc", "an Anthropic (Claude) key, not an OpenRouter key"),
    ],
)
def test_a_key_for_another_provider_is_refused_and_asked_again(
    tmp_path: Path, chosen: str, key: str, named: str
) -> None:
    """AC5."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, chosen),
            (_HIDDEN, key),
            (_HIDDEN, ""),
            ("Skip", "y"),
            ("Choose at least one", "q"),
        ],
    )
    assert f"That looks like {named}." in out
    assert out.count(_HIDDEN) == 2


def test_an_empty_key_offers_to_skip_and_the_rest_carry_on(tmp_path: Path) -> None:
    """AC6: chose three, has two."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "1,2,3"),
            ("Gemini key", "AIza-g"),
            ("Choose your Gemini models", "1"),
            ("OpenRouter key", ""),
            ("Skip OpenRouter for now?", "y"),
            ("OpenAI key", "sk-proj-o"),
            ("Choose your OpenAI models", "1"),
            ("Continue?", "q"),
        ],
    )
    assert "Skipped OpenRouter. Add it any time: onex models add openrouter" in out
    summary = out.split("Ready to set up:")[1]
    assert "Gemini      key received" in summary
    assert "OpenAI      key received" in summary
    assert "OpenRouter  skipped (no key)" in summary


def test_n_at_the_skip_question_asks_for_the_key_again(tmp_path: Path) -> None:
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "1"),
            (_HIDDEN, ""),
            ("Skip Gemini for now?", "n"),
            (_HIDDEN, "AIza-g"),
            ("Choose your Gemini models", "1"),
            ("Continue?", "q"),
        ],
    )
    assert "Gemini key received." in out


def test_skipping_every_model_asks_the_choice_again(tmp_path: Path) -> None:
    """AC6: at least one model."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "1"),
            (_HIDDEN, ""),
            ("Skip", "y"),
            (_MENU, "q"),
        ],
    )
    assert "Every model was skipped. Choose at least one." in out
    assert out.count(_MENU) == 2


def test_a_stored_key_is_kept_with_enter_or_replaced(tmp_path: Path) -> None:
    """AC7."""
    _stored_keys(tmp_path, "openai")
    out, _ = _preflight(
        tmp_path,
        [(_MENU, "3"), ("stored; press Enter to keep it", ""), ("Continue?", "q")],
    )
    assert (
        "3) OpenAI      your key, from platform.openai.com/api-keys (needs credits)  (key stored)"
        in out
    )
    assert "Keeping your stored OpenAI key." in out
    assert "OpenAI      your stored key" in out.split("Ready to set up:")[1]


def test_change_at_the_summary_keeps_keys_already_entered(tmp_path: Path) -> None:
    """AC8: c goes back to the choice; a key already entered is not asked again."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "1"),
            (_HIDDEN, "AIza-g"),
            ("Choose your Gemini models", "1"),
            ("Continue?", "c"),
            (_MENU, "1,3"),
            ("OpenAI key (2 of 2)", "sk-proj-o"),
            ("Choose your OpenAI models", "1"),
            ("Continue?", "q"),
        ],
    )
    assert "Gemini key (1 of 2): already entered." in out
    assert out.count("Gemini key (1 of") == 2  # the second time only says it is entered


def test_quit_at_the_summary_installs_nothing(tmp_path: Path) -> None:
    out, returncode = _preflight(
        tmp_path, [(_MENU, "4"), ("Choose your Ollama models", "1"), ("Continue?", "q")]
    )
    assert returncode == 4
    assert "Nothing was installed." in out
    assert sorted((tmp_path / "home").rglob("*")) == []


def test_every_question_comes_before_the_preflight_verdict(tmp_path: Path) -> None:
    """AC2: models, keys, Docker and its terms are all answered before phase 0 passes."""
    out, returncode = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path))],
        _phase0_env(
            tmp_path, ONBOARD_TEST_DOCKER="not installed", ONBOARD_TEST_DISK_GB="100"
        ),
        [
            (_MENU, "1"),
            (_HIDDEN, "AIza-g"),
            ("Choose your Gemini models", "1"),
            ("Continue?", "y"),
            ("Set up the local stack in Docker too?", "y"),
            ("Accept it now?", "y"),
        ],
    )
    assert returncode == 0, out[-600:]
    verdict = out.index("Phase 0/6 PASSED")
    for question in (_MENU, "Continue?", "Docker too?", "Accept it now?"):
        assert out.index(question) < verdict
    assert "Everything from here runs without questions." in out


def test_the_docker_terms_answer_is_used_in_phase_4_without_asking() -> None:
    body = _function_body("accept_docker_terms")
    assert "read" not in body
    assert '"$DOCKER_TERMS"' in body


def test_provider_takes_a_comma_separated_list(tmp_path: Path) -> None:
    """AC11: --provider gemini,ollama skips the menu and still asks Gemini's key."""
    out, _ = _preflight(
        tmp_path,
        [
            (_HIDDEN, "AIza-g"),
            ("Choose your Gemini models", "1"),
            ("Choose your Ollama models", "1"),
            ("Continue?", "q"),
        ],
        "--provider",
        "ollama,gemini",
    )
    assert _MENU not in out
    assert "Your models (from --provider): Gemini, Ollama" in out
    assert "Gemini key (1 of 1)" in out


def test_an_unattended_run_uses_every_stored_key(tmp_path: Path) -> None:
    _stored_keys(tmp_path, "gemini", "openai")
    result = subprocess.run(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        env=_phase0_env(tmp_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert (
        "No terminal to ask on, so these models are used: Gemini, OpenAI."
        in result.stdout
    )


def test_an_unattended_run_refuses_a_named_model_with_no_stored_key(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            "/bin/bash",
            str(_phase0_only(tmp_path)),
            "--no-containers",
            "--provider",
            "openai",
        ],
        env=_phase0_env(tmp_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 1
    assert "no key is stored for openai" in result.stdout
    assert "Nothing was installed" in result.stdout


def _phase3_harness(
    tmp_path: Path,
    answers: dict[str, str],
    skipped: str = "",
    preamble: str = 'KEY_GEMINI="AIza-g"\n',
) -> subprocess.CompletedProcess[str]:
    """Phase 3's model loop with `onex models` and the delegation faked.

    ``answers`` maps a provider, or ``provider:model``, to the JSON line the fake
    `onex models` prints when that provider is tested (``MODEL`` in it becomes
    the model the fake holds first). The fake keeps each key's ordered models as
    `add --model`, repeated, and `reorder` leave them, and `list --json` prints
    them, as the real command does. Each call's arguments, and whether a key came
    on stdin, land in ``calls``.
    """
    fake = tmp_path / "onex-models"
    calls = tmp_path / "calls"
    state = tmp_path / "onex-state"
    state.mkdir(exist_ok=True)
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        f"answers = json.loads({json.dumps(json.dumps(answers))})\n"
        f"state, calls = Path({str(state)!r}), Path({str(calls)!r})\n"
        "stdin = '' if sys.stdin.isatty() else sys.stdin.read()\n"
        "args = sys.argv[1:]\n"
        "with calls.open('a') as f:\n"
        "    f.write(' '.join(args) + f' stdin={len(stdin)}\\n')\n"
        "cmd = args[0]\n"
        "if cmd == 'list':\n"
        "    for f in sorted(state.glob('*.order')):\n"
        "        print(json.dumps({'provider': f.stem, 'models': f.read_text().split()}))\n"
        "    sys.exit(0)\n"
        "p = args[1]\n"
        "order = state / f'{p}.order'\n"
        "if cmd == 'reorder':\n"
        "    order.write_text(' '.join(args[2:]))\n"
        "    sys.exit(0)\n"
        "if cmd == 'add':\n"
        "    models = [args[i + 1] for i, a in enumerate(args) if a == '--model']\n"
        "    if models:\n"
        "        order.write_text(' '.join(models))\n"
        "first = order.read_text().split()[0] if order.exists() else ''\n"
        "line = answers.get(f'{p}:{first}') or answers.get(p)\n"
        "if line:\n"
        "    print(line.replace('MODEL', first))\n"
    )
    fake.chmod(0o755)
    providers = list(dict.fromkeys(k.split(":", 1)[0] for k in answers))
    snippet = (
        f'LOG=/dev/null; STATUS={tmp_path}/status; RUN_DIR={tmp_path}; MODELS="{" ".join(providers)}"; SKIPPED="{skipped}"\n'
        "say() { printf '%s\\n' \"$*\"; }\n"
        + _functions(
            "pending_key",
            "set_pending_key",
            "uses_key",
            "in_list",
            "provider_label",
            "receipt_field",
            "set_result",
            "result_of",
            "passed_models",
            "add_model_res",
            "result_line",
            "record_model_status",
            "cause_of",
            "model_result",
            "put_first",
            "onex_order",
            "setup_model",
            "count_words",
            "labels",
        )
        + "\n"
        + _functions("chosen_models", "set_chosen_models", "comma_list", source=HANDLER)
        + f'\nmodels_cmd() {{ "{fake}" "$@"; }}\n'
        + f'write_ollama_overrides() {{ echo "overrides $1" >>"{calls}"; echo "$1" >"{state}/ollama.order"; }}\n'
        + "local_url_add_args() { :; }\n"
        + 'KEY_OPENROUTER=""; KEY_OPENAI=""; MODEL_RES=""\n'
        + 'CHOSEN_GEMINI=""; CHOSEN_OPENROUTER=""; CHOSEN_OPENAI=""; CHOSEN_OLLAMA=""\n'
        + preamble
        + 'for p in $MODELS; do setup_model "$p"; result_line "$p" | while IFS= read -r l; do say "$l"; done; done\n'
        + 'for p in $SKIPPED; do say "$(result_line "$p")"; done\n'
        + 'for p in $MODELS $SKIPPED; do record_model_status "$p"; done\n'
        + 'say "passed: $(passed_models)"\n'
    )
    return subprocess.run(
        ["/bin/bash", "-c", snippet],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_phase_3_reports_one_line_per_model_and_keeps_the_ones_that_passed(
    tmp_path: Path,
) -> None:
    """AC9: pass, fail with the provider's reason, or skipped, one line each."""
    result = _phase3_harness(
        tmp_path,
        {
            "gemini": '{"provider": "gemini", "status": "passed", "model": "gemini-3.5-flash-lite"}',
            "openai": '{"provider": "openai", "status": "failed", "reason": "provider_error: insufficient_quota"}',
        },
        skipped="openrouter",
        preamble='KEY_GEMINI="AIza-g"; CHOSEN_GEMINI="gemini-3.5-flash-lite"\n',
    )
    out = result.stdout
    assert "Gemini      ✓ answered (gemini-3.5-flash-lite)" in out, result.stderr
    assert "OpenAI      ✗ provider_error: insufficient_quota" in out
    assert "OpenRouter  skipped (no key)" in out
    assert "passed: gemini" in out
    status = (tmp_path / "status").read_text()
    assert 'model=gemini result=PASS detail="gemini-3.5-flash-lite"' in status
    assert "model=openai result=FAIL" in status
    assert "model=openrouter result=SKIPPED" in status


def test_a_key_goes_to_onex_models_add_on_stdin_and_a_kept_one_is_tested() -> None:
    body = _function_body("setup_model")
    assert 'printf \'%s\' "$key" | models_cmd add "$p" --json' in body
    assert 'models_cmd test "$p" --json' in body


def test_phase_3_fails_only_when_no_model_passed() -> None:
    body = _function_body("phase3")
    assert 'if [ -z "$passed" ]; then' in body
    assert body.index('if [ -z "$passed" ]; then') < body.index("delegate_hello")


def test_phase_4_accepts_an_answer_from_any_key_that_passed_and_nothing_else() -> None:
    body = _function_body("phase4")
    assert (
        'for p in $keyed; do case "$served" in "byok-$p"*) ok=1 ;; esac; done' in body
    )
    assert "phase_fail" in body.split('if [ "$ok" -eq 1 ]', 1)[1]
    # Resume repair can boot before the fresh path prepares a tenant.
    fresh = body.split("  local host_ram", 1)[1]
    assert fresh.index("ensure_stack_tenant") < fresh.index("make up-local")
    assert 'register_key_in_stack "$p"' in body


# ---------------------------------------------------------------------------
# OMN-21058: after each key, onboarding lists the models that key can use,
# numbered, from the provider's own list for that key, with onex's preferred
# models first and recommended, and the developer picks one or more by number
# in the order to try them. The order reaches onex through `onex models add
# --model`, repeated (the OMN-21059 path), and each chosen model is tested with
# a delegation pinned to it. Ollama offers the models this Mac can run. Nothing
# is picked for the developer, and a list that cannot be read ends that model
# alone. Every model id below is a fixture.
# ---------------------------------------------------------------------------

# The merge-base control runs these against a script that asks no model
# question: fail inside the verifier's 30 s per-check ceiling, not after 120 s.
_OR_TIMEOUT = 10.0
_OR_KEY = "sk-or-v1-test"
_OR_MODELS = {
    "data": [
        {"id": "z-lab/zeta-7b:free"},
        {"id": "a-lab/alpha-70b"},
        {"id": "m-lab/mu-12b-it:free"},
        {"id": "b-lab/beta-coder:free", "hugging_face_id": "b-lab/not-an-id:free"},
        {"id": "fx/fam-2-it:free"},
        {"id": "fx/fam-10-it:free"},
    ]
}
# fam (newest generation first) is the catalogue's preferred family here.
_OR_LISTED = [
    "fx/fam-10-it:free",
    "b-lab/beta-coder:free",
    "fx/fam-2-it:free",
    "m-lab/mu-12b-it:free",
    "z-lab/zeta-7b:free",
]
_OR_PICK = "Choose your OpenRouter models, 1 to 5:"


def test_openrouter_model_is_chosen_by_number_from_the_keys_own_list(
    tmp_path: Path,
) -> None:
    """AC1: the key's live list, numbered, the preferred model first and
    recommended; out-of-range answers ask again (an empty one takes the
    recommended order, OMN-21209)."""
    with _models_server({"openrouter": (200, _OR_MODELS)}) as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "2"),
                ("OpenRouter key (1 of 1)", _OR_KEY),
                (_OR_PICK, "6"),
                (_OR_PICK, "0"),
                (_OR_PICK, "x"),
                (_OR_PICK, "4"),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue(tmp_path, served["url"]),
        )
    assert served["auth"] == {"openrouter": [f"Bearer {_OR_KEY}"]}  # read for this key
    assert _listed(out, "free models OpenRouter lists for your key.") == _OR_LISTED
    assert " 1) fx/fam-10-it:free  (recommended)" in out
    assert "Recommended, in this order: 1 " in out
    assert "a-lab/alpha-70b" not in out and "not-an-id" not in out
    assert out.count(_OR_PICK) == 4
    assert out.count("Choose one or more numbers, 1 to 5 (for example 2,1)") == 3
    assert "OpenRouter models, first tried first: m-lab/mu-12b-it:free" in out
    summary = out.split("Ready to set up:")[1]
    assert "OpenRouter  key received, models m-lab/mu-12b-it:free" in summary
    assert _OR_KEY not in out  # never echoed


def test_openrouter_model_key_is_sent_by_header_on_stdin_never_as_an_argument() -> None:
    body = _function_body("key_models", source=HANDLER)
    assert "| curl -sS -m 30 -H @- " in body
    assert "Authorization: Bearer %s" in body


def test_openrouter_model_chosen_reaches_onex_models_add(tmp_path: Path) -> None:
    """AC2: `onex models add openrouter --model <chosen>`, key on stdin; the
    pinned test delegation answers on that model."""
    result = _phase3_harness(
        tmp_path,
        {
            "openrouter": '{"provider": "openrouter", "status": "passed", "model": "MODEL"}'
        },
        preamble=f'KEY_OPENROUTER="{_OR_KEY}"; CHOSEN_OPENROUTER="m-lab/mu-12b-it:free"\n',
    )
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[0] == (
        f"add openrouter --json --model m-lab/mu-12b-it:free stdin={len(_OR_KEY)}"
    )
    assert not [c for c in calls if c.startswith(("reorder", "test"))]
    assert "OpenRouter  ✓ answered (m-lab/mu-12b-it:free)" in result.stdout, (
        result.stderr
    )
    assert "passed: openrouter" in result.stdout


def test_openrouter_model_never_stored_unless_chosen(tmp_path: Path) -> None:
    """AC3: an OpenRouter key with no chosen model is never handed to onex."""
    result = _phase3_harness(
        tmp_path,
        {"openrouter": '{"provider": "openrouter", "status": "passed", "model": "x"}'},
        preamble=f'KEY_OPENROUTER="{_OR_KEY}"\n',
    )
    assert not (tmp_path / "calls").exists()
    assert (
        "OpenRouter  ✗ no OpenRouter model was chosen, so nothing was stored"
        in result.stdout
    )


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (
            401,
            {"error": {"message": "No auth credentials found", "code": 401}},
            "its model list answered HTTP 401: No auth credentials found",
        ),
        (
            200,
            {"data": [{"id": "a-lab/alpha-70b"}]},
            "its model list names no free model for this key",
        ),
    ],
)
def test_openrouter_model_list_unreadable_ends_openrouter_and_the_rest_carry_on(
    tmp_path: Path, status: int, body: object, reason: str
) -> None:
    """AC3: the provider's reason, nothing stored for OpenRouter, Gemini carries on."""
    with _models_server({"openrouter": (status, body)}) as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "1,2"),
                ("Gemini key (1 of 2)", "AIza-g"),
                ("Choose your Gemini models", "1"),
                ("OpenRouter key (2 of 2)", _OR_KEY),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue(tmp_path, served["url"]),
        )
    assert f"✗ OpenRouter: {reason}. Nothing was stored for it" in out
    assert _OR_PICK not in out
    summary = out.split("Ready to set up:")[1]
    assert "Gemini      key received, models" in summary
    assert f"OpenRouter  ✗ {reason}" in summary


def test_openrouter_model_unattended_with_a_stored_key_asks_nothing(
    tmp_path: Path,
) -> None:
    """AC4: --provider openrouter, no terminal, a stored key: no question, and
    phase 3 tests the stored key's model rather than adding one."""
    _stored_keys(tmp_path, "openrouter")
    result = subprocess.run(
        [
            "/bin/bash",
            str(_phase0_only(tmp_path)),
            "--no-containers",
            "--provider",
            "openrouter",
        ],
        env=_phase0_env(tmp_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_OR_TIMEOUT * 2,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert (
        "No terminal to ask on, so these models are used: OpenRouter." in result.stdout
    )
    assert "Choose your OpenRouter models" not in result.stdout

    kept = _phase3_harness(
        tmp_path,
        {
            "openrouter": '{"provider": "openrouter", "status": "passed", "model": "stored/model"}'
        },
        preamble="",
    )
    assert (tmp_path / "calls").read_text().splitlines() == [
        "test openrouter --json stdin=0"
    ]
    assert "OpenRouter  ✓ answered (stored/model)" in kept.stdout


# AC6 to AC9: every key and Ollama, one or more models, in order.

_GEMINI_MODELS = {
    "object": "list",
    "data": [
        {"id": "models/gemini-2.0-flash-lite", "object": "model"},
        {"id": "models/gemini-3-flash", "object": "model"},
        {"id": "models/gemini-embedding-001", "object": "model"},
        {"id": "models/gemini-3-pro", "object": "model"},
        {"id": "models/gemini-3-flash-lite", "object": "model"},
        {"id": "models/gemini-2.5-flash", "object": "model"},
    ],
}


def test_chosen_models_for_each_key_are_picked_by_number_in_order(
    tmp_path: Path,
) -> None:
    """AC6: after each key its own list; one or more by number, in the order given."""
    with _models_server() as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "1,2,3"),
                ("Gemini key (1 of 3)", "AIza-g"),
                ("Choose your Gemini models, 1 to 2:", "2,1"),
                ("OpenRouter key (2 of 3)", _OR_KEY),
                ("Choose your OpenRouter models, 1 to 2:", "2"),
                ("OpenAI key (3 of 3)", "sk-proj-o"),
                ("Choose your OpenAI models, 1 to 2:", "1 2"),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue(tmp_path, served["url"]),
        )
    assert served["auth"] == {
        "gemini": ["Bearer AIza-g"],
        "openrouter": [f"Bearer {_OR_KEY}"],
        "openai": ["Bearer sk-proj-o"],
    }
    summary = out.split("Ready to set up:")[1]
    assert (
        "Gemini      key received, models gemini-3-flash, gemini-3-flash-lite"
        in summary
    )
    assert "OpenRouter  key received, models fx/free-b:free" in summary
    assert "OpenAI      key received, models gpt-4.1-nano, gpt-4.1-mini" in summary


@pytest.mark.parametrize("answer", ["0", "3", "x", "1,1", "2,,9"])
def test_chosen_models_out_of_range_asks_again(tmp_path: Path, answer: str) -> None:
    """AC6: a bad answer picks nothing; an empty one takes the recommended
    order (OMN-21209, test_recommended_order_*)."""
    with _models_server() as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "3"),
                ("OpenAI key (1 of 1)", "sk-proj-o"),
                ("Choose your OpenAI models, 1 to 2:", answer),
                ("Choose one or more numbers, 1 to 2", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue(tmp_path, served["url"]),
        )
    assert out.count("Choose your OpenAI models, 1 to 2:") == 2


def test_chosen_models_list_recommends_the_preferred_models_first(
    tmp_path: Path,
) -> None:
    """AC6, recommended: the newest of each family onex's catalogue prefers, in
    its order, then the rest; models that are not for chat are not offered."""
    with _models_server({"gemini": (200, _GEMINI_MODELS)}) as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "1"),
                ("Gemini key (1 of 1)", "AIza-g"),
                ("Choose your Gemini models, 1 to 5:", "3,1"),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue(tmp_path, served["url"]),
        )
    assert _listed(out, "chat models Gemini lists for your key.") == [
        "gemini-3-flash-lite",
        "gemini-3-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-3-pro",
    ]
    assert " 2) gemini-3-flash  (recommended)" in out
    assert " 3) gemini-2.0-flash-lite\n" in out
    assert "Recommended, in this order: 1,2 " in out
    assert "embedding" not in out
    assert (
        "Gemini models, first tried first: gemini-2.0-flash-lite, gemini-3-flash-lite"
        in out
    )


def test_chosen_models_for_ollama_come_from_what_this_mac_can_run(
    tmp_path: Path,
) -> None:
    """AC7: the model config's Ollama models that fit this Mac's memory, the one
    sized to it recommended; picked in order instead of chosen by memory."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "4"),
            ("Choose your Ollama models, 1 to 2:", "2,1"),
            ("Continue?", "q"),
        ],
        timeout=_OR_TIMEOUT,
        ONBOARD_TEST_RAM_GB="32",
    )
    assert _listed(out, "models Ollama can run in this Mac's 32 GB of memory.") == [
        "fixture-ollama-mid",
        "fixture-ollama-small",
    ]
    assert "fixture-ollama-huge" not in out
    assert " 1) fixture-ollama-mid  (recommended)" in out
    summary = out.split("Ready to set up:")[1]
    assert (
        "Ollama      no key; models fixture-ollama-small, fixture-ollama-mid" in summary
    )


def test_chosen_models_for_ollama_are_each_downloaded() -> None:
    """AC7: phase 3 downloads every model chosen, not only the first."""
    body = _function_body("setup_ollama")
    assert "for m in ${CHOSEN_OLLAMA:-$OLLAMA_MODEL}; do" in body
    assert 'pull "$m"' in body


def test_chosen_models_reach_onex_in_order_and_onex_models_list_shows_it(
    tmp_path: Path,
) -> None:
    """AC8: one `onex models add` naming each model in the chosen order, the key
    on stdin; the order onex holds afterwards is the developer's."""
    result = _phase3_harness(
        tmp_path,
        {"gemini": '{"provider": "gemini", "status": "passed", "model": "MODEL"}'},
        preamble='KEY_GEMINI="AIza-g"; CHOSEN_GEMINI="g-b g-a"\n',
    )
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[0] == "add gemini --json --model g-b --model g-a stdin=6"
    assert (tmp_path / "onex-state" / "gemini.order").read_text() == "g-b g-a"
    assert "onex holds your Gemini models in this order: g-b, g-a" in result.stdout, (
        result.stderr
    )


def test_chosen_models_each_get_a_pinned_test_and_a_result_line(
    tmp_path: Path,
) -> None:
    """AC9: every chosen model is put first and tested with one pinned
    delegation, gets its own line, and the developer's order is put back."""
    result = _phase3_harness(
        tmp_path,
        {
            "openai": '{"provider": "openai", "status": "passed", "model": "MODEL"}',
            "openai:o-b": '{"provider": "openai", "status": "failed", "reason": "provider_error: model_not_found"}',
        },
        preamble='KEY_OPENAI="sk-proj-o"; CHOSEN_OPENAI="o-a o-b o-c"\n',
    )
    out = result.stdout
    assert "OpenAI      ✓ answered (o-a)" in out, result.stderr
    assert "OpenAI      ✗ o-b: provider_error: model_not_found" in out
    assert "OpenAI      ✓ answered (o-c)" in out
    assert "passed: openai" in out
    calls = (tmp_path / "calls").read_text().splitlines()
    assert [c for c in calls if not c.startswith("list")] == [
        "add openai --json --model o-a --model o-b --model o-c stdin=9",
        "reorder openai o-b o-a o-c stdin=0",
        "test openai --json stdin=0",
        "reorder openai o-c o-a o-b stdin=0",
        "test openai --json stdin=0",
        "reorder openai o-a o-b o-c stdin=0",
    ]
    assert (tmp_path / "onex-state" / "openai.order").read_text() == "o-a o-b o-c"


def test_chosen_models_for_ollama_each_get_a_pinned_test(tmp_path: Path) -> None:
    """AC9: Ollama's routes point at each chosen model in turn for its test,
    then back at the first."""
    result = _phase3_harness(
        tmp_path,
        {"ollama": '{"provider": "ollama", "status": "passed", "model": "MODEL"}'},
        preamble='CHOSEN_OLLAMA="ol-a ol-b"\n',
    )
    assert "Ollama      ✓ answered (ol-a)" in result.stdout, result.stderr
    assert "Ollama      ✓ answered (ol-b)" in result.stdout
    assert (tmp_path / "calls").read_text().splitlines() == [
        "overrides ol-a",
        "test ollama --json stdin=0",
        "overrides ol-b",
        "test ollama --json stdin=0",
        "overrides ol-a",
    ]


def test_chosen_models_never_register_a_key_with_none_chosen(tmp_path: Path) -> None:
    """AC9: a key with no chosen model never reaches onex."""
    result = _phase3_harness(
        tmp_path,
        {"gemini": '{"provider": "gemini", "status": "passed", "model": "x"}'},
        preamble='KEY_GEMINI="AIza-g"\n',
    )
    assert not (tmp_path / "calls").exists()
    assert (
        "Gemini      ✗ no Gemini model was chosen, so nothing was stored"
        in result.stdout
    )


# ---------------------------------------------------------------------------
# OMN-16632: the workspace is OMNIBASE_PATH only. OMNI_HOME names the operator's
# private orchestration workspace; a run on a machine that has it set must never
# land there, and no run may plant it in a profile. A workspace that already
# holds clones this script did not create is refused, not re-pinned.
# ---------------------------------------------------------------------------

OMNI_HOME_READ = re.compile(r"\$\{?OMNI_HOME\b")


def _decoy(tmp_path: Path) -> tuple[Path, dict[Path, bytes]]:
    decoy = tmp_path / "decoy_legacy_home"
    (decoy / "omnibase_infra" / ".git").mkdir(parents=True)
    (decoy / "omnibase_infra" / "README").write_text("the operator's own clone\n")
    return decoy, _snapshot(decoy)


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()} | {
        p: b"<dir>" for p in sorted(root.rglob("*")) if p.is_dir()
    }


def test_legacy_variable_set_and_omnibase_path_unset_uses_the_omnibase_default(
    tmp_path: Path,
) -> None:
    decoy, before = _decoy(tmp_path)
    result = _run(tmp_path, "--preflight-only", "--no-containers", OMNI_HOME=str(decoy))
    assert result.returncode == 0, result.stdout + result.stderr
    default = tmp_path / "home" / "Code" / "omnibase"
    assert f"Workspace: {default} (the default" in result.stdout
    assert str(decoy) not in result.stdout.replace(f"OMNI_HOME is set ({decoy})", ""), (
        result.stdout
    )
    assert _snapshot(decoy) == before
    assert _home_files(tmp_path) == []


def test_omnibase_path_names_the_workspace(tmp_path: Path) -> None:
    decoy, _ = _decoy(tmp_path)
    ws = tmp_path / "mine"
    result = _run(
        tmp_path,
        "--preflight-only",
        "--no-containers",
        OMNI_HOME=str(decoy),
        OMNIBASE_PATH=str(ws),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Workspace: {ws} (from OMNIBASE_PATH)" in result.stdout


def test_the_workspace_flag_still_wins(tmp_path: Path) -> None:
    decoy, _ = _decoy(tmp_path)
    ws = tmp_path / "flagged"
    result = _run(
        tmp_path,
        "--preflight-only",
        "--no-containers",
        "--workspace",
        str(ws),
        OMNI_HOME=str(decoy),
        OMNIBASE_PATH=str(tmp_path / "env"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Workspace: {ws} (from --workspace)" in result.stdout


def test_the_script_never_reads_or_exports_the_legacy_variable() -> None:
    text = SCRIPT.read_text()
    assert not OMNI_HOME_READ.search(text), OMNI_HOME_READ.findall(text)
    assert not re.search(r"\bexport\s[^\n]*\bOMNI_HOME\b", text)
    # The decoy must not reach any child process (the onex wrapper prefers an
    # inherited OMNI_HOME over its own location).
    assert re.search(r"^unset OMNI_HOME$", text, re.M)


def _profile_block(tmp_path: Path, existing: str = "") -> str:
    zshrc = tmp_path / "home" / ".zshrc"
    zshrc.parent.mkdir(parents=True, exist_ok=True)
    zshrc.write_text(existing)
    text = SCRIPT.read_text()
    begin = text[text.index("PROFILE_BEGIN=") : text.index("write_profile_block()")]
    workspace = tmp_path / "home" / "Code" / "omnibase"
    snippet = (
        f"RUN_DIR={tmp_path}\nWORKSPACE={workspace}\n"
        f"WORKSPACE_CONFIG_ROOT=$WORKSPACE/.onex/workspace-config\n"
        "brew_bin() { echo /opt/homebrew/bin/brew; }\n"
        + begin
        + _functions("write_profile_block")
        + f'\nwrite_profile_block "{zshrc}"\n'
    )
    _shell(snippet, tmp_path / "home")
    return zshrc.read_text()


def test_no_profile_line_names_the_legacy_variable(tmp_path: Path) -> None:
    profile = _profile_block(tmp_path)
    workspace = tmp_path / "home" / "Code" / "omnibase"
    assert f'export OMNIBASE_PATH="{workspace}"' in profile
    assert "OMNI_HOME" not in profile


def test_a_v1_profile_block_loses_its_legacy_variable_line(tmp_path: Path) -> None:
    v1 = (
        "alias ll='ls -l'\n# >>> omninode onboarding >>>\n"
        'export OMNIBASE_PATH="/x"\n'
        'export OMNI_HOME="/x"   # legacy name, still read by the reconcile scripts\n'
        "# <<< omninode onboarding <<<\n"
    )
    profile = _profile_block(tmp_path, v1)
    assert "OMNI_HOME" not in profile
    assert "alias ll='ls -l'" in profile
    assert profile.count("# >>> omninode onboarding >>>") == 1


def test_phase_2_is_redone_while_the_profile_names_the_legacy_variable() -> None:
    body = _function_body("phase2_verified")
    assert "OMNI_HOME" in body and "WORKSPACE_MARKER" in body, body


def _clone(ws: Path, repo: str = "omnibase_infra") -> Path:
    d = ws / repo
    (d / ".git").mkdir(parents=True)
    (d / "work.txt").write_text("a developer's own work\n")
    return d


def test_a_workspace_holding_clones_it_did_not_create_is_refused(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "devs_own"
    _clone(ws)
    before = _snapshot(ws)
    result = _run(
        tmp_path, "--preflight-only", "--no-containers", "--workspace", str(ws)
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{ws} holds clones this setup did not create" in result.stdout
    assert "--workspace" in result.stdout
    assert _snapshot(ws) == before


def test_a_linked_worktree_in_the_workspace_is_refused_too(tmp_path: Path) -> None:
    ws = tmp_path / "devs_own"
    (ws / "omniclaude").mkdir(parents=True)
    (ws / "omniclaude" / ".git").write_text("gitdir: /elsewhere\n")
    result = _run(
        tmp_path, "--preflight-only", "--no-containers", "--workspace", str(ws)
    )
    assert result.returncode == 1, result.stdout
    assert "holds clones this setup did not create" in result.stdout


@pytest.mark.parametrize("owned_by", ["marker", "v1-runtime-config"])
def test_a_workspace_this_setup_created_is_accepted(
    tmp_path: Path, owned_by: str
) -> None:
    ws = tmp_path / "ours"
    _clone(ws)
    if owned_by == "marker":
        (ws / ".omninode-dev-setup").write_text("created by omninode-dev-setup\n")
    else:
        cfg = ws / ".onex/workspace-config/config/onex/runtime/runtime_config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("# Written by omninode-dev-setup.\n")
    result = _run(
        tmp_path, "--preflight-only", "--no-containers", "--workspace", str(ws)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "did not create" not in result.stdout


def test_phase_2_writes_the_marker_before_the_first_clone() -> None:
    body = _function_body("phase2")
    assert body.index("WORKSPACE_MARKER") < body.index("sync_clone")
    assert "refuse_foreign_workspace" in body


# ---------------------------------------------------------------------------
# OMN-21163: a local model server by URL (LM Studio, llama.cpp, vLLM, MLX) is a
# fifth choice. Onboarding asks for its URL and model name and never for a key,
# hands both to `onex models add local --url --model` (omnimarket 0.4.316,
# OMN-21162), and stops, naming the URL, when nothing answers there.
# ---------------------------------------------------------------------------

# The merge-base control runs these against a script with no local choice:
# fail inside the verifier's 30 s per-check ceiling, not after 120 s.
_LOCAL_TIMEOUT = 10.0
_LOCAL_MODEL = "fixture-local-model"


@pytest.fixture
def local_model_server() -> Iterator[str]:
    """A server answering HTTP on 127.0.0.1, where a model server such as LM Studio listens."""

    class _Models(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(
                {"object": "list", "data": [{"id": _LOCAL_MODEL, "object": "model"}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Models)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _closed_url() -> str:
    """A URL on 127.0.0.1 where nothing listens."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _unattended_preflight(
    tmp_path: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers", *args],
        env=_phase0_env(tmp_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_LOCAL_TIMEOUT * 2,
        check=False,
    )


def test_local_url_menu_asks_its_url_and_model_and_never_a_key(
    tmp_path: Path, local_model_server: str
) -> None:
    """AC1: the menu's fifth choice asks for the server's URL and model, no key."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "5"),
            ("Its URL, such as http://127.0.0.1:1234", local_model_server),
            ("The model it runs", _LOCAL_MODEL),
            ("Continue?", "q"),
        ],
        timeout=_LOCAL_TIMEOUT,
    )
    menu = out.split(_MENU)[0]
    assert "5) Local URL   a model server you already run" in menu
    assert "You chose: Local URL" in out
    assert _HIDDEN not in out and " key (" not in out
    summary = out.split("Ready to set up:")[1]
    assert (
        f"Local URL   no key; {_LOCAL_MODEL} on the server at {local_model_server}"
        in summary
    )


def test_local_url_beside_a_keyed_model_asks_only_that_models_key(
    tmp_path: Path, local_model_server: str
) -> None:
    """AC1: with Gemini and the local server, one key prompt: Gemini's (1 of 1)."""
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "5,1"),
            ("Gemini key (1 of 1)", "AIza-g"),
            ("Choose your Gemini models", "1"),
            ("Its URL, such as http://127.0.0.1:1234", local_model_server),
            ("The model it runs", _LOCAL_MODEL),
            ("Continue?", "q"),
        ],
        timeout=_LOCAL_TIMEOUT,
    )
    assert "You chose: Gemini, Local URL" in out
    assert out.count(_HIDDEN) == 1
    assert "Local URL key" not in out


def test_local_url_by_provider_flag_runs_unattended(
    tmp_path: Path, local_model_server: str
) -> None:
    """AC1: --provider local with --local-url and --local-model asks nothing."""
    result = _unattended_preflight(
        tmp_path,
        "--provider",
        "local",
        "--local-url",
        local_model_server,
        "--local-model",
        _LOCAL_MODEL,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "No terminal to ask on, so these models are used: Local URL." in out
    assert (
        f"Model: the local model server at {local_model_server}, no key. Model: {_LOCAL_MODEL}."
        in out
    )
    assert (
        "key"
        not in out.split("Model: the local model server")[0].split("Local URL.")[1]
    )


def test_local_url_unattended_without_a_url_stops_before_installing(
    tmp_path: Path,
) -> None:
    result = _unattended_preflight(tmp_path, "--provider", "local")
    assert result.returncode == 1, result.stdout
    assert "pass --local-url URL and --local-model NAME" in result.stdout
    assert "Nothing was installed" in result.stdout
    assert sorted((tmp_path / "home").rglob("*")) == []


def test_local_url_that_nothing_answers_stops_naming_it(tmp_path: Path) -> None:
    """AC2: nothing answers at the URL: the run stops before installing, naming it."""
    url = _closed_url()
    result = _unattended_preflight(
        tmp_path, "--provider", "local", "--local-url", url, "--local-model", "m"
    )
    assert result.returncode == 1, result.stdout
    assert f"Nothing answers at {url}" in result.stdout
    assert f"start the model server at {url}" in result.stdout
    assert "Nothing was installed" in result.stdout
    assert sorted((tmp_path / "home").rglob("*")) == []


def test_local_url_that_nothing_answers_is_asked_again_in_a_terminal(
    tmp_path: Path,
) -> None:
    url = _closed_url()
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "5"),
            ("Its URL, such as http://127.0.0.1:1234", url),
            (f"Nothing answers at {url}", ""),
            ("Its URL, such as http://127.0.0.1:1234", "q"),
        ],
        timeout=_LOCAL_TIMEOUT,
    )
    assert "Nothing was installed" in out


def _local_url_phase3(
    tmp_path: Path, stdout: str, stderr: str = "", rc: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Phase 3's local model step with `onex models` faked; returns the run and its calls."""
    fake = tmp_path / "onex-models"
    calls = tmp_path / "calls"
    (tmp_path / "out").write_text(stdout)
    (tmp_path / "err").write_text(stderr)
    fake.write_text(
        "#!/bin/bash\n"
        f'stdin="$(cat)"; echo "$* stdin=${{#stdin}}" >>"{calls}"\n'
        f'cat "{tmp_path / "out"}"; cat "{tmp_path / "err"}" >&2; exit {rc}\n'
    )
    fake.chmod(0o755)
    snippet = (
        f"LOG=/dev/null; STATUS={tmp_path}/status; RUN_DIR={tmp_path}; MODELS=local; SKIPPED=\n"
        "say() { printf '%s\\n' \"$*\"; }\n"
        'phase_fail() { say "STOPPED step=$FAILED_STEP err=$LAST_ERR next=$1"; exit 1; }\n'
        + _functions(
            "pending_key",
            "set_pending_key",
            "uses_key",
            "in_list",
            "has_model",
            "provider_label",
            "receipt_field",
            "set_result",
            "result_of",
            "passed_models",
            "add_model_res",
            "result_line",
            "cause_of",
            "model_result",
            "setup_model",
        )
        + "\n"
        + _functions(
            "local_url_add_args",
            "stop_local_url_unanswered",
            "chosen_models",
            source=HANDLER,
        )
        + f'\nmodels_cmd() {{ "{fake}" "$@"; }}\n'
        + 'KEY_GEMINI=""; KEY_OPENROUTER=""; KEY_OPENAI=""; MODEL_RES=""\n'
        + f'LOCAL_URL="http://127.0.0.1:1234"; LOCAL_MODEL="{_LOCAL_MODEL}"\n'
        + 'setup_model local; say "$(result_line local)"\n'
        + 'say "passed: $(passed_models)"\n'
    )
    result = subprocess.run(
        ["/bin/bash", "-c", snippet],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, (calls.read_text().splitlines() if calls.exists() else [])


def test_local_url_and_model_reach_onex_models_add_local(tmp_path: Path) -> None:
    """AC2: the URL and model go to `onex models add local --url --model`, no key on
    stdin; its one pinned test delegation's answer is the model's line."""
    result, calls = _local_url_phase3(
        tmp_path,
        f'{{"provider": "local", "status": "passed", "backend_id": "local-url", "model": "{_LOCAL_MODEL}"}}\n',
    )
    assert calls == [
        f"add local --json --url http://127.0.0.1:1234 --model {_LOCAL_MODEL} stdin=0"
    ]
    assert f"Local URL   ✓ answered ({_LOCAL_MODEL})" in result.stdout, result.stderr
    assert "passed: local" in result.stdout
    assert "STOPPED" not in result.stdout


def test_local_url_failed_test_delegation_is_reported_not_stopped(
    tmp_path: Path,
) -> None:
    result, _ = _local_url_phase3(
        tmp_path,
        '{"provider": "local", "status": "failed", "reason": "answered by another model"}\n',
        rc=1,
    )
    assert "Local URL   ✗ answered by another model" in result.stdout
    assert "STOPPED" not in result.stdout


def test_local_url_refused_by_onex_stops_phase_3_naming_the_url(
    tmp_path: Path,
) -> None:
    """AC2: `onex models add local` refuses a server that does not answer; phase 3
    stops there and names the URL."""
    result, _ = _local_url_phase3(
        tmp_path,
        "",
        stderr=(
            "Error: http://127.0.0.1:1234 does not answer an OpenAI-compatible "
            "models or chat request (GET /v1/models: ConnectError). Nothing was changed\n"
        ),
        rc=1,
    )
    assert result.returncode == 1
    stopped = [
        line for line in result.stdout.splitlines() if line.startswith("STOPPED")
    ]
    assert stopped, result.stdout + result.stderr
    assert "step=set up the local model server at http://127.0.0.1:1234" in stopped[0]
    assert "does not answer an OpenAI-compatible" in stopped[0]
    assert "at http://127.0.0.1:1234; start it there" in stopped[0]


def _local_url_onex(
    tmp_path: Path, reconcile_fixes: bool
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """ensure_local_url_onex with a dispatch venv whose omnimarket predates --url."""
    ws = tmp_path / "ws"
    scripts = ws / "omnibase_infra" / "scripts"
    scripts.mkdir(parents=True)
    (ws / ".onex-workspace-floor.json").write_text('{"omnimarket_commit": "old"}\n')
    upgraded = tmp_path / "upgraded"
    (scripts / "reconcile-workspace-venvs.sh").write_text(
        f'echo "$*" >>"{tmp_path / "reconcile-calls"}"\n'
        + (f'touch "{upgraded}"\n' if reconcile_fixes else "")
    )
    snippet = (
        f'LOG=/dev/null; RETRIES=3; STAMP=20261017-000000; WORKSPACE="{ws}"\n'
        'LOCAL_URL_OMNIMARKET="0.4.316"\n'
        "say() { printf '%s\\n' \"$*\"; }\n"
        "sleep() { :; }\n"
        'phase_fail() { say "STOPPED step=$FAILED_STEP err=$LAST_ERR next=$1"; exit 1; }\n'
        + _functions(
            "log",
            "last_log_lines",
            "retry",
        )
        + "\n"
        + _functions("local_url_supported", "ensure_local_url_onex", source=HANDLER)
        + "\nmodels_cmd() {\n"
        + f'  [ "$1 $2" = "add --help" ] && {{ echo "  --model TEXT"; [ -f "{upgraded}" ] && echo "  --url TEXT"; }}\n'
        + "  return 0\n}\n"
        + 'ensure_local_url_onex; say "supported"\n'
    )
    result = subprocess.run(
        ["/bin/bash", "-c", snippet],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, ws


def test_local_url_installs_an_omnimarket_new_enough_for_it(tmp_path: Path) -> None:
    """AC2: an omnimarket older than 0.4.316 has no `add local --url`; the floor is
    set aside and the proven omnimarket installed, then the add is there."""
    result, ws = _local_url_onex(tmp_path, reconcile_fixes=True)
    assert "supported" in result.stdout, result.stdout + result.stderr
    assert (
        "predates 'onex models add local --url' (omnimarket 0.4.316)" in result.stdout
    )
    assert not (ws / ".onex-workspace-floor.json").exists()
    assert (ws / ".onex-workspace-floor.json.pre-local-url.20261017-000000").exists()
    assert "--proven" in (tmp_path / "reconcile-calls").read_text()


def test_local_url_with_no_omnimarket_new_enough_stops(tmp_path: Path) -> None:
    result, _ = _local_url_onex(tmp_path, reconcile_fixes=False)
    assert "STOPPED" in result.stdout
    assert "older than 0.4.316" in result.stdout
    assert "supported" not in result.stdout.replace("local_url_supported", "")


@pytest.mark.parametrize(
    ("url", "reached"),
    [
        (
            "http://127.0.0.1:1234/v1/chat/completions",
            "http://host.docker.internal:1234/v1/chat/completions",
        ),
        ("http://localhost:8080/x", "http://host.docker.internal:8080/x"),
        ("https://gpu.lan:9000/x", "https://gpu.lan:9000/x"),
    ],
)
def test_local_url_on_this_mac_is_reached_from_docker_by_its_host_name(
    url: str, reached: str
) -> None:
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            _functions("docker_url", source=HANDLER) + f'\ndocker_url "{url}"\n',
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.stdout == reached, result.stderr


def test_local_url_choice_reaches_a_downloaded_script() -> None:
    """AC1 for the guide's download path: a downloaded script fetches the handler
    from the commit its URL names, and that handler offers the Local URL choice.
    While the handler change waited for its own commit on dev, a download fetched
    the handler before it, which has no local choice."""
    text = SCRIPT.read_text()
    match = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        text,
    )
    assert match
    commit = match.group(1)
    rel = HANDLER.relative_to(SCRIPT.parents[4]).as_posix()
    git = ["git", "-C", str(SCRIPT.parents[4])]
    env = scrub_git_location_env(os.environ)
    if subprocess.run(
        [*git, "cat-file", "-e", f"{commit}^{{commit}}"], env=env, check=False
    ).returncode:
        subprocess.run(
            [*git, "fetch", "--no-tags", "--depth=1", "origin", commit],
            env=env,
            check=False,
        )
    served = subprocess.run(
        [*git, "show", f"{commit}:{rel}"], env=env, capture_output=True, check=False
    )
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    assert b"$i) Local URL" in served.stdout
    assert b"settle_local_url" in served.stdout


def test_chosen_models_reach_a_downloaded_script() -> None:
    """AC6 to AC9 on the download path: a script downloaded on its own fetches
    its handler from the commit its URL names, so that commit's handler must be
    the one that asks for each key's models and registers them in order, with
    the bytes download_digest checks."""
    text = SCRIPT.read_text()
    commit = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        text,
    )
    digest = re.search(r'\bdownload_digest="([0-9a-f:]+)"', text)
    assert commit and digest
    repo = SCRIPT.parents[4]
    rel = HANDLER.relative_to(repo).as_posix()

    def git(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            env=scrub_git_location_env(os.environ),
        )

    if git("cat-file", "-e", f"{commit.group(1)}^{{commit}}").returncode != 0:
        git("fetch", "--no-tags", "--depth=1", "origin", commit.group(1))
    served = git("show", f"{commit.group(1)}:{rel}")
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    handler = served.stdout.decode()
    for function in ("key_models", "choose_models", "ask_ollama_models", "setup_model"):
        assert f"\n{function}() {{" in handler, (
            f"the handler a downloaded script fetches has no {function}"
        )
    assert hashlib.sha256(served.stdout).hexdigest() == digest.group(1).replace(":", "")


# OMN-21209: the routing contract's recommended order is the pre-selected
# answer. A key's order is its catalogue row's default_models, the models of it
# the key lists, in that order; Ollama's is the catalogue's local model sized to
# this Mac. Enter takes it, so a developer types no model id.


def _catalogue_with_order(tmp_path: Path, base: str) -> str:
    """The fixture catalogue with a default_models order on the Gemini and
    OpenAI rows: OpenAI's opposite to its preferred family, Gemini's naming a
    model the key does not list."""
    path = Path(_catalogue(tmp_path, base))
    text = path.read_text()
    text = text.replace(
        f'    models_url: "{base}/openai"\n',
        f'    models_url: "{base}/openai"\n'
        "    default_models:\n"
        '      - "gpt-4.1-mini"\n'
        '      - "gpt-4.1-nano"\n',
    ).replace(
        f'    models_url: "{base}/gemini"\n',
        f'    models_url: "{base}/gemini"\n'
        "    default_models:\n"
        '      - "gemini-9-unlisted"\n'
        '      - "gemini-3-flash"\n',
    )
    ordered = tmp_path / "catalogue-ordered.yaml"
    ordered.write_text(text)
    return str(ordered)


def test_recommended_order_is_the_preselected_answer_for_each_key(
    tmp_path: Path,
) -> None:
    with _models_server() as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "1,3"),
                ("Gemini key (1 of 2)", "AIza-g"),
                ("Choose your Gemini models, 1 to 2:", ""),
                ("OpenAI key (2 of 2)", "sk-proj-o"),
                ("Choose your OpenAI models, 1 to 2:", ""),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue_with_order(tmp_path, served["url"]),
        )
    assert out.count("Press Enter to take the recommended order.") == 2
    assert _listed(out, "chat models OpenAI lists for your key.") == [
        "gpt-4.1-mini",
        "gpt-4.1-nano",
    ]
    assert "Recommended, in this order: 1,2 " in out
    assert "gemini-9-unlisted" not in out
    assert "Choose one or more numbers" not in out
    summary = out.split("Ready to set up:")[1]
    assert "Gemini      key received, models gemini-3-flash" in summary
    assert "OpenAI      key received, models gpt-4.1-mini, gpt-4.1-nano" in summary


def test_recommended_order_is_the_preselected_answer_for_ollama(
    tmp_path: Path,
) -> None:
    out, _ = _preflight(
        tmp_path,
        [
            (_MENU, "4"),
            ("Choose your Ollama models, 1 to 2:", ""),
            ("Continue?", "q"),
        ],
        timeout=_OR_TIMEOUT,
        ONBOARD_TEST_RAM_GB="32",
    )
    assert " 1) fixture-ollama-mid  (recommended)" in out
    assert "Press Enter to take the recommended order." in out
    summary = out.split("Ready to set up:")[1]
    assert "Ollama      no key; models fixture-ollama-mid" in summary


def test_recommended_order_with_none_listed_keeps_the_preferred_families(
    tmp_path: Path,
) -> None:
    with _models_server() as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "3"),
                ("OpenAI key (1 of 1)", "sk-proj-o"),
                ("Choose your OpenAI models, 1 to 2:", ""),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue(tmp_path, served["url"]),
        )
    assert " 1) gpt-4.1-nano  (recommended)" in out
    summary = out.split("Ready to set up:")[1]
    assert "OpenAI      key received, models gpt-4.1-nano" in summary


def test_recommended_order_holds_no_model_id_in_the_script() -> None:
    """The order is read from the catalogue; neither file names a model."""
    reader = _functions("recommended_order")
    assert "default_models:" in reader and "$CATALOGUE_REL" in reader
    for text in (SCRIPT.read_text(), HANDLER.read_text()):
        assert not re.search(r"qwen|gemma|nemotron|gpt-4|gemini-[0-9]", text)


def test_recommended_order_ollama_download_is_sized_from_the_catalogue(
    tmp_path: Path,
) -> None:
    """The catalogue's local model is offered for Ollama, so its download size
    is read from the catalogue's local row when the model config omits it."""
    ws = _workspace_with_config(tmp_path, _OLLAMA_BLOCK)
    catalogue = ws / "omnimarket" / "src" / "omnimarket" / "configs"
    (catalogue / "byok_provider_backends.v1.yaml").write_text(
        "providers: []\n" + _LOCAL_BLOCK.replace("download_gb: 40", "download_gb: 9")
    )
    consts = "\n".join(
        line
        for line in (SCRIPT.read_text() + HANDLER.read_text()).splitlines()
        if line.startswith(("OLLAMA_CONFIG_REL=", "CATALOGUE_REL="))
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f"WORKSPACE={ws}\n{consts}\n"
            + _functions("ollama_config")
            + '\nollama_config 64 "fixture-ollama-huge"\n',
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.stdout.strip() == "11434 /v1/chat/completions fixture-ollama-huge 9"


def test_recommended_order_names_the_record_it_rests_on(tmp_path: Path) -> None:
    """AC4: the order is offered with the basis the routing contract names."""
    with _models_server() as served:
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "3,4"),
                ("OpenAI key (1 of 1)", "sk-proj-o"),
                ("Choose your OpenAI models, 1 to 2:", ""),
                ("Choose your Ollama models, 1 to 2:", ""),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=_catalogue_with_order(tmp_path, served["url"]),
        )
    assert (
        out.count("(the routing contract's order for this key; it rests on OMN-21215).")
        == 2
    )


def test_recommended_order_without_a_basis_is_not_presented_as_the_contracts(
    tmp_path: Path,
) -> None:
    """AC4: an order the catalogue gives no basis for is not offered as sourced."""
    with _models_server() as served:
        catalogue = Path(_catalogue_with_order(tmp_path, served["url"]))
        catalogue.write_text(
            catalogue.read_text().replace('      basis: "OMN-21215"\n', "")
        )
        out, _ = _preflight(
            tmp_path,
            [
                (_MENU, "3"),
                ("OpenAI key (1 of 1)", "sk-proj-o"),
                ("Choose your OpenAI models, 1 to 2:", ""),
                ("Continue?", "q"),
            ],
            timeout=_OR_TIMEOUT,
            ONBOARD_TEST_CATALOGUE=str(catalogue),
        )
    assert "it rests on" not in out
    assert (
        "Recommended, in this order: 1,2 (the models onex prefers for this key)." in out
    )


def test_recommended_order_accepted_reaches_onex_models_add_in_order(
    tmp_path: Path,
) -> None:
    """AC3: the contract's order, as accepted, is the list `onex models add`
    registers (the OMN-21059 path), first tried first."""
    with _models_server() as served:
        catalogue = _catalogue_with_order(tmp_path, served["url"])
    order = subprocess.run(
        [
            "/bin/bash",
            "-c",
            "ram_gb() { echo 32; }\nWORKSPACE=/nonexistent\n"
            'CATALOGUE_REL="omnimarket/src/omnimarket/configs/byok_provider_backends.v1.yaml"\n'
            + _functions("omnimarket_file", "recommended_order")
            + "\nrecommended_order openai | tr '\\n' ' '\n",
        ],
        env={"PATH": "/usr/bin:/bin", "ONBOARD_TEST_CATALOGUE": catalogue},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()
    assert order == "gpt-4.1-mini gpt-4.1-nano"
    _phase3_harness(
        tmp_path,
        {"openai": '{"provider": "openai", "status": "passed", "model": "MODEL"}'},
        preamble=f'KEY_OPENAI="sk-proj-o"; CHOSEN_OPENAI="{order}"\n',
    )
    calls = (tmp_path / "calls").read_text().splitlines()
    assert (
        calls[0]
        == "add openai --json --model gpt-4.1-mini --model gpt-4.1-nano stdin=9"
    )
    assert (tmp_path / "onex-state" / "openai.order").read_text() == order


@pytest.mark.parametrize(
    ("answer", "chosen"), [("\n", "gpt-b gpt-a"), ("1\n", "gpt-a")]
)
def test_recommended_order_enter_takes_it_without_a_model_id(
    answer: str, chosen: str
) -> None:
    """AC2: Enter takes the recommended order (2,1 here); no model id is typed."""
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            "say() { printf '%s\\n' \"$*\"; }\nquit_setup() { echo QUIT; exit 3; }\n"
            "provider_label() { echo OpenAI; }\nram_gb() { echo 32; }\n"
            + _functions(
                "in_list",
                "comma_list",
                "set_chosen_models",
                "parse_ordered_choice",
                "choose_models",
            )
            + '\nMODEL_LIST="gpt-a\ngpt-b"; RECOMMENDED="2,1"\n'
            + 'choose_models openai; echo "CHOSEN=$CHOSEN_OPENAI"\n',
        ],
        input=answer,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert "Press Enter to take the recommended order." in result.stdout
    assert f"CHOSEN={chosen}" in result.stdout, result.stdout + result.stderr


# OMN-20825 / T6: drive the real phase functions, with only external work stubbed.
def _mint_harness(
    tmp_path: Path,
    *,
    resumed: bool = False,
    running: bool = False,
    check_status: int = 0,
    mint_status: int = 0,
    no_docker: bool = False,
    source: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str], str]:
    script = source or SCRIPT
    home, workspace, bin_dir = (tmp_path / n for n in ("home", "workspace", "bin"))
    for directory in (home, workspace / "omnibase_infra", bin_dir):
        directory.mkdir(parents=True)
    # Run the production Python handler using phase 3's dispatch interpreter.
    # A base checkout copies its real node too; the missing new handler then
    # fails at the phase call, rather than failing this fixture's setup.
    repo = Path(__file__).resolve().parents[2]
    package = workspace / "omniclaude/src/omniclaude"
    package.mkdir(parents=True)
    shutil.copy2(repo / "src/omniclaude/__init__.py", package / "__init__.py")
    nodes = package / "nodes"
    nodes.mkdir()
    (nodes / "__init__.py").write_text("")
    shutil.copytree(
        repo / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator",
        nodes / "node_skill_omninode_dev_setup_orchestrator",
    )
    dispatch = workspace / ".onex-dispatch-venv/bin"
    dispatch.mkdir(parents=True)
    # Exec the original venv entrypoint; a relocated symlink loses pyvenv.cfg.
    dispatch_python = dispatch / "python"
    dispatch_python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    dispatch_python.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/sh\nprintf '%s\\n' '{\"healthy\":true}'\n")
    curl.chmod(0o755)
    calls, events, log = (tmp_path / n for n in ("make-targets", "events", "run.log"))
    fake = bin_dir / "make"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "assert args[:2] == ['-C', os.environ['WORKSPACE'] + '/omnibase_infra'], args\n"
        "assert len(args) == 3, args\n"
        "target = args[2]\n"
        "if target == 'status-local':\n"
        "    with Path(os.environ['MINT_EVENTS']).open('a') as out: out.write('health_wait\\n')\n"
        "    print('migration-gate: healthy')\n"
        "    sys.exit(0)\n"
        "assert target in {'local-env', 'check-sasl-local', 'up-local', 'mint-local'}, target\n"
        "for name, value in [('MINT_CALLS', target), ('MINT_EVENTS', target)]:\n"
        "    with Path(os.environ[name]).open('a') as out: out.write(value + '\\n')\n"
        "if target == 'check-sasl-local': sys.exit(int(os.environ['MINT_CHECK_RC']))\n"
        "if target == 'mint-local':\n"
        "    print('fixture mint result')\n"
        "    sys.exit(int(os.environ['MINT_RC']))\n"
    )
    fake.chmod(0o755)
    names = (
        "elapsed",
        "phase_start",
        "phase_pass",
        "phase_skip",
        "phase_fail",
        "last_log_lines",
        "onboarding_bus_identity",
        "step",
        "retry",
        "retry_capture",
        "check",
        "phase3",
        "phase4",
        "phase6",
        "main",
    )
    constants = re.search(r"^TOTAL_PHASES=\d+$", script.read_text(), re.M)
    assert constants
    snippet = (
        "set -uo pipefail\n"
        + constants.group()
        + "\n"
        + _functions(*names, source=script)
        + r"""
say() { printf '%s\n' "$*"; }
hr() { :; }
notify() { :; }
log() { printf '%s\n' "$*" >>"$LOG"; }
mark_done() { :; }
is_done() { [ "$MINT_RESUMED" = 1 ] && [ "$1" = 4 ]; }
rerun_note() { :; }
docker_ready() { return 0; }
docker_installed() { return 0; }
size_docker() { return 2; }
wait_for_docker() { return 0; }
compose_ok() { return 0; }
boot_resources_ok() { return 0; }
ram_gb() { echo 32; }
local_stack_running() { [ "$MINT_RUNNING" = 1 ]; }
stack_healthy() { return 0; }
wait_until() { echo health_wait >>"$MINT_EVENTS"; return 0; }
passed_models() { echo local; }
uses_key() { return 1; }
in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
point_stack_at_local_url() { :; }
stack_delegate() { echo stack_delegate >>"$MINT_EVENTS"; echo '{}'; }
accepted_backend() { echo local-fixture; }
dispatch_venv_current() { return 0; }
link_onex() { :; }
onex_run() { echo fixture; }
models_cmd() { return 0; }
has_model() { return 1; }
retire_lab_model_overrides() { :; }
result_of() { echo pass:fixture; }
result_line() { echo fixture; }
record_model_status() { :; }
place_local_url_on_ladder() { :; }
delegate_hello() { echo '{}'; }
receipt_field() { echo fixture; }
stamp_proven_floor() { :; }
count_words() { echo 1; }
labels() { echo fixture; }
no_shadow() { return 0; }
shell_runs_workspace_onex() { return 0; }
workspace_floor() { return 0; }
sqlite_rows() { return 0; }
local_url_answers() { return 0; }
plugin_installed() { return 0; }
bind_workspace_env() { :; }
save_choices() { :; }
phase0() { MODE2_OK=0; }
phase1() { :; }
phase2() { :; }
phase5() { :; }
MODE2_OK=1; MODE2_WHY=' Docker skipped'; STACK_RUNNING=0; STACK_TENANT_CHANGED=0
DOCKER_MEM_GB=10; HOST_RESERVE_GB=6; DOCKER_CPUS=4
FAILED_STEP=''; FAILED_ATTEMPTS=0; LAST_ERR=''; CHECKS_FAILED=0; CAPTURED=''
ONEX=''; OLLAMA_HEADLESS=0; MODELS=local; SKIPPED=''; SELECTED=local
WANT_PLUGIN=fixture; LOCAL_URL=fixture; OLLAMA_MODEL=fixture
RESTART=0; PREFLIGHT_ONLY=0; DEVELOPER=0; RETRIES=3
"""
        + ("\nmain\n" if no_docker else "\nphase4\n")
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "WORKSPACE": str(workspace),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "LOG": str(log),
        "STATUS": str(tmp_path / "status"),
        "DONE_FILE": str(tmp_path / "done"),
        "MINT_CALLS": str(calls),
        "MINT_EVENTS": str(events),
        "MINT_RESUMED": str(int(resumed)),
        "MINT_RUNNING": str(int(running)),
        "MINT_CHECK_RC": str(check_status),
        "MINT_RC": str(mint_status),
    }
    result = subprocess.run(
        ["/bin/bash", "-c", snippet],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return (
        result,
        calls.read_text().splitlines() if calls.exists() else [],
        events.read_text().splitlines() if events.exists() else [],
        log.read_text() if log.exists() else "",
    )


def test_mint_fresh_phase4_runs_after_delegation_before_pass(tmp_path: Path) -> None:
    result, calls, events, log = _mint_harness(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ["local-env", "up-local", "mint-local"]
    assert events == [
        "local-env",
        "up-local",
        "health_wait",
        "stack_delegate",
        "mint-local",
    ]
    assert "Phase 4/6 PASSED" in result.stdout
    # A late call after phase_pass would wrongly leave the phase marked complete.
    body = _function_body("phase4")
    assert body.rindex('step "mint your bus identity"') < body.rindex("phase_pass")
    assert "fixture mint result" in log
    assert "fixture mint result" not in result.stdout


@pytest.mark.parametrize("check_status", [0, 2])
def test_resume_mint_checks_sasl_and_rebuilds_only_on_failure(
    tmp_path: Path, check_status: int
) -> None:
    result, calls, events, _ = _mint_harness(
        tmp_path, resumed=True, running=True, check_status=check_status
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = ["check-sasl-local"]
    if check_status:
        expected.append("up-local")
    expected.append("mint-local")
    assert calls == expected
    assert events == (
        ["check-sasl-local", "up-local", "health_wait", "mint-local"]
        if check_status
        else expected
    )
    assert "already running" in result.stdout


@pytest.mark.parametrize("resumed", [False, True])
def test_mint_failure_stops_phase4_once_with_next_step_and_log(
    tmp_path: Path, resumed: bool
) -> None:
    result, calls, _, _ = _mint_harness(tmp_path, resumed=resumed, mint_status=75)
    assert result.returncode == 1, result.stdout + result.stderr
    assert calls.count("mint-local") == 1
    assert "Phase 4/6 FAILED" in result.stdout
    assert "mint your bus identity (after 1 attempt(s))" in result.stdout
    assert "Next:" in result.stdout and "make mint-local" in result.stdout
    assert f"Log:       {tmp_path}/run.log" in result.stdout
    assert "Phase 4/6 PASSED" not in result.stdout


def test_in_memory_main_finishes_without_mint_and_explains_no_broker(
    tmp_path: Path,
) -> None:
    result, calls, _, _ = _mint_harness(tmp_path, no_docker=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == []
    assert "result=COMPLETE" in (tmp_path / "status").read_text()
    phase3 = next(
        line for line in result.stdout.splitlines() if "Phase 3/6 PASSED" in line
    )
    assert "no broker" in phase3 and "no identity to mint" in phase3
    phase6 = result.stdout.split("Phase 6/6:", 1)[1]
    assert any(
        "no broker" in line and "no identity to mint" in line
        for line in phase6.splitlines()
    )


def test_ports_cover_the_six_local_bundle_listeners() -> None:
    ports = re.search(r'^MODE2_PORTS="([0-9 ]+)"$', SCRIPT.read_text(), re.M)
    assert ports
    assert ports.group(1).split() == ["5436", "19092", "16379", "8085", "8086", "8098"]


@pytest.mark.parametrize("check_status", [0, 2])
def test_mint_fresh_old_stack_checks_sasl_before_delegation(
    tmp_path: Path, check_status: int
) -> None:
    result, calls, events, _ = _mint_harness(
        tmp_path, running=True, check_status=check_status
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = ["check-sasl-local"] + (["up-local"] if check_status else [])
    assert calls == expected + ["mint-local"]
    assert events == expected + ["health_wait", "stack_delegate", "mint-local"]


@pytest.mark.parametrize("mode", ["secure", "mint", "resume"])
def test_bus_identity_missing_dependency_refuses_before_commands(
    tmp_path: Path, mode: str
) -> None:
    """A broken dispatch environment reports a result, never a traceback or mint."""
    repo = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace with spaces"
    (workspace / "omnibase_infra").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "make-called"
    fake_make = fake_bin / "make"
    fake_make.write_text(f"#!/bin/sh\nprintf called > {shlex.quote(str(marker))}\n")
    fake_make.chmod(0o755)
    log = tmp_path / "run.log"
    env = {
        **os.environ,
        "PYTHONPATH": str(repo / "src"),
        "PYTHONNOUSERSITE": "1",
        "PATH": f"{fake_bin}:/usr/bin:/bin",
    }
    # Prove the command sentinel works before asking the helper not to call it.
    subprocess.run(["make"], env=env, check=True)
    assert marker.read_text() == "called"
    marker.unlink()
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-m",
            "omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.runtime_onboarding_bus_identity",
            str(workspace),
            str(log),
            mode,
            "3",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert not marker.exists(), "bootstrap failure must run no broker command"
    lines = result.stderr.splitlines()
    refusal = json.loads(lines[0])
    assert refusal["success"] is False
    assert refusal["failed_step"] == "dispatch_environment"
    assert refusal["returncode"] == 2
    assert refusal["attempts"] == 0
    assert refusal["reason"] == "dispatch_environment_unavailable"
    assert ".onex-dispatch-venv" in refusal["next_step"]
    assert lines[1] == f"Next: {refusal['next_step']}"
    assert lines[2] == f"Log: {log}"
