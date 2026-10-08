# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18782: exercise citation admission through the existing Git handler."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from omniclaude.nodes.node_git_effect.handlers.handler_git_subprocess import (
    HandlerGitSubprocess,
    pr_failure_citation_errors,
)
from omniclaude.nodes.node_git_effect.models import ModelGitRequest, ModelGitResult

ROOT = Path(__file__).resolve().parents[4]
RUN = "https://github.com/OmniNode-ai/omniclaude/actions/runs/123456"
pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["pr_create", "pr_update"])
async def test_bare_failure_is_refused_before_gh(operation: str) -> None:
    handler = HandlerGitSubprocess()
    handler._run_gh = AsyncMock(
        return_value=ModelGitResult(operation=operation, status="success")
    )
    paragraph = "The test failure is pre-existing and unrelated to this change."
    request = ModelGitRequest(
        operation=operation,
        pr_title="fix: citation admission (OMN-18782)",
        pr_number=42,
        pr_body="Summary.\n\n" + paragraph,
        ticket_id="OMN-18782",
        base_branch="dev",
    )
    result = await getattr(handler, operation)(request)
    assert result.status == "failed"
    assert paragraph in result.error
    handler._run_gh.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_credential_is_admitted() -> None:
    handler = HandlerGitSubprocess()
    handler._run_gh = AsyncMock(
        return_value=ModelGitResult(operation="pr_create", status="success")
    )
    result = await handler.pr_create(
        ModelGitRequest(
            operation="pr_create",
            pr_title="fix: citation admission (OMN-18782)",
            pr_body="A credential unrelated to the PR.",
            base_branch="dev",
        )
    )
    assert result.status == "success"
    handler._run_gh.assert_awaited_once()


@pytest.mark.parametrize(
    "body",
    [
        "Pre-existing failure.",
        "PREEXISTING test FAILED.",
        "The errors are unrelated to this PR.",
        "The CI is red for unrelated reasons.",
        "Failure is pre-existing; same result on the base, trust me.",
        "Pre-existing failure; will bisect later.",
        "Pre-existing failure; bisect investigation ongoing.",
        "Pre-existing failure.\n\n" + RUN,
        "Ticket OMN-18782.\n\nPre-existing failure.",
        "Pre-existing failure.\n\n> " + RUN,
        "Pre-existing failure.\n```\n" + RUN + "\n```",
        "Pre-existing failure. <!-- " + RUN + " -->",
        "Pre-existing failure. https://github.com/OmniNode-ai/omniclaude/pull/42",
        "Pre-existing failure. https://example.com/actions/runs/123",
        "Pre-existing failure. https://github.com/OmniNode-ai/omniclaude/actions/runs/abc",
    ],
)
def test_uncited_claims_and_unrelated_citations_fail(body: str) -> None:
    assert pr_failure_citation_errors(body)


@pytest.mark.parametrize(
    "body",
    [
        "Pre-existing failure: base dev-tip run " + RUN,
        "Pre-existing failure: [base run](" + RUN + ").",
        "Unrelated error, tracked specifically in OMN-18782.",
        "Pre-existing failure: git bisect identified abc1234 as first bad commit.",
        "Pre-existing failure: bisected to abc1234.",
        "A credential unrelated to the PR.",
        "Added unrelated tests for a different component.",
        "An unrelated red button changes color.",
        "Pre-existing regression tests were extended.",
        "We fixed a failure.",
        "```text\nPre-existing failure.\n```",
        "> Pre-existing failure.",
        "<!-- Pre-existing failure. -->",
        "",
    ],
)
def test_citations_and_non_failure_claims_pass(body: str) -> None:
    assert not pr_failure_citation_errors(body)


def test_every_offender_is_named_despite_other_substantiated_paragraphs() -> None:
    paragraphs = [
        "First pre-existing failure.",
        "Second unrelated error.",
    ]
    errors = pr_failure_citation_errors(
        "Pre-existing failure " + RUN + "\n\n" + "\n\n".join(paragraphs)
    )
    assert len(errors) == 2
    for paragraph, error in zip(paragraphs, errors, strict=True):
        assert paragraph in error


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["pr_create", "pr_update"])
async def test_cited_failure_reaches_existing_gh_backend(operation: str) -> None:
    handler = HandlerGitSubprocess()
    handler._run_gh = AsyncMock(
        return_value=ModelGitResult(operation=operation, status="success")
    )
    request = ModelGitRequest(
        operation=operation,
        pr_title="fix: citation admission (OMN-18782)",
        pr_number=42,
        pr_body="Pre-existing failure: dev-tip run " + RUN,
        ticket_id="OMN-18782",
        base_branch="dev",
    )
    result = await getattr(handler, operation)(request)
    assert result.status == "success"
    handler._run_gh.assert_awaited_once()


def run_gate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/lint_verification_evidence.py"),
            "--pr-body",
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ci_event_red_green_and_malformed_input(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    paragraph = "Pre-existing test failure, unrelated to this change."
    event.write_text(json.dumps({"pull_request": {"body": paragraph}}))
    result = run_gate("--github-event", str(event), "--event-name", "pull_request")
    assert result.returncode == 1
    assert paragraph in result.stderr
    event.write_text(json.dumps({"pull_request": {"body": paragraph + " " + RUN}}))
    result = run_gate("--github-event", str(event), "--event-name", "pull_request")
    assert result.returncode == 0
    assert "1 bodies evaluated" in result.stdout
    event.write_text("{}")
    result = run_gate("--github-event", str(event), "--event-name", "pull_request")
    assert result.returncode == 2
    assert "pull_request.body" in result.stderr
    event.write_text("not json")
    result = run_gate("--github-event", str(event), "--event-name", "pull_request")
    assert result.returncode == 2
    assert "cannot evaluate input" in result.stderr


def test_precommit_body_file_uses_same_gate(tmp_path: Path) -> None:
    body = tmp_path / "PR_BODY.md"
    body.write_text("Pre-existing failure.")
    result = run_gate("--body-files", str(body))
    assert result.returncode == 1
    assert "Pre-existing failure." in result.stderr
    body.write_text("A credential unrelated to the PR.")
    result = run_gate("--body-files", str(body))
    assert result.returncode == 0
    assert "1 bodies evaluated" in result.stdout
    result = run_gate("--body-files", str(tmp_path / "missing.md"))
    assert result.returncode == 2
    assert "cannot evaluate input" in result.stderr


def test_ci_and_precommit_enforcement_wiring() -> None:
    import yaml

    from scripts.ci.ci_summary_gate import GATE_JOBS, STRICT_SUCCESS_JOBS

    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = ci["jobs"]["pr-failure-citations"]
    assert job["name"] in GATE_JOBS
    assert job["name"] in STRICT_SUCCESS_JOBS
    assert "needs" not in job and "if" not in job
    triggers = ci.get("on", ci.get(True))
    assert "edited" in triggers["pull_request"]["types"]
    assert "--github-event" in job["steps"][-1]["run"]
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        hook
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook["id"] == "pr-failure-citations"
    )
    assert (
        "scripts/lint_verification_evidence.py --pr-body --body-files" in hook["entry"]
    )
    assert "pre-commit" in hook["stages"]
