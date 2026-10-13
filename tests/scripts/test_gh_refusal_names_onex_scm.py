# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20913: every gh read the shim refuses from a lane names its `onex scm` verb.

The PR-state guard (OMN-19856) and the strict lane read guard (OMN-20911) refuse a read
and point at local readers. This pins the line they now add, ``Use instead: onex scm
<verb> ...``, for each refused read shape, and that a read no verb serves says so rather
than naming a verb that does not exist.

Each test puts a scripted fake ``gh`` behind the user shim. No test uses the network or
an operator credential.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from tests.scripts.conftest import install_ancestry_ps

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"

FAKE_GH = r"""#!/bin/bash
printf '%s' "${FAKE_GH_STDOUT:-ok}"
exit "${FAKE_GH_RC:-0}"
"""

SHA = "0123456789abcdef0123456789abcdef01234567"
STRICT_ALL_CONF = "ONEX_GH_LANE_READ_STRICT=1\n"
NO_VERB = "No onex scm verb serves this read yet"


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    fake_dir = tmp_path / "realbin"
    fake_dir.mkdir()
    _write_exec(fake_dir / "gh", FAKE_GH)
    install_ancestry_ps(fake_dir)
    conf = tmp_path / "config" / "omni" / "gh-gateway.env"
    conf.parent.mkdir(parents=True)
    conf.write_text(STRICT_ALL_CONF)
    return {
        "PATH": f"{SHIM.parent}:{fake_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "ONEX_GH_CALLS_LOG": str(tmp_path / "gh-calls.log"),
        "ONEX_LANDING_CONTROLLER_ROOT": str(tmp_path / "controller"),
        "ONEX_LANE": "names-the-verb",
        "GIT_CONFIG_NOSYSTEM": "1",
        "ONEX_GH_READ_ROUTING": "0",
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _use_instead(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 1, result.stderr
    lines = [ln for ln in result.stderr.splitlines() if ln.startswith("Use instead:")]
    assert len(lines) == 1, result.stderr
    return lines[0]


def _argv_id(value: object) -> str | None:
    return " ".join(value)[:60] if isinstance(value, list) else None


# (argv, the replacement the refusal must name). The first group is refused by the
# PR-state guard (OMN-19856), the second by the strict lane read guard (OMN-20911).
PR_STATE_READS = [
    (["pr", "view", "5", "--repo", "o/r", "--json", "title"], "onex scm pr-view o/r#5"),
    (["pr", "checks", "5", "--repo", "o/r"], "onex scm pr-checks o/r#5"),
    (["run", "view", "9", "--repo", "o/r"], "onex scm run-view o/r --run-id"),
    (["api", "repos/o/r/pulls/5"], "onex scm pr-view o/r#5"),
    (["api", "repos/o/r/pulls/5/commits"], "onex scm pr-commits o/r#5"),
    (["api", "repos/o/r/pulls/5/reviews"], "onex scm pr-review o/r#5"),
    (["api", "repos/o/r/pulls"], "onex scm pr-list o/r"),
    (
        ["api", f"repos/o/r/commits/{SHA}/check-runs"],
        "onex scm commit-checks o/r --sha",
    ),
    (["api", f"repos/o/r/commits/{SHA}/status"], "onex scm commit-checks o/r --sha"),
    (
        ["api", f"repos/o/r/commits/{SHA}/check-suites"],
        "onex scm commit-checks o/r --sha",
    ),
    (["api", "repos/o/r/actions/runs"], "onex scm run-list o/r"),
    (["api", "repos/o/r/actions/runs/7"], "onex scm run-view o/r --run-id"),
    (["api", "repos/o/r/actions/runs/7/jobs"], "onex scm run-view o/r --run-id"),
]
LANE_READS = [
    (["api", "repos/o/r/contents/a/b.py"], "onex scm file-read o/r --path"),
    (["api", "repos/o/r/commits/abc"], "onex scm commit-view o/r --ref"),
    (["api", "repos/o/r/artifacts"], NO_VERB),
    (["api", "repos/o/r/actions/artifacts"], "onex scm run-download o/r --run-id"),
    (["api", "repos/o/r/branches/dev/protection"], "onex scm branch-protection o/r"),
    (["api", "repos/o/r/releases"], "onex scm release-list o/r"),
    (["pr", "list", "--repo", "o/r"], "onex scm pr-list o/r"),
    (["pr", "diff", "9", "--repo", "o/r"], "onex scm pr-commits o/r#9"),
    (["run", "list", "--repo", "o/r"], "onex scm run-list o/r"),
    (["run", "download", "123", "--repo", "o/r"], "onex scm run-download o/r"),
    (["release", "list", "--repo", "o/r"], "onex scm release-list o/r"),
    (["repo", "view", "o/r"], NO_VERB),
    (["issue", "view", "9", "--repo", "o/r"], NO_VERB),
    (["workflow", "list", "--repo", "o/r"], NO_VERB),
    (["api", "graphql", "-f", "query={viewer{login}}"], NO_VERB),
]


@pytest.mark.unit
@pytest.mark.parametrize(("argv", "replacement"), PR_STATE_READS, ids=_argv_id)
def test_pr_state_refusal_names_the_onex_scm_verb(
    env: dict[str, str], argv: list[str], replacement: str
) -> None:
    result = _run(env, *argv)
    assert result.stderr.startswith("REFUSED (OMN-19856): "), result.stderr
    assert replacement in _use_instead(result)


@pytest.mark.unit
@pytest.mark.parametrize(("argv", "replacement"), LANE_READS, ids=_argv_id)
def test_strict_lane_read_refusal_names_the_onex_scm_verb(
    env: dict[str, str], argv: list[str], replacement: str
) -> None:
    result = _run(env, *argv)
    assert result.stderr.startswith("REFUSED (OMN-20911): "), result.stderr
    line = _use_instead(result) if replacement != NO_VERB else None
    if line is not None:
        assert replacement in line
    else:
        assert replacement in result.stderr
        assert "Use instead:" not in result.stderr


@pytest.mark.unit
def test_the_line_comes_before_the_local_readers_and_keeps_them(
    env: dict[str, str],
) -> None:
    result = _run(env, "pr", "list", "--repo", "o/r")
    lines = result.stderr.splitlines()
    use = next(i for i, ln in enumerate(lines) if ln.startswith("Use instead:"))
    local = next(i for i, ln in enumerate(lines) if ln == "Read it locally instead:")
    assert use < local
    assert any("pr_state_local.py --pr" in ln for ln in lines)
    assert "onex scm verbs" in lines[use]


@pytest.mark.unit
def test_the_exact_head_check_is_still_allowed_and_prints_no_refusal(
    env: dict[str, str],
) -> None:
    # Positive control: a call the guard allows prints neither refusal nor the new line.
    result = _run(
        {**env, "ONEX_GH_EXACT_HEAD": "o/r#5"},
        "pr",
        "view",
        "5",
        "--repo",
        "o/r",
        "--json",
        "headRefOid",
    )
    assert result.returncode == 0, result.stderr
    assert "Use instead:" not in result.stderr
