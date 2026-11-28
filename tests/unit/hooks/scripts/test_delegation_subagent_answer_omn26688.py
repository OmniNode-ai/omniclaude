# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A delegated subagent answer reaches Claude as a result, not an error (OMN-26688).

Found in the interactive Claude Code test of 2026-11-26 (delegation switched on in
onex's /delegation tab, a subagent launched in ``claude``). The hook exited 2 with
"DELEGATION RESULT: DELEGATED: research answered by Qwen3.8-27B (run ...)", the
runner's telemetry JSON and the answer on stderr. Claude Code showed it as
"PreToolUse:Agent hook error: [<the whole hook command, with the user's paths>]:
...", and Claude told the user the subagent "did not run". Headless, Claude called
the Agent tool twice. The same answer returned as a PreToolUse "deny" with a plain
reason was shown without the command or the JSON, and Claude called the tool once
(measured 2026-11-26 with a scratch hook, claude 2.1.332).

Failure modes, each caught below:

  A1  an answered subagent call is still an exit-2 error, so Claude sees the hook
      command, and retries.
  A2  a run without the telemetry line is not denied the same way.
  A3  the reason's wording and an uncut answer are the omnimarket node's
      (ModelHookDelegateResult.hook_output, tested there); the hook prints it as is.
  A4  an older node's plain answer (no deny line) lets the subagent run on
      Claude after it was delegated (it must still block, as before).
  A5  the hook log no longer records the block.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.hooks.scripts.test_delegation_hook_edges_omn23413 import (
    _AGENT,
    _hook,
)
from tests.unit.hooks.scripts.test_prompt_delegation_ac33_omn23413 import (
    _plugin_with_stub_runner,
)

pytestmark = pytest.mark.unit

_HEAD = "DELEGATED: research answered by Qwen3.8-27B (run 3b917cd9)"
#: The runner's telemetry line, as the interactive test showed it (trimmed).
_TELEMETRY = json.dumps(
    {
        "correlation_id": "",
        "task_type": "research",
        "delegated_to": "Qwen3.8-27B",
        "delegated_by": "omniclaude.hook.pre_tool_use_delegation",
        "cost_usd": 0.0,
        "hook_path_non_authoritative": True,
    }
)
_ANSWER = (
    "A Python dictionary is a mutable collection of key-value pairs.\n"
    "\n"
    "Keys are unique and hashable."
)

_DENY = json.dumps(
    {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Subagent task completed by onex delegation with Qwen3.8-27B "
                "(run 3b917cd9), in place of a Claude subagent. This is the "
                "subagent's result: relay it as the answer and do not launch "
                "the subagent again.\n\nResult:\n" + _ANSWER
            ),
        }
    }
)


def test_an_answered_subagent_prints_the_node_deny(tmp_path: Path) -> None:
    """A1: A complete delegation with telemetry and deny must exit 0."""
    stub = f"{_HEAD}\n{_TELEMETRY}\n{_DENY}\n"
    proc = _hook(
        tmp_path,
        _plugin_with_stub_runner(tmp_path, stub),
        "subagents",
        _AGENT,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == json.loads(_DENY)
    assert "DELEGATION RESULT" not in proc.stderr


def test_an_answered_subagent_without_telemetry_prints_the_node_deny(
    tmp_path: Path,
) -> None:
    """A2: A delegation without telemetry must still exit 0 and print deny."""
    stub = f"{_HEAD}\n{_DENY}\n"
    proc = _hook(
        tmp_path,
        _plugin_with_stub_runner(tmp_path, stub),
        "subagents",
        _AGENT,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == json.loads(_DENY)
    assert "DELEGATION RESULT" not in proc.stderr


def test_an_answered_subagent_preserves_multiline_and_json_in_deny_reason(
    tmp_path: Path,
) -> None:
    """A3: An uncut multi-line answer containing JSON inside deny prints as-is."""
    rich_answer = 'Line one\n{"name": "dict", "items": [1, 2]}\nLine three'
    deny = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Result:\n{rich_answer}",
            }
        }
    )
    stub = f"{_HEAD}\n{_TELEMETRY}\n{deny}\n"
    proc = _hook(
        tmp_path,
        _plugin_with_stub_runner(tmp_path, stub),
        "subagents",
        _AGENT,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == deny
    assert (
        rich_answer
        in json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    )


def test_compact_or_reordered_deny_json_exits_zero(tmp_path: Path) -> None:
    """Valid PreToolUse deny JSON with compact separators and reordered keys exits 0."""
    compact_deny = json.dumps(
        {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": _ANSWER,
                "hookEventName": "PreToolUse",
            }
        },
        separators=(",", ":"),
    )
    stub = f"{_HEAD}\n{_TELEMETRY}\n{compact_deny}\n"
    proc = _hook(
        tmp_path,
        _plugin_with_stub_runner(tmp_path, stub),
        "subagents",
        _AGENT,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == json.loads(compact_deny)


def test_an_answered_subagent_without_a_deny_line_blocks(tmp_path: Path) -> None:
    """A4: An older node without a deny line must exit 2 and block."""
    stub = f"{_HEAD}\n{_ANSWER}\n"
    proc = _hook(
        tmp_path,
        _plugin_with_stub_runner(tmp_path, stub),
        "subagents",
        _AGENT,
    )
    assert proc.returncode == 2
    assert "Keys are unique and hashable." in proc.stderr


@pytest.mark.parametrize(
    "last_line",
    [
        json.dumps({"name": "dict"}),
        json.dumps({"hookSpecificOutput": {"other": 1}}),
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "not a deny",
                }
            }
        ),
        '{"hookSpecificOutput": {"hookEventName": "PreToolUse"',
    ],
)
def test_a_plain_json_answer_from_an_older_node_still_blocks(
    tmp_path: Path, last_line: str
) -> None:
    """A4 negative: Plain, non-deny, or truncated JSON last lines must exit 2."""
    stub = f"{_HEAD}\n{last_line}\n"
    proc = _hook(
        tmp_path,
        _plugin_with_stub_runner(tmp_path, stub),
        "subagents",
        _AGENT,
    )
    assert proc.returncode == 2
    assert json.loads(proc.stdout) == _AGENT
    assert last_line in proc.stderr


def test_a_delegated_subagent_is_logged_as_blocked(tmp_path: Path) -> None:
    """A5: The hook must log the blocked delegation with the agent name."""
    stub = f"{_HEAD}\n{_TELEMETRY}\n{_DENY}\n"
    _hook(
        tmp_path,
        _plugin_with_stub_runner(tmp_path, stub),
        "subagents",
        _AGENT,
    )
    log_file = tmp_path / "state" / "hooks" / "logs" / "pre-tool-delegation.log"
    assert "[pre_tool_use_delegation.sh[subagents]] BLOCK tool=Agent" in (
        log_file.read_text()
    )
