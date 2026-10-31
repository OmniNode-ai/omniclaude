# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The ``onex:preflight`` skill picks its runner profile from the team identity [OMN-21388].

The skill resolves the session's role through G0's resolver, the omnimarket node
``node_team_identity_compute``, and runs the session preflight runner with
``--profile operator`` only when that node positively identifies the operator.
Every other outcome — a member match, no authenticated identity to offer, the
node missing, failing, or answering something unreadable — runs ``--profile
team``. Unknown identity gets team restrictions, never the operator's.

The identity offered to that node is the **declared lane identity** [OMN-21660]: the broker
principal of the lane the hook edge contract declares, read from the surface the contract
names for that lane (the ``~/.onex`` lane store or the operator env file). The skill never
calls ``gh``: on a lane the ``gh`` shim refuses ``gh api user``, and a block that depends on
it cannot run there.

The skill's selection is the one shell block in ``SKILL.md`` that opens with the
``# onex:preflight profile selection`` marker. These tests run that exact block
with ``onex`` and the runner replaced by recorders and ``gh`` replaced by a stub that
refuses every call, so what is proven is
the text a session actually executes.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "plugins" / "onex" / "skills" / "preflight" / "SKILL.md"
_MARKER = "# onex:preflight profile selection"
_NODE = "node_team_identity_compute"

_FAKE_RUNNER = """\
import json, os, sys
with open(os.environ["FAKE_RUNNER_LOG"], "w") as stream:
    json.dump(sys.argv[1:], stream)
"""

# Records its argv and the input file it was handed, then answers per STUB_ONEX_MODE.
_FAKE_ONEX = r"""#!/bin/sh
printf '%s\n' "$*" > "$STUB_ONEX_LOG"
input=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--input" ]; then input="$arg"; fi
  prev="$arg"
done
if [ -n "$input" ]; then cp "$input" "$STUB_ONEX_INPUT_COPY"; fi
receipt() {
  printf '{"status": "%s", "exit_code": 0, "node_name": "node_team_identity_compute", "result_model": "ModelTeamIdentityResult", "result": {"privileges": "%s", "entry_id": "%s", "role": "%s", "diagnostic": null, "source": null}}\n' "$1" "$2" "$3" "$4"
}
case "$STUB_ONEX_MODE" in
  operator) receipt success operator lead operator ;;
  member) receipt success team member-1 member ;;
  unknown) printf '{"status": "success", "exit_code": 0, "result": {"privileges": "team", "entry_id": null, "role": null, "diagnostic": "names no entry", "source": null}}\n' ;;
  failed_status) receipt failed operator lead operator ;;
  nonzero) receipt success operator lead operator; exit 1 ;;
  garbage) printf 'drift_guard: proceed\nnot json at all\n' ;;
  list) printf '[{"result": {"privileges": "operator"}}]\n' ;;
  *) exit 3 ;;
esac
"""

# The lane gh shim: every call is refused, and the attempt is recorded.
_FAKE_GH = r"""#!/bin/sh
printf '%s\n' "$*" >> "$STUB_GH_LOG"
echo "gh: refused by the lane shim" >&2
exit 4
"""

_PRINCIPAL = "lane-principal"
_HOOKS = _REPO_ROOT / "plugins" / "onex" / "hooks"


def _write_lane_store(
    home: Path, *, username: str | None = _PRINCIPAL, mode: int = 0o600
) -> None:
    """The ``~/.onex`` store ``onex auth lane-login`` writes, for the declared dev lane."""
    onex = home / ".onex"
    onex.mkdir(exist_ok=True)
    entry: dict[str, str] = {"sasl_password_ref": "dev-ref"}
    if username is not None:
        entry["sasl_username"] = username
    (onex / "config.yaml").write_text(json.dumps({"lanes": {"dev": entry}}))
    secrets = onex / "credentials.json"
    secrets.write_text(json.dumps({"dev-ref": "not-a-real-secret"}))
    secrets.chmod(mode)


def _selection_block() -> str:
    blocks = re.findall(r"```bash\n(.*?)```", _SKILL.read_text(), flags=re.DOTALL)
    chosen = [block for block in blocks if block.startswith(_MARKER)]
    assert len(chosen) == 1, (
        f"SKILL.md must carry exactly one bash block opening with {_MARKER!r}; "
        f"found {len(chosen)}"
    )
    return str(chosen[0])


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_skill(
    tmp_path: Path,
    *,
    onex_mode: str | None,
    lane_store: bool = True,
    args: tuple[str, ...] = ("--intent", "tick", "--receipt", "/dev/null"),
) -> dict[str, Any]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "gh", _FAKE_GH)
    if onex_mode is not None:
        _executable(bin_dir / "onex", _FAKE_ONEX)
    plugin_root = tmp_path / "plugin"
    (plugin_root / "scripts").mkdir(parents=True)
    (plugin_root / "scripts" / "session_preflight.py").write_text(_FAKE_RUNNER)
    # The real hook lane code and contract the block reads the declared identity through.
    (plugin_root / "hooks").symlink_to(_HOOKS)
    if lane_store:
        _write_lane_store(tmp_path)

    # Only python3 is borrowed from the test interpreter, through its own
    # directory: the interpreter's bin may hold a real ``onex``, which would
    # answer in place of the recorder.
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    (python_dir / "python3").symlink_to(Path(sys.executable).resolve())
    gh_log = tmp_path / "gh.calls"
    runner_log = tmp_path / "runner.json"
    onex_log = tmp_path / "onex.args"
    onex_input = tmp_path / "onex.input.json"
    env = {
        "PATH": os.pathsep.join([str(bin_dir), str(python_dir), "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        # The borrowed interpreter is the bare base one, so PyYAML (which the plugin's
        # python3 has, and the real runner imports) is handed over by path.
        "PYTHONPATH": str(Path(yaml.__file__).resolve().parent.parent),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "FAKE_RUNNER_LOG": str(runner_log),
        "STUB_ONEX_LOG": str(onex_log),
        "STUB_ONEX_INPUT_COPY": str(onex_input),
        "STUB_ONEX_MODE": onex_mode or "",
        "STUB_GH_LOG": str(gh_log),
    }
    completed = subprocess.run(
        ["bash", "-c", _selection_block(), "preflight", *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert runner_log.is_file(), (
        "the selection block must always run the runner; it never skips the "
        f"preflight\n{completed.stdout}{completed.stderr}"
    )
    argv = json.loads(runner_log.read_text())
    return {
        "argv": argv,
        "gh_calls": gh_log.read_text() if gh_log.is_file() else None,
        "onex_args": onex_log.read_text() if onex_log.is_file() else None,
        "onex_input": json.loads(onex_input.read_text())
        if onex_input.is_file()
        else None,
    }


def _profile(argv: list[str]) -> str:
    assert argv.count("--profile") == 1, argv
    return argv[argv.index("--profile") + 1]


def test_the_selection_calls_the_team_identity_node() -> None:
    block = _selection_block()
    assert f"onex node {_NODE}" in block, (
        "the role comes from G0's resolver node, not a heuristic of the skill's own"
    )
    assert "--profile" in block


def test_a_positive_operator_match_runs_the_operator_profile(tmp_path: Path) -> None:
    seen = _run_skill(tmp_path, onex_mode="operator")
    assert _profile(seen["argv"]) == "operator"
    assert seen["onex_args"] is not None and _NODE in str(seen["onex_args"])
    assert seen["onex_input"] == {
        "claims": [{"source": "broker_binding", "value": _PRINCIPAL}]
    }


def test_the_caller_arguments_reach_the_runner(tmp_path: Path) -> None:
    seen = _run_skill(
        tmp_path, onex_mode="operator", args=("--intent", "quiet", "--all")
    )
    argv = seen["argv"]
    assert isinstance(argv, list)
    assert argv[argv.index("--profile") + 2 :] == ["--intent", "quiet", "--all"]


def test_a_member_match_runs_the_team_profile(tmp_path: Path) -> None:
    seen = _run_skill(tmp_path, onex_mode="member")
    assert _profile(seen["argv"]) == "team"


@pytest.mark.parametrize(
    "onex_mode", ["unknown", "failed_status", "nonzero", "garbage", "list", "crash"]
)
def test_an_unresolved_or_failed_identity_read_runs_team(
    tmp_path: Path, onex_mode: str
) -> None:
    """Fail closed: nothing short of a clean operator answer selects operator."""
    seen = _run_skill(tmp_path, onex_mode=onex_mode)
    assert _profile(seen["argv"]) == "team"


def test_a_missing_resolver_runs_team(tmp_path: Path) -> None:
    seen = _run_skill(tmp_path, onex_mode=None)
    assert _profile(seen["argv"]) == "team"


def test_gh_refuses_every_call_and_the_operator_is_still_selected(
    tmp_path: Path,
) -> None:
    """OMN-21660: a PATH whose gh refuses every call changes nothing, because none is made."""
    code = "\n".join(
        line
        for line in _selection_block().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert not re.search(r"(^|[\s;|&(])gh\s", code), (
        "the lane gh shim refuses `gh api user`; the identity is the declared lane identity"
    )
    seen = _run_skill(tmp_path, onex_mode="operator")
    assert seen["gh_calls"] is None
    assert _profile(seen["argv"]) == "operator"


def test_no_lane_identity_runs_team(tmp_path: Path) -> None:
    seen = _run_skill(tmp_path, onex_mode="operator", lane_store=False)
    assert _profile(seen["argv"]) == "team"
    assert seen["onex_args"] is None, (
        "with no declared lane identity there is nothing to resolve"
    )
    assert seen["gh_calls"] is None


@pytest.mark.parametrize("fault", ["no_username", "loose_mode"])
def test_a_broken_lane_identity_runs_team(tmp_path: Path, fault: str) -> None:
    """A half-written or world-readable lane store is unreadable, so the role is team."""
    if fault == "no_username":
        _write_lane_store(tmp_path, username=None)
    else:
        _write_lane_store(tmp_path, mode=0o644)
    seen = _run_skill(tmp_path, onex_mode="operator", lane_store=False)
    assert _profile(seen["argv"]) == "team"
    assert seen["onex_args"] is None
    assert seen["gh_calls"] is None


def test_the_lane_identity_never_prints_the_secret(tmp_path: Path) -> None:
    seen = _run_skill(tmp_path, onex_mode="operator")
    assert "not-a-real-secret" not in json.dumps(seen["onex_input"])
    assert "not-a-real-secret" not in str(seen["onex_args"])


def test_every_documented_runner_call_passes_a_profile() -> None:
    """The skill's runner call no longer runs with no profile."""
    calls = [
        line
        for line in _SKILL.read_text().splitlines()
        if "session_preflight.py" in line
        and line.lstrip().startswith("python3")
        and "--install-overlay" not in line
    ]
    assert calls, "SKILL.md must show the runner call"
    for line in calls:
        assert "--profile" in line, line
