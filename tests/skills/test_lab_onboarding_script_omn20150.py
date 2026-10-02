# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20150: the lab onboarding script's preflight contract.

Preflight reads the machine and changes nothing. A machine below the minimum
exits 3 having written nothing under $HOME, and a VM is never given containers.
Readings are overridden through the script's ONBOARD_TEST_* seams, so these run
on any macOS host and install nothing. The script must also parse under the
stock macOS /bin/bash 3.2 (the D4 failure class).
"""

from __future__ import annotations

import os
import re
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
SKILL = SCRIPT.parents[1] / "omninode_dev_setup" / "SKILL.md"

pytestmark = pytest.mark.unit
macos_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="the script targets macOS only"
)


def _run(tmp_path: Path, *args: str, **seams: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(tmp_path / "run") + "/",
        "ONBOARD_NOTIFY": "0",
        "ONBOARD_TEST_DISK_GB": "100",
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
        if re.search(rb"\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]", line)
    ]
    assert not offenders, (
        "brace these expansions; on bash 3.2 the multibyte character joins the "
        f"variable name: {offenders}"
    )


def test_the_multibyte_expansion_guard_would_catch_the_regression(
    tmp_path: Path,
) -> None:
    """The guard above is worthless if it cannot fail, so prove it fails."""
    bash = "/bin/bash" if os.path.exists("/bin/bash") else "bash"
    probe = tmp_path / "probe.sh"
    probe.write_text('set -u\nf=gh\necho "Installing $f\u2026"\n', encoding="utf-8")
    assert subprocess.run([bash, "-n", str(probe)], check=False).returncode == 0
    # stderr carries the stray 0xE2 itself, so it is not decodable as UTF-8.
    result = subprocess.run([bash, str(probe)], capture_output=True, check=False)
    assert result.returncode != 0, "bash 3.2 should refuse the unbraced form"
    assert b"unbound variable" in result.stderr


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


@macos_only
def test_below_minimum_exits_3_and_writes_nothing_under_home(tmp_path: Path) -> None:
    result = _run(tmp_path, ONBOARD_TEST_RAM_GB="4")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "below the minimum requirements" in result.stdout
    assert "Nothing was installed" in result.stdout
    assert "VM" in result.stdout
    assert _home_files(tmp_path) == []


@macos_only
def test_preflight_only_changes_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, "--preflight-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Preflight only: nothing was changed." in result.stdout
    assert _home_files(tmp_path) == []


@macos_only
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


@macos_only
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


@macos_only
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


@macos_only
def test_no_containers_is_honoured(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--preflight-only",
        "--no-containers",
        ONBOARD_TEST_RAM_GB="32",
        ONBOARD_TEST_CPUS="10",
    )
    assert "No local Docker: --no-containers was passed" in result.stdout


@macos_only
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


@macos_only
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


@macos_only
def test_status_file_records_each_phase(tmp_path: Path) -> None:
    _run(tmp_path, "--preflight-only")
    status = (tmp_path / "run" / "omninode-onboarding" / "status").read_text()
    assert 'phase=0 name="Preflight' in status
    assert "result=PASS" in status


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


@macos_only
@pytest.mark.skipif(
    not os.path.exists("/usr/bin/expect"), reason="needs expect to answer on a terminal"
)
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
        "ONBOARD_TEST_DISK_GB": "100",
        "ONBOARD_TEST_RAM_GB": "32",
        "ONBOARD_TEST_CPUS": "10",
        "ONBOARD_TEST_VM": "0",
        "ONBOARD_TEST_ADMIN": "1",
        "ONBOARD_TEST_NO_GUI": "1",
    }
    script = (
        f"set timeout 60; spawn /bin/bash {phase0_only} --provider gemini; "
        'expect "key (input is hidden)"; send "not-a-real-key\\r"; '
        f'expect "Set up the local stack in Docker too?"; send "{answer}\\r"; expect eof'
    )
    result = subprocess.run(
        ["/usr/bin/expect", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = result.stdout.replace("\r", "")
    if "ports in use" in out:
        pytest.skip("the local stack's ports are held by something else on this host")
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
        "ONBOARD_TEST_NO_GUI": "1",
        "ONBOARD_TEST_DISK_GB": "100",
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


@macos_only
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


@macos_only
@pytest.mark.skipif(
    not os.path.exists("/usr/bin/expect"), reason="needs expect to answer on a terminal"
)
@pytest.mark.parametrize(
    ("key", "outcome"),
    [("", "no key was given"), ("not-a-real-key", "Model key: received")],
)
def test_the_key_is_settled_in_preflight(
    tmp_path: Path, key: str, outcome: str
) -> None:
    """Provider then key, both before anything installs; an empty key stops the run."""
    script = (
        f"set timeout 60; spawn /bin/bash {_phase0_only(tmp_path)} --no-containers; "
        'expect "Choose 1, 2, 3 or 4:"; send "1\\r"; '
        f'expect "key (input is hidden)"; send "{key}\\r"; expect eof'
    )
    result = subprocess.run(
        ["/usr/bin/expect", "-c", script],
        env=_phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = result.stdout.replace("\r", "")
    assert outcome in out
    assert (
        "not-a-real-key" not in out.split("key (input is hidden)")[-1]
    )  # never echoed
    assert sorted(p for p in (tmp_path / "home").rglob("*")) == []


@macos_only
@pytest.mark.skipif(
    not os.path.exists("/usr/bin/expect"), reason="needs expect to answer on a terminal"
)
@pytest.mark.parametrize(
    "answers",
    [
        'expect "Choose 1, 2, 3 or 4:"; send "4\\r"; expect "Set up the local stack in Docker too?"; send "q\\r"; ',
        'expect "Choose 1, 2, 3 or 4:"; send "q\\r"; ',
    ],
    ids=["quit-at-docker", "quit-at-provider"],
)
def test_quit_setup_stops_before_anything_installs(
    tmp_path: Path, answers: str
) -> None:
    """ "Quit setup" (q on a terminal) is offered only before any install, and says so."""
    script = f"set timeout 60; spawn /bin/bash {_phase0_only(tmp_path)}; {answers}expect eof; catch wait result; exit [lindex $result 3]"
    result = subprocess.run(
        ["/usr/bin/expect", "-c", script],
        env=_phase0_env(
            tmp_path,
            ONBOARD_TEST_RAM_GB="32",
            ONBOARD_TEST_CPUS="10",
            ONBOARD_TEST_VM="0",
        ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = result.stdout.replace("\r", "")
    if "ports in use" in out:
        pytest.skip("the local stack's ports are held by something else on this host")
    assert "Nothing was installed. Run onboarding again when you're ready." in out
    assert result.returncode == 4, out[-400:]
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


@macos_only
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


@macos_only
@pytest.mark.skipif(
    not os.path.exists("/usr/bin/expect"), reason="needs expect to answer on a terminal"
)
def test_choosing_ollama_on_the_menu_skips_the_key(tmp_path: Path) -> None:
    script = (
        f"set timeout 60; spawn /bin/bash {_phase0_only(tmp_path)} --no-containers; "
        'expect "Choose 1, 2, 3 or 4:"; send "4\\r"; expect eof'
    )
    result = subprocess.run(
        ["/usr/bin/expect", "-c", script],
        env=_phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = result.stdout.replace("\r", "")
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


@macos_only  # the script edits with BSD sed (-i '')
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
        _functions("point_bundle_model")
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


@macos_only
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


def test_the_key_dialog_is_not_indented_like_the_terminal_prompt() -> None:
    body = _functions("read_secret")
    assert "sed 's/^[[:space:]]*//'" in body


@macos_only
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


@macos_only
@pytest.mark.skipif(
    not os.path.exists("/usr/bin/expect"), reason="needs expect to answer on a terminal"
)
def test_choosing_openai_on_the_menu_asks_for_an_openai_key(tmp_path: Path) -> None:
    script = (
        f"set timeout 60; spawn /bin/bash {_phase0_only(tmp_path)} --no-containers; "
        'expect "Choose 1, 2, 3 or 4:"; send "3\\r"; '
        'expect "key (input is hidden)"; send "\\r"; expect eof'
    )
    result = subprocess.run(
        ["/usr/bin/expect", "-c", script],
        env=_phase0_env(tmp_path, ONBOARD_TEST_RAM_GB="32", ONBOARD_TEST_CPUS="10"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = result.stdout.replace("\r", "")
    assert "Paste your OpenAI API key (input is hidden):" in out
    assert "it is only ever sent to OpenAI" in out


@macos_only
@pytest.mark.skipif(
    not os.path.exists("/usr/bin/expect"), reason="needs expect to answer on a terminal"
)
def test_the_model_is_asked_before_docker(tmp_path: Path) -> None:
    script = (
        f"set timeout 60; spawn /bin/bash {_phase0_only(tmp_path)}; "
        'expect "Choose 1, 2, 3 or 4:"; send "4\\r"; '
        'expect "Set up the local stack in Docker too?"; send "n\\r"; expect eof'
    )
    result = subprocess.run(
        ["/usr/bin/expect", "-c", script],
        env=_phase0_env(
            tmp_path,
            ONBOARD_TEST_RAM_GB="32",
            ONBOARD_TEST_CPUS="10",
            ONBOARD_TEST_VM="0",
        ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = result.stdout.replace("\r", "")
    if "ports in use" in out:
        pytest.skip("the local stack's ports are held by something else on this host")
    assert out.index("Choose 1, 2, 3 or 4:") < out.index(
        "Set up the local stack in Docker too?"
    )


@macos_only
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
