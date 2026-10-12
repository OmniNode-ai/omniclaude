# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20914: the gh shim refuses a covered gh write from a lane and names its onex scm verb.

RULING 2026-10-10T18:32:46Z: GitHub access moves onto the source-control nodes and gh CLI
access is turned off for sub-agents, so lanes drive everything through the node. The shim
refuses a gh write verb from a lane only when `onex scm` serves its replacement, read from
one table: the `operations` block of node_github_repo_write_effect's contract.yaml in the
omnimarket the `onex` command runs (`${ONEX_DISPATCH_VENV:-$OMNI_HOME/.onex-dispatch-venv}`).
`onex scm` reads the same block (contract_operations, and omnimarket's test that binds every
operation to exactly one verb).

Each test builds that install under a temporary OMNI_HOME, with the pinned omnimarket's own
contract.yaml copied in, and puts a scripted fake ``gh`` behind the shim. A refused call must
never reach the fake. No test uses the network or an operator credential.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-ok}"
exit "${FAKE_GH_RC:-0}"
"""

# The write verbs of omnimarket's onex scm table (handlers/scm/handler_scm_dispatch.py, as
# merged by omnimarket#3765), in that file's own spelling. The pinned omnimarket predates
# the command, so the fixture install carries this copy beside the real contract.
SCM_DISPATCH_WRITES = """\
SCM_VERBS: Final[tuple[ModelScmVerb, ...]] = (
    ModelScmVerb(
        verb="pr-create", node=_W, operation="pr_create", replaces="gh pr create"
    ),
    ModelScmVerb(verb="pr-edit", node=_W, operation="pr_edit", replaces="gh pr edit"),
    ModelScmVerb(
        verb="pr-ready", node=_W, operation="pr_ready", replaces="gh pr ready"
    ),
    ModelScmVerb(
        verb="pr-close", node=_W, operation="pr_close", replaces="gh pr close"
    ),
    ModelScmVerb(
        verb="pr-comment", node=_W, operation="pr_comment", replaces="gh pr comment"
    ),
    ModelScmVerb(
        verb="workflow-run",
        node=_W,
        operation="workflow_dispatch",
        replaces="gh workflow run",
    ),
)
"""

ENFORCED = "OmniNode-ai/omnimarket"  # the one repository the contract puts in enforce
LANE = "write-guard-lane"

# gh verb -> (argv, onex scm verb, node operation)
COVERED: dict[str, tuple[list[str], str, str]] = {
    "pr create": (
        ["pr", "create", "--repo", ENFORCED, "--title", "t", "--body", "b"],
        "pr-create",
        "pr_create",
    ),
    "pr edit": (
        ["pr", "edit", "9", "--repo", ENFORCED, "--add-label", "x"],
        "pr-edit",
        "pr_edit",
    ),
    "pr ready": (["pr", "ready", "9", "--repo", ENFORCED], "pr-ready", "pr_ready"),
    "pr close": (["pr", "close", "9", "--repo", ENFORCED], "pr-close", "pr_close"),
    "pr comment": (
        ["pr", "comment", "9", "--repo", ENFORCED, "--body", "hi"],
        "pr-comment",
        "pr_comment",
    ),
    "workflow run": (
        ["workflow", "run", "ci.yml", "--repo", ENFORCED],
        "workflow-run",
        "workflow_dispatch",
    ),
}

# Writes onex scm has no operation for (it refuses merge, arm, rerun and update-branch,
# naming the landing controller): by AC3 they stay allowed from a lane.
UNCOVERED_WRITES = [
    ["pr", "merge", "9", "--repo", ENFORCED, "--squash", "--auto"],
    ["run", "rerun", "123", "--repo", ENFORCED],
    ["run", "cancel", "123", "--repo", ENFORCED],
    ["pr", "review", "9", "--repo", ENFORCED, "--approve"],
    ["pr", "reopen", "9", "--repo", ENFORCED],
    ["api", "-X", "POST", f"repos/{ENFORCED}/issues/9/comments", "-f", "body=hi"],
    ["api", "-X", "PATCH", f"repos/{ENFORCED}/pulls/9", "-f", "title=t"],
    ["api", "-X", "POST", f"repos/{ENFORCED}/actions/runs/123/rerun"],
    ["api", "graphql", "-f", "query=mutation{x}"],
    ["issue", "create", "--repo", ENFORCED, "--title", "t"],
]

LANE_MARKERS = [
    "ONEX_LANE",
    "ONEX_LANE_ID",
    "ONEX_AGENT_NAME",
    "CLAUDE_AGENT_NAME",
    "CLAUDE_SUBAGENT_NAME",
    "CODEX_THREAD_ID",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_MANAGED_BY_NPM",
]


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _pinned_contract() -> str:
    spec = importlib.util.find_spec("omnimarket")
    assert spec is not None and spec.submodule_search_locations
    pkg = Path(next(iter(spec.submodule_search_locations)))
    return (
        pkg / "nodes" / "node_github_repo_write_effect" / "contract.yaml"
    ).read_text()


def _install(
    workspace: Path, contract: str | None = None, dispatch: str | None = None
) -> Path:
    """An omnimarket install where the onex wrapper looks for it; returns the package dir."""
    pkg = (
        workspace
        / ".onex-dispatch-venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "omnimarket"
    )
    node = pkg / "nodes" / "node_github_repo_write_effect"
    node.mkdir(parents=True, exist_ok=True)
    (node / "contract.yaml").write_text(
        _pinned_contract() if contract is None else contract
    )
    scm = pkg / "handlers" / "scm"
    scm.mkdir(parents=True, exist_ok=True)
    (scm / "handler_scm_dispatch.py").write_text(
        SCM_DISPATCH_WRITES if dispatch is None else dispatch
    )
    return pkg


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    fake_dir = tmp_path / "realbin"
    fake_dir.mkdir()
    _write_exec(fake_dir / "gh", FAKE_GH)
    workspace = tmp_path / "workspace"
    _install(workspace)
    return {
        "PATH": f"{SHIM.parent}:{fake_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "FAKE_GH_LOG": str(tmp_path / "calls.jsonl"),
        "ONEX_GH_CALLS_LOG": str(tmp_path / "gh-calls.log"),
        "OMNI_HOME": str(workspace),
        "ONEX_LANE": LANE,
        "GIT_CONFIG_NOSYSTEM": "1",
        "ONEX_GH_READ_ROUTING": "0",
    }


def _operator(env: dict[str, str]) -> dict[str, str]:
    """The same environment with no lane marker: the operator's foreground shell."""
    return {k: v for k, v in env.items() if k != "ONEX_LANE"}


def _run(
    env: dict[str, str], *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _calls(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["FAKE_GH_LOG"])
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _call_log_rows(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["ONEX_GH_CALLS_LOG"])
    if not log.exists():
        return []
    return [line.split("\t") for line in log.read_text().splitlines()]


def _assert_refused(
    env: dict[str, str],
    result: subprocess.CompletedProcess[str],
    gh_verb: str,
    scm_verb: str,
) -> None:
    assert result.returncode == 1, result.stderr
    assert _calls(env) == [], "a refused write must never reach the real gh"
    first = result.stderr.splitlines()[0]
    assert first.startswith(f"REFUSED (OMN-20914): gh {gh_verb} from a lane ("), first
    assert "RULING 2026-10-10T18:32:46Z" in first
    assert f"onex scm {scm_verb}" in result.stderr
    rows = _call_log_rows(env)
    assert rows, "a refusal is logged"
    assert rows[-1][3:] == [gh_verb, "WRITE", f"onex scm {scm_verb}", "1", "refused"]


def _assert_passed(
    env: dict[str, str], result: subprocess.CompletedProcess[str], argv: list[str]
) -> None:
    assert result.returncode == 0, result.stderr
    assert "OMN-20914" not in result.stderr
    assert _calls(env) == [argv]


# --- AC1: a covered verb from a lane is refused, naming its replacement ---------------


@pytest.mark.unit
@pytest.mark.parametrize("gh_verb", list(COVERED), ids=str)
def test_covered_verb_from_a_lane_is_refused_naming_the_onex_scm_verb(
    env: dict[str, str], gh_verb: str
) -> None:
    argv, scm_verb, operation = COVERED[gh_verb]

    result = _run(env, *argv)

    _assert_refused(env, result, gh_verb, scm_verb)
    assert f"node_github_repo_write_effect operation {operation}" in result.stderr
    assert rows_lane(env) == [LANE, "env"]


def rows_lane(env: dict[str, str]) -> list[str]:
    return _call_log_rows(env)[-1][1:3]


@pytest.mark.unit
@pytest.mark.parametrize("marker", LANE_MARKERS)
def test_every_lane_marker_makes_a_lane(env: dict[str, str], marker: str) -> None:
    run_env = _operator(env)
    run_env[marker] = "some-lane"

    result = _run(run_env, *COVERED["pr create"][0])

    _assert_refused(run_env, result, "pr create", "pr-create")
    assert f"environment {marker}" in result.stderr.splitlines()[0]


@pytest.mark.unit
@pytest.mark.parametrize("entrypoint", ["sdk-cli", "sdk-py", "sdk-ts"])
def test_a_headless_claude_session_is_a_lane(
    env: dict[str, str], entrypoint: str
) -> None:
    run_env = _operator(env)
    run_env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint

    result = _run(run_env, *COVERED["pr comment"][0])

    _assert_refused(run_env, result, "pr comment", "pr-comment")
    assert f"headless entrypoint {entrypoint}" in result.stderr.splitlines()[0]


@pytest.mark.unit
def test_repository_resolves_from_a_pr_url_and_from_the_origin_remote(
    env: dict[str, str], tmp_path: Path
) -> None:
    url = _run(
        env, "pr", "edit", f"https://github.com/{ENFORCED}/pull/9", "--title", "x"
    )
    _assert_refused(env, url, "pr edit", "pr-edit")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "init", "-q", str(clone)],
        env=scrub_git_location_env(os.environ),
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(clone),
            "remote",
            "add",
            "origin",
            f"git@github.com:{ENFORCED}.git",
        ],
        env=scrub_git_location_env(os.environ),
        check=True,
    )
    origin = _run(env, "pr", "create", "--title", "t", "--body", "b", cwd=clone)
    _assert_refused(env, origin, "pr create", "pr-create")


# --- AC2: allowlisted identities and the operator's foreground shell pass -------------


@pytest.mark.unit
@pytest.mark.parametrize("gh_verb", list(COVERED), ids=str)
def test_operator_foreground_shell_passes(env: dict[str, str], gh_verb: str) -> None:
    run_env = _operator(env)
    argv = COVERED[gh_verb][0]

    _assert_passed(run_env, _run(run_env, *argv), argv)


@pytest.mark.unit
def test_operator_interactive_claude_session_passes(env: dict[str, str]) -> None:
    run_env = _operator(env)
    run_env.update(
        {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "CLAUDE_CODE_SESSION_ID": "sess-1",
        }
    )
    argv = COVERED["pr create"][0]

    _assert_passed(run_env, _run(run_env, *argv), argv)


@pytest.mark.unit
@pytest.mark.parametrize("gh_verb", list(COVERED), ids=str)
def test_pr_watcher_marker_passes_from_a_lane_environment(
    env: dict[str, str], gh_verb: str
) -> None:
    run_env = dict(env, ONEX_PR_WATCHER="1")
    argv = COVERED[gh_verb][0]

    _assert_passed(run_env, _run(run_env, *argv), argv)


def _run_from_parent(
    env: dict[str, str], parent: list[str], argv: list[str]
) -> subprocess.CompletedProcess[str]:
    """Run `gh <argv>` as the direct child of the process `parent` starts."""
    return subprocess.run(
        parent,
        env=dict(env, GH_ARGV=json.dumps(["gh", *argv])),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


CHILD = (
    "import json, os, subprocess, sys\n"
    "sys.exit(subprocess.run(json.loads(os.environ['GH_ARGV'])).returncode)\n"
)


def _identity_parent(tmp_path: Path, env: dict[str, str], identity: str) -> list[str]:
    """The argv of a process that is the named allowlisted identity, running CHILD."""
    if identity == "landing-controller":
        root = tmp_path / "ctl"
        script = root / "skills" / "merge-drain" / "scripts" / "landing_controller.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(CHILD)
        env["ONEX_LANDING_CONTROLLER_ROOT"] = str(root)
        return [sys.executable, str(script)]
    if identity in ("node-effect-runner", "onex-runtime"):
        name = "onex" if identity == "node-effect-runner" else "onex-runtime"
        entry = tmp_path / "venv-bin" / name
        _write_exec(entry, f"#!{sys.executable}\n{CHILD}")
        return [str(entry), "run-node", "node_x"] if name == "onex" else [str(entry)]
    if identity == "release-cut-tick":
        module = "omnimarket_release_cut_tick"
        pkg = tmp_path / "pylib" / "lanepkg"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("")
        (pkg / f"{module}.py").write_text(CHILD)
        env["PYTHONPATH"] = str(tmp_path / "pylib")
        return [sys.executable, "-m", f"lanepkg.{module}"]
    raise AssertionError(identity)


IDENTITIES = [
    "landing-controller",
    "node-effect-runner",
    "onex-runtime",
    "release-cut-tick",
]


@pytest.mark.unit
@pytest.mark.parametrize("identity", IDENTITIES)
@pytest.mark.parametrize("gh_verb", ["pr create", "pr edit", "workflow run"])
def test_allowlisted_identity_passes_from_a_lane_environment(
    env: dict[str, str], tmp_path: Path, identity: str, gh_verb: str
) -> None:
    run_env = dict(env)
    parent = _identity_parent(tmp_path, run_env, identity)
    argv = COVERED[gh_verb][0]

    result = _run_from_parent(run_env, parent, argv)

    _assert_passed(run_env, result, argv)


@pytest.mark.unit
def test_an_unlisted_parent_script_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    """Positive control for the allowlist: the same child under another name is a lane."""
    script = tmp_path / "skills" / "merge-drain" / "scripts" / "my_lane_helper.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(CHILD)

    result = _run_from_parent(
        env, [sys.executable, str(script)], COVERED["pr create"][0]
    )

    _assert_refused(env, result, "pr create", "pr-create")


@pytest.mark.unit
def test_onex_without_run_node_is_not_the_effect_runner(
    env: dict[str, str], tmp_path: Path
) -> None:
    entry = tmp_path / "venv-bin" / "onex"
    _write_exec(entry, f"#!{sys.executable}\n{CHILD}")

    result = _run_from_parent(env, [str(entry), "delegate", "x"], COVERED["pr edit"][0])

    _assert_refused(env, result, "pr edit", "pr-edit")


# --- AC3: refused only when the replacement exists, read from the one table ------------


@pytest.mark.unit
def test_pinned_contract_operations_are_the_covered_verbs() -> None:
    """The table the shim reads, at the omnimarket pin: a new operation fails here first."""
    operations = yaml.safe_load(_pinned_contract())["operations"]
    assert sorted(op["name"] for op in operations) == sorted(
        op for _, _, op in COVERED.values()
    )
    for op in operations:
        gh_verb = next(v for v, (_, _, o) in COVERED.items() if o == op["name"])
        assert f"replaces gh {gh_verb}." in op["description"]


def _drop_operation(contract: str, name: str) -> str:
    """The contract text with one operations entry removed, everything else verbatim."""
    out: list[str] = []
    skipping = False
    for line in contract.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("- name: "):
            skipping = stripped == f"- name: {name}"
        elif not line.startswith(" "):
            skipping = False
        if not skipping:
            out.append(line)
    dropped = "".join(out)
    assert f"name: {name}\n" not in dropped
    return dropped


@pytest.mark.unit
@pytest.mark.parametrize("gh_verb", list(COVERED), ids=str)
def test_a_verb_dropped_from_the_table_is_allowed(
    env: dict[str, str], gh_verb: str
) -> None:
    argv, _, operation = COVERED[gh_verb]
    _install(Path(env["OMNI_HOME"]), _drop_operation(_pinned_contract(), operation))

    _assert_passed(env, _run(env, *argv), argv)


@pytest.mark.unit
def test_dropping_one_verb_leaves_the_others_refused(env: dict[str, str]) -> None:
    _install(Path(env["OMNI_HOME"]), _drop_operation(_pinned_contract(), "pr_edit"))

    edit = COVERED["pr edit"][0]
    _assert_passed(env, _run(env, *edit), edit)
    Path(env["FAKE_GH_LOG"]).unlink()
    _assert_refused(env, _run(env, *COVERED["pr create"][0]), "pr create", "pr-create")


@pytest.mark.unit
def test_a_verb_the_onex_scm_command_does_not_serve_is_allowed(
    env: dict[str, str],
) -> None:
    served_without_edit = SCM_DISPATCH_WRITES.replace(
        'verb="pr-edit"', 'verb="pr-amend"'
    )
    _install(Path(env["OMNI_HOME"]), dispatch=served_without_edit)

    edit = COVERED["pr edit"][0]
    _assert_passed(env, _run(env, *edit), edit)


@pytest.mark.unit
def test_an_install_without_the_onex_scm_command_refuses_nothing(
    env: dict[str, str],
) -> None:
    """An omnimarket from before omnimarket#3765 has the contract and no `onex scm`."""
    scm = (
        Path(env["OMNI_HOME"])
        / ".onex-dispatch-venv/lib/python3.12/site-packages/omnimarket/handlers/scm"
    )
    (scm / "handler_scm_dispatch.py").unlink()

    for gh_verb, (argv, _, _) in COVERED.items():
        Path(env["FAKE_GH_LOG"]).unlink(missing_ok=True)
        _assert_passed(env, _run(env, *argv), argv)


@pytest.mark.unit
def test_no_dispatch_venv_refuses_nothing(env: dict[str, str]) -> None:
    run_env = {k: v for k, v in env.items() if k != "OMNI_HOME"}
    argv = COVERED["pr create"][0]

    _assert_passed(run_env, _run(run_env, *argv), argv)


@pytest.mark.unit
def test_onex_dispatch_venv_overrides_workspace(
    env: dict[str, str], tmp_path: Path
) -> None:
    """The shim reads the install the onex wrapper runs: ONEX_DISPATCH_VENV first."""
    other = tmp_path / "other_home"
    _install(other)
    run_env = dict(env, OMNI_HOME=str(tmp_path / "empty"))
    argv = COVERED["pr create"][0]
    _assert_passed(run_env, _run(run_env, *argv), argv)
    Path(env["FAKE_GH_LOG"]).unlink()

    run_env["ONEX_DISPATCH_VENV"] = str(other / ".onex-dispatch-venv")
    _assert_refused(run_env, _run(run_env, *argv), "pr create", "pr-create")


@pytest.mark.unit
@pytest.mark.parametrize("gh_verb", list(COVERED), ids=str)
def test_a_repository_in_dry_run_mode_is_allowed(
    env: dict[str, str], gh_verb: str
) -> None:
    """write_config puts only omnimarket in enforce: elsewhere onex scm sends nothing."""
    argv = [
        a if a != ENFORCED else "OmniNode-ai/omniclaude" for a in COVERED[gh_verb][0]
    ]

    _assert_passed(env, _run(env, *argv), argv)


@pytest.mark.unit
def test_repository_match_ignores_case(env: dict[str, str]) -> None:
    argv = ["pr", "ready", "9", "--repo", "omninode-ai/OMNIMARKET"]

    _assert_refused(env, _run(env, *argv), "pr ready", "pr-ready")


@pytest.mark.unit
@pytest.mark.parametrize("argv", UNCOVERED_WRITES, ids=lambda a: " ".join(a)[:60])
def test_a_write_with_no_onex_scm_operation_stays_allowed(
    env: dict[str, str], argv: list[str]
) -> None:
    _assert_passed(env, _run(env, *argv), argv)


# --- reads stay as they are ------------------------------------------------------------


@pytest.mark.unit
def test_reads_are_untouched(env: dict[str, str]) -> None:
    listed = ["pr", "list", "--repo", ENFORCED]
    listed_result = _run(env, *listed)
    # The lane read guard's fallback (OMN-20911) serves it; the write guard never sees it.
    assert listed_result.returncode == 0, listed_result.stderr
    assert _calls(env) == [listed]
    assert _call_log_rows(env)[-1][7] == "fallback"

    state = _run(env, "pr", "view", "9", "--repo", ENFORCED)
    assert state.returncode == 1
    assert state.stderr.startswith("REFUSED (OMN-19856): ")
    assert _calls(env) == [listed]
