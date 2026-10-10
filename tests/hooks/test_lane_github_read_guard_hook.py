# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20916 AC1-AC3: the registered PreToolUse entrypoint refuses a lane's GitHub reads
around the gh shim, and never refuses the operator's own interactive session.

Each test runs ``pre_tool_use_bash_guards.sh`` exactly as Claude Code does: the hook
payload on stdin, the caller's environment, exit 2 with the block JSON for a refusal.
The lane shape carries the ``ONEX_LANE`` marker the shim also reads; the operator shape
is an interactive session (entrypoint ``cli``, no marker, no ``agent_id``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "plugins/onex/hooks/scripts/pre_tool_use_bash_guards.sh"
HOOKS_JSON = ROOT / "plugins/onex/hooks/hooks.json"

#: A token-shaped value that must never appear in the hook's output.
FAKE_TOKEN = "ghp_" + "F" * 36

AC1_TOOL = "mcp__github__pull_request_read"
AC2_COMMAND = 'curl -sS -H "Authorization: token $GH_PAT" https://api.github.com/user'
AC3_COMMAND = "/opt/homebrew/bin/gh pr list --repo OmniNode-ai/omniclaude"

LOCAL_READERS = ("pr_state_local.py", "canonical clones", "pr-state-observed")


def _env(tmp_path: Path, *, lane: bool) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ONEX_", "CLAUDE_", "CODEX_", "GIT_", "GH_", "GITHUB_"))
    }
    registry = tmp_path / "registry"
    registry.mkdir(exist_ok=True)
    env.update(
        OMNI_HOME=str(registry),
        ONEX_STATE_DIR=str(tmp_path / "state"),
        ONEX_HOOK_LOG=str(tmp_path / "hooks.log"),
        CLAUDE_PLUGIN_ROOT=str(ROOT / "plugins/onex"),
        CLAUDE_PROJECT_DIR=str(ROOT),
        CLAUDE_CODE_ENTRYPOINT="cli",
        CLAUDECODE="1",
        PLUGIN_PYTHON_BIN=sys.executable,
        OMNICLAUDE_MODE="full",
        HOME=str(tmp_path),
        GH_PAT=FAKE_TOKEN,
        GH_PAT_TOKEN=FAKE_TOKEN,
    )
    if lane:
        env["ONEX_LANE"] = "fixture-lane-omn20916"
    return env


def _payload(tool_name: str, tool_input: dict[str, str], **extra: str) -> str:
    return json.dumps(
        {
            "session_id": "fixture-session",
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": str(ROOT),
            **extra,
        }
    )


def _run(payload: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        env=env,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def _bash(command: str) -> str:
    return _payload("Bash", {"command": command})


def _assert_denied(result: subprocess.CompletedProcess[str], *needles: str) -> None:
    assert result.returncode == 2, (result.stdout, result.stderr)
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = decision["reason"]
    assert reason.startswith("REFUSED (OMN-20916)"), reason
    for reader in LOCAL_READERS:
        assert reader in reason, reason
    for needle in needles:
        assert needle in reason, reason
    # The refusal reaches the model on stderr, the channel exit 2 feeds back.
    assert "REFUSED (OMN-20916)" in result.stderr
    assert FAKE_TOKEN not in result.stdout + result.stderr


def _assert_allowed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "OMN-20916" not in result.stdout + result.stderr
    assert FAKE_TOKEN not in result.stdout + result.stderr


# --- AC1: a GitHub MCP read tool ------------------------------------------------


def test_ac1_lane_mcp_pull_request_read_is_denied(tmp_path: Path) -> None:
    result = _run(
        _payload(AC1_TOOL, {"owner": "OmniNode-ai", "repo": "omniclaude"}),
        _env(tmp_path, lane=True),
    )
    _assert_denied(result, AC1_TOOL, "environment ONEX_LANE")


def test_ac1_operator_mcp_pull_request_read_is_allowed(tmp_path: Path) -> None:
    result = _run(
        _payload(AC1_TOOL, {"owner": "OmniNode-ai", "repo": "omniclaude"}),
        _env(tmp_path, lane=False),
    )
    _assert_allowed(result)


def test_ac1_subagent_of_the_operator_session_is_a_lane(tmp_path: Path) -> None:
    payload = _payload(
        "mcp__github__list_commits", {"owner": "o", "repo": "r"}, agent_id="a1b2c3"
    )
    _assert_denied(_run(payload, _env(tmp_path, lane=False)), "subagent a1b2c3")


def test_ac1_headless_session_is_a_lane(tmp_path: Path) -> None:
    env = _env(tmp_path, lane=False)
    env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-cli"
    result = _run(
        _payload("mcp__plugin_github_github__get_file_contents", {"path": "x"}), env
    )
    _assert_denied(result, "headless entrypoint sdk-cli")


def test_ac1_lane_mcp_write_is_allowed(tmp_path: Path) -> None:
    payload = _payload(
        "mcp__github__create_pull_request", {"title": "x", "head": "b", "base": "dev"}
    )
    _assert_allowed(_run(payload, _env(tmp_path, lane=True)))


def test_ac1_entrypoint_is_registered_on_github_mcp_tools() -> None:
    import re

    hooks = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    matchers = [
        group["matcher"]
        for group in hooks
        if any(
            h["command"].endswith("/pre_tool_use_bash_guards.sh")
            for h in group["hooks"]
        )
    ]
    assert len(matchers) == 1
    for tool in (
        AC1_TOOL,
        "mcp__plugin_github_github__search_code",
        "mcp__claude_ai_GitHub__list_commits",
        "Bash",
    ):
        assert re.fullmatch(matchers[0], tool), (matchers[0], tool)
    for tool in ("mcp__linear-server__save_comment", "Edit", "Read"):
        assert not re.fullmatch(matchers[0], tool), (matchers[0], tool)


# --- AC2: a direct call to api.github.com ---------------------------------------


def test_ac2_lane_curl_to_api_with_gh_pat_is_denied(tmp_path: Path) -> None:
    _assert_denied(_run(_bash(AC2_COMMAND), _env(tmp_path, lane=True)), "curl")


def test_ac2_operator_curl_to_api_with_gh_pat_is_allowed(tmp_path: Path) -> None:
    _assert_allowed(_run(_bash(AC2_COMMAND), _env(tmp_path, lane=False)))


@pytest.mark.parametrize(
    "command",
    [
        'wget -qO- --header="Authorization: Bearer $GH_PAT_TOKEN" https://api.github.com/repos/o/r/pulls',
        "python3 - <<'EOF'\nimport os, urllib.request\nreq = urllib.request.Request('https://api.github.com/user', headers={'Authorization': 'token ' + os.environ['GH_PAT']})\nprint(urllib.request.urlopen(req).read())\nEOF",
        "python3 -c \"import requests,os; requests.get('https://api.github.com/rate_limit', headers={'Authorization': 'token '+os.environ['GH_PAT']})\"",
        'curl -s -X POST -H "Authorization: bearer $GH_PAT" https://api.github.com/graphql -d \'{"query":"{viewer{login}}"}\'',
    ],
)
def test_ac2_lane_other_clients_are_denied(tmp_path: Path, command: str) -> None:
    _assert_denied(_run(_bash(command), _env(tmp_path, lane=True)))


def test_ac2_lane_curl_write_is_allowed(tmp_path: Path) -> None:
    command = (
        'curl -s -X POST -H "Authorization: token $GH_PAT" '
        'https://api.github.com/repos/o/r/issues/1/comments -d \'{"body":"x"}\''
    )
    _assert_allowed(_run(_bash(command), _env(tmp_path, lane=True)))


def test_ac2_lane_text_naming_the_host_without_a_client_is_allowed(
    tmp_path: Path,
) -> None:
    _assert_allowed(
        _run(
            _bash("git -C . log --oneline -1 -- README.md; echo api.github.com"),
            _env(tmp_path, lane=True),
        )
    )


# --- AC3: the real gh binary by its path -----------------------------------------


def test_ac3_lane_homebrew_gh_pr_list_is_denied(tmp_path: Path) -> None:
    _assert_denied(
        _run(_bash(AC3_COMMAND), _env(tmp_path, lane=True)),
        "/opt/homebrew/bin/gh",
        "pr list",
    )


def test_ac3_operator_homebrew_gh_pr_list_is_allowed(tmp_path: Path) -> None:
    _assert_allowed(_run(_bash(AC3_COMMAND), _env(tmp_path, lane=False)))


@pytest.mark.parametrize(
    "command",
    [
        "/usr/bin/gh api repos/OmniNode-ai/omniclaude/contents/README.md",
        "cd /tmp && /usr/bin/gh run list --limit 5",
        "env GH_TOKEN=$GH_PAT /usr/local/bin/gh pr view 12",
        "/usr/bin/gh api graphql -f query='{viewer{login}}'",
    ],
)
def test_ac3_lane_other_real_gh_reads_are_denied(tmp_path: Path, command: str) -> None:
    _assert_denied(_run(_bash(command), _env(tmp_path, lane=True)))


@pytest.mark.parametrize(
    "command",
    [
        "/opt/homebrew/bin/gh pr create --base dev --title t --body-file b.md",
        "/usr/bin/gh pr comment 12 --body-file c.md",
        "/usr/bin/gh api -X POST repos/o/r/issues/1/comments -f body=x",
        "/usr/bin/gh --version",
    ],
)
def test_ac3_lane_real_gh_writes_and_local_verbs_are_allowed(
    tmp_path: Path, command: str
) -> None:
    _assert_allowed(_run(_bash(command), _env(tmp_path, lane=True)))


def test_ac3_lane_shim_by_its_path_is_left_to_the_shim(tmp_path: Path) -> None:
    shim = tmp_path / ".local" / "bin" / "gh"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/bash\n# ONEX_GH_USER_SHIM (OMN-19479) -- fixture copy\n")
    _assert_allowed(_run(_bash("~/.local/bin/gh pr list"), _env(tmp_path, lane=True)))


# --- the allowlisted flows keep working from a lane ---------------------------------


@pytest.mark.parametrize(
    "command",
    [
        # the exact-head check before a mutation goes through the shim on PATH
        "gh pr view 2661 --repo OmniNode-ai/omniclaude --json headRefOid,state",
        # the PR watcher state and the canonical clones
        "python3 plugins/onex/skills/merge-drain/scripts/pr_state_local.py --pr OmniNode-ai/omniclaude#2661",
        "git -C $OMNI_HOME/omniclaude log --oneline -3 origin/dev",
        # the shim's cached read gateway
        "gh api repos/OmniNode-ai/omniclaude/actions/jobs/123/logs",
    ],
)
def test_lane_local_reads_and_shim_calls_are_allowed(
    tmp_path: Path, command: str
) -> None:
    _assert_allowed(_run(_bash(command), _env(tmp_path, lane=True)))


def test_lite_mode_install_has_no_lanes(tmp_path: Path) -> None:
    # A non-OmniNode install (omniclaude_mode lite) is never refused, marker or not.
    env = _env(tmp_path, lane=True)
    env["OMNICLAUDE_MODE"] = "lite"
    _assert_allowed(_run(_payload(AC1_TOOL, {"owner": "o", "repo": "r"}), env))
    _assert_allowed(_run(_bash(AC3_COMMAND), env))
