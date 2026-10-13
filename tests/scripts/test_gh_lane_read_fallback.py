# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20911: lane reads fall back to the cached, hourly-budgeted gh gateway.

RULING 2026-10-12T05:03:28Z: fall back with a logged fallback until the replacement
proves out, then go strict. Strictness and budget come only from gh-gateway.env;
PR-state refusals and write guards remain in force.

Each test puts a scripted fake ``gh`` and a fake ``ps`` behind the user shim.
No test uses the network or an operator credential.
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
LANE = "lane-read-fallback-test"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-ok}"
exit "${FAKE_GH_RC:-0}"
"""


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """No lane markers or strict config; cron and init are the only ancestors."""
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


def _budget_spent(env: dict[str, str]) -> int:
    budget = Path(env["XDG_CACHE_HOME"]) / "omni" / "gh-shim" / "gateway" / "budget"
    return sum(len(f.read_text().splitlines()) for f in budget.glob("*"))


def _configure(env: dict[str, str], body: str) -> None:
    conf = Path(env["XDG_CONFIG_HOME"]) / "omni" / "gh-gateway.env"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(body)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "call_class"),
    [
        (["api", "user"], "api"),
        (["pr", "list", "--repo", "o/r"], "pr list"),
        (["api", "graphql", "-f", "query={viewer{login}}"], "api graphql"),
        (["run", "list", "--repo", "o/r"], "run list"),
        (["status"], "status"),
    ],
)
def test_lane_read_inside_budget_passes(
    env: dict[str, str], argv: list[str], call_class: str
) -> None:
    result = _run(env, *argv, extra={"ONEX_LANE": LANE})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 1
    rows = _call_log_rows(env)
    assert len(rows) == 1
    row = rows[-1]
    assert len(row) == 8
    assert row[1] == LANE
    assert row[3] == call_class
    if argv == ["api", "user"]:
        assert row[5] == "user"
    assert (row[6], row[7]) == ("0", "fallback")


@pytest.mark.unit
def test_identical_lane_read_is_served_from_cache(env: dict[str, str]) -> None:
    argv = ["api", "user"]
    lane = {"ONEX_LANE": LANE, "FAKE_GH_STDOUT": "the answer"}
    first = _run(env, *argv, extra=lane)
    second = _run(env, *argv, extra=lane)
    assert (first.returncode, first.stdout) == (0, "the answer"), first.stderr
    assert (second.returncode, second.stdout) == (0, first.stdout), second.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 1
    assert [row[7] for row in _call_log_rows(env)] == ["fallback", "fallback"]


@pytest.mark.unit
def test_spent_budget_refuses_and_ignores_the_environment(env: dict[str, str]) -> None:
    _configure(env, "ONEX_GH_GATEWAY_BUDGET=2\n")
    lane = {"ONEX_LANE": LANE, "ONEX_GH_GATEWAY_BUDGET": "100"}
    reads = [["api", "user"], ["api", "repos/o/r/releases"]]
    for argv in reads:
        result = _run(env, *argv, extra=lane)
        assert result.returncode == 0, result.stderr
    assert _budget_spent(env) == 2
    refused = _run(env, "pr", "list", "--repo", "o/r", extra=lane)
    assert refused.returncode == 1, refused.stderr
    first = refused.stderr.splitlines()[0]
    assert first.startswith("REFUSED (OMN-20911): "), refused.stderr
    assert "is a GitHub read from a lane" in first
    assert "lane read fallback budget is spent" in first
    assert "ONEX_GH_GATEWAY_BUDGET=2" in first
    assert _calls(env) == reads
    assert [row[7] for row in _call_log_rows(env)] == [
        "fallback",
        "fallback",
        "refused",
    ]
    assert _call_log_rows(env)[-1][6] == "1"


@pytest.mark.unit
def test_failed_answer_is_not_cached(env: dict[str, str]) -> None:
    argv = ["api", "user"]
    for _ in range(2):
        result = _run(env, *argv, extra={"ONEX_LANE": LANE, "FAKE_GH_RC": "1"})
        assert result.returncode == 1, result.stderr
    assert _calls(env) == [argv, argv]
    assert _budget_spent(env) == 2
    assert [(row[6], row[7]) for row in _call_log_rows(env)] == [
        ("1", "fallback"),
        ("1", "fallback"),
    ]


@pytest.mark.unit
def test_strict_config_refuses_only_that_verb(env: dict[str, str]) -> None:
    _configure(env, "ONEX_GH_LANE_READ_STRICT_PR_LIST=1\n")
    refused = _run(env, "pr", "list", "--repo", "o/r", extra={"ONEX_LANE": LANE})
    assert refused.returncode == 1, refused.stderr
    first = refused.stderr.splitlines()[0]
    assert first.startswith("REFUSED (OMN-20911): "), refused.stderr
    assert "is a GitHub read from a lane" in first
    assert "RULING 2026-10-10T18:17:36Z" in first
    assert first.endswith("This verb is strict in gh-gateway.env.")
    assert "pr_state_local.py --pr" in refused.stderr
    assert "canonical clones" in refused.stderr
    assert "pr-state-observed" in refused.stderr
    assert _calls(env) == []
    assert _budget_spent(env) == 0
    assert [(row[6], row[7]) for row in _call_log_rows(env)] == [("1", "refused")]
    allowed = _run(env, "api", "user", extra={"ONEX_LANE": LANE})
    assert allowed.returncode == 0, allowed.stderr
    assert _calls(env) == [["api", "user"]]
    assert _budget_spent(env) == 1
    assert [row[7] for row in _call_log_rows(env)] == ["refused", "fallback"]


@pytest.mark.unit
@pytest.mark.parametrize("value", ["0", "yes"])
def test_strict_values_other_than_one_fall_back(
    env: dict[str, str], value: str
) -> None:
    _configure(env, f"ONEX_GH_LANE_READ_STRICT_PR_LIST={value}\n")
    argv = ["pr", "list", "--repo", "o/r"]
    result = _run(env, *argv, extra={"ONEX_LANE": LANE})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 1
    assert [row[7] for row in _call_log_rows(env)] == ["fallback"]


@pytest.mark.unit
def test_strict_environment_key_does_not_make_a_verb_strict(
    env: dict[str, str],
) -> None:
    argv = ["pr", "list", "--repo", "o/r"]
    result = _run(
        env,
        *argv,
        extra={"ONEX_LANE": LANE, "ONEX_GH_LANE_READ_STRICT_PR_LIST": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 1
    assert [row[7] for row in _call_log_rows(env)] == ["fallback"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "view", "9", "--repo", "o/r"],
        ["pr", "checks", "9", "--repo", "o/r"],
        ["api", "repos/o/r/pulls/9"],
        ["api", "repos/o/r/commits/abc/status"],
        ["run", "view", "123", "--repo", "o/r"],
    ],
)
def test_pr_state_reads_still_refuse_without_strict_config(
    env: dict[str, str], argv: list[str]
) -> None:
    result = _run(env, *argv, extra={"ONEX_LANE": LANE})
    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-19856): "), result.stderr
    assert _calls(env) == []
    assert _budget_spent(env) == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "create", "--title", "t", "--body", "b"],
        ["api", "-X", "POST", "repos/o/r/issues/9/comments", "-f", "body=hi"],
        ["pr", "comment", "9", "--body", "hi"],
    ],
)
def test_lane_writes_are_unaffected(env: dict[str, str], argv: list[str]) -> None:
    result = _run(env, *argv, extra={"ONEX_LANE": LANE})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 0
    assert [row[7] for row in _call_log_rows(env)] == ["allowed"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "checkout", "9"],
        ["run", "download", "123"],
        ["run", "watch", "123"],
        ["release", "download", "v1"],
        ["browse"],
    ],
)
def test_local_actions_and_streams_are_never_cached(
    env: dict[str, str], argv: list[str]
) -> None:
    for _ in range(2):
        result = _run(env, *argv, extra={"ONEX_LANE": LANE})
        assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv, argv]
    assert _budget_spent(env) == 2
    assert [row[7] for row in _call_log_rows(env)] == ["fallback", "fallback"]


@pytest.mark.unit
@pytest.mark.parametrize("field", ["-F", "--input", "--input="])
def test_graphql_query_from_a_file_is_never_cached(
    env: dict[str, str], tmp_path: Path, field: str
) -> None:
    query = tmp_path / "query.graphql"
    query.write_text("query { viewer { login } }")
    if field == "-F":
        args = [field, f"query=@{query}"]
    elif field == "--input":
        args = [field, str(query)]
    else:
        args = [f"{field}{query}"]
    argv = ["api", "graphql", *args]
    for _ in range(2):
        result = _run(env, *argv, extra={"ONEX_LANE": LANE})
        assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv, argv]
    assert _budget_spent(env) == 2
    assert [row[7] for row in _call_log_rows(env)] == ["fallback", "fallback"]


@pytest.mark.unit
def test_fallback_cache_key_includes_gh_repo(env: dict[str, str]) -> None:
    argv = ["pr", "list"]
    for repo in ("a/b", "c/d"):
        result = _run(env, *argv, extra={"ONEX_LANE": LANE, "GH_REPO": repo})
        assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv, argv]
    assert _budget_spent(env) == 2
    assert [row[7] for row in _call_log_rows(env)] == ["fallback", "fallback"]


@pytest.mark.unit
def test_non_lane_read_is_allowed_without_spending_budget(env: dict[str, str]) -> None:
    argv = ["pr", "list", "--repo", "o/r"]
    result = _run(env, *argv)
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 0
    assert [row[7] for row in _call_log_rows(env)] == ["allowed"]


# OMN-20911 (unenforced-rulings plan, unit W8): the read-strict switch. One line in
# gh-gateway.env, ONEX_GH_LANE_READ_STRICT=1, makes every lane read verb strict at once;
# it is OFF unless that line is there. It is flipped in its own change, on a recorded
# window in which every lane read verb was answered locally with zero fallback events.
STRICT_ALL = "ONEX_GH_LANE_READ_STRICT=1\n"


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["api", "user"],
        ["api", "repos/o/r/releases"],
        ["api", "graphql", "-f", "query={viewer{login}}"],
        ["pr", "list", "--repo", "o/r"],
        ["pr", "diff", "9", "--repo", "o/r"],
        ["run", "list", "--repo", "o/r"],
        ["repo", "view", "o/r"],
        ["issue", "list", "--repo", "o/r"],
        ["release", "list", "--repo", "o/r"],
        ["status"],
    ],
)
def test_strict_read_refused_for_every_lane_read_verb_when_the_switch_is_on(
    env: dict[str, str], argv: list[str]
) -> None:
    _configure(env, STRICT_ALL)
    refused = _run(env, *argv, extra={"ONEX_LANE": LANE})
    assert refused.returncode == 1, refused.stderr
    first = refused.stderr.splitlines()[0]
    assert first.startswith("REFUSED (OMN-20911): "), refused.stderr
    assert "is a GitHub read from a lane" in first
    assert first.endswith("This verb is strict in gh-gateway.env.")
    assert "pr_state_local.py --pr" in refused.stderr
    assert "canonical clones" in refused.stderr
    assert _calls(env) == []
    assert _budget_spent(env) == 0
    assert [(row[6], row[7]) for row in _call_log_rows(env)] == [("1", "refused")]


@pytest.mark.unit
def test_strict_read_refused_for_a_lane_pr_view_names_the_local_reader(
    env: dict[str, str],
) -> None:
    _configure(env, STRICT_ALL)
    refused = _run(env, "pr", "view", "9", "--repo", "o/r", extra={"ONEX_LANE": LANE})
    assert refused.returncode == 1, refused.stderr
    assert refused.stderr.startswith("REFUSED (OMN-19856): "), refused.stderr
    assert "pr_state_local.py --pr o/r#9" in refused.stderr
    assert "git -C $OMNI_HOME/r log|diff origin/dev..." in refused.stderr
    assert _calls(env) == []
    assert _budget_spent(env) == 0


@pytest.mark.unit
def test_strict_read_refused_is_off_unless_the_file_says_one(
    env: dict[str, str],
) -> None:
    """Positive control: the same reads fall back with no switch, or any value but 1."""
    argvs = []
    for n, body in enumerate(
        (None, "ONEX_GH_LANE_READ_STRICT=0\n", "ONEX_GH_LANE_READ_STRICT=yes\n")
    ):
        if body is not None:
            _configure(env, body)
        argvs.append(["pr", "list", "--repo", f"o/r{n}"])  # distinct: no cache hit
        result = _run(env, *argvs[-1], extra={"ONEX_LANE": LANE})
        assert result.returncode == 0, result.stderr
    assert _calls(env) == argvs
    assert [row[7] for row in _call_log_rows(env)] == ["fallback"] * 3


@pytest.mark.unit
def test_strict_read_refused_never_reads_the_switch_from_the_environment(
    env: dict[str, str],
) -> None:
    argv = ["pr", "list", "--repo", "o/r"]
    result = _run(
        env, *argv, extra={"ONEX_LANE": LANE, "ONEX_GH_LANE_READ_STRICT": "1"}
    )
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert [row[7] for row in _call_log_rows(env)] == ["fallback"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "create", "--title", "t", "--body", "b"],
        ["pr", "comment", "9", "--body", "hi"],
        ["api", "-X", "POST", "repos/o/r/issues/9/comments", "-f", "body=hi"],
        ["api", "rate_limit"],
    ],
)
def test_strict_read_refused_leaves_writes_and_rate_limit_alone(
    env: dict[str, str], argv: list[str]
) -> None:
    _configure(env, STRICT_ALL)
    result = _run(env, *argv, extra={"ONEX_LANE": LANE})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 0


@pytest.mark.unit
def test_strict_read_refused_does_not_refuse_the_gateway_shapes(
    env: dict[str, str],
) -> None:
    """A failing-job log is served by the budgeted gateway whatever the switch says."""
    _configure(env, STRICT_ALL)
    argv = ["api", "repos/o/r/actions/jobs/123/logs"]
    result = _run(env, *argv, extra={"ONEX_LANE": LANE})
    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert _budget_spent(env) == 1
