# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20911: the gh shim refuses every GitHub read from a lane; writes stay allowed.

RULING 2026-10-10T18:17:36Z (re-affirming RULING 2026-09-25T14:34:28Z): lanes read the
canonical clones and the PR watcher, and gh is for writes. The shim enforces it: a lane
context (an agent environment marker, or a Claude Code / Codex / ChatGPT ancestor) gets
exit 1 and the local reader for every read verb, while the PR watcher, the landing
controller's own scripts and the sanctioned read scripts keep their access, and
failing-job logs and one check run's detail go through a cached, per-hour-budgeted read
gateway.

Each test puts a scripted fake ``gh`` (and, for ancestry, a fake ``ps``) behind the user
shim. No test uses the network or an operator credential.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from tests.scripts.conftest import install_ancestry_ps

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-ok}"
exit "${FAKE_GH_RC:-0}"
"""

RULING = "RULING 2026-10-10T18:17:36Z"


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A caller that is NOT a lane: no agent marker, and an ancestry of cron and init."""
    fake_dir = tmp_path / "realbin"
    fake_dir.mkdir()
    _write_exec(fake_dir / "gh", FAKE_GH)
    install_ancestry_ps(fake_dir)
    return {
        "PATH": f"{SHIM.parent}:{fake_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "FAKE_GH_LOG": str(tmp_path / "calls.jsonl"),
        "ONEX_GH_CALLS_LOG": str(tmp_path / "gh-calls.log"),
        "ONEX_LANDING_CONTROLLER_ROOT": str(tmp_path / "controller"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "ONEX_GH_READ_ROUTING": "0",
    }


def _run(
    env: dict[str, str],
    *args: str,
    extra: dict[str, str] | None = None,
    argv0: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env)
    run_env.update(extra or {})
    return subprocess.run(
        argv0 if argv0 is not None else ["gh", *args],
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


def _assert_lane_refused(
    env: dict[str, str], result: subprocess.CompletedProcess[str]
) -> None:
    assert result.returncode == 1, result.stderr
    assert _calls(env) == [], "a refused read must never reach the real gh"
    first = result.stderr.splitlines()[0]
    assert first.startswith("REFUSED (OMN-20911): "), result.stderr
    assert "is a GitHub read from a lane" in first
    assert RULING in first
    # The refusal names the local readers, not just "no".
    assert "pr_state_local.py --pr" in result.stderr
    assert "canonical clones" in result.stderr
    assert "pr-state-observed" in result.stderr
    rows = _call_log_rows(env)
    assert rows, "a refusal is logged"
    assert (rows[-1][6], rows[-1][7]) == ("1", "refused")


# Reads the PR-state guard (OMN-19856) never covered: the lane guard must refuse each.
LANE_READS = [
    ["api", "repos/OmniNode-ai/onex_change_control/contents/contracts/OMN-1.yaml"],
    ["api", "repos/OmniNode-ai/omnimarket/actions/artifacts"],
    ["api", "repos/o/r/actions/artifacts/9/zip"],
    ["api", "repos/o/r/commits/abc"],
    ["api", "repos/o/r/issues/9/comments"],
    ["api", "user"],
    ["api", "-X", "GET", "repos/o/r/releases", "-f", "per_page=5"],
    ["api", "-X", "HEAD", "repos/o/r"],
    ["api", "graphql", "-f", "query={viewer{login}}"],
    ["pr", "list", "--repo", "o/r"],
    ["pr", "diff", "9"],
    ["pr", "status"],
    ["pr", "checkout", "9"],
    ["run", "list", "--repo", "o/r"],
    ["run", "download", "123", "-n", "receipt"],
    ["run", "watch", "123"],
    ["repo", "view", "o/r"],
    ["issue", "view", "9"],
    ["issue", "list", "--repo", "o/r"],
    ["release", "list", "--repo", "o/r"],
    ["workflow", "list", "--repo", "o/r"],
    ["variable", "get", "X", "--repo", "o/r"],
    ["status"],
]

LANE_MARKERS = [
    {"ONEX_LANE": "some-lane"},
    {"ONEX_LANE_ID": "some-lane"},
    {"CLAUDECODE": "1"},
    {"CLAUDE_CODE_SESSION_ID": "sess-1"},
    {"CLAUDE_SUBAGENT_NAME": "worker"},
    {"CODEX_SANDBOX": "seatbelt"},
    {"CODEX_THREAD_ID": "t-1"},
]

AGENT_ANCESTORS = [
    "/opt/agent/.local/share/claude/versions/2.1.295",
    "claude",
    "/srv/agent/.local/bin/claude",
    "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT",
    "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node",
    "/opt/homebrew/bin/codex",
    "codex",
]


@pytest.mark.unit
@pytest.mark.parametrize("argv", LANE_READS, ids=lambda a: " ".join(a)[:70])
def test_lane_gh_read_refused(env: dict[str, str], argv: list[str]) -> None:
    result = _run(env, *argv, extra={"ONEX_LANE": "no-gh-reads-test"})
    _assert_lane_refused(env, result)


@pytest.mark.unit
@pytest.mark.parametrize("marker", LANE_MARKERS, ids=lambda m: next(iter(m)))
def test_lane_gh_read_refused_for_every_environment_marker(
    env: dict[str, str], marker: dict[str, str]
) -> None:
    result = _run(env, "pr", "list", "--repo", "o/r", extra=marker)
    _assert_lane_refused(env, result)
    assert f"(environment {next(iter(marker))})" in result.stderr.splitlines()[0]


@pytest.mark.unit
@pytest.mark.parametrize("comm", AGENT_ANCESTORS)
def test_lane_gh_read_refused_for_an_agent_ancestor(
    env: dict[str, str], tmp_path: Path, comm: str
) -> None:
    """No marker in the environment: the ancestry alone makes it a lane (the Codex app's
    own gh polling, a Claude Code Bash tool whose environment was scrubbed)."""
    install_ancestry_ps(tmp_path / "realbin", comm)
    result = _run(env, "api", "user")
    _assert_lane_refused(env, result)
    assert "ancestor process" in result.stderr.splitlines()[0]


@pytest.mark.unit
@pytest.mark.parametrize("argv", LANE_READS, ids=lambda a: " ".join(a)[:70])
def test_positive_control_the_same_read_passes_outside_a_lane(
    env: dict[str, str], argv: list[str]
) -> None:
    """Rule 16 positive control: the refusal above is the lane guard deciding, not a shim
    that fails every call. The identical argv, minus the lane context, reaches gh."""
    result = _run(env, *argv)
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_positive_control_refusal_path_really_runs(
    env: dict[str, str], tmp_path: Path
) -> None:
    """The same caller flips between pass and refuse on the lane context alone, and the
    ancestry query really reached ps (the walk is not short-circuited)."""
    ps_log = tmp_path / "ps.log"
    ps = tmp_path / "realbin" / "ps"
    ps.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$*" >> {ps_log}\n'
        'case " $* " in *" comm= "*) printf "1 %s\\n" "$FAKE_ANCESTOR"; exit 0 ;; esac\n'
        'exec /bin/ps "$@"\n'
    )
    ps.chmod(0o755)
    passed = _run(env, "api", "user", extra={"FAKE_ANCESTOR": "/usr/sbin/cron"})
    assert passed.returncode == 0, passed.stderr
    refused = _run(
        env, "api", "user", extra={"FAKE_ANCESTOR": "/opt/homebrew/bin/codex"}
    )
    assert refused.returncode == 1
    assert refused.stderr.startswith("REFUSED (OMN-20911): ")
    assert _calls(env) == [["api", "user"]]
    assert any("comm=" in line for line in ps_log.read_text().splitlines())


LANE_WRITES = [
    ["api", "-X", "POST", "repos/o/r/pulls/9/comments", "-f", "body=hi"],
    ["api", "-X", "PATCH", "repos/o/r/pulls/9", "-f", "title=t"],
    ["api", "-X", "DELETE", "repos/o/r/git/refs/heads/x"],
    ["api", "repos/o/r/issues/9/comments", "-f", "body=hi"],  # -f makes it a POST
    ["api", "graphql", "-f", "query=mutation{addComment(input:{}){clientMutationId}}"],
    ["pr", "create", "--title", "t", "--body", "b"],
    ["pr", "edit", "9", "--add-label", "x"],
    ["pr", "comment", "9", "--body", "hi"],
    ["pr", "review", "9", "--approve"],
    ["pr", "ready", "9", "--repo", "o/r"],
    ["pr", "merge", "9", "--repo", "o/r", "--squash", "--match-head-commit", "abc"],
    ["workflow", "run", "ci.yml", "--repo", "o/r"],
    ["run", "rerun", "123", "--repo", "o/r"],
    ["run", "cancel", "123"],
    ["auth", "status"],
]


@pytest.mark.unit
@pytest.mark.parametrize("argv", LANE_WRITES, ids=lambda a: " ".join(a)[:70])
def test_lane_writes_are_allowed(env: dict[str, str], argv: list[str]) -> None:
    result = _run(env, *argv, extra={"ONEX_LANE": "no-gh-reads-test"})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_graphql_query_from_a_file_is_judged_by_the_file(
    env: dict[str, str], tmp_path: Path
) -> None:
    mutation = tmp_path / "m.graphql"
    mutation.write_text("mutation { closePullRequest(input: {}) { clientMutationId } }")
    query = tmp_path / "q.graphql"
    query.write_text("query { viewer { login } }")
    lane = {"ONEX_LANE": "no-gh-reads-test"}

    write = _run(env, "api", "graphql", "-F", f"query=@{mutation}", extra=lane)
    assert write.returncode == 0, write.stderr

    read = _run(env, "api", "graphql", "-F", f"query=@{query}", extra=lane)
    assert read.returncode == 1
    assert read.stderr.startswith("REFUSED (OMN-20911): ")
    assert len(_calls(env)) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "view", "--json", "url"],
        ["pr", "view", "feature", "--json", "number,url,state"],
        ["api", "rate_limit"],
    ],
    ids=" ".join,
)
def test_lane_keeps_the_harness_link_shapes_and_rate_limit(
    env: dict[str, str], argv: list[str]
) -> None:
    result = _run(env, *argv, extra={"CLAUDECODE": "1"})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_lane_keeps_the_declared_exact_head_check(env: dict[str, str]) -> None:
    argv = ["pr", "view", "9", "--repo", "o/r", "--json", "headRefOid,state"]
    result = _run(
        env, *argv, extra={"ONEX_LANE": "lane", "ONEX_GH_EXACT_HEAD": "o/r#9"}
    )
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


# --- allowlisted callers ---------------------------------------------------------


@pytest.mark.unit
def test_pr_watcher_reads_from_a_lane_context(env: dict[str, str]) -> None:
    result = _run(
        env,
        "api",
        "repos/o/r/commits/abc",
        extra={"ONEX_LANE": "pr-watcher", "ONEX_PR_WATCHER": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [["api", "repos/o/r/commits/abc"]]


@pytest.mark.unit
def test_landing_controller_script_reads(env: dict[str, str], tmp_path: Path) -> None:
    script = (
        tmp_path / "controller" / "skills" / "merge-drain" / "scripts"
    ) / "landing_controller.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import subprocess, sys\n"
        "r = subprocess.run(['gh', 'pr', 'list', '--repo', 'o/r'])\n"
        "sys.exit(r.returncode)\n"
    )
    result = _run(env, argv0=["python3", str(script)], extra={"CLAUDECODE": "1"})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [["pr", "list", "--repo", "o/r"]]


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel",
    [
        "skills/pr-handoff/scripts/handoff.sh",
        "skills/pr-handoff/scripts/handoff_row.sh",
        "skills/release-cut/scripts/cut_facts.sh",
        "skills/lab-rebuild-triage/scripts/read_receipt.sh",
        "skills/lab-rebuild-triage/scripts/trigger_for_sha.sh",
    ],
)
def test_sanctioned_read_scripts_read(
    env: dict[str, str], tmp_path: Path, rel: str
) -> None:
    script = tmp_path / "plugin" / rel
    script.parent.mkdir(parents=True)
    script.write_text('gh api "repos/o/r/actions/artifacts?name=x"\nexit $?\n')
    result = _run(env, argv0=["bash", str(script)], extra={"ONEX_LANE": "lane"})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [["api", "repos/o/r/actions/artifacts?name=x"]]


_GATE_BODY = (
    "import subprocess, sys\n"
    "r = subprocess.run(['gh', 'api', 'repos/o/r/branches/dev/protection'])\n"
    "sys.exit(r.returncode)\n"
)


@pytest.mark.unit
@pytest.mark.parametrize("relative", [True, False])
def test_the_advisory_job_gate_hook_reads_branch_protection(
    env: dict[str, str], tmp_path: Path, relative: bool
) -> None:
    """The advisory-job-gate pre-commit hook runs inside a lane's commit and reads the
    repository's branch protection, which no clone holds; refusing it would make every
    lane commit that touches a workflow fail with THE GATE DID NOT RUN. pre-commit runs
    it as `python3 scripts/advisory_job_gate.py` from the repository root."""
    script = tmp_path / "scripts" / "advisory_job_gate.py"
    script.parent.mkdir(parents=True)
    script.write_text(_GATE_BODY)
    arg = "scripts/advisory_job_gate.py" if relative else str(script)
    result = subprocess.run(
        ["python3", arg, "--repo-root", "."],
        env={**env, "CLAUDECODE": "1"},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [["api", "repos/o/r/branches/dev/protection"]]


@pytest.mark.unit
def test_another_python_script_in_a_lane_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    """Negative twin: the same body under another script name is a lane read."""
    script = tmp_path / "scripts" / "advisory_job_gate_copy.py"
    script.parent.mkdir(parents=True)
    script.write_text(_GATE_BODY)
    result = subprocess.run(
        ["python3", "scripts/advisory_job_gate_copy.py", "--repo-root", "."],
        env={**env, "CLAUDECODE": "1"},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    _assert_lane_refused(env, result)


@pytest.mark.unit
def test_an_unsanctioned_script_in_a_lane_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    """Negative twin of the test above: the same script under another name."""
    script = tmp_path / "plugin" / "skills" / "my-skill" / "scripts" / "handoff.sh"
    script.parent.mkdir(parents=True)
    script.write_text('gh api "repos/o/r/actions/artifacts?name=x"\nexit $?\n')
    result = _run(env, argv0=["bash", str(script)], extra={"ONEX_LANE": "lane"})
    _assert_lane_refused(env, result)


# --- cached read gateway ---------------------------------------------------------

GATEWAY = [
    ["run", "view", "123", "--repo", "o/r", "--log-failed"],
    ["api", "repos/o/r/actions/jobs/555/logs"],
    ["api", "repos/o/r/check-runs/77"],
    ["api", "repos/o/r/check-runs/77/annotations"],
    ["api", "repos/o/r/actions/jobs/555"],
]


@pytest.mark.unit
@pytest.mark.parametrize("argv", GATEWAY, ids=lambda a: " ".join(a)[:70])
def test_gateway_serves_a_lane_once_then_from_cache(
    env: dict[str, str], argv: list[str]
) -> None:
    lane = {"ONEX_LANE": "lane", "FAKE_GH_STDOUT": "the log"}
    first = _run(env, *argv, extra=lane)
    second = _run(env, *argv, extra=lane)
    assert (first.returncode, first.stdout) == (0, "the log"), first.stderr
    assert (second.returncode, second.stdout) == (0, "the log"), second.stderr
    assert _calls(env) == [argv], "the second read is a cache hit"


@pytest.mark.unit
def test_gateway_does_not_cache_a_failure(env: dict[str, str]) -> None:
    argv = ["api", "repos/o/r/actions/jobs/555/logs"]
    _run(env, *argv, extra={"ONEX_LANE": "lane", "FAKE_GH_RC": "1"})
    _run(env, *argv, extra={"ONEX_LANE": "lane"})
    assert _calls(env) == [argv, argv]


@pytest.mark.unit
def test_gateway_budget_refuses_when_spent_and_ignores_the_environment(
    env: dict[str, str], tmp_path: Path
) -> None:
    conf = tmp_path / "config" / "omni" / "gh-gateway.env"
    conf.parent.mkdir(parents=True)
    conf.write_text("ONEX_GH_GATEWAY_BUDGET=2\n")
    lane = {"ONEX_LANE": "lane", "ONEX_GH_GATEWAY_BUDGET": "1000"}
    for job in ("1", "2"):
        ok = _run(env, "api", f"repos/o/r/actions/jobs/{job}/logs", extra=lane)
        assert ok.returncode == 0, ok.stderr
    spent = _run(env, "api", "repos/o/r/actions/jobs/3/logs", extra=lane)
    assert spent.returncode == 1
    assert spent.stderr.startswith("REFUSED (OMN-20911): the cached read gateway")
    assert len(_calls(env)) == 2
    # A cached answer is still served once the budget is spent.
    hit = _run(env, "api", "repos/o/r/actions/jobs/1/logs", extra=lane)
    assert hit.returncode == 0, hit.stderr
    assert len(_calls(env)) == 2
