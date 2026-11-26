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
  A2  the reason carries the runner's telemetry JSON or "DELEGATION RESULT", or
      does not say who answered and that the subagent must not run again.
  A3  the answer is cut: a multi-line answer loses lines, or an answer that is
      itself JSON is dropped as if it were the telemetry line.
  A4  a result line the hook cannot read lets the subagent run on Claude after
      it was delegated (it must still block, as before).
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


def _reason(tmp_path: Path, stub: str) -> str:
    proc = _hook(
        tmp_path, _plugin_with_stub_runner(tmp_path, stub), "subagents", _AGENT
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    decision = out["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    return str(decision["permissionDecisionReason"])


def test_an_answered_subagent_is_a_deny_with_a_plain_reason(tmp_path: Path) -> None:
    """A1, A2, A3."""
    reason = _reason(tmp_path, f"{_HEAD}\n{_TELEMETRY}\n{_ANSWER}\n")
    first, _, rest = reason.partition("\n\n")
    assert first == (
        "Subagent task completed by onex delegation with Qwen3.8-27B (run 3b917cd9), "
        "in place of a Claude subagent. This is the subagent's result: relay it as "
        "the answer and do not launch the subagent again."
    )
    assert rest == f"Result:\n{_ANSWER}"
    for leaked in ("DELEGATION RESULT", "DELEGATED:", "delegated_to", "{"):
        assert leaked not in reason


@pytest.mark.parametrize("answer", [_ANSWER, '{"name": "dict", "mutable": true}'])
def test_an_answer_without_telemetry_or_that_is_json_is_kept_whole(
    tmp_path: Path, answer: str
) -> None:
    """A3."""
    assert _reason(tmp_path, f"{_HEAD}\n{answer}\n").endswith(f"Result:\n{answer}")


def test_an_unreadable_result_line_still_blocks_the_subagent(tmp_path: Path) -> None:
    """A4: the fallback is the old exit 2, never a native run."""
    stub = f"DELEGATED: research answered without a run\n{_ANSWER}\n"
    proc = _hook(
        tmp_path, _plugin_with_stub_runner(tmp_path, stub), "subagents", _AGENT
    )
    assert proc.returncode == 2
    assert "Keys are unique and hashable." in proc.stderr


def test_the_block_is_still_logged(tmp_path: Path) -> None:
    """A5."""
    _reason(tmp_path, f"{_HEAD}\n{_TELEMETRY}\n{_ANSWER}\n")
    log = (
        tmp_path / "state" / "hooks" / "logs" / "pre-tool-delegation.log"
    ).read_text()
    assert "[pre_tool_use_delegation.sh[subagents]] BLOCK tool=Agent" in log
