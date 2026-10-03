# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19852: guard GitHub's secondary-rate-limited search API bucket.

Each test puts a scripted fake ``gh`` behind the user shim. No test uses the
network or an operator credential.
"""

from __future__ import annotations

import json
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-ok}"
exit "${FAKE_GH_RC:-0}"
"""

QUEUE_RULES = json.dumps([{"type": "merge_queue", "parameters": {}}])
NO_QUEUE_RULES = json.dumps([{"type": "required_status_checks", "parameters": {}}])


def _write_exec(path: Path, body: str) -> None:
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


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["api", "search/issues?q=is:open"],
        ["api", "/search/code"],
        ["api", "-X", "GET", "/search/code"],
        ["api", "https://api.github.com/search/issues?q=is:open"],
    ],
)
def test_api_search_is_refused_without_calling_real_gh(
    env: dict[str, str], argv: list[str]
) -> None:
    result = _run(env, *argv)

    assert result.returncode == 1
    assert _calls(env) == []
    assert "secondary-rate-limited bucket" in result.stderr
    assert "21:5xZ on 2026-09-28" in result.stderr
    assert "state.json" in result.stderr
    assert "pr_state_local.py" in result.stderr
    assert "git -C <canonical clone> log origin/dev" in result.stderr


@pytest.mark.unit
def test_search_group_is_refused_without_calling_real_gh(
    env: dict[str, str],
) -> None:
    result = _run(env, "search", "prs", "is:open")

    assert result.returncode == 1
    assert _calls(env) == []
    assert "state.json" in result.stderr
    assert "pr_state_local.py" in result.stderr


@pytest.mark.unit
def test_watcher_marker_allows_search_with_identical_argv(
    env: dict[str, str],
) -> None:
    argv = ["api", "-i", "search/issues?q=x&per_page=100"]
    result = _run(env, *argv, extra={"ONEX_PR_WATCHER": "1"})

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["api", "repos/o/r/issues"],
        ["api", "graphql", "-f", "query={viewer{login}}"],
        ["pr", "view", "1", "--json", "url"],
    ],
)
def test_non_search_reads_are_unaffected(env: dict[str, str], argv: list[str]) -> None:
    result = _run(env, *argv)

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
@pytest.mark.parametrize("rules", [QUEUE_RULES, NO_QUEUE_RULES])
def test_exact_head_pr_merge_is_unaffected(env: dict[str, str], rules: str) -> None:
    argv = [
        "pr",
        "merge",
        "9",
        "--repo",
        "o/r",
        "--squash",
        "--match-head-commit",
        "deadbeef",
    ]
    result = _run(env, *argv, extra={"FAKE_RULES": rules})

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]


@pytest.mark.unit
def test_shared_log_has_exact_shape_and_no_query_or_argv_leakage(
    env: dict[str, str], tmp_path: Path
) -> None:
    log = tmp_path / "state" / "gh-calls.log"
    token = "ghp_DO_NOT_LOG_THIS_SENTINEL"
    common = {"ONEX_GH_CALLS_LOG": str(log), "ONEX_LANE": "gh-reads-2203"}
    allowed = _run(
        env,
        "api",
        f"search/issues?q={token}&per_page=100",
        extra={**common, "ONEX_PR_WATCHER": "1", "GH_TOKEN": token},
    )
    refused = _run(
        env,
        "api",
        f"search/issues?q={token}&per_page=100",
        extra={**common, "GH_TOKEN": token},
    )

    assert allowed.returncode == 0
    assert refused.returncode == 1
    raw = log.read_text()
    rows = [line.split("\t") for line in raw.splitlines()]
    assert len(rows) == 2
    assert all(len(row) == 8 for row in rows)
    assert all(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", row[0]) for row in rows
    )
    assert rows[0][1:] == [
        "gh-reads-2203",
        "env",
        "api",
        "GET",
        "search/issues",
        "0",
        "allowed",
    ]
    assert rows[1][1:] == [
        "gh-reads-2203",
        "env",
        "api",
        "GET",
        "search/issues",
        "1",
        "refused",
    ]
    assert token not in raw
    assert "per_page" not in raw
    assert "ONEX_PR_WATCHER" not in raw


@pytest.mark.unit
def test_shared_log_is_skipped_without_resolvable_state_dir(
    env: dict[str, str], tmp_path: Path
) -> None:
    result = _run(env, "api", "repos/o/r/issues")

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.rglob("gh-calls.log")) == []


@pytest.mark.unit
def test_unwritable_log_location_never_fails_gh_call(
    env: dict[str, str], tmp_path: Path
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied")
    result = _run(
        env,
        "api",
        "repos/o/r/issues",
        extra={"ONEX_GH_CALLS_LOG": str(blocked_parent / "gh-calls.log")},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"
    assert _calls(env) == [["api", "repos/o/r/issues"]]
