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
import os
import pty
import re
import select
import signal
import subprocess
import sys
import time
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
SKILL = SCRIPT.parents[1] / "omninode_dev_setup" / "SKILL.md"
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
        "ONBOARD_TEST_NO_GUI": "1",
    }
    out, returncode = _drive_tty(
        ["/bin/bash", str(phase0_only), "--provider", "gemini"],
        env,
        [
            ("key (input is hidden)", "not-a-real-key"),
            ("Set up the local stack in Docker too?", answer),
        ],
    )
    assert "You're already covered" in out
    assert outcome in out


# ---------------------------------------------------------------------------
# OMN-17099: the containers run the developer's model and key, not a template's.
# ---------------------------------------------------------------------------


def _function_body(name: str) -> str:
    """The text of one top-level shell function, from its first line to its `}`."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
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


def test_a_delegation_that_fell_through_to_another_route_does_not_pass_phase_4() -> (
    None
):
    phase_4 = _function_body("phase4")
    assert 'case "$served" in' in phase_4
    assert '"byok-$MODEL_CHOICE"*' in phase_4
    assert "not byok-$MODEL_CHOICE" in phase_4
    assert "phase_fail" in phase_4.split('"byok-$MODEL_CHOICE"*', 1)[1]


def test_the_stack_only_gets_a_tenant_when_a_key_was_chosen() -> None:
    phase_4 = _function_body("phase4")
    assert 'if uses_key "$MODEL_CHOICE"; then\n    step "give the stack a tenant' in (
        phase_4
    )
    assert phase_4.index("ensure_stack_tenant") < phase_4.index("make up-local")


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
        **extra,
    }


def _phase0_only(tmp_path: Path) -> Path:
    p = tmp_path / "phase0.sh"
    p.write_text(SCRIPT.read_text().replace("\nmain\n", "\nphase0\n"))
    return p


@pytest.mark.parametrize("provider", ["none", "glm"])
def test_only_the_beta_providers_are_accepted(tmp_path: Path, provider: str) -> None:
    """No lab-model fallback, and GLM is out of the beta: gemini, openrouter, openai or ollama."""
    result = _run(tmp_path, "--provider", provider)
    assert result.returncode == 2
    assert "must be gemini, openrouter, openai or ollama" in result.stderr


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


@pytest.mark.parametrize(
    ("key", "outcome"),
    [("", "no key was given"), ("not-a-real-key", "Model key: received")],
)
def test_the_key_is_settled_in_preflight(
    tmp_path: Path, key: str, outcome: str
) -> None:
    """Provider then key, both before anything installs; an empty key stops the run."""
    out, returncode = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        _phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        [("Choose 1, 2, 3 or 4:", "1"), ("key (input is hidden)", key)],
    )
    assert outcome in out
    assert (
        "not-a-real-key" not in out.split("key (input is hidden)")[-1]
    )  # never echoed
    assert sorted(p for p in (tmp_path / "home").rglob("*")) == []


def _stored_keys(tmp_path: Path, *providers: str) -> None:
    """A fake `onex` whose `secret list` reports keys an earlier run stored."""
    bindir = tmp_path / "home" / ".local" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"    llm.{p}.api_key  (updated 2026-10-02)\n" for p in providers)
    onex = bindir / "onex"
    onex.write_text(f'#!/bin/sh\n[ "$1" = secret ] || exit 1\ncat <<EOF\n{rows}EOF\n')
    onex.chmod(0o755)


def test_a_stored_key_is_offered_and_not_assumed(tmp_path: Path) -> None:
    """AC1 (OMN-20393): the run names the stored provider and offers to change it."""
    _stored_keys(tmp_path, "openai")
    out, _ = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        _phase0_env(tmp_path),
        [("Use it?", "n"), ("Choose 1, 2, 3 or 4:", "q")],
    )
    assert "already has your OpenAI key stored" in out
    assert "Choose 1, 2, 3 or 4:" in out, (
        "declining the stored key reached no model menu"
    )


def test_keeping_the_stored_key_asks_nothing_further(tmp_path: Path) -> None:
    """AC1 (OMN-20393): keeping it is one keystroke, and no key is re-typed."""
    _stored_keys(tmp_path, "openai")
    out, _ = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        _phase0_env(tmp_path),
        [("Use it?", "y")],
    )
    assert "your openai key is already stored; it will be used" in out
    assert "key (input is hidden)" not in out


def test_an_unattended_run_still_uses_the_stored_key(tmp_path: Path) -> None:
    """AC1 (OMN-20393): with nowhere to ask, the stored key is used and named."""
    _stored_keys(tmp_path, "openai")
    result = subprocess.run(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        env=_phase0_env(tmp_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert "No terminal or desktop to ask on" in result.stdout
    assert "your openai key is already stored" in result.stdout


def test_the_stored_providers_own_key_can_be_replaced(tmp_path: Path) -> None:
    """AC2 (OMN-20393): --provider equal to the stored one reaches the key prompt."""
    _stored_keys(tmp_path, "openai")
    out, _ = _drive_tty(
        [
            "/bin/bash",
            str(_phase0_only(tmp_path)),
            "--no-containers",
            "--provider",
            "openai",
        ],
        _phase0_env(tmp_path),
        [("key (input is hidden)", "replacement-key")],
    )
    assert "Model key: received" in out
    assert "already stored; it will be used" not in out


def test_two_stored_keys_let_the_developer_pick(tmp_path: Path) -> None:
    """AC3 (OMN-20393): the developer's choice wins, not the scan order."""
    _stored_keys(tmp_path, "openrouter", "gemini")
    out, _ = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        _phase0_env(tmp_path),
        [("Which one?", "2")],
    )
    assert "your gemini key is already stored; it will be used" in out
    assert "your openrouter key is already stored" not in out


def test_the_scan_order_is_documented_as_a_fallback_only() -> None:
    """AC3 (OMN-20393): nothing picks a stored provider by scan order while a
    developer can be asked."""
    body = _function_body("stored_key_provider")
    assert "stored_key_providers | head -n 1" in body
    offer = _function_body("offer_stored_key")
    assert "No terminal or desktop to ask on" in offer


@pytest.mark.parametrize(
    "answers",
    [
        [
            ("Choose 1, 2, 3 or 4:", "4"),
            ("Set up the local stack in Docker too?", "q"),
        ],
        [("Choose 1, 2, 3 or 4:", "q")],
    ],
    ids=["quit-at-docker", "quit-at-provider"],
)
def test_quit_setup_stops_before_anything_installs(
    tmp_path: Path, answers: list[tuple[str, str]]
) -> None:
    """ "Quit setup" (q on a terminal) is offered only before any install, and says so."""
    out, returncode = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path))],
        _phase0_env(
            tmp_path,
            ONBOARD_TEST_RAM_GB="32",
            ONBOARD_TEST_CPUS="10",
            ONBOARD_TEST_VM="0",
        ),
        answers,
    )
    assert "Nothing was installed. Run onboarding again when you're ready." in out
    assert returncode == 4, out[-400:]
    assert sorted((tmp_path / "home").rglob("*")) == []


def _functions(*names: str) -> str:
    """The named top-level functions of the script, as bash source."""
    out, keep = [], False
    for line in SCRIPT.read_text().splitlines():
        if any(line.startswith(f"{n}() {{") for n in names):
            keep = True
        if keep:
            out.append(line)
            if line == "}":
                keep = False
    return "\n".join(out)


def test_phase5_installs_the_full_onex_tree_and_omni_where_reachable() -> None:
    text = SCRIPT.read_text()
    assert "plugin install onex@omninode-tools-dev" in text
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


def test_choosing_ollama_on_the_menu_skips_the_key(tmp_path: Path) -> None:
    out, returncode = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        _phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        [("Choose 1, 2, 3 or 4:", "4")],
    )
    assert "Model: Ollama on this Mac, no key." in out
    assert "key (input is hidden)" not in out


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


def test_every_dialog_activates_before_it_asks() -> None:
    """A dialog that never activates cannot be typed into.

    `osascript` shows the dialog but keyboard focus stays with the frontmost
    app, so a `default answer` field reads as locked and the confirm button
    returns an empty answer. Click-only dialogs still work, which is why this
    surfaced on exactly the two that take typing: the model key and the
    administrator password. Both are the developer's only way through the run
    when there is no tty.
    """
    text = SCRIPT.read_text()
    missing = []
    for match in re.finditer(r"display dialog|choose from list", text):
        window = text[max(0, match.start() - 900) : match.start()]
        if "activate" not in window:
            missing.append(text[match.start() : match.start() + 70])
    assert not missing, (
        "these dialogs never activate, so their fields cannot take keystrokes: "
        f"{missing}"
    )


def test_the_key_dialog_is_not_indented_like_the_terminal_prompt() -> None:
    body = _functions("read_secret")
    assert "sed 's/^[[:space:]]*//'" in body


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
    """The hardcoded-model-config gate's rule: those live in the model config."""
    text = SCRIPT.read_text()
    assert not re.search(r"qwen|gpt-oss|llama[0-9]|11434", text)
    assert "/v1/chat/completions" not in text


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


def test_choosing_openai_on_the_menu_asks_for_an_openai_key(tmp_path: Path) -> None:
    out, returncode = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path)), "--no-containers"],
        _phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        [("Choose 1, 2, 3 or 4:", "3"), ("key (input is hidden)", "")],
    )
    assert "Paste your OpenAI API key (input is hidden):" in out
    assert "it is only ever sent to OpenAI" in out


def test_the_model_is_asked_before_docker(tmp_path: Path) -> None:
    out, returncode = _drive_tty(
        ["/bin/bash", str(_phase0_only(tmp_path))],
        _phase0_env(
            tmp_path,
            ONBOARD_TEST_RAM_GB="32",
            ONBOARD_TEST_CPUS="10",
            ONBOARD_TEST_VM="0",
        ),
        [
            ("Choose 1, 2, 3 or 4:", "4"),
            ("Set up the local stack in Docker too?", "n"),
        ],
    )
    assert out.index("Choose 1, 2, 3 or 4:") < out.index(
        "Set up the local stack in Docker too?"
    )


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
    assert "set msg to (item 1 of argv)" in _functions("ask_docker")


def test_questions_go_to_dialogs_whenever_there_is_a_desktop() -> None:
    """The terminal shows progress; questions are dialogs unless there is no desktop."""
    text = SCRIPT.read_text()
    assert (
        'if [ "$IS_TTY" -eq 1 ] && { [ "$GUI_SESSION" -eq 0 ] || [ "${ONBOARD_PROMPTS:-}" = "terminal" ]; }; then'
        in text
    )
    for fn in (
        "ask_provider",
        "read_secret",
        "ask_docker",
        "ensure_sudo",
        "accept_docker_terms",
    ):
        body = _functions(fn)
        assert '"$IS_TTY"' not in body, fn
        assert '"$PROMPT_TTY"' in body, fn
