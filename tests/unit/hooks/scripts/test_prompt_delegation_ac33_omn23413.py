# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Every prompt goes to delegation first; Claude answers what it cannot (OMN-23413 AC33).

Spec: records/plans/OMN-23413/spec.md, Amendment 9. The prompt rules (skip,
decline, recent conversation, history, bar, limit) live in omnimarket
node_hook_delegate_effect's prompt handler, whose tests cover each one; these
tests drive the real runner and node with a stand-in onex, and the shell entry
with a stub runner. Failure modes, each caught below:

  P1  a prompt the classifier rejects is never delegated (AC33 says every prompt).
  P2  a model that cannot answer still replaces Claude (decline must pass through).
  P4  "@claude" at the start of a prompt still delegates it.
  P6  Claude never learns what delegation answered while it was blocked.
  L4  a prompt waits longer than the hook's own limit.
  S1  an accepted prompt answer only adds context, so Claude still runs (and is
      billed) for the same prompt. Verified 2026-11-13: decision "block" makes
      Claude Code skip the model call (num_turns 0, total_cost_usd 0).
  S2  a prompt that passes through injects the raw hook envelope into Claude's
      context (plain stdout of a UserPromptSubmit hook is added as context).
  S3  with the switch OFF a prompt still prints the envelope.
  S4  the Agent/Task path changes (it must still block with exit 2).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[4]
_PLUGIN = _REPO / "plugins" / "onex"
_RUNNER = _PLUGIN / "hooks" / "lib" / "delegation_hook_runner.py"
_ANSWER = "TCP is connection-oriented and reliable; UDP is connectionless and faster."
_DECLINE = "CANNOT_ANSWER"


def _install(bin_dir: Path) -> Path:
    bin_dir.mkdir(exist_ok=True)
    python = bin_dir / "python"
    if not python.exists():
        python.symlink_to(sys.executable)
    return bin_dir


def _fake_onex(tmp_path: Path, responses: list[dict[str, object]]) -> Path:
    """A stand-in onex that records its argv and answers from ``responses`` in turn."""
    bin_dir = _install(tmp_path / "bin")
    (tmp_path / "responses.json").write_text(json.dumps(responses))
    script = f"""#!{sys.executable}
import json, pathlib, sys
root = pathlib.Path({str(tmp_path)!r})
calls = root / "calls.jsonl"
n = len(calls.read_text().splitlines()) if calls.exists() else 0
with calls.open("a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
responses = json.loads((root / "responses.json").read_text())
doc = responses[min(n, len(responses) - 1)]
print(json.dumps(doc))
sys.exit(1 if doc.get("status") == "failed" else 0)
"""
    onex = bin_dir / "onex"
    onex.write_text(script)
    onex.chmod(0o755)
    return bin_dir


def _doc(answer: str, run: str, model: str = "Qwen3.8-27B") -> dict[str, object]:
    return {"run_id": run, "result": {"response": answer, "model_name": model}}


def _calls(tmp_path: Path) -> list[list[str]]:
    path = tmp_path / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _prompt(text: str, session: str = "ac33", transcript: Path | None = None) -> dict:
    return {
        "session_id": session,
        "hook_event_name": "UserPromptSubmit",
        "prompt": text,
        "transcript_path": str(transcript) if transcript else "",
    }


def _run(
    tmp_path: Path,
    payload: dict,
    bin_dir: Path,
    limit: str = "30",
) -> str:
    """The runner's stdout: for a prompt, the hook's whole output."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [str(bin_dir / "python"), str(_RUNNER)],
        input=json.dumps(payload),
        env={
            "HOME": str(home),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "ONEX_HOOK_DELEGATE_TIMEOUT_S": limit,
            "PYTHONPATH": os.pathsep.join(sys.path),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


# --- the runner and the node -------------------------------------------------


def test_any_prompt_is_delegated_and_its_answer_blocks_claude(tmp_path: Path) -> None:
    """P1, S1: "hi" is not delegatable to the classifier; AC33 still delegates it,
    and the accepted answer is a block naming the model and run."""
    bin_dir = _fake_onex(tmp_path, [_doc("Hello! How can I help?", "r-hi")])
    out = json.loads(
        _run(tmp_path, _prompt("hello there, how are you today?"), bin_dir)
    )
    assert out["decision"] == "block"
    assert out["reason"].startswith("Hello! How can I help?")
    assert "Qwen3.8-27B" in out["reason"]
    assert "run r-hi" in out["reason"]
    (argv,) = _calls(tmp_path)
    assert "--system-prompt" in argv


def test_a_declined_prompt_passes_to_claude_silently(tmp_path: Path) -> None:
    """P2, S2: nothing is printed, so Claude answers the prompt as typed."""
    bin_dir = _fake_onex(
        tmp_path, [_doc(f"{_DECLINE}: needs the user's files", "r-no")]
    )
    assert _run(tmp_path, _prompt("what does notes.txt say?"), bin_dir) == ""


def test_the_skip_prefix_sends_the_prompt_to_claude_without_delegating(
    tmp_path: Path,
) -> None:
    """P4."""
    bin_dir = _fake_onex(tmp_path, [_doc(_ANSWER, "r-skip")])
    assert _run(tmp_path, _prompt("@claude explain TCP"), bin_dir) == ""
    assert _calls(tmp_path) == []


def test_claude_is_told_once_what_delegation_answered(tmp_path: Path) -> None:
    """P6: the next prompt that reaches Claude carries the delegated exchange."""
    bin_dir = _fake_onex(
        tmp_path, [_doc(_ANSWER, "r-1"), _doc(_DECLINE, "r-2"), _doc(_DECLINE, "r-3")]
    )
    _run(tmp_path, _prompt("How do TCP and UDP differ?"), bin_dir)
    out = json.loads(_run(tmp_path, _prompt("now edit my file"), bin_dir))
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "How do TCP and UDP differ?" in context
    assert _ANSWER in context
    assert "decision" not in out
    assert _run(tmp_path, _prompt("and run the tests"), bin_dir) == ""


def test_a_prompt_never_waits_past_the_hook_limit(tmp_path: Path) -> None:
    """L4: past the limit the prompt goes to Claude."""
    bin_dir = _install(tmp_path / "bin")
    onex = bin_dir / "onex"
    onex.write_text("#!/bin/sh\nsleep 10\n")
    onex.chmod(0o755)
    assert (
        _run(tmp_path, _prompt("How do TCP and UDP differ?"), bin_dir, limit="1") == ""
    )


# --- the shell entry --------------------------------------------------------


def _plugin_with_stub_runner(tmp_path: Path, stub_stdout: str) -> Path:
    plugin = tmp_path / "plugin" / "onex"
    shutil.copytree(_PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__"))
    runner = plugin / "hooks" / "lib" / "delegation_hook_runner.py"
    runner.write_text(
        "import sys\nsys.stdin.read()\nsys.stdout.write(" + repr(stub_stdout) + ")\n"
    )
    return plugin


def _run_shell(
    tmp_path: Path, plugin: Path, payload: dict, mask: str = "0xffffffff"
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    marker = home / ".omninode" / "delegation" / "hooks-delegation.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}")
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    jq = shutil.which("jq")
    assert jq, "jq is required by the hook"
    if not (tools / "jq").exists():
        (tools / "jq").symlink_to(jq)
    return subprocess.run(
        ["/bin/bash", str(plugin / "hooks" / "scripts" / "pre_tool_use_delegation.sh")],
        input=json.dumps(payload) + "\n",
        env={
            "HOME": str(home),
            "PATH": f"{tools}:/usr/bin:/bin",
            "TMPDIR": str(tmp_path),
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "ONEX_HOOKS_MASK": mask,
            "PLUGIN_PYTHON_BIN": sys.executable,
            "CLAUDE_PLUGIN_ROOT": str(plugin),
            "CLAUDE_PROJECT_DIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_the_prompt_hook_prints_exactly_the_runner_output(tmp_path: Path) -> None:
    """S1: the runner's block reaches Claude Code unchanged."""
    block = json.dumps({"decision": "block", "reason": _ANSWER})
    plugin = _plugin_with_stub_runner(tmp_path, block + "\n")
    proc = _run_shell(tmp_path, plugin, _prompt("How do TCP and UDP differ?"))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"decision": "block", "reason": _ANSWER}


def test_a_passed_through_prompt_prints_nothing(tmp_path: Path) -> None:
    """S2: never the hook envelope."""
    plugin = _plugin_with_stub_runner(tmp_path, "\n")
    proc = _run_shell(tmp_path, plugin, _prompt("edit my file"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_a_failed_runner_prints_nothing_for_a_prompt(tmp_path: Path) -> None:
    """S2: a runner that crashes after printing must not leak partial output."""
    plugin = _plugin_with_stub_runner(tmp_path, "partial")
    runner = plugin / "hooks" / "lib" / "delegation_hook_runner.py"
    runner.write_text(runner.read_text() + "sys.exit(1)\n")
    proc = _run_shell(tmp_path, plugin, _prompt("edit my file"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_with_the_switch_off_a_prompt_prints_nothing(tmp_path: Path) -> None:
    """S3: bit 11 (POST_SKILL_DELEGATION_ENFORCER) cleared."""
    block = json.dumps({"decision": "block", "reason": _ANSWER})
    plugin = _plugin_with_stub_runner(tmp_path, block + "\n")
    proc = _run_shell(
        tmp_path, plugin, _prompt("How do TCP and UDP differ?"), mask="0x0"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_the_agent_task_path_still_blocks_with_exit_2(tmp_path: Path) -> None:
    """S4: regression control for Amendment 8's subagent path."""
    plugin = _plugin_with_stub_runner(
        tmp_path, f"DELEGATED: research answered by m (run r-agent)\n{_ANSWER}\n"
    )
    agent = {
        "session_id": "ac33",
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": {"prompt": "How do TCP and UDP differ?", "description": "q"},
    }
    proc = _run_shell(tmp_path, plugin, agent)
    assert proc.returncode == 2
    assert _ANSWER in proc.stderr
