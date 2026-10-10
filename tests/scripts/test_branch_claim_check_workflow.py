# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Exercise the lab-check reader's actual Bash without contacting GitHub."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
CHECK_NAME = "branch-claim / work-ledger"
APP_SLUG = "onexbot-occ-writer"
HEAD_SHA = "a" * 40
CHECK_URL = "https://github.com/example/repo/runs/123"
LAB_STEP_NAME = "Read the lab branch-claim check for this head"


def _workflow(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text())


@pytest.fixture
def lab_step() -> dict[str, Any]:
    workflow = _workflow("branch-claim-check-reusable.yml")
    return next(
        step
        for step in workflow["jobs"]["branch-claim-check"]["steps"]
        if step["name"] == LAB_STEP_NAME
    )


def _check(
    outcome: str = "unclaimed",
    *,
    app: str = APP_SLUG,
    completed_at: str = "2026-10-07T12:00:00Z",
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "app": {"slug": app},
        "status": status,
        "completed_at": completed_at,
        "html_url": CHECK_URL,
        "output": {
            "summary": (
                f"branch-claim-outcome: {outcome} ticket=OMN-20708 holder=peer-lane "
                "window=2026-10-06T12:00:00Z..2026-10-07T12:00:00Z rows=3\n"
                "The lab node's cause and findings: holder=peer-lane."
            ),
        },
    }


@pytest.fixture
def run_lab_step(tmp_path: Path, lab_step: dict[str, Any]):
    if shutil.which("jq") is None:
        pytest.skip("jq is required to execute the workflow's Bash check reader")

    # Only gh is replaced: Bash, jq and the workflow script execute for real.
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "calls = Path(os.environ['FAKE_GH_CALLS'])\n"
        "with calls.open('a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "error = os.environ.get('FAKE_GH_ERROR')\n"
        "if error:\n"
        "    print(error, file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "print(os.environ['FAKE_GH_RESPONSE'])\n"
    )
    fake_gh.chmod(0o755)
    calls_path = tmp_path / "calls.jsonl"

    def run(
        runs: list[dict[str, Any]],
        mode: str = "record",
        *,
        api_error: str = "",
        pages: list[dict[str, Any]] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls_path.write_text("")
        response_pages = pages if pages is not None else [{"check_runs": runs}]
        env = {
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "test-token",
            "REPO": "example/repo",
            "HEAD_SHA": HEAD_SHA,
            "LAB_CHECK_NAME": CHECK_NAME,
            "LAB_CHECK_APP_SLUG": APP_SLUG,
            "LAB_CHECK_WAIT_SECONDS": "0",
            "MODE": mode,
            "FAKE_GH_CALLS": str(calls_path),
            "FAKE_GH_RESPONSE": "\n".join(json.dumps(p) for p in response_pages),
            "FAKE_GH_ERROR": api_error,
        }
        result = subprocess.run(
            ["bash", "-c", lab_step["run"]],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
        # A zero deadline permits exactly one request and never sleeps/retries.
        assert calls == [
            [
                "api",
                "--paginate",
                f"repos/example/repo/commits/{HEAD_SHA}/check-runs"
                "?check_name=branch-claim%20%2F%20work-ledger&filter=all&per_page=100",
            ],
        ]
        return result

    return run


def test_sources_gate_all_file_steps(lab_step: dict[str, Any]) -> None:
    assert lab_step["if"] == "inputs.claim_source == 'work-ledger'"
    workflow = _workflow("branch-claim-check-reusable.yml")
    steps = workflow["jobs"]["branch-claim-check"]["steps"]
    file_steps = {
        "Checkout the pull request head",
        "Set up Python 3.13",
        "Resolve the gate pin",
        "Fetch the resolution (omniclaude canonical source)",
        "Assert the branch-claim checkout is at the pin",
        "Resolve the private claim store repo",
        "Mint token for the private claim store repo",
        "Fetch the claim store and its rolls",
        "Resolve this branch against the claim store",
    }
    by_name = {step["name"]: step for step in steps}
    for name in file_steps:
        assert by_name[name]["if"].startswith("inputs.claim_source == 'file'")
    for name in (
        "Fetch the resolution (omniclaude canonical source)",
        "Assert the branch-claim checkout is at the pin",
    ):
        assert "&& github.repository != 'OmniNode-ai/omniclaude'" in by_name[name]["if"]


def test_lab_step_has_no_database_or_ledger_checkout(lab_step: dict[str, Any]) -> None:
    script = lab_step["run"]
    for forbidden in (
        "psql",
        "asyncpg",
        "psycopg",
        "postgres",
        "5436",
        "DATABASE_URL",
        "_DSN",
        "checkout",
        "ROLLING_WORK_LEDGER",
        ".branch-claim-store",
        "|| true",
        "2>/dev/null",
    ):
        assert forbidden.lower() not in script.lower()
    assert lab_step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "REPO": "${{ github.repository }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
        "LAB_CHECK_NAME": "${{ inputs.lab_check_name }}",
        "LAB_CHECK_APP_SLUG": "${{ inputs.lab_check_app_slug }}",
        "LAB_CHECK_WAIT_SECONDS": "${{ inputs.lab_check_wait_seconds }}",
        "MODE": "${{ inputs.mode }}",
    }


def test_input_defaults_and_permissions() -> None:
    reusable = _workflow("branch-claim-check-reusable.yml")
    # PyYAML's YAML 1.1 loader treats the unquoted Actions `on` key as True.
    inputs = reusable[True]["workflow_call"]["inputs"]
    for name, expected in (
        ("claim_source", "file"),
        ("lab_check_name", CHECK_NAME),
        ("lab_check_app_slug", APP_SLUG),
        ("lab_check_wait_seconds", 900),
    ):
        assert inputs[name]["default"] == expected
    assert inputs["lab_check_wait_seconds"]["type"] == "number"
    caller = _workflow("branch-claim-check.yml")
    assert caller["jobs"]["branch-claim-check"]["with"]["claim_source"] == "work-ledger"
    assert caller["jobs"]["branch-claim-check"]["secrets"] == "inherit"
    for workflow in (reusable, caller):
        assert workflow["permissions"]["checks"] == "read"
        assert workflow["permissions"]["contents"] == "read"


def test_unknown_source_fails(tmp_path: Path) -> None:
    workflow = _workflow("branch-claim-check-reusable.yml")
    step = next(
        s
        for s in workflow["jobs"]["branch-claim-check"]["steps"]
        if s["name"] == "Validate the claim source"
    )
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "CLAIM_SOURCE": "unknown-source"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert "unknown-source" in result.stdout
    assert "THE CHECK DID NOT RUN." in result.stdout


@pytest.mark.parametrize("mode", ["record", "refuse"])
@pytest.mark.parametrize(
    "runs",
    [
        [],
        [_check(app="github-actions")],
        [_check(app="another-app")],
        [_check(status="in_progress")],
    ],
    ids=["absent", "github-actions", "another-app", "pending"],
)
def test_no_completed_matching_run_fails(run_lab_step, runs, mode: str) -> None:
    result = run_lab_step(runs, mode)
    assert result.returncode == 1
    for required in (
        CHECK_NAME,
        APP_SLUG,
        HEAD_SHA,
        "0 seconds",
        "THE CHECK DID NOT RUN.",
    ):
        assert required in result.stdout
    assert "::error::" in result.stdout
    if runs and runs[0]["app"]["slug"] != APP_SLUG:
        assert "Ignored 1 check run(s)" in result.stdout


def test_api_failure_is_not_a_pass_and_stderr_is_preserved(run_lab_step) -> None:
    result = run_lab_step([], api_error="GitHub is unavailable")
    assert result.returncode == 1
    assert "GitHub is unavailable" in result.stderr
    assert "THE CHECK DID NOT RUN." in result.stdout


@pytest.mark.parametrize("mode", ["record", "refuse"])
@pytest.mark.parametrize(
    ("outcome", "refuse_exit", "annotation"),
    [
        ("did-not-run", 1, "::error::"),
        ("held-elsewhere", 1, "::warning::"),
        ("fence-behind", 1, "::warning::"),
        ("unidentified", 0, "::warning::"),
        ("held-by-pusher", 0, ""),
        ("unclaimed", 0, ""),
        ("no-ticket", 0, ""),
    ],
)
def test_outcomes_follow_mode(run_lab_step, outcome, refuse_exit, annotation, mode):
    check = _check(outcome)
    result = run_lab_step([check], mode)
    expected = refuse_exit if mode == "refuse" or outcome == "did-not-run" else 0
    assert result.returncode == expected
    assert CHECK_URL in result.stdout
    summary = check["output"]["summary"]
    assert summary.splitlines()[0] in result.stdout
    if annotation:
        assert annotation in result.stdout
        assert "holder=peer-lane" in result.stdout
        assert summary.splitlines()[1] in result.stdout
    if outcome == "did-not-run":
        assert (
            f"::error::{summary.splitlines()[1]} THE CHECK DID NOT RUN."
            in result.stdout
        )


@pytest.mark.parametrize(
    "summary",
    [
        "garbled first line\nbranch-claim-outcome: unclaimed ticket=OMN-20708",
        "branch-claim-outcome: unclaimed-extra ticket=OMN-20708",
        "branch-claim-outcome: unknown ticket=OMN-20708",
        "branch-claim-outcome: unclaimed",
        "",
    ],
)
def test_garbled_first_line_fails(run_lab_step, summary: str) -> None:
    check = _check()
    check["output"]["summary"] = summary
    result = run_lab_step([check])
    assert result.returncode == 1
    assert CHECK_URL in result.stdout
    assert summary.split("\n", 1)[0] in result.stdout
    assert "THE CHECK DID NOT RUN." in result.stdout


def test_latest_completed_trusted_run_wins_across_pages(run_lab_step) -> None:
    older = _check("did-not-run", completed_at="2026-10-07T11:00:00Z")
    newer = _check("unclaimed")
    unrelated = _check("did-not-run", app="github-actions")
    unrelated["completed_at"] = "2026-10-07T13:00:00Z"
    pending = _check("held-elsewhere", status="in_progress")
    pending["completed_at"] = None
    result = run_lab_step(
        [],
        "refuse",
        pages=[{"check_runs": [newer, unrelated, pending]}, {"check_runs": [older]}],
    )
    assert result.returncode == 0
    assert "branch-claim-outcome: unclaimed " in result.stdout
    assert "branch-claim-outcome: did-not-run " not in result.stdout
    assert "Ignored 1 check run(s)" in result.stdout


def test_gate_collects_workflow_tests() -> None:
    gate = _workflow("branch-claim-gate.yml")
    test_path = "tests/scripts/test_branch_claim_check_workflow.py"
    for event in ("push", "pull_request"):
        assert test_path in gate[True][event]["paths"]
    commands = [
        step.get("run", "") for step in gate["jobs"]["branch-claim-gate"]["steps"]
    ]
    assert any(
        test_path in command and "uv run pytest" in command for command in commands
    )
