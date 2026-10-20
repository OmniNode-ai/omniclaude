# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21087: onboarding on a machine that ran an earlier setup.

Preflight runs the existing install as the developer's shell does and reports
what an earlier setup left (an onex alias or function, old variables in the
profile, a published onex, a local-model routes file, clones holding work). It
asks once, before anything installs, whether to set those aside (moved or
commented out, never deleted) or stop. The run itself inherits none of the old
variables, a resumed run binds the onboarding workspace before any phase, and a
failed model test prints the error that caused it.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_preflight = importlib.import_module("test_lab_onboarding_script_omn20150")
SCRIPT = _preflight.SCRIPT
_drive_tty = _preflight._drive_tty
_functions = _preflight._functions
_run = _preflight._run

pytestmark = pytest.mark.unit

LEFTOVER_ENV = {
    "OMNI_HOME": "/old/omni",
    "OMNIBASE_INTERNAL_PATH": "/old/omni/internal-clone",
    "ONEX_EVENT_BUS_TYPE": "kafka",
    "ONEX_LAB_TENANT_STATE_DIR": "/old/tenant",
    "ONEX_STATE_DIR": "/old/omni/.onex_state",
    "ONEX_DISPATCH_VENV": "/old/venv",
    "ONEX_CONTRACTS_DIR": "/old/contracts",
    "KAFKA_BOOTSTRAP_SERVERS": "lab:9092",
}

ZSHRC = (
    "alias ll='ls -l'\n"
    "export OMNI_HOME=/old/omni\n"
    "alias onex='uv run --project $OMNI_HOME/omnibase_infra onex'\n"
    "export ONEX_LAB_TENANT_STATE_DIR=/old/tenant\n"
    "onex() {\n"
    "  echo old\n"
    "}\n"
    "export EDITOR=vim\n"
)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _seed_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".omninode" / "delegation").mkdir(parents=True)
    (home / ".zshrc").write_text(ZSHRC)
    (home / ".omninode" / "delegation" / "bifrost_overrides.yaml").write_text(
        "backends:\n  - backend_id: local-coder\n"
    )
    return home


def _sourced(
    tmp_path: Path, snippet: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """The whole script with its functions defined and main not run, then snippet."""
    body = SCRIPT.read_text()
    assert body.rstrip().endswith("\nmain")
    script = tmp_path / "sourced.sh"
    script.write_text(body.rstrip()[: -len("main")] + "\n" + snippet + "\n")
    (tmp_path / "run").mkdir(exist_ok=True)
    return subprocess.run(
        ["/bin/bash", str(script)],
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR": str(tmp_path / "run") + "/",
            "ONBOARD_NOTIFY": "0",
            "ONBOARD_TEST_NO_USER_SHELL": "1",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


# ---------------------------------------------------------------------------
# The run's own environment
# ---------------------------------------------------------------------------


def test_no_leftover_variable_reaches_the_run(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    result = _sourced(
        tmp_path,
        'echo "INHERITED=$INHERITED_ENV"; env | cut -d= -f1 | sort',
        **LEFTOVER_ENV,
    )
    assert result.returncode == 0, result.stderr
    names = set(result.stdout.splitlines())
    for name in LEFTOVER_ENV:
        assert name not in names, name
        assert name in result.stdout.split("INHERITED=", 1)[1].splitlines()[0]


def test_a_resumed_run_binds_the_workspace_before_any_phase(tmp_path: Path) -> None:
    """Phase 2 is skipped on resume; phase 3 must still run against this workspace."""
    (tmp_path / "home").mkdir()
    ws = tmp_path / "ws"
    stubs = "".join(f"phase{n}() {{ :; }}\n" for n in (0, 1, 2, 4, 5, 6))
    result = _sourced(
        tmp_path,
        stubs
        + 'phase3() { echo "P3 $OMNIBASE_PATH $ONEX_WORKSPACE_CONFIG_ROOT ${ONEX_STATE_DIR:-unset}"; }\n'
        + "main",
        OMNIBASE_PATH=str(ws),
        **LEFTOVER_ENV,
    )
    assert f"P3 {ws} {ws}/.onex/workspace-config unset" in result.stdout, (
        result.stdout + result.stderr
    )


# ---------------------------------------------------------------------------
# Preflight: what an earlier setup left, reported before anything installs
# ---------------------------------------------------------------------------


def test_preflight_reports_each_leftover_and_changes_nothing(tmp_path: Path) -> None:
    home = _seed_home(tmp_path)
    before = _snapshot(home)
    result = _run(
        tmp_path,
        "--preflight-only",
        "--no-containers",
        ONBOARD_TEST_NO_USER_SHELL="1",
        **LEFTOVER_ENV,
    )
    out = result.stdout
    assert result.returncode == 0, out + result.stderr
    assert "What an earlier setup left on this Mac" in out
    assert "✗ ~/.zshrc line 2: export OMNI_HOME=…" in out
    assert "✗ ~/.zshrc line 3: alias onex=…" in out
    assert "✗ ~/.zshrc line 4: export ONEX_LAB_TENANT_STATE_DIR=…" in out
    assert "✗ ~/.zshrc line 5: onex() {" in out
    assert (
        "✗ ~/.omninode/delegation/bifrost_overrides.yaml (not written by this setup)"
        in out
    )
    assert "· exported in this terminal: " in out and "ONEX_STATE_DIR" in out
    assert "line 1:" not in out and "EDITOR" not in out
    assert "5 of these (✗) would interfere" in out
    assert _snapshot(home) == before


def test_preflight_never_starts_a_tool_that_writes_under_home(tmp_path: Path) -> None:
    """A first `pipx list` creates pipx's directories; preflight writes nothing in $HOME."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("pipx", "uv"):
        (tools / name).write_text(f'#!/bin/sh\ntouch "$HOME/{name}-was-run"\n')
        (tools / name).chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    result = _run(
        tmp_path,
        "--preflight-only",
        "--no-containers",
        PATH=f"{tools}:/usr/bin:/bin:/usr/sbin:/sbin",
        ONBOARD_TEST_NO_USER_SHELL="1",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(p.name for p in home.rglob("*")) == []


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_preflight_runs_onex_as_the_developers_shell_does(tmp_path: Path) -> None:
    """The reported case: an alias in the profile shadowed the installed onex."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("alias onex='echo old-onex 0.4.3'\n")
    result = _run(tmp_path, "--preflight-only", "--no-containers", SHELL="/bin/bash")
    out = result.stdout
    assert result.returncode == 0, out + result.stderr
    assert "✗ onex is a shell alias (onex --version: old-onex 0.4.3 --version)" in out
    assert "shadows the onex this setup installs" in out


def test_with_no_terminal_leftovers_stop_the_run_before_installing(
    tmp_path: Path,
) -> None:
    home = _seed_home(tmp_path)
    before = _snapshot(home)
    result = _run(tmp_path, "--no-containers", ONBOARD_TEST_NO_USER_SHELL="1")
    assert result.returncode == 1, result.stdout
    assert "FAILED: Preflight" in result.stdout
    assert "pass --set-aside" in result.stdout
    assert "Nothing was installed or changed" in result.stdout
    assert _snapshot(home) == before


def test_q_at_the_set_aside_question_stops_with_nothing_changed(
    tmp_path: Path,
) -> None:
    home = _seed_home(tmp_path)
    before = _snapshot(home)
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
        "ONBOARD_TEST_NO_USER_SHELL": "1",
    }
    (tmp_path / "run").mkdir()
    out, code = _drive_tty(
        ["/bin/bash", str(SCRIPT), "--no-containers"],
        env,
        [("Set them aside now?", "q")],
        # The merge-base control has no such question and waits at the model
        # prompt instead: fail inside the verifier's 30 s per-check ceiling.
        timeout=6,
    )
    assert code == 4, out
    assert "Nothing was installed" in out
    assert _snapshot(home) == before


def test_setting_aside_comments_out_and_moves_never_deletes(tmp_path: Path) -> None:
    home = _seed_home(tmp_path)
    routes = home / ".omninode" / "delegation" / "bifrost_overrides.yaml"
    routes_text = routes.read_text()
    result = _sourced(
        tmp_path,
        "STAMP=T1; survey_leftovers; SET_ASIDE=1; set_aside_leftovers\n"
        'survey_leftovers; echo "LEFT=$(leftovers_interfering)"',
    )
    out = result.stdout
    assert result.returncode == 0, out + result.stderr
    zshrc = (home / ".zshrc").read_text().splitlines()
    mark = ": # [set aside by omninode-dev-setup T1] "
    assert zshrc == [
        "alias ll='ls -l'",
        mark + "export OMNI_HOME=/old/omni",
        mark + "alias onex='uv run --project $OMNI_HOME/omnibase_infra onex'",
        mark + "export ONEX_LAB_TENANT_STATE_DIR=/old/tenant",
        mark + "onex() {",
        mark + "  echo old",
        mark + "}",
        "export EDITOR=vim",
    ]
    assert (home / ".zshrc.pre-onboarding.T1").read_text() == ZSHRC
    assert not routes.exists()
    assert (routes.parent / "bifrost_overrides.yaml.pre-onboarding.T1").read_text() == (
        routes_text
    )
    listed = (home / ".omninode" / "onboarding" / "set-aside.T1.txt").read_text()
    assert listed.count("\n") == 5
    assert "LEFT=0" in out
    if shutil.which("zsh"):
        subprocess.run(["zsh", "-n", str(home / ".zshrc")], check=True)


def test_a_clone_holding_work_is_moved_aside_whole(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    ws = tmp_path / "ws"
    clone = ws / "omnimarket"
    clone.mkdir(parents=True)
    (ws / ".omninode-dev-setup").write_text("ours\n")
    git = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (
        ["init", "--quiet", "-b", "dev"],
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "mine",
        ],
    ):
        subprocess.run(
            ["git", "-C", str(clone), *args],
            check=True,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin", **git},
        )
    result = _sourced(
        tmp_path,
        'STAMP=T2; clone_problem() { echo "1 commit(s) that origin does not have"; }\n'
        "survey_leftovers; SET_ASIDE=1; set_aside_leftovers",
        OMNIBASE_PATH=str(ws),
        **git,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not clone.exists()
    assert (ws / ".set-aside" / "omnimarket.T2" / ".git").is_dir()


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def test_a_resumed_run_says_where_it_picks_up_and_keeps_its_answers(
    tmp_path: Path,
) -> None:
    state = tmp_path / "home" / ".omninode" / "onboarding"
    state.mkdir(parents=True)
    (state / "phases.v2.done").write_text("1\n2\n")
    (state / "choices").write_text("models=openrouter\ncontainers=0\n")
    result = _run(tmp_path, "--preflight-only", ONBOARD_TEST_NO_USER_SHELL="1")
    out = result.stdout
    assert result.returncode == 0, out + result.stderr
    assert "Resuming an earlier run: phase(s) 1, 2 passed then" in out
    assert "picks up at phase 3" in out
    assert "Docker: no, as in your last run" in out
    assert "One optional extra" not in out


def test_restart_ignores_the_last_runs_answers(tmp_path: Path) -> None:
    state = tmp_path / "home" / ".omninode" / "onboarding"
    state.mkdir(parents=True)
    (state / "phases.v2.done").write_text("1\n2\n")
    (state / "choices").write_text("models=openrouter\ncontainers=0\n")
    result = _run(
        tmp_path, "--preflight-only", "--restart", ONBOARD_TEST_NO_USER_SHELL="1"
    )
    assert "Resuming" not in result.stdout
    assert "as in your last run" not in result.stdout


# ---------------------------------------------------------------------------
# Phase 3 names the error, not just an exit status
# ---------------------------------------------------------------------------


def test_a_failed_model_test_prints_the_error_that_caused_it(tmp_path: Path) -> None:
    fake = tmp_path / "models"
    fake.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = default-model ]; then echo fixture-vendor/model; exit 0; fi\n'
        "cat >/dev/null\n"
        'echo "delegate artifacts (REFUSED -- refused_before_dispatch): /x" >&2\n'
        'echo "Error: lab tenant declaration /y/lab_run_hosts.yaml refused: '
        'expected one host row for omnibook, found 0" >&2\n'
        'echo \'{"provider": "openrouter", "status": "failed", '
        '"reason": "the test delegation exited with status 1"}\'\n'
    )
    fake.chmod(0o755)
    snippet = (
        f"LOG=/dev/null; RUN_DIR={tmp_path}; KEY_OPENROUTER=k; KEY_GEMINI=; KEY_OPENAI=\n"
        + _functions(
            "pending_key",
            "set_pending_key",
            "provider_label",
            "receipt_field",
            "set_result",
            "result_of",
            "result_line",
            "cause_of",
            "default_model",
            "setup_model",
        )
        + f'\nmodels_cmd() {{ "{fake}" "$@"; }}\n'
        + "setup_model openrouter; result_line openrouter\n"
    )
    out = subprocess.run(
        ["/bin/bash", "-c", snippet], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == (
        "OpenRouter  ✗ the test delegation exited with status 1: lab tenant "
        "declaration /y/lab_run_hosts.yaml refused: expected one host row for "
        "omnibook, found 0"
    )


def test_a_resumed_phase_3_checks_the_venv_before_rebuilding_it() -> None:
    text = SCRIPT.read_text()
    phase3 = text.split("phase3() {", 1)[1].split("\n}", 1)[0]
    assert phase3.index("dispatch_venv_current") < phase3.index("--proven")
    check = text.split("dispatch_venv_current() {", 1)[1].split("\n}", 1)[0]
    assert "--check" in check and "--proven" not in check


NESTED_ZSHRC = (
    "onex() {\n"
    "  if true; then\n"
    "    { echo a; }\n"
    "  fi\n"
    "  for x in 1; do\n"
    "    inner() {\n"
    "      echo b\n"
    "    }\n"
    "  done\n"
    "}\n"
    "export EDITOR=vim\n"
)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_setting_aside_keeps_every_profile_parseable(tmp_path: Path) -> None:
    """A nested function body is commented out whole; an alias alone in an if stays valid."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text(NESTED_ZSHRC)
    (home / ".bashrc").write_text(
        "if true; then\n  alias onex='old'\nfi\nonex() { echo one-line; }\n"
    )
    result = _sourced(
        tmp_path, "STAMP=T3; survey_leftovers; SET_ASIDE=1; set_aside_leftovers"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    mark = ": # [set aside by omninode-dev-setup T3] "
    zshrc = (home / ".zshrc").read_text().splitlines()
    assert all(line.startswith(mark) for line in zshrc[:10]), zshrc
    assert zshrc[10] == "export EDITOR=vim"
    bashrc = (home / ".bashrc").read_text().splitlines()
    assert bashrc == [
        "if true; then",
        mark + "  alias onex='old'",
        "fi",
        mark + "onex() { echo one-line; }",
    ]
    if shutil.which("zsh"):
        subprocess.run(["zsh", "-n", str(home / ".zshrc")], check=True)
    subprocess.run(["bash", "-n", str(home / ".bashrc")], check=True)


def test_an_edit_that_would_break_a_profile_changes_nothing(tmp_path: Path) -> None:
    """A brace inside a string ends the body early; the broken copy is refused."""
    home = tmp_path / "home"
    home.mkdir()
    text = 'onex() {\n  echo "}"\n  echo hi\n}\n'
    (home / ".bashrc").write_text(text)
    routes = home / ".omninode" / "delegation" / "bifrost_overrides.yaml"
    routes.parent.mkdir(parents=True)
    routes.write_text("backends: []\n")
    result = _sourced(
        tmp_path, "STAMP=T4; survey_leftovers; SET_ASIDE=1; set_aside_leftovers"
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "unreadable by its shell" in result.stdout
    assert "Nothing was installed or changed" in result.stdout
    assert (home / ".bashrc").read_text() == text
    assert routes.exists()
    assert not list(home.glob(".bashrc.pre-onboarding.*"))


def test_an_alias_in_a_file_setup_does_not_read_stops_before_asking(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".config" / "extra.sh").write_text("alias onex='old'\n")
    (home / ".bashrc").write_text(". ~/.config/extra.sh\n")
    before = _snapshot(home)
    result = _run(tmp_path, "--no-containers", "--set-aside", SHELL="/bin/bash")
    out = result.stdout
    assert result.returncode == 1, out + result.stderr
    assert "✗ the onex alias is defined in a file this setup does not read" in out
    assert "remove it by hand" in out
    assert "Nothing was installed or changed" in out
    assert _snapshot(home) == before


def test_a_run_whose_phases_all_passed_says_it_only_checks_them(
    tmp_path: Path,
) -> None:
    state = tmp_path / "home" / ".omninode" / "onboarding"
    state.mkdir(parents=True)
    (state / "phases.v2.done").write_text("1\n2\n3\n4\n5\n6\n")
    result = _run(tmp_path, "--preflight-only", ONBOARD_TEST_NO_USER_SHELL="1")
    assert "every phase passed, so this run only checks them" in result.stdout
    assert "picks up at phase" not in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_phase_6_checks_what_a_new_terminal_runs(tmp_path: Path) -> None:
    """Run with the developer's shell: an alias fails it; the workspace onex passes it."""
    home = tmp_path / "home"
    ws = tmp_path / "ws"
    wrapper = ws / "omnibase_infra" / "scripts" / "onex"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/bin/sh\necho workspace\n")
    wrapper.chmod(0o755)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "onex").symlink_to(wrapper)
    bashrc = home / ".bashrc"
    bashrc.write_text(f'export PATH="{home}/.local/bin:$PATH"\nalias onex=old\n')
    probe = "shell_runs_workspace_onex; echo rc=$?"
    env = {
        "SHELL": "/bin/bash",
        "OMNIBASE_PATH": str(ws),
        "ONBOARD_TEST_NO_USER_SHELL": "0",
    }
    shadowed = _sourced(tmp_path, probe, **env)
    assert "in a new terminal onex is: alias" in shadowed.stdout, shadowed.stderr
    assert "rc=1" in shadowed.stdout
    bashrc.write_text(f'export PATH="{home}/.local/bin:$PATH"\n')
    clean = _sourced(tmp_path, probe, **env)
    assert "rc=0" in clean.stdout, clean.stdout + clean.stderr
