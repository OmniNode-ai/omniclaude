# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22447: a CI job on a lab runner reads its own PR body through the gh shim.

Recorded case: deploy-gate, job 126037381765 (PR 2013 of the cloud repo, runner
``h203-light-4``, 2026-11-03T16:05Z). The step ran ``gh pr view "${PR_NUMBER}"
--json body -q '.body'`` with ``GITHUB_ACTIONS=true`` and a shim answered
``REFUSED (OMN-19856)``. The current shim execs the real gh for exactly
``GITHUB_ACTIONS=true`` (OMN-19856 pass-through), so the shim on that PATH was a
copy that predates the pass-through. The log lines are stored in
``tests/scripts/fixtures/ci_runner_shim_job_126037381765.txt``.

Select with ``-k ci_runner_shim``. No test touches the network.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"
ROUTER = REPO_ROOT / "scripts" / "user-bin" / "gh_route.py"
INSTALLER = REPO_ROOT / "scripts" / "user-bin" / "install-gh-shim.sh"
FIXTURE = Path(__file__).parent / "fixtures" / "ci_runner_shim_job_126037381765.txt"

PASSTHROUGH_LINE = 'if [ "${GITHUB_ACTIONS:-}" = "true" ]; then'

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf 'PR body from the real gh'
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _pre_passthrough_shim() -> str:
    """The current shim with the OMN-19856 CI pass-through removed: the broken shape."""
    lines = SHIM.read_text().splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.strip() == PASSTHROUGH_LINE)
    assert lines[start + 1].strip() == 'exec "$real" "$@"'
    assert lines[start + 2].strip() == "fi"
    return "".join(lines[:start] + lines[start + 3 :])


def _recorded_gate_call() -> tuple[str, str]:
    """(shell command, PR number) the deploy-gate step ran, read from the recorded log."""
    log = FIXTURE.read_text()
    command = re.search(r"if ! (gh pr view .+?) >", log)
    assert command, "the recorded log must carry the deploy-gate gh pr view line"
    number = re.search(r"^\S+\s+PR_NUMBER: (\d+)$", log, re.MULTILINE)
    assert number, "the recorded log must carry the step's PR_NUMBER"
    return command.group(1), number.group(1)


def _recorded_refusal() -> str:
    """The refusal sentence the runner printed, up to its ruling citation."""
    line = next(
        row for row in FIXTURE.read_text().splitlines() if "REFUSED (OMN-19856)" in row
    )
    return line.split("Z ", 1)[1].split(" (RULING", 1)[0]


@pytest.fixture
def runner(tmp_path: Path) -> dict[str, object]:
    home = tmp_path / "runner-home"
    realbin = tmp_path / "usr-local-bin"
    _write_exec(realbin / "gh", FAKE_GH)
    (tmp_path / "work").mkdir()
    return {
        "home": home,
        "realbin": realbin,
        "work": tmp_path / "work",
        "log": tmp_path / "calls.jsonl",
        "tmp": tmp_path,
    }


def _env(runner: dict[str, object], path_dirs: list[Path]) -> dict[str, str]:
    return {
        "PATH": ":".join([*(str(d) for d in path_dirs), "/usr/bin", "/bin"]),
        "HOME": str(runner["home"]),
        "FAKE_GH_LOG": str(runner["log"]),
        "XDG_CACHE_HOME": str(Path(str(runner["tmp"])) / "cache"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def _install(env: dict[str, str], runner: dict[str, object], *args: str):
    return subprocess.run(
        ["/bin/bash", str(INSTALLER), *args],
        cwd=str(runner["work"]),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _gate_step(
    env: dict[str, str], runner: dict[str, object], github_actions: str | None
) -> subprocess.CompletedProcess[str]:
    """The recorded step: bash -e, GH_TOKEN and PR_NUMBER in env, the recorded call."""
    command, number = _recorded_gate_call()
    e = dict(env)
    e["GH_TOKEN"] = "x"
    e["PR_NUMBER"] = number
    if github_actions is not None:
        e["GITHUB_ACTIONS"] = github_actions
    return subprocess.run(
        ["/usr/bin/bash", "-e", "-c", command],
        cwd=str(runner["work"]),
        env=e,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _real_calls(runner: dict[str, object]) -> list[list[str]]:
    log = Path(str(runner["log"]))
    if not log.exists():
        return []
    return [json.loads(row) for row in log.read_text().splitlines()]


STALE_PLACES = ["legacy-home-local-bin", "runner-bin-dir", "second-path-entry"]


def _place_stale_copy(runner: dict[str, object], place: str) -> tuple[Path, list[Path]]:
    """Put a pre-pass-through shim where a runner's job PATH reaches it first."""
    home = Path(str(runner["home"]))
    realbin = Path(str(runner["realbin"]))
    tmp = Path(str(runner["tmp"]))
    if place == "legacy-home-local-bin":
        directory = home / ".local" / "bin"
        path_dirs = [directory, realbin]
    elif place == "runner-bin-dir":
        directory = tmp / "actions-runner-4" / "bin"
        path_dirs = [directory, home / ".local" / "bin", realbin]
    else:
        directory = tmp / "opt-ci-tools"
        path_dirs = [home / ".local" / "bin", directory, realbin]
    _write_exec(directory / "gh", _pre_passthrough_shim())
    (directory / "gh_route.py").write_text("stale router\n")
    return directory / "gh", path_dirs


@pytest.mark.unit
def test_ci_runner_shim_fixture_is_the_recorded_job() -> None:
    log = FIXTURE.read_text()
    assert "Runner name: 'h203-light-4'" in log
    assert "Runner group name: 'omnibase-ci'" in log
    assert "GH_TOKEN: ***" in log
    assert "PR-METADATA READ FAILED -- could not read the body of PR #2013" in log
    command, number = _recorded_gate_call()
    assert command == """gh pr view "${PR_NUMBER}" --json body -q '.body'"""
    assert number == "2013"
    assert _recorded_refusal() == (
        "REFUSED (OMN-19856): gh pr view is a PR-state read; GitHub is for "
        "mutations and the declared exact-head check only"
    )


@pytest.mark.unit
def test_ci_runner_shim_broken_shape_reproduces_the_recorded_refusal(
    runner: dict[str, object],
) -> None:
    """RED shape: a shim copy without the pass-through refuses the CI job's own read."""
    assert PASSTHROUGH_LINE not in _pre_passthrough_shim()
    _, path_dirs = _place_stale_copy(runner, "legacy-home-local-bin")
    result = _gate_step(_env(runner, path_dirs), runner, "true")
    assert result.returncode != 0
    assert _recorded_refusal() in result.stdout + result.stderr
    assert _real_calls(runner) == []


@pytest.mark.unit
@pytest.mark.parametrize("place", STALE_PLACES)
def test_ci_runner_shim_install_makes_the_recorded_gate_step_read_its_body(
    runner: dict[str, object], place: str
) -> None:
    """GREEN: after the install the recorded step reads the body through the real gh."""
    stale, path_dirs = _place_stale_copy(runner, place)
    env = _env(runner, path_dirs)
    installed = _install(env, runner)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    result = _gate_step(env, runner, "true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "PR body from the real gh"
    assert _real_calls(runner) == [
        ["pr", "view", "2013", "--json", "body", "-q", ".body"]
    ]
    if stale.exists():
        assert PASSTHROUGH_LINE in stale.read_text()
    checked = _install(env, runner, "--check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "STALE" not in checked.stderr


@pytest.mark.unit
@pytest.mark.parametrize("place", STALE_PLACES)
def test_ci_runner_shim_check_names_a_stale_copy(
    runner: dict[str, object], place: str
) -> None:
    stale, path_dirs = _place_stale_copy(runner, place)
    env = _env(runner, path_dirs)
    before = stale.read_bytes()
    checked = _install(env, runner, "--check")
    assert checked.returncode == 4, checked.stdout + checked.stderr
    assert f"STALE: {stale} " in checked.stderr
    assert stale.read_bytes() == before


@pytest.mark.unit
def test_ci_runner_shim_refresh_keeps_the_guard_for_every_value_but_true(
    runner: dict[str, object],
) -> None:
    """AC2: a refreshed copy passes through for exactly true and refuses the rest."""
    _, path_dirs = _place_stale_copy(runner, "runner-bin-dir")
    env = _env(runner, path_dirs)
    assert _install(env, runner).returncode == 0
    for value in ("false", "1", "TRUE", "True", " true", "true ", "yes", "", None):
        result = _gate_step(env, runner, value)
        assert result.returncode != 0, f"GITHUB_ACTIONS={value!r} passed through"
        assert _recorded_refusal() in result.stdout + result.stderr
    assert _real_calls(runner) == []
    passed = _gate_step(env, runner, "true")
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert len(_real_calls(runner)) == 1


@pytest.mark.unit
def test_ci_runner_shim_refresh_does_not_touch_a_foreign_gh_or_a_current_copy(
    runner: dict[str, object],
) -> None:
    tmp = Path(str(runner["tmp"]))
    foreign = tmp / "foreign-bin"
    _write_exec(foreign / "gh", "#!/bin/bash\necho mine\n")
    current = tmp / "current-bin"
    _write_exec(current / "gh", SHIM.read_text())
    realbin = Path(str(runner["realbin"]))
    env = _env(runner, [foreign, current, realbin])
    installed = _install(env, runner)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert (foreign / "gh").read_text() == "#!/bin/bash\necho mine\n"
    assert (current / "gh").read_text() == SHIM.read_text()
    assert "refreshed" not in installed.stdout
    assert os.access(
        Path(str(runner["home"])) / ".local/share/omni/lane-bin/gh", os.X_OK
    )
