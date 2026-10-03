# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19856: the gh shim refuses PR-state reads from every caller but the landing controller.

RULING 2026-09-27T18:05:21Z: every PR-state read comes from the PR watcher's state file; GitHub
is for mutations and the exact-head check right before one. The shim carries that as a refusal,
not a warning: `gh pr view|checks`, `gh run view` and the `gh api` GET/HEAD shapes that read PR,
check or run state exit 1 with the local alternatives, unless the caller is the PR watcher
(`ONEX_PR_WATCHER=1`), the direct parent is one of the landing-controller scripts, or the call
declares itself an exact-head check with `ONEX_GH_EXACT_HEAD`.

Each test puts a scripted fake ``gh`` behind the user shim. No test uses the network or an
operator credential.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-ok}"
exit "${FAKE_GH_RC:-0}"
"""

REFUSAL_RULING = "RULING 2026-09-27T18:05:21Z"


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    fake_dir = tmp_path / "realbin"
    fake_dir.mkdir()
    _write_exec(fake_dir / "gh", FAKE_GH)
    return {
        "PATH": f"{SHIM.parent}:{fake_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "FAKE_GH_LOG": str(tmp_path / "calls.jsonl"),
        "ONEX_GH_CALLS_LOG": str(tmp_path / "gh-calls.log"),
        "ONEX_LANE": "read-guard-lane",
        "GIT_CONFIG_NOSYSTEM": "1",
        "ONEX_GH_READ_ROUTING": "0",
    }


def _run(
    env: dict[str, str], *args: str, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env)
    run_env.update(extra or {})
    return subprocess.run(
        ["gh", *args],
        env=run_env,
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
    env: dict[str, str], result: subprocess.CompletedProcess[str]
) -> None:
    assert result.returncode == 1, result.stderr
    assert _calls(env) == [], "a refused read must never reach the real gh"
    first = result.stderr.splitlines()[0]
    assert first.startswith("REFUSED (OMN-19856): ")
    assert (
        "is a PR-state read; GitHub is for mutations and the declared exact-head "
        f"check only ({REFUSAL_RULING})." in first
    )
    rows = _call_log_rows(env)
    assert rows, "a refusal is logged"
    assert rows[-1][7] == "refused"
    assert rows[-1][6] == "1"


# --- the guarded shapes ---------------------------------------------------------

GUARDED = [
    ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"],
    ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket", "--json", "body,files"],
    ["pr", "view", "9002", "--json", "url,headRefOid"],
    ["pr", "checks", "9002", "--repo", "OmniNode-ai/omnimarket"],
    ["pr", "checks", "9002", "--watch"],
    ["run", "view", "123456", "--repo", "OmniNode-ai/omnimarket", "--log-failed"],
    ["api", "repos/OmniNode-ai/omnimarket/pulls"],
    ["api", "repos/OmniNode-ai/omnimarket/pulls/9002"],
    ["api", "repos/OmniNode-ai/omnimarket/pulls/9002/files", "--paginate"],
    ["api", "/repos/OmniNode-ai/omnimarket/pulls/9002/reviews"],
    ["api", "https://api.github.com/repos/OmniNode-ai/omnimarket/pulls?state=open"],
    ["api", "-X", "GET", "repos/OmniNode-ai/omnimarket/pulls/9002"],
    ["api", "-X", "HEAD", "repos/OmniNode-ai/omnimarket/pulls/9002"],
    ["api", "repos/OmniNode-ai/omnimarket/commits/abc123/check-runs"],
    ["api", "repos/OmniNode-ai/omnimarket/check-runs/77"],
    ["api", "repos/OmniNode-ai/omnimarket/commits/abc123/check-suites"],
    ["api", "repos/OmniNode-ai/omnimarket/commits/abc123/status"],
    ["api", "repos/OmniNode-ai/omnimarket/commits/abc123/statuses"],
    ["api", "repos/OmniNode-ai/omnimarket/statuses/abc123"],
    ["api", "repos/OmniNode-ai/omnimarket/actions/runs/123456"],
    ["api", "repos/OmniNode-ai/omnimarket/actions/runs?head_sha=abc"],
    ["api", "repos/OmniNode-ai/omnimarket/actions/jobs/555"],
]


@pytest.mark.unit
@pytest.mark.parametrize("argv", GUARDED, ids=lambda a: " ".join(a)[:70])
def test_guarded_shape_is_refused_with_alternatives(
    env: dict[str, str], argv: list[str]
) -> None:
    result = _run(env, *argv)

    _assert_refused(env, result)
    assert "pr_state_local.py --pr " in result.stderr
    assert "--json" in result.stderr
    assert "--status" in result.stderr
    assert "drain_map.py --only-pr " in result.stderr
    assert "git -C $OMNI_HOME/" in result.stderr
    assert "origin/dev..." in result.stderr
    assert (
        "ONEX_GH_EXACT_HEAD=<owner>/<repo>#<n> gh pr view <n> --repo <owner>/<repo>"
        in result.stderr
    )


@pytest.mark.unit
def test_refusal_fills_repo_and_number_when_argv_resolves_them(
    env: dict[str, str],
) -> None:
    result = _run(env, "pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket")

    _assert_refused(env, result)
    assert "pr_state_local.py --pr OmniNode-ai/omnimarket#9002" in result.stderr
    assert "drain_map.py --only-pr omnimarket#9002" in result.stderr
    assert "git -C $OMNI_HOME/omnimarket " in result.stderr
    assert (
        "ONEX_GH_EXACT_HEAD=OmniNode-ai/omnimarket#9002 gh pr view 9002 "
        "--repo OmniNode-ai/omnimarket --json headRefOid" in result.stderr
    )


@pytest.mark.unit
def test_refusal_resolves_an_api_endpoint_and_a_pr_url(env: dict[str, str]) -> None:
    api = _run(env, "api", "repos/OmniNode-ai/omnibase_infra/pulls/4222/files")
    assert api.returncode == 1
    assert "pr_state_local.py --pr OmniNode-ai/omnibase_infra#4222" in api.stderr

    url = _run(env, "pr", "checks", "https://github.com/OmniNode-ai/omniclaude/pull/77")
    assert url.returncode == 1
    assert "pr_state_local.py --pr OmniNode-ai/omniclaude#77" in url.stderr


@pytest.mark.unit
def test_refusal_keeps_placeholders_when_argv_resolves_nothing(
    env: dict[str, str], tmp_path: Path
) -> None:
    # No --repo, and a working directory that is not a clone.
    result = subprocess.run(
        ["gh", "run", "view", "123"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 1
    assert "pr_state_local.py --pr OmniNode-ai/<repo>#<n>" in result.stderr


@pytest.mark.unit
def test_refusal_log_row_has_class_and_no_argv(
    env: dict[str, str],
) -> None:
    token = "TOKEN-SENTINEL-8844"
    result = _run(
        env,
        "api",
        f"repos/o/r/pulls/9?access_token={token}",
        extra={"GH_TOKEN": token},
    )

    assert result.returncode == 1
    rows = _call_log_rows(env)
    assert len(rows) == 1
    assert rows[0][1:] == [
        "read-guard-lane",
        "env",
        "api",
        "GET",
        "repos/o/r/pulls/9",
        "1",
        "refused",
    ]
    assert token not in Path(env["ONEX_GH_CALLS_LOG"]).read_text()


# --- shapes that are never guarded ------------------------------------------------

HARNESS_LINK = [
    ["pr", "view", "--json", "url"],
    ["pr", "view", "main", "--json", "url"],
    ["pr", "view", "--json", "number,url,state"],
    ["pr", "view", "feature", "--json", "number,url,state"],
]


@pytest.mark.unit
@pytest.mark.parametrize("argv", HARNESS_LINK, ids=" ".join)
def test_harness_link_lookup_is_still_served(
    env: dict[str, str], argv: list[str]
) -> None:
    result = _run(env, *argv)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert _calls(env) == [argv]


WRITES = [
    ["api", "-X", "POST", "repos/o/r/pulls/9/comments", "-f", "body=hi"],
    ["api", "-X", "PUT", "repos/o/r/pulls/9/merge"],  # queue guard handles this one
    ["api", "-X", "PATCH", "repos/o/r/pulls/9", "-f", "title=t"],
    ["api", "-X", "POST", "repos/o/r/actions/runs/123/rerun"],
    ["api", "-X", "DELETE", "repos/o/r/actions/runs/123"],
    ["api", "repos/o/r/pulls/9/comments", "-f", "body=hi"],  # -f makes it a POST
    ["pr", "merge", "9", "--repo", "o/r", "--squash", "--match-head-commit", "abc"],
    ["pr", "ready", "9", "--repo", "o/r"],
    ["pr", "create", "--title", "t", "--body", "b"],
    ["pr", "edit", "9", "--add-label", "x"],
    ["pr", "comment", "9", "--body", "hi"],
    ["pr", "close", "9"],
    ["run", "rerun", "123", "--repo", "o/r"],
    ["run", "cancel", "123"],
    ["workflow", "run", "ci.yml", "--repo", "o/r"],
]


@pytest.mark.unit
@pytest.mark.parametrize("argv", WRITES, ids=lambda a: " ".join(a)[:70])
def test_writes_pass_through_untouched(env: dict[str, str], argv: list[str]) -> None:
    result = _run(env, *argv, extra={"FAKE_RULES": "[]", "FAKE_BASE": "base"})

    if argv[:3] == ["api", "-X", "PUT"]:
        # The OMN-17427 merge-queue guard owns this shape and may refuse it; this guard
        # must not be the one that does.
        assert "OMN-19856" not in result.stderr
        return
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["api", "graphql", "-f", "query={viewer{login}}"],
        ["api", "repos/o/r/contents/README.md"],
        ["api", "repos/o/r/issues/9/comments"],
        ["api", "repos/o/r/commits/abc"],
        ["api", "repos/o/r/actions/runners"],
        ["api", "user"],
        ["pr", "list", "--repo", "o/r"],
        ["pr", "diff", "9"],
        ["run", "list", "--repo", "o/r"],
        ["issue", "view", "9"],
        ["repo", "view", "o/r"],
    ],
    ids=" ".join,
)
def test_other_reads_are_unaffected(env: dict[str, str], argv: list[str]) -> None:
    result = _run(env, *argv)

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


# --- allowed callers ----------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("argv", GUARDED[:6], ids=lambda a: " ".join(a)[:70])
def test_watcher_marker_allows_guarded_reads(
    env: dict[str, str], argv: list[str]
) -> None:
    result = _run(env, *argv, extra={"ONEX_PR_WATCHER": "1"})

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_watcher_marker_must_be_exactly_one(env: dict[str, str]) -> None:
    result = _run(env, "pr", "checks", "9", extra={"ONEX_PR_WATCHER": "yes"})

    _assert_refused(env, result)


def _controller_tree(root: Path, name: str = "landing_controller.py") -> Path:
    script = root / "skills" / "merge-drain" / "scripts" / name
    script.parent.mkdir(parents=True, exist_ok=True)
    return script


def _run_from_parent_script(
    env: dict[str, str],
    script: Path,
    argv: list[str],
    *,
    extra: dict[str, str] | None = None,
    via_bash: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run `gh <argv>` from a python script at `script`, optionally through a bash hop."""
    gh_argv = json.dumps(["gh", *argv])
    if via_bash:
        hop = script.parent / "hop.sh"
        _write_exec(hop, '#!/bin/bash\ngh "$@"\nrc=$?\nexit $rc\n')
        body = (
            "import subprocess, sys\n"
            f"argv = {gh_argv}\n"
            f"sys.exit(subprocess.run(['bash', {str(hop)!r}] + argv[1:]).returncode)\n"
        )
    else:
        body = (
            "import subprocess, sys\n"
            f"argv = {gh_argv}\n"
            "sys.exit(subprocess.run(argv).returncode)\n"
        )
    script.write_text(body)
    run_env = dict(env)
    run_env.update(extra or {})
    return subprocess.run(
        [sys.executable, str(script)],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "name", ["landing_controller.py", "landing_lab_prover.py", "landing_worker_run.py"]
)
def test_direct_parent_landing_script_under_the_root_is_allowed(
    env: dict[str, str], tmp_path: Path, name: str
) -> None:
    root = tmp_path / "ctl"
    script = _controller_tree(root, name)
    argv = ["pr", "view", "9002", "--repo", "o/r", "--json", "statusCheckRollup"]

    result = _run_from_parent_script(
        env, script, argv, extra={"ONEX_LANDING_CONTROLLER_ROOT": str(root)}
    )

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_default_root_is_home_omninode_landing_controller(
    env: dict[str, str], tmp_path: Path
) -> None:
    root = Path(env["HOME"]) / ".omninode" / "landing-controller"
    script = _controller_tree(root)
    argv = ["run", "view", "123", "--repo", "o/r"]

    result = _run_from_parent_script(env, script, argv)

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_same_script_name_outside_the_root_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    root = tmp_path / "ctl"
    root.mkdir()
    elsewhere = _controller_tree(tmp_path / "other")
    argv = ["pr", "checks", "9002", "--repo", "o/r"]

    result = _run_from_parent_script(
        env, elsewhere, argv, extra={"ONEX_LANDING_CONTROLLER_ROOT": str(root)}
    )

    _assert_refused(env, result)


@pytest.mark.unit
def test_a_script_with_another_name_under_the_root_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    root = tmp_path / "ctl"
    script = _controller_tree(root, "landing_other.py")

    result = _run_from_parent_script(
        env,
        script,
        ["pr", "checks", "9"],
        extra={"ONEX_LANDING_CONTROLLER_ROOT": str(root)},
    )

    _assert_refused(env, result)


@pytest.mark.unit
def test_grandchild_of_the_controller_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    """controller -> bash -> gh: a worker the controller spawns must stay refused."""
    root = tmp_path / "ctl"
    script = _controller_tree(root)

    result = _run_from_parent_script(
        env,
        script,
        ["pr", "view", "9002", "--repo", "o/r", "--json", "headRefOid"],
        extra={"ONEX_LANDING_CONTROLLER_ROOT": str(root)},
        via_bash=True,
    )

    _assert_refused(env, result)


@pytest.mark.unit
def test_controller_environment_is_not_a_credential(
    env: dict[str, str], tmp_path: Path
) -> None:
    """No env marker identifies the controller: a worker inherits its environment."""
    root = tmp_path / "ctl"
    result = _run(
        env,
        "pr",
        "checks",
        "9",
        extra={
            "ONEX_LANDING_CONTROLLER_ROOT": str(root),
            "ONEX_LANDING_CONTROLLER": "1",
            "ONEX_LANE": "landing-controller",
        },
    )

    _assert_refused(env, result)


@pytest.mark.unit
def test_pr_watcher_module_as_direct_parent_is_allowed(
    env: dict[str, str], tmp_path: Path
) -> None:
    pkg = tmp_path / "pkgs" / "omnibase_internal"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "pr_watcher.py").write_text(
        "import subprocess, sys\n"
        "sys.exit(subprocess.run(['gh', 'pr', 'view', '9', '--repo', 'o/r']).returncode)\n"
    )
    run_env = dict(env)
    run_env["PYTHONPATH"] = str(tmp_path / "pkgs")

    result = subprocess.run(
        [sys.executable, "-m", "omnibase_internal.pr_watcher"],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [["pr", "view", "9", "--repo", "o/r"]]


@pytest.mark.unit
def test_ps_is_only_consulted_for_a_guarded_shape(
    env: dict[str, str], tmp_path: Path
) -> None:
    """Unrelated calls pay nothing: a PATH with no `ps` still serves them."""
    bindir = tmp_path / "noprocs"
    bindir.mkdir()
    for tool in (
        "bash",
        "env",
        "head",
        "grep",
        "date",
        "mkdir",
        "python3",
        "cat",
        "git",
        "tr",
        "cut",
        "sed",
        "basename",
        "dirname",
        "find",
        "rm",
        "mv",
        "mktemp",
        "sha256sum",
    ):
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    e = dict(env)
    e["PATH"] = f"{SHIM.parent}:{tmp_path / 'realbin'}:{bindir}"
    argv = ["api", "-X", "POST", "repos/o/r/issues/1/comments", "-f", "body=x"]

    result = subprocess.run(
        ["bash", str(SHIM), *argv],
        env=e,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


# --- the declared exact-head check ---------------------------------------------------

DECL = "OmniNode-ai/omnimarket#9002"
GOOD = [
    "pr",
    "view",
    "9002",
    "--repo",
    "OmniNode-ai/omnimarket",
    "--json",
    "headRefOid,state,mergeStateStatus",
]


@pytest.mark.unit
def test_matching_declaration_is_allowed(env: dict[str, str]) -> None:
    result = _run(env, *GOOD, extra={"ONEX_GH_EXACT_HEAD": DECL})

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [GOOD]
    rows = _call_log_rows(env)
    assert rows[-1][7] == "allowed"


@pytest.mark.unit
@pytest.mark.parametrize(
    "fields",
    [
        "headRefOid",
        "headRefOid,headRefName,baseRefName,state,isDraft,mergedAt,mergeStateStatus,number",
    ],
)
def test_every_listed_field_is_allowed(env: dict[str, str], fields: str) -> None:
    argv = ["pr", "view", "9002", "-R", "OmniNode-ai/omnimarket", "--json", fields]

    result = _run(env, *argv, extra={"ONEX_GH_EXACT_HEAD": DECL})

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_equals_forms_are_allowed(env: dict[str, str]) -> None:
    argv = [
        "pr",
        "view",
        "9002",
        "--repo=OmniNode-ai/omnimarket",
        "--json=headRefOid,state",
    ]

    result = _run(env, *argv, extra={"ONEX_GH_EXACT_HEAD": DECL})

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "decl", "named"),
    [
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omniclaude"]
            + ["--json", "headRefOid"],
            DECL,
            "repo",
        ),
        (
            ["pr", "view", "9003", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "headRefOid"],
            DECL,
            "number",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "headRefOid,statusCheckRollup"],
            DECL,
            "statusCheckRollup",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "headRefOid,body"],
            DECL,
            "body",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "headRefOid", "--jq", ".headRefOid"],
            DECL,
            "--jq",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "headRefOid", "--template", "{{.headRefOid}}"],
            DECL,
            "--template",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket", "--web"],
            DECL,
            "--web",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "state", "--comments"],
            DECL,
            "--comments",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"],
            DECL,
            "--json",
        ),
        (
            ["pr", "view", "9002", "--json", "headRefOid"],
            DECL,
            "--repo",
        ),
        (
            ["pr", "view", "--repo", "OmniNode-ai/omnimarket", "--json", "state"],
            DECL,
            "number",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "state", "--paginate"],
            DECL,
            "--paginate",
        ),
        (
            ["pr", "view", "9002", "--repo", "OmniNode-ai/omnimarket"]
            + ["--json", "state"],
            "not-a-declaration",
            "ONEX_GH_EXACT_HEAD",
        ),
        (
            ["pr", "checks", "9002", "--repo", "OmniNode-ai/omnimarket"],
            DECL,
            "pr view",
        ),
        (
            ["api", "repos/OmniNode-ai/omnimarket/pulls/9002"],
            DECL,
            "pr view",
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and len(v) < 30 else None,
)
def test_declaration_with_the_wrong_shape_is_refused_naming_the_part(
    env: dict[str, str], argv: list[str], decl: str, named: str
) -> None:
    result = _run(env, *argv, extra={"ONEX_GH_EXACT_HEAD": decl})

    _assert_refused(env, result)
    assert named in result.stderr
    assert "ONEX_GH_EXACT_HEAD" in result.stderr


@pytest.mark.unit
def test_undeclared_exact_head_shaped_call_is_refused(env: dict[str, str]) -> None:
    result = _run(env, *GOOD)

    _assert_refused(env, result)
    assert "ONEX_GH_EXACT_HEAD=OmniNode-ai/omnimarket#9002" in result.stderr


@pytest.mark.unit
def test_declaration_does_not_widen_other_reads(env: dict[str, str]) -> None:
    result = _run(
        env,
        "api",
        "repos/OmniNode-ai/omnimarket/commits/abc/check-runs",
        extra={"ONEX_GH_EXACT_HEAD": DECL},
    )

    _assert_refused(env, result)


@pytest.mark.unit
def test_declaration_does_not_touch_writes(env: dict[str, str]) -> None:
    argv = [
        "pr",
        "merge",
        "9002",
        "--repo",
        "o/r",
        "--squash",
        "--match-head-commit",
        "a",
    ]

    result = _run(env, *argv, extra={"ONEX_GH_EXACT_HEAD": DECL})

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_refusal_text_is_one_block_not_a_warning(env: dict[str, str]) -> None:
    """No off switch: the refusal does not mention one, and nothing turns it into a warning."""
    result = _run(env, "pr", "checks", "9", "--repo", "o/r")

    assert result.returncode == 1
    assert not re.search(r"\b(warn|observe|disable|bypass)\b", result.stderr, re.I)
    for off in ("ONEX_GH_PR_STATE_GUARD", "ONEX_GH_READ_GUARD", "ONEX_GH_GUARD"):
        again = _run(env, "pr", "checks", "9", "--repo", "o/r", extra={off: "0"})
        assert again.returncode == 1
