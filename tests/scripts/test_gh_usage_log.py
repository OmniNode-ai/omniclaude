# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19585: every gh call through the shim is logged by lane, and the report attributes it.

* AC1 (``-k record``): one JSON line per invocation carrying timestamp, lane,
  command class, method, repository and exit code;
* AC2 (``-k passthrough``): argv, stdout, stderr and exit code are unchanged
  with logging on;
* AC3 (``-k secret``): no token value reaches the log, with ``GH_TOKEN`` set to
  a sentinel and the sentinel also passed on the command line;
* AC4 (``-k report``): ``gh_usage_report.py`` prints weighted requests per lane
  per hour and names the share it cannot attribute.

No test touches the network.
"""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "scripts" / "user-bin"
REPORT = SHIM_DIR / "gh_usage_report.py"
SENTINEL = "ghp_SENTINEL0123456789abcdefghijklmnopqr"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-out}"
printf '%s' "${FAKE_GH_STDERR:-}" >&2
exit "${FAKE_GH_RC:-0}"
"""


def _load_report() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gh_usage_report", REPORT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


# --- AC1 ------------------------------------------------------------------------

RECORD_CASES = [
    (
        [
            "api",
            "repos/OmniNode-ai/omnibase_infra/pulls/12/files?per_page=100",
            "--paginate",
        ],
        "api",
        "GET",
        "omnibase_infra",
        "repos/OmniNode-ai/omnibase_infra/pulls/12/files",
    ),
    (
        [
            "api",
            "-X",
            "PUT",
            "repos/OmniNode-ai/omnimarket/pulls/1/merge",
            "-f",
            "sha=x",
        ],
        "api",
        "PUT",
        "omnimarket",
        "repos/OmniNode-ai/omnimarket/pulls/1/merge",
    ),
    (
        ["api", "repos/OmniNode-ai/omnidash/issues/3/comments", "-f", "body=x"],
        "api",
        "POST",
        "omnidash",
        "repos/OmniNode-ai/omnidash/issues/3/comments",
    ),
    (
        ["api", "graphql", "-f", "query={ viewer { login } }"],
        "api graphql",
        "POST",
        "",
        "graphql",
    ),
    (
        ["api", "graphql", "-f", "query=mutation { x }"],
        "api graphql",
        "MUTATION",
        "",
        "graphql",
    ),
    (
        ["pr", "checks", "12", "-R", "OmniNode-ai/omnimarket"],
        "pr checks",
        "GET",
        "omnimarket",
        "",
    ),
    (["pr", "view", "12", "--json", "headRefOid"], "pr view", "GET", "omniclaude", ""),
    (["pr", "merge", "12", "--squash"], "pr merge", "WRITE", "omniclaude", ""),
    (
        ["run", "list", "--repo=OmniNode-ai/omnibase_core"],
        "run list",
        "GET",
        "omnibase_core",
        "",
    ),
    (["auth", "status"], "auth status", "LOCAL", "", ""),
]


@pytest.mark.unit
@pytest.mark.parametrize(("argv", "cls", "method", "repo", "endpoint"), RECORD_CASES)
def test_record_one_line_per_call(
    env: dict[str, str],
    argv: list[str],
    cls: str,
    method: str,
    repo: str,
    endpoint: str,
) -> None:
    r = _gh(env, *argv, extra={"FAKE_GH_RC": "5", "ONEX_LANE": "pr-lander-83b"})
    assert r.returncode == 5
    lines = _log_lines(env)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["cls"] == cls
    assert rec["method"] == method
    assert rec["repo"] == repo
    assert rec["endpoint"] == endpoint
    assert rec["exit"] == 5
    assert rec["lane"] == "pr-lander-83b"
    assert rec["lane_source"] == "env"
    datetime.fromisoformat(str(rec["ts"]).replace("Z", "+00:00"))


@pytest.mark.unit
def test_record_lane_falls_back_to_session_then_parent(env: dict[str, str]) -> None:
    _gh(env, "pr", "list", extra={"CLAUDE_CODE_SESSION_ID": "sess-1"})
    e = dict(env)
    e.pop("CLAUDE_CODE_SESSION_ID", None)
    _gh(e, "pr", "list")
    first, second = _log_lines(env)
    assert (first["lane"], first["lane_source"], first["session"]) == (
        "session:sess-1",
        "session",
        "sess-1",
    )
    assert second["lane_source"] == "parent"
    assert str(second["lane"]).startswith("parent:")


@pytest.mark.unit
def test_record_cache_hits_are_logged_as_hits(env: dict[str, str]) -> None:
    _gh(env, "pr", "view", "--json", "url")
    _gh(env, "pr", "view", "--json", "url")
    caches = [rec["cache"] for rec in _log_lines(env)]
    assert caches == ["miss", "hit"]
    assert len(Path(env["FAKE_GH_LOG"]).read_text().splitlines()) == 1


@pytest.mark.unit
def test_record_off_switch(env: dict[str, str]) -> None:
    _gh(env, "pr", "list", extra={"ONEX_GH_USAGE_LOG": "0"})
    assert _log_lines(env) == []


# --- AC2 ------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "merge", "1", "--squash"],
        ["api", "-X", "POST", "repos/o/r/issues/1/comments", "-f", "body=two words"],
        ["pr", "checks", "7"],
        ["api", "graphql", "-f", "query=q"],
    ],
)
def test_passthrough_unchanged_with_logging(
    env: dict[str, str], argv: list[str]
) -> None:
    r = _gh(
        env,
        *argv,
        extra={"FAKE_GH_RC": "9", "FAKE_GH_STDOUT": "a\nb", "FAKE_GH_STDERR": "warn"},
    )
    assert (r.returncode, r.stdout, r.stderr) == (9, "a\nb", "warn")
    calls = [
        json.loads(line) for line in Path(env["FAKE_GH_LOG"]).read_text().splitlines()
    ]
    assert calls == [argv]


# --- AC3 ------------------------------------------------------------------------


@pytest.mark.unit
def test_secret_never_reaches_the_log(env: dict[str, str]) -> None:
    extra = {
        "GH_TOKEN": SENTINEL,
        "GITHUB_TOKEN": SENTINEL,
        "ONEX_LANE": f"lane-{SENTINEL}",
    }
    _gh(env, "api", "-H", f"Authorization: token {SENTINEL}", "user", extra=extra)
    _gh(env, "api", f"repos/o/r/contents/x?access_token={SENTINEL}", extra=extra)
    _gh(env, "api", f"repos/o/{SENTINEL}/pulls", extra=extra)
    _gh(env, "pr", "view", "--json", "url", extra=extra)
    raw = "".join(
        f.read_text()
        for f in (Path(env["XDG_CACHE_HOME"]) / "omni" / "gh-usage").glob("*.jsonl")
    )
    assert raw.count("\n") == 4
    assert SENTINEL not in raw
    assert "SENTINEL" not in raw


# --- AC4 ------------------------------------------------------------------------


def _write_fixture_log(d: Path, base: datetime) -> None:
    rows = [
        # lane A: 2 pr checks (4 each) + 1 api (1) = 9
        {
            "lane": "pr-lander-83b",
            "lane_source": "env",
            "cls": "pr checks",
            "method": "GET",
            "cache": "none",
        },
        {
            "lane": "pr-lander-83b",
            "lane_source": "env",
            "cls": "pr checks",
            "method": "GET",
            "cache": "none",
        },
        {
            "lane": "pr-lander-83b",
            "lane_source": "env",
            "cls": "api",
            "method": "GET",
            "cache": "none",
        },
        # session: 1 pr view (2) + 1 cache hit (0) + 1 graphql (0 core, 1 gql)
        {
            "lane": "session:s1",
            "lane_source": "session",
            "session": "s1",
            "cls": "pr view",
            "method": "GET",
            "cache": "miss",
        },
        {
            "lane": "session:s1",
            "lane_source": "session",
            "session": "s1",
            "cls": "pr view",
            "method": "GET",
            "cache": "hit",
        },
        {
            "lane": "session:s1",
            "lane_source": "session",
            "session": "s1",
            "cls": "api graphql",
            "method": "POST",
            "cache": "none",
        },
        # unattributed: 1 run view (2) + 1 auth (0)
        {
            "lane": "parent:launchd",
            "lane_source": "parent",
            "cls": "run view",
            "method": "GET",
            "cache": "none",
        },
        {
            "lane": "parent:launchd",
            "lane_source": "parent",
            "cls": "auth status",
            "method": "LOCAL",
            "cache": "none",
        },
    ]
    d.mkdir(parents=True)
    with (d / f"{base.date().isoformat()}.jsonl").open("w") as fh:
        for i, row in enumerate(rows):
            row = {
                "ts": (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "exit": 0,
                **row,
            }
            fh.write(json.dumps(row) + "\n")
        fh.write("not json\n")


@pytest.mark.unit
def test_report_weights_per_lane_and_names_unattributed(tmp_path: Path) -> None:
    mod = _load_report()
    base = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
    log_dir = tmp_path / "gh-usage"
    _write_fixture_log(log_dir, base)
    since, until = base, base + timedelta(hours=1)
    rep = mod.build_report(mod.load_records(log_dir, since, until), since, until, None)
    by_lane = {r["lane"]: r for r in rep["lanes"]}
    assert by_lane["pr-lander-83b"]["core_requests_est"] == 9
    assert by_lane["pr-lander-83b"]["core_requests_per_hour_est"] == 9.0
    assert by_lane["session:s1"]["core_requests_est"] == 2
    assert by_lane["session:s1"]["graphql_calls"] == 1
    assert by_lane["session:s1"]["cache_hits"] == 1
    assert by_lane["parent:launchd"]["core_requests_est"] == 2
    assert rep["total_calls"] == 8
    assert rep["unattributed_calls"] == 2
    assert rep["unattributed_share_of_calls"] == 0.25
    assert rep["total_core_requests_est"] == 13
    text = mod.render_text(rep)
    assert "UNATTRIBUTED: 2 calls (25.0%)" in text


@pytest.mark.unit
def test_report_cli_json_and_window(tmp_path: Path) -> None:
    base = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
    log_dir = tmp_path / "gh-usage"
    _write_fixture_log(log_dir, base)
    r = subprocess.run(
        [
            "python3",
            str(REPORT),
            "--log-dir",
            str(log_dir),
            "--since",
            "2026-09-25T10:00:00Z",
            "--until",
            "2026-09-25T10:02:30Z",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["total_calls"] == 3


@pytest.mark.unit
def test_report_missing_log_dir_is_loud(tmp_path: Path) -> None:
    r = subprocess.run(
        ["python3", str(REPORT), "--log-dir", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode != 0
    assert "no usage log directory" in r.stderr


@pytest.mark.unit
def test_report_resolves_session_calls_to_the_running_subagent(tmp_path: Path) -> None:
    mod = _load_report()
    base = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
    proj = tmp_path / "proj"
    wf = proj / "s1" / "subagents" / "workflows" / "wf_1"
    wf.mkdir(parents=True)
    (wf / "agent-aaa.meta.json").write_text(
        json.dumps({"description": "pr-lander-83c"})
    )
    (wf / "agent-bbb.meta.json").write_text(json.dumps({"description": "red-fix-1"}))

    def tool_pair(agent: str, uid: str, start: datetime, end: datetime) -> str:
        use = {
            "timestamp": start.isoformat().replace("+00:00", "Z"),
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": uid,
                        "name": "Bash",
                        "input": {"command": "x"},
                    }
                ]
            },
        }
        res = {
            "timestamp": end.isoformat().replace("+00:00", "Z"),
            "message": {"content": [{"type": "tool_result", "tool_use_id": uid}]},
        }
        return json.dumps(use) + "\n" + json.dumps(res) + "\n"

    (wf / "agent-aaa.jsonl").write_text(
        tool_pair("aaa", "t1", base, base + timedelta(seconds=30))
    )
    (wf / "agent-bbb.jsonl").write_text(
        tool_pair(
            "bbb", "t2", base + timedelta(seconds=20), base + timedelta(seconds=90)
        )
    )
    recs = [
        {
            "_ts": base + timedelta(seconds=5),
            "lane": "session:s1",
            "lane_source": "session",
            "session": "s1",
            "cls": "api",
            "method": "GET",
        },
        {
            "_ts": base + timedelta(seconds=25),
            "lane": "session:s1",
            "lane_source": "session",
            "session": "s1",
            "cls": "api",
            "method": "GET",
        },
        {
            "_ts": base + timedelta(seconds=60),
            "lane": "session:s1",
            "lane_source": "session",
            "session": "s1",
            "cls": "api",
            "method": "GET",
        },
    ]
    rep = mod.build_report(recs, base, base + timedelta(hours=1), proj)
    by_lane = {r["lane"]: r["calls"] for r in rep["lanes"]}
    # 5 s: only aaa running; 25 s: both running, stays on the session; 60 s: only bbb
    assert by_lane == {"pr-lander-83c": 1, "session:s1": 1, "red-fix-1": 1}
    assert rep["unattributed_calls"] == 0
