# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-17427 phase (a): caller roles and gateway read attribution.

All calls use a fake real gh; no test touches the network.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import stat
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "scripts" / "user-bin"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-out}"
printf '%s' "${FAKE_GH_STDERR:-}" >&2
exit "${FAKE_GH_RC:-0}"
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    real = tmp_path / "realbin"
    real.mkdir()
    (real / "gh").write_text(FAKE_GH)
    (real / "gh").chmod(0o755 | stat.S_IXUSR)
    repo = tmp_path / "repo"
    repo.mkdir()
    base_env = {
        "PATH": f"{SHIM_DIR}:{real}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "FAKE_GH_LOG": str(tmp_path / "calls.jsonl"),
        "GIT_CONFIG_NOSYSTEM": "1",
        # These suites test shim mechanics, not callers: run them as the PR watcher so the
        # PR-state read guard (OMN-19856) lets their pass-through shapes reach the fake gh.
        "ONEX_PR_WATCHER": "1",
        "ONEX_GH_READ_ROUTING": "0",
    }
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=repo,
        env=scrub_git_location_env(base_env),
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:OmniNode-ai/omniclaude.git"],
        cwd=repo,
        env=scrub_git_location_env(base_env),
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "i",
        ],
        cwd=repo,
        env=scrub_git_location_env(base_env),
        check=True,
    )
    base_env.pop("CLAUDE_CODE_SESSION_ID", None)
    base_env.pop("ONEX_LANE", None)
    base_env["REPO"] = str(repo)
    return base_env


def _gh(
    env: dict[str, str], *args: str, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    e = dict(env)
    e.update(extra or {})
    return subprocess.run(
        ["gh", *args],
        cwd=env["REPO"],
        env=e,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _log_lines(env: dict[str, str]) -> list[dict[str, object]]:
    d = Path(env["XDG_CACHE_HOME"]) / "omni" / "gh-usage"
    out: list[dict[str, object]] = []
    for f in sorted(d.glob("*.jsonl")):
        out.extend(
            json.loads(line) for line in f.read_text().splitlines() if line.strip()
        )
    return out


def _run(env: dict[str, str], argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=env["REPO"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _python_script(
    env: dict[str, str], tmp_path: Path, name: str, *, through_sh: bool = False
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / name
    argv = ["sh", "-c", "gh pr list"] if through_sh else ["gh", "pr", "list"]
    script.write_text(
        f"import subprocess\nraise SystemExit(subprocess.run({argv!r}).returncode)\n"
    )
    return _run(env, ["python3", str(script)])


def _module(
    env: dict[str, str], tmp_path: Path, package: str, module: str
) -> subprocess.CompletedProcess[str]:
    package_dir = tmp_path / package
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    (package_dir / f"{module}.py").write_text(
        'import subprocess\nraise SystemExit(subprocess.run(["gh", "pr", "list"]).returncode)\n'
    )
    return _run(
        {**env, "PYTHONPATH": str(tmp_path)},
        ["python3", "-u", "-m", f"{package}.{module}"],
    )


WARNING = (
    "gh shim (OMN-17427): direct GitHub read by {lane} ({cls} {method} {endpoint}); "
    "reads are moving to the GitHub gateway on the event bus. "
    "Set ONEX_GH_WARN=0 to silence this line.\n"
)


def _fake_ancestry(env: dict[str, str], tmp_path: Path, rows: list[str]) -> Path:
    """Supply deterministic ps ancestry and record the exact ps invocations."""
    log = tmp_path / "ps-calls.log"
    env["FAKE_PS_LOG"] = str(log)
    ps = tmp_path / "realbin" / "ps"
    cases = "\n".join(
        f"{i}) printf '%s\\n' {shlex.quote(row)} ;;"
        for i, row in enumerate(rows, start=1)
    )
    ps.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$FAKE_PS_LOG"\n'
        '_n=0\nwhile IFS= read -r _line; do _n=$((_n + 1)); done < "$FAKE_PS_LOG"\n'
        f'case "$_n" in\n{cases}\nesac\n'
    )
    ps.chmod(0o755)
    return log


@pytest.mark.unit
@pytest.mark.parametrize("source", ["env", "agent-env", "registry", "session"])
def test_existing_attribution_never_calls_ps(
    env: dict[str, str], tmp_path: Path, source: str
) -> None:
    ps_log = _fake_ancestry(env, tmp_path, ["1 python3 landing_controller.py"])
    env["CLAUDE_CODE_SESSION_ID"] = "sess-precedence"
    if source == "env":
        env["ONEX_LANE"] = "explicit-lane"
        env["ONEX_LANE_ID"] = "agent-lane"
        lane = "explicit-lane"
    elif source == "agent-env":
        env["ONEX_LANE_ID"] = "agent-lane"
        lane = "agent-lane"
    elif source == "registry":
        worktree = tmp_path / "omni_worktrees" / "OMN-17427" / "omniclaude"
        worktree.mkdir(parents=True)
        env["REPO"] = str(worktree)
        registry = tmp_path / "registry"
        records = registry / "lane_identity"
        records.mkdir(parents=True)
        digest = hashlib.sha256(str(worktree.resolve()).encode()).hexdigest()[:32]
        (records / f"{digest}.json").write_text(json.dumps({"lane": "registered-lane"}))
        env["ONEX_LANE_REGISTRY_ROOT"] = str(registry)
        lane = "registered-lane"
    else:
        lane = "session:sess-precedence"
    r = _gh(env, "pr", "list")
    assert (r.returncode, r.stdout, r.stderr) == (
        0,
        "out",
        WARNING.format(lane=lane, cls="pr list", method="GET", endpoint="-"),
    )
    (rec,) = _log_lines(env)
    assert (rec["lane"], rec["lane_source"]) == (lane, source)
    assert not ps_log.exists()


@pytest.mark.unit
@pytest.mark.parametrize("role_at", [1, 6, 7, None])
def test_ancestry_walk_is_bounded_and_reuses_direct_parent(
    env: dict[str, str], tmp_path: Path, role_at: int | None
) -> None:
    rows = [
        f"{4200 + i} python3 "
        + ("/jobs/landing_controller.py" if i == role_at else "/jobs/runner.py")
        for i in range(1, 8)
    ]
    log = _fake_ancestry(env, tmp_path, rows)
    r = _gh(env, "pr", "list")
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    is_role = role_at in (1, 6)
    assert (rec["lane"], rec["lane_source"]) == (
        ("role:landing-controller", "role")
        if is_role
        else ("script:runner.py", "script")
    )
    calls = log.read_text().splitlines()
    assert len(calls) == (role_at if is_role else 6)
    assert all(call.startswith("-ww -o ppid= -o args= -p ") for call in calls)
    if len(calls) > 1:
        assert calls[1].endswith("-p 4201")


@pytest.mark.unit
@pytest.mark.parametrize("pid", ["0", "1"])
def test_ancestry_stops_at_init(env: dict[str, str], tmp_path: Path, pid: str) -> None:
    log = _fake_ancestry(env, tmp_path, [f"{pid} bash /jobs/tick.sh"])
    r = _gh(env, "pr", "list")
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    assert (rec["lane"], rec["lane_source"]) == ("script:tick.sh", "script")
    assert len(log.read_text().splitlines()) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "role"),
    [
        ("landing_controller.py", "landing-controller"),
        ("landing_worker_run.py", "landing-worker"),
        ("landing_lab_prover.py", "landing-lab-prover"),
        ("onex_remote_lane.py", "remote-lane-runner"),
    ],
)
def test_role_walks_through_sh(
    env: dict[str, str], tmp_path: Path, script: str, role: str
) -> None:
    r = _python_script(env, tmp_path, script, through_sh=True)
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    assert (rec["lane"], rec["lane_source"]) == (f"role:{role}", "role")
    assert rec["gateway"] == "bypass"


@pytest.mark.unit
def test_watcher_module_role(env: dict[str, str], tmp_path: Path) -> None:
    r = _module(env, tmp_path, "omnibase_internal", "pr_watcher")
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    assert (rec["lane"], rec["lane_source"]) == ("role:pr-watcher", "role")


@pytest.mark.unit
@pytest.mark.parametrize("job", ["lab-fill", "hourly-tick", "lab-fill!", "ghp_secret"])
def test_morning_workflow_names_and_cleans_job(
    env: dict[str, str], tmp_path: Path, job: str
) -> None:
    script = tmp_path / "morning_workflows_tick.sh"
    script.write_text("gh pr list\nexit $?\n")
    r = _run(env, ["bash", str(script), job])
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    cleaned = "REDACTED" if job == "ghp_secret" else job.replace("!", "")
    assert (rec["lane"], rec["lane_source"]) == (f"role:{cleaned}", "role")


@pytest.mark.unit
def test_unmapped_module_lane(env: dict[str, str], tmp_path: Path) -> None:
    r = _module(env, tmp_path, "some_pkg", "tool")
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    assert (rec["lane"], rec["lane_source"]) == ("module:some_pkg.tool", "module")
    assert rec["gateway"] == "bypass"


@pytest.mark.unit
def test_role_requires_exact_basename(env: dict[str, str], tmp_path: Path) -> None:
    r = _python_script(env, tmp_path, "foo_landing_controller.py")
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    assert (rec["lane"], rec["lane_source"]) == (
        "script:foo_landing_controller.py",
        "script",
    )


@pytest.mark.unit
def test_session_still_wins_over_role(env: dict[str, str], tmp_path: Path) -> None:
    env["CLAUDE_CODE_SESSION_ID"] = "sess-role"
    r = _python_script(env, tmp_path, "landing_controller.py")
    assert r.returncode == 0
    (rec,) = _log_lines(env)
    assert (rec["lane"], rec["lane_source"]) == ("session:sess-role", "session")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("extra", "gateway", "warn"),
    [
        ({}, "bypass", True),
        ({"ONEX_GH_GATEWAY": "1"}, "gateway", False),
        ({"ONEX_GH_WARN": "0"}, "bypass", False),
        ({"ONEX_GH_GATEWAY": "1", "ONEX_GH_WARN": "1"}, "gateway", False),
        ({"ONEX_GH_GATEWAY": "0"}, "bypass", True),
    ],
)
def test_session_read_warning_and_tsv(
    env: dict[str, str], tmp_path: Path, extra: dict[str, str], gateway: str, warn: bool
) -> None:
    calls = tmp_path / "gh-calls.log"
    r = _gh(
        env,
        "pr",
        "list",
        extra={
            "CLAUDE_CODE_SESSION_ID": "sess-read",
            "ONEX_GH_CALLS_LOG": str(calls),
            "FAKE_GH_STDOUT": "fake stdout\n",
            **extra,
        },
    )
    expected = WARNING.format(
        lane="session:sess-read", cls="pr list", method="GET", endpoint="-"
    )
    assert (r.returncode, r.stdout, r.stderr) == (
        0,
        "fake stdout\n",
        expected if warn else "",
    )
    (rec,) = _log_lines(env)
    assert rec["gateway"] == gateway
    cells = calls.read_text().splitlines()[-1].split("\t")
    assert len(cells) == 8
    assert cells[7] == "allowed"


@pytest.mark.unit
@pytest.mark.parametrize("warn", [None, "0", "1"])
def test_program_read_warns_only_when_requested(
    env: dict[str, str], tmp_path: Path, warn: str | None
) -> None:
    if warn is not None:
        env["ONEX_GH_WARN"] = warn
    env["FAKE_GH_RC"] = "7"
    env["FAKE_GH_STDERR"] = "fake stderr"
    r = _python_script(env, tmp_path, "read_prs.py")
    expected = WARNING.format(
        lane="script:read_prs.py", cls="pr list", method="GET", endpoint="-"
    )
    assert (r.returncode, r.stdout, r.stderr) == (
        7,
        "out",
        (expected if warn == "1" else "") + "fake stderr",
    )
    (rec,) = _log_lines(env)
    assert rec["gateway"] == "bypass"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "gateway", "cls", "method", "endpoint"),
    [
        (["pr", "comment", "1", "--body", "x"], "", "pr comment", "WRITE", "-"),
        (["auth", "status"], "", "auth status", "LOCAL", "-"),
        (
            ["api", "graphql", "-f", "query=mutation { x }"],
            "",
            "api graphql",
            "MUTATION",
            "graphql",
        ),
        (
            ["api", "graphql", "-f", "query={ viewer { login } }"],
            "bypass",
            "api graphql",
            "POST",
            "graphql",
        ),
        (["api", "-X", "HEAD", "user"], "bypass", "api", "HEAD", "user"),
        (["api", "user", "-f", "x=y"], "", "api", "POST", "user"),
        (["api", "-X", "PUT", "user"], "", "api", "PUT", "user"),
        (["api", "-X", "PATCH", "user"], "", "api", "PATCH", "user"),
        (["api", "-X", "DELETE", "user"], "", "api", "DELETE", "user"),
    ],
)
def test_read_classification(
    env: dict[str, str],
    argv: list[str],
    gateway: str,
    cls: str,
    method: str,
    endpoint: str,
) -> None:
    r = _gh(env, *argv, extra={"CLAUDE_CODE_SESSION_ID": "sess-classify"})
    expected = WARNING.format(
        lane="session:sess-classify", cls=cls, method=method, endpoint=endpoint
    )
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", expected if gateway else "")
    (rec,) = _log_lines(env)
    assert rec["gateway"] == gateway


@pytest.mark.unit
@pytest.mark.parametrize("marker", ["0", "1"])
def test_cached_link_shape_is_marked_and_never_warns(
    env: dict[str, str], marker: str
) -> None:
    """The harness PR-link shapes (``pr view --json url``) never warn, hit or miss."""
    extra = {
        "CLAUDE_CODE_SESSION_ID": "sess-cache",
        "ONEX_GH_GATEWAY": marker,
        "ONEX_GH_WARN": "1",
    }
    miss = _gh(env, "pr", "view", "--json", "url", extra=extra)
    hit = _gh(env, "pr", "view", "--json", "url", extra=extra)
    assert (miss.returncode, miss.stdout, miss.stderr) == (0, "out", "")
    assert (hit.returncode, hit.stdout, hit.stderr) == (0, "out", "")
    records = _log_lines(env)
    assert [r["cache"] for r in records] == ["miss", "hit"]
    assert [r["gateway"] for r in records] == [
        "bypass" if marker == "0" else "gateway"
    ] * 2
    assert len(Path(env["FAKE_GH_LOG"]).read_text().splitlines()) == 1


@pytest.mark.unit
def test_routed_json_has_gateway_field(env: dict[str, str]) -> None:
    r = _gh(
        env,
        "pr",
        "list",
        extra={
            "CLAUDE_CODE_SESSION_ID": "sess-route",
            "ONEX_GH_READ_ROUTING": "1",
            "ONEX_GH_ROUTER": "/nonexistent",
            "ONEX_GH_WARN": "0",
        },
    )
    assert (r.returncode, r.stdout, r.stderr) == (0, "out", "")
    (rec,) = _log_lines(env)
    assert rec["identity"] == "operator-fallback"
    assert rec["gateway"] == "bypass"


@pytest.mark.unit
@pytest.mark.parametrize("argv", [["search", "prs", "x"], ["pr", "checks", "1"]])
def test_refused_reads_do_not_warn(env: dict[str, str], argv: list[str]) -> None:
    env.pop("ONEX_PR_WATCHER")
    r = _gh(
        env,
        *argv,
        extra={"CLAUDE_CODE_SESSION_ID": "sess-refused", "ONEX_GH_WARN": "1"},
    )
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr.startswith("REFUSED (")
    assert "direct GitHub read" not in r.stderr
    assert not Path(env["FAKE_GH_LOG"]).exists()
