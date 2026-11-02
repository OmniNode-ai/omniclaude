# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""HandlerLaneGithubReadGuard.handle: the three read paths around the gh shim (OMN-20916)."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_lane_github_read_guard_effect.enums import (
    EnumLaneGithubReadShape,
    EnumLaneGithubReadVerdict,
    EnumSessionMode,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.handlers.handler_lane_github_read_guard import (
    LANE_ENV_MARKERS,
    HandlerLaneGithubReadGuard,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.models import (
    ModelLaneGithubReadRequest,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.runtime_lane_github_read import (
    build_request,
)

pytestmark = pytest.mark.unit

SHIM = "/srv/fixture-home/.local/bin/gh"


class _FixtureProbe:
    """The shim lives at SHIM and nowhere else."""

    def is_gh_shim(self, path: str) -> bool:
        return path == SHIM


def _decide(tool: str = "Bash", command: str = "", **facts: object):
    base: dict[str, object] = {
        "tool_name": tool,
        "command": command,
        "cwd": "/work",
        "home": "/srv/fixture-home",
        "entrypoint": "cli",
        "lane_markers": ("ONEX_LANE",),
    }
    base.update(facts)
    request = ModelLaneGithubReadRequest.model_validate(base)
    return HandlerLaneGithubReadGuard(_FixtureProbe()).handle(request)


@pytest.mark.parametrize(
    "tool",
    [
        "mcp__github__pull_request_read",
        "mcp__github__list_pull_requests",
        "mcp__github__get_file_contents",
        "mcp__github__search_code",
        "mcp__github__list_commits",
        "mcp__plugin_github_github__issue_read",
        "mcp__claude_ai_GitHub__get_me",
        "mcp__github__a_tool_nobody_has_seen_yet",
    ],
)
def test_mcp_reads_are_refused(tool: str) -> None:
    decision = _decide(tool)
    assert decision.verdict is EnumLaneGithubReadVerdict.REFUSE
    assert decision.shape is EnumLaneGithubReadShape.MCP_TOOL


@pytest.mark.parametrize(
    "tool",
    [
        "mcp__github__create_pull_request",
        "mcp__github__add_issue_comment",
        "mcp__github__merge_pull_request",
        "mcp__github__pull_request_review_write",
        "mcp__github__update_pull_request_branch",
        "mcp__linear-server__get_issue",
        "Read",
    ],
)
def test_mcp_writes_and_other_tools_are_allowed(tool: str) -> None:
    assert _decide(tool).verdict is EnumLaneGithubReadVerdict.ALLOW


@pytest.mark.parametrize(
    ("command", "shape"),
    [
        (
            'curl -H "Authorization: token $GH_PAT" https://api.github.com/user',
            EnumLaneGithubReadShape.RAW_API,
        ),
        ("curl -I https://API.GITHUB.COM/repos/o/r", EnumLaneGithubReadShape.RAW_API),
        (
            "wget -qO- https://api.github.com/repos/o/r/pulls",
            EnumLaneGithubReadShape.RAW_API,
        ),
        (
            "node -e \"fetch('https://api.github.com/user')\"",
            EnumLaneGithubReadShape.RAW_API,
        ),
        (
            'curl -X POST https://api.github.com/graphql -d \'{"query":"{viewer{login}}"}\'',
            EnumLaneGithubReadShape.RAW_API,
        ),
        ("/opt/homebrew/bin/gh pr list", EnumLaneGithubReadShape.REAL_GH),
        ("/usr/bin/gh pr checks 12", EnumLaneGithubReadShape.REAL_GH),
        ("timeout 30 /usr/bin/gh run view 99 --log", EnumLaneGithubReadShape.REAL_GH),
        ("FOO=1 /usr/bin/gh -R o/r issue list", EnumLaneGithubReadShape.REAL_GH),
        ("echo x | xargs /usr/bin/gh pr view", EnumLaneGithubReadShape.REAL_GH),
        ("$GHBIN/gh pr view 3", EnumLaneGithubReadShape.REAL_GH),
        ("/usr/bin/gh api --method=GET repos/o/r", EnumLaneGithubReadShape.REAL_GH),
        (
            "/usr/bin/gh api graphql --field=query={viewer{login}}",
            EnumLaneGithubReadShape.REAL_GH,
        ),
    ],
)
def test_bash_reads_are_refused(command: str, shape: EnumLaneGithubReadShape) -> None:
    decision = _decide(command=command)
    assert decision.verdict is EnumLaneGithubReadVerdict.REFUSE, decision
    assert decision.shape is shape


@pytest.mark.parametrize(
    "command",
    [
        "gh pr list",
        "gh api https://api.github.com/user",
        "~/.local/bin/gh pr list",
        "$HOME/.local/bin/gh pr view 1",
        "/usr/bin/gh pr merge 12 --squash --auto",
        "/usr/bin/gh workflow run ci.yml",
        "/usr/bin/gh api rate_limit",
        "/usr/bin/gh api -X PATCH repos/o/r/pulls/1 -f state=closed",
        "/usr/bin/gh api graphql -f query='mutation { x }'",
        "/usr/bin/gh auth status",
        "curl -X DELETE https://api.github.com/repos/o/r/git/refs/heads/x",
        'curl -X POST https://api.github.com/graphql -d \'{"query":"mutation{x}"}\'',
        "grep -rn api.github.com src/",
        "curl https://example.com/api",
        "ls /usr/bin/gh",
    ],
)
def test_shim_calls_writes_and_non_reads_are_allowed(command: str) -> None:
    assert _decide(command=command).verdict is EnumLaneGithubReadVerdict.ALLOW, command


@pytest.mark.parametrize(
    "facts",
    [
        {"lane_markers": ()},
        {"lane_markers": (), "entrypoint": "claude-desktop"},
        {"lane_markers": ("ONEX_LANE",), "mode": EnumSessionMode.LITE},
        {"lane_markers": (), "agent_id": "a1", "mode": EnumSessionMode.LITE},
    ],
)
def test_operator_and_lite_sessions_are_never_refused(facts: dict[str, object]) -> None:
    for tool, command in (
        ("mcp__github__pull_request_read", ""),
        ("Bash", 'curl -H "Authorization: token $GH_PAT" https://api.github.com/user'),
        ("Bash", "/opt/homebrew/bin/gh pr list"),
    ):
        decision = _decide(tool, command, **facts)
        assert decision.verdict is EnumLaneGithubReadVerdict.ALLOW, (facts, tool)
        assert decision.is_read is True


@pytest.mark.parametrize(
    ("facts", "why"),
    [
        ({"lane_markers": ("CODEX_THREAD_ID",)}, "environment CODEX_THREAD_ID"),
        ({"lane_markers": (), "agent_id": "a9f"}, "subagent a9f"),
        ({"lane_markers": (), "entrypoint": "sdk-py"}, "headless entrypoint sdk-py"),
    ],
)
def test_every_lane_shape_is_a_lane(facts: dict[str, object], why: str) -> None:
    decision = _decide("mcp__github__list_commits", **facts)
    assert decision.verdict is EnumLaneGithubReadVerdict.REFUSE
    assert decision.lane_reason == why
    assert why in decision.reason


def test_build_request_carries_marker_names_never_values() -> None:
    environ = dict.fromkeys(LANE_ENV_MARKERS, "ghp_" + "X" * 36)
    environ.update(
        HOME="/srv/fixture-home", CLAUDE_CODE_ENTRYPOINT="cli", CLAUDECODE="1"
    )
    request = build_request(
        {"tool_name": "Bash", "tool_input": {"command": "true"}}, environ, "/w"
    )
    assert request.lane_markers == LANE_ENV_MARKERS
    assert "ghp_" not in request.model_dump_json()
    # CLAUDECODE marks every Claude Code session, the operator's included: not a lane marker.
    assert "CLAUDECODE" not in LANE_ENV_MARKERS
    assert "CLAUDE_CODE_SESSION_ID" not in LANE_ENV_MARKERS


def test_refusal_names_the_local_reader() -> None:
    reason = _decide("mcp__github__pull_request_read").reason
    for reader in ("pr_state_local.py", "canonical clones", "pr-state-observed"):
        assert reader in reason
