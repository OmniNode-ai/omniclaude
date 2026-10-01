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
import socket
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
SKILL = SCRIPT.parents[1] / "lab_onboarding" / "SKILL.md"

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
    assert "No local Docker: you said no" in result.stdout


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
    assert "the lab dev lane runs your delegations" in result.stdout


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
    }
    script = (
        f"set timeout 60; spawn /bin/bash {phase0_only} --provider gemini; "
        f'expect "Set up the local stack in Docker too?"; send "{answer}\\r"; '
        'expect "key (input is hidden)"; send "not-a-real-key\\r"; expect eof'
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


_TEMPLATE_OVERLAY = (
    'backends:\n  - backend_id: local-coder\n    endpoint_url: &model_endpoint "http://host.docker.internal:8000/v1/chat/completions"\n'
    '    served_model_id: "a-placeholder-model"\n'
    '  - backend_id: local-heavy-reasoning\n    endpoint_url: *model_endpoint\n    served_model_id: "a-placeholder-model"\n'
)


@macos_only
def test_phase_6_writes_the_labs_model_into_the_overlay_not_the_templates(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".omnibase").mkdir(parents=True)
    overlay = home / ".omnibase" / "local.bifrost.yaml"
    overlay.write_text(_TEMPLATE_OVERLAY, encoding="utf-8")
    snippet = (
        f"{_function_body('point_bundle_model')}\n"
        'point_bundle_model "http://lab.example:8000/v1/chat/completions" "lab-served-id"\n'
    )
    subprocess.run(
        ["/bin/bash", "-c", snippet],
        env={"HOME": str(home), "STAMP": "t", "PATH": "/usr/bin:/bin"},
        check=True,
        capture_output=True,
        text=True,
    )
    text = overlay.read_text(encoding="utf-8")
    assert '&model_endpoint "http://lab.example:8000/v1/chat/completions"' in text
    assert text.count('served_model_id: "lab-served-id"') == 2
    assert "a-placeholder-model" not in text
    assert (home / ".omnibase" / "local.bifrost.yaml.pre-onboarding.t").exists()


@macos_only
def test_phase_6_leaves_an_overlay_the_developer_already_pointed_alone(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".omnibase").mkdir(parents=True)
    overlay = home / ".omnibase" / "local.bifrost.yaml"
    mine = _TEMPLATE_OVERLAY.replace("host.docker.internal:8000", "my-box:9000")
    overlay.write_text(mine, encoding="utf-8")
    snippet = (
        f"{_function_body('point_bundle_model')}\n"
        'point_bundle_model "http://lab.example:8000/v1/chat/completions" "lab-served-id"\n'
    )
    subprocess.run(
        ["/bin/bash", "-c", snippet],
        env={"HOME": str(home), "STAMP": "t", "PATH": "/usr/bin:/bin"},
        check=True,
        capture_output=True,
        text=True,
    )
    assert overlay.read_text(encoding="utf-8") == mine


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


def test_a_delegation_that_fell_through_to_the_lab_model_does_not_pass_phase_6() -> (
    None
):
    phase_6 = _function_body("phase6")
    assert 'case "$served" in' in phase_6
    assert '"byok-$MODEL_CHOICE"*' in phase_6
    assert "not byok-$MODEL_CHOICE" in phase_6
    assert "phase_fail" in phase_6.split('"byok-$MODEL_CHOICE"*', 1)[1]


def test_the_stack_only_gets_a_tenant_when_a_key_was_chosen() -> None:
    phase_6 = _function_body("phase6")
    assert (
        'if [ "$MODEL_CHOICE" != "none" ]; then\n    step "give the stack a tenant'
        in (phase_6)
    )
    assert phase_6.index("ensure_stack_tenant") < phase_6.index("make up-local")


def test_phase_5_does_not_let_a_bare_answered_read_as_proof_the_key_was_used() -> None:
    phase_5 = _function_body("phase5")
    assert "accepted_backend" in phase_5
    assert "was not used on the lab lane" in phase_5


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
    """No lab-model fallback, and GLM is out of the beta: only openrouter and gemini."""
    result = _run(tmp_path, "--provider", provider)
    assert result.returncode == 2
    assert "must be openrouter or gemini" in result.stderr


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
        'expect "Choose 1 or 2:"; send "2\\r"; '
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
        'expect "Set up the local stack in Docker too?"; send "q\\r"; ',
        'expect "Set up the local stack in Docker too?"; send "n\\r"; expect "Choose 1 or 2:"; send "q\\r"; ',
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


@pytest.mark.parametrize(
    ("status", "rc", "next_words"),
    [
        (201, 0, None),
        (403, 86, "sign in to Tailscale as yourself"),
        (409, 86, "ask the lab operator to retire one"),
        (502, 1, None),
    ],
)
def test_an_issuer_refusal_is_reported_not_retried(
    tmp_path: Path, status: int, rc: int, next_words: str | None
) -> None:
    """A 4xx is the issuer's answer about this machine, so asking again cannot help."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Issuer(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            ok = {"principal": "dev-x", "password": "p"}  # pragma: allowlist secret
            body = json.dumps(ok if status < 300 else {"error": "refused"}).encode()
            self.send_response(status)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Issuer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        harness = (
            "REFUSED=86\n"
            + _functions("request_identity", "refusal_next")
            + "\nlab_fact() { case $1 in principal_issuer_url) "
            + f"echo http://127.0.0.1:{server.server_port};; lane) echo dev;; esac; }}\n"
            + 'out="$(request_identity 2>err)"; rc=$?; LAST_ERR="$(cat err)"\n'
            + 'echo "rc=$rc"; [ "$rc" -eq "$REFUSED" ] && echo "next=$(refusal_next)"\n'
        )
        result = subprocess.run(
            ["/bin/bash", "-c", harness],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=tmp_path,
        )
    finally:
        server.shutdown()
    assert f"rc={rc}" in result.stdout, result.stdout + result.stderr
    if next_words:
        assert next_words in result.stdout


def test_retry_capture_stops_at_a_refusal() -> None:
    text = SCRIPT.read_text()
    assert '[ "$n" -ge "$RETRIES" ] || [ "$rc" -eq "$REFUSED" ]' in text


def test_phase7_installs_the_full_onex_tree_and_omni_where_reachable() -> None:
    text = SCRIPT.read_text()
    assert "plugin install onex@omninode-tools-dev" in text
    assert (
        'plugin marketplace add "$WORKSPACE/omniclaude/plugins/"*-dev-marketplace'
        in text
    )
    assert "for p in omni onex-overlays" in text
    assert "internal_plugins_reachable" in text


def _ci_bus_harness(tmp_path: Path, facts: str, issuer_port: int | None) -> str:
    """ci_bus_identity with the machine-touching helpers stubbed out."""
    facts_file = tmp_path / "facts.yaml"
    url = f"http://127.0.0.1:{issuer_port}" if issuer_port else ""
    facts_file.write_text(facts.replace("URL", url))
    return (
        "REFUSED=86; REISSUE=0; CI_BUS_NOTE=; ISSUED_PRINCIPAL=\n"
        f"LOG={tmp_path}/log; ONBOARD_LAB_FACTS={facts_file}\n"
        + _functions("lab_fact", "request_identity", "refusal_next", "ci_bus_identity")
        + '\nsay() { echo "$*"; }\n'
        'phase_fail() { echo "FAIL: $*"; exit 1; }\n'
        "lane_identity_stored() { return 1; }\n"
        'retry_capture() { shift; CAPTURED="$("$@")"; }\n'
        'step() { shift; "$@"; }\n'
        'store_identity() { ISSUED_PRINCIPAL=$(printf \'%s\' "$CAPTURED" | jq -r .principal); echo "stored for $1"; }\n'
        'retry() { shift; "$@"; }\n'
        'lab_work_hosts() { echo "hosts on $1"; }\n'
        'ci_bus_identity; echo "note=$CI_BUS_NOTE"\n'
    )


def test_the_ci_bus_login_is_skipped_until_the_lab_offers_it(tmp_path: Path) -> None:
    # A port nothing listens on: the issuer is not deployed yet.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    harness = _ci_bus_harness(
        tmp_path, "lane: dev\nci_bus_lane: work-lane\nci_bus_issuer_url: URL\n", port
    )
    out = subprocess.run(
        ["/bin/bash", "-c", harness],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    ).stdout
    assert "the lab does not offer it yet; skipped" in out
    assert "note=no CI bus login yet" in out
    assert "FAIL" not in out


def test_an_older_workspace_without_ci_bus_facts_is_skipped(tmp_path: Path) -> None:
    harness = _ci_bus_harness(tmp_path, "lane: dev\n", None)
    out = subprocess.run(
        ["/bin/bash", "-c", harness],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    ).stdout
    assert "declares no CI bus issuer; skipped" in out
    assert "FAIL" not in out


def test_the_ci_bus_login_is_requested_for_its_own_lane_and_proven(
    tmp_path: Path,
) -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    asked: list[dict[str, str]] = []

    class Issuer(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_POST(self) -> None:
            asked.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            issued = {
                "principal": "dev-x-mac",
                "password": "p",  # pragma: allowlist secret
            }
            body = json.dumps(issued).encode()
            self.send_response(201)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Issuer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        harness = _ci_bus_harness(
            tmp_path,
            "lane: dev\nci_bus_lane: work-lane\nci_bus_issuer_url: URL\n",
            server.server_port,
        )
        out = subprocess.run(
            ["/bin/bash", "-c", harness],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        ).stdout
    finally:
        server.shutdown()
    assert [a["lane"] for a in asked] == ["work-lane"]
    assert "stored for work-lane" in out
    assert "Stored bus identity 'dev-x-mac' for lane work-lane." in out
    assert "hosts on work-lane" in out
    assert "note=CI bus login for lab work stored" in out
