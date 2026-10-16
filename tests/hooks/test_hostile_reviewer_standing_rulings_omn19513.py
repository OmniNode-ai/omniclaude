# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19513: the Hostile Reviewer reads standing rulings from the base commit.

The reviewer sees only the diff, so it cannot know a standing operator ruling.
On omniclaude#2798 both voters blocked, by quorum, the passthrough publish
transform that RULING 2026-10-15T04:24:42Z mandates for ``content.captured``
and ``hook.event``. The workflow now prepends
``.github/hostile-review/standing-rulings.md`` to the reviewer's system prompt.

The file is read from the pull request's BASE commit. Read from the head, a
pull request could write the context that reviews it. The behavioural tests
run the step's own script against a real git remote whose head commit rewrites
the file, and assert the base content is the one handed to the reviewer.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hostile-reviewer.yml"
RULINGS_PATH = ".github/hostile-review/standing-rulings.md"
RULINGS_STEP_ID = "rulings"


@pytest.fixture(scope="module")
def review_job() -> dict[object, object]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    job = loaded["jobs"]["hostile-review"]
    assert isinstance(job, dict)
    return job


def _steps(job: dict[object, object]) -> list[dict[object, object]]:
    steps = job.get("steps") or []
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _step(job: dict[object, object], step_id: str) -> dict[object, object]:
    found = next((s for s in _steps(job) if s.get("id") == step_id), None)
    assert found is not None, f"step id={step_id!r} missing from hostile-review"
    return found


def _git(cwd: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    return completed.stdout.strip()


def _commit(repo: pathlib.Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-q",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def _run_rulings_step(
    review_job: dict[object, object],
    tmp_path: pathlib.Path,
    *,
    base_has_file: bool,
) -> tuple[dict[str, str], pathlib.Path]:
    """Run the step's script in a clone whose head rewrites the rulings file."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q")
    _git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    rulings = origin / RULINGS_PATH
    if base_has_file:
        rulings.parent.mkdir(parents=True)
        rulings.write_text("BASE RULINGS\n", encoding="utf-8")
    (origin / "README.md").write_text("base\n", encoding="utf-8")
    base_sha = _commit(origin, "base")
    rulings.parent.mkdir(parents=True, exist_ok=True)
    rulings.write_text("HEAD INJECTED RULINGS\n", encoding="utf-8")
    _commit(origin, "head")

    workspace = tmp_path / "workspace"
    subprocess.run(
        ["git", "clone", "-q", "--depth=1", origin.as_uri(), str(workspace)],
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    assert (workspace / RULINGS_PATH).read_text(encoding="utf-8") == (
        "HEAD INJECTED RULINGS\n"
    ), "the clone must stand at the head that rewrites the file"

    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    github_output = tmp_path / "github-output"
    github_output.touch()
    step = _step(review_job, RULINGS_STEP_ID)
    step_env = step.get("env")
    assert isinstance(step_env, dict)
    env = {
        **scrub_git_location_env(os.environ),
        "BASE_SHA": base_sha,
        "RULINGS_PATH": str(step_env["RULINGS_PATH"]),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_OUTPUT": str(github_output),
    }
    subprocess.run(
        ["bash", "-c", str(step["run"])],
        cwd=workspace,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    outputs = dict(
        line.split("=", 1)
        for line in github_output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    return outputs, runner_temp


@pytest.mark.unit
def test_the_rulings_step_reads_the_base_commit_not_the_head(
    review_job: dict[object, object], tmp_path: pathlib.Path
) -> None:
    outputs, _ = _run_rulings_step(review_job, tmp_path, base_has_file=True)
    path = outputs.get("path", "")
    assert path, "a base carrying the rulings file must hand its path on"
    assert pathlib.Path(path).read_text(encoding="utf-8") == "BASE RULINGS\n", (
        "the reviewer must get the base commit's rulings, never the head's: a "
        "pull request must not write the context that reviews it"
    )


@pytest.mark.unit
def test_a_base_without_the_file_runs_the_reviewer_unchanged(
    review_job: dict[object, object], tmp_path: pathlib.Path
) -> None:
    outputs, runner_temp = _run_rulings_step(review_job, tmp_path, base_has_file=False)
    assert outputs.get("path") == "", (
        "a base without the file must hand on no path, even when the head adds one"
    )
    assert list(runner_temp.iterdir()) == []


@pytest.mark.unit
def test_the_step_reads_the_committed_file_from_the_pull_request_base(
    review_job: dict[object, object],
) -> None:
    ids = [step.get("id") for step in _steps(review_job)]
    assert RULINGS_STEP_ID in ids
    assert ids.index(RULINGS_STEP_ID) < ids.index("review")
    step = _step(review_job, RULINGS_STEP_ID)
    env = step.get("env")
    assert isinstance(env, dict)
    assert env["RULINGS_PATH"] == RULINGS_PATH
    assert env["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert "continue-on-error" not in step


@pytest.mark.unit
def test_the_review_passes_the_rulings_as_a_system_prompt_prefix(
    review_job: dict[object, object],
) -> None:
    step = _step(review_job, "review")
    env = step.get("env")
    assert isinstance(env, dict)
    assert env["STANDING_RULINGS"] == "${{ steps.rulings.outputs.path }}"
    run_text = str(step.get("run", ""))
    assert 'RULINGS_ARGS=(--system-prompt "$STANDING_RULINGS")' in run_text
    invocation = run_text[
        run_text.index("omniintelligence.review_pairing.cli_review") :
    ]
    invocation = invocation[: invocation.index('2>"$ATTEMPT_ERR")')]
    assert '"${RULINGS_ARGS[@]}"' in invocation


@pytest.mark.unit
def test_the_rulings_file_states_the_raw_capture_ruling() -> None:
    text = (REPO_ROOT / RULINGS_PATH).read_text(encoding="utf-8")
    for needle in (
        "RULING 2026-10-15T04:24:42Z",
        "`content.captured`",
        "`hook.event`",
        "onex.cmd.omniintelligence.content-captured.v1",
        "onex.evt.omniclaude.hook-event.v1",
        "Still report:",
    ):
        assert needle in text, needle
