# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A lane's bare gh, when the real binary is first on PATH (OMN-22539)."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_lane_github_read_guard_effect.enums import (
    EnumLaneGithubReadShape,
    EnumLaneGithubReadVerdict,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.handlers.handler_lane_github_read_guard import (
    HandlerLaneGithubReadGuard,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.models import (
    ModelLaneGithubReadRequest,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.runtime_lane_github_read import (
    build_request,
)

pytestmark = pytest.mark.unit

SHIM = "/fixture/lane-bin/gh"
REAL = "/fixture/homebrew/gh"
_ROUTES = build_request({}, {}, "/work")


class _Probe:
    def is_gh_shim(self, path: str) -> bool:
        return path == SHIM


def _decide(
    command: str, *, gh_on_path: str = REAL, agent_id: str = "a1", **facts: object
):
    request = ModelLaneGithubReadRequest.model_validate(
        {
            "tool_name": "Bash",
            "command": command,
            "entrypoint": "cli",
            "gh_on_path": gh_on_path,
            "gh_routes": _ROUTES.gh_routes,
            "api_routes": _ROUTES.api_routes,
            "agent_id": agent_id,
            **facts,
        }
    )
    return HandlerLaneGithubReadGuard(_Probe()).handle(request)


@pytest.mark.parametrize(
    ("command", "scm"),
    [
        ("gh pr view 12 --json url", "pr-view"),
        ("gh pr list -R OmniNode-ai/omnimarket --state open", "pr-list"),
        ("gh pr checks 12", "pr-checks"),
        ("gh pr create --base dev --title t --body-file b.md", "pr-create"),
        ("gh pr comment 12 --body-file c.md", "pr-comment"),
        ("gh run view 123 --log-failed", "run-view"),
        ("gh run list -R OmniNode-ai/omnimarket --limit 5", "run-list"),
        ("gh api repos/OmniNode-ai/omnimarket/actions/jobs/9/logs", "job-log"),
        (
            "gh api repos/OmniNode-ai/$r/commits/$sha/check-runs --jq .x",
            "commit-check-runs",
        ),
        ("gh api 'repos/o/r/pulls?per_page=100'", "pr-list"),
        (
            "gh api repos/o/r/branches/dev/protection/required_status_checks",
            "branch-protection",
        ),
        ("cd /tmp; timeout 30 gh pr view 12", "pr-view"),
        ("for n in 1 2; do gh pr view $n; done", "pr-view"),
        ("X=1 gh run list", "run-list"),
    ],
)
def test_routed_shape_is_refused_naming_the_verb(command: str, scm: str) -> None:
    decision = _decide(command)
    assert decision.verdict is EnumLaneGithubReadVerdict.REFUSE
    assert decision.shape is EnumLaneGithubReadShape.BARE_GH
    assert f"onex scm {scm}" in decision.reason


@pytest.mark.parametrize(
    "command",
    [
        "gh --version",
        "gh auth status",
        "gh api rate_limit",
        "gh api orgs/OmniNode-ai/actions/runners",
        "gh api -X PATCH orgs/OmniNode-ai/actions/runner-groups/4 -F a=b",
        "gh run rerun 5 -R o/r",
        "gh secret set X",
        "git push origin HEAD",
    ],
)
def test_a_shape_with_no_route_passes(command: str) -> None:
    assert _decide(command).verdict is EnumLaneGithubReadVerdict.ALLOW


@pytest.mark.parametrize(
    "command",
    [
        "onex scm pr-create --body 'first; gh pr view 12 then read it'",
        'git commit -m "note: gh pr view 12"',
        "cat > body.md <<'EOF'\ngh pr view 12\nEOF\nonex scm pr-edit x --body-file body.md",
        "grep -n 'gh pr view' plugins/onex/SKILL.md",
    ],
)
def test_prose_naming_gh_is_not_a_call(command: str) -> None:
    assert _decide(command).verdict is EnumLaneGithubReadVerdict.ALLOW


def test_the_shim_first_on_path_judges_it_itself() -> None:
    assert (
        _decide("gh pr view 12", gh_on_path=SHIM).verdict
        is EnumLaneGithubReadVerdict.ALLOW
    )


def test_no_gh_on_path_is_not_judged() -> None:
    assert (
        _decide("gh pr view 12", gh_on_path="").verdict
        is EnumLaneGithubReadVerdict.ALLOW
    )


def test_the_operators_own_session_keeps_its_login() -> None:
    assert (
        _decide("gh pr view 12", agent_id="").verdict is EnumLaneGithubReadVerdict.ALLOW
    )


def test_build_request_reads_the_first_gh_on_path(tmp_path) -> None:
    real = tmp_path / "gh"
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    request = build_request(
        {"tool_name": "Bash", "tool_input": {"command": "gh pr view 1"}},
        {"PATH": str(tmp_path), "HOME": "/fixture"},
        "/work",
    )
    assert request.gh_on_path == str(real)
