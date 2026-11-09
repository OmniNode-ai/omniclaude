# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23307 AC1: ``pre_tool_use_agent_model_guard.sh`` calls omnimarket's agent-prompt gh-read node.

92 of the 101 gh-read refusals counted in the 24 hours to 2026-11-09T06:46Z came from subagents
following a prompt that names gh. The refusal of such a prompt is a node
(``node_agent_prompt_gh_read_guard_effect``); the hook stays a thin shim that decides whether to call
it and relays its verdict. The node's own decisions are tested in omnimarket. These tests run the
registered hook as Claude Code does, against a stand-in node package on the registry venv path, and
show the wiring: the hook calls the node for a dispatch whose text names gh, relays its exit-2 block,
passes its exit 0, does not call it for a dispatch that names no gh, and refuses a dispatch the node
cannot judge. Remove the node call from the hook and the refusal test goes red.
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
HOOK = ROOT / "plugins/onex/hooks/scripts/pre_tool_use_agent_model_guard.sh"
NODE_MODULE = "omnimarket/nodes/node_agent_prompt_gh_read_guard_effect/runtime_agent_prompt_gh_read.py"
ROUTE = "ROUTE: band=B3 score=9 dims=S2A1R1V2N1C1J1 dest=lane model=sonnet effort=high"

# The stand-in node: records that it ran, refuses a payload that names `gh pr view`, passes the rest.
STAND_IN = """\
import os, sys
payload = sys.stdin.read()
open(os.environ["STAND_IN_CALLS"], "a").write(" ".join(sys.argv[1:]) + "\\n")
if "gh pr view" in payload:
    sys.stdout.write('{"decision": "block", "reason": "BLOCKED: stand-in refusal naming onex scm pr-view"}\\n')
    sys.exit(2)
sys.exit(0)
"""


def _registry(tmp_path: Path, *, with_node: bool) -> Path:
    """The lab layout: ``<registry>/omnimarket/.venv/bin/python3`` is the interpreter with omnimarket."""
    registry = tmp_path / "registry"
    python = registry / "omnimarket" / ".venv" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    packages = tmp_path / "stand_in_packages"
    if with_node:
        node = packages / NODE_MODULE
        node.parent.mkdir(parents=True)
        node.write_text(STAND_IN, encoding="utf-8")
        for directory in (
            packages / "omnimarket",
            packages / "omnimarket/nodes",
            packages / "omnimarket/nodes/node_agent_prompt_gh_read_guard_effect",
        ):
            (directory / "__init__.py").write_text("", encoding="utf-8")
    python.write_text(
        f'#!/bin/sh\nPYTHONPATH="{packages}" exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    return registry


def _env(tmp_path: Path, registry: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("ONEX_", "CLAUDE_", "CODEX_", "GIT_", "PLUGIN_", "PYTHON")
        )
    }
    env.update(
        OMNI_HOME=str(registry),
        ONEX_STATE_DIR=str(tmp_path / "state"),
        ONEX_HOOK_LOG=str(tmp_path / "hooks.log"),
        CLAUDE_PLUGIN_ROOT=str(ROOT / "plugins/onex"),
        CLAUDE_PROJECT_DIR=str(ROOT),
        OMNICLAUDE_MODE="full",
        HOME=str(tmp_path),
        STAND_IN_CALLS=str(tmp_path / "node-calls.log"),
    )
    return env


def _agent(prompt: str) -> dict[str, object]:
    return {
        "tool_name": "Agent",
        "tool_input": {
            "subagent_type": "general-purpose",
            "model": "sonnet",
            "description": "check the pull request",
            "prompt": f"{ROUTE}\n{prompt}",
        },
    }


def _run(
    payload: dict[str, object], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "node-calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_agent_prompt_gh_read_hook_relays_the_nodes_refusal(tmp_path: Path) -> None:
    env = _env(tmp_path, _registry(tmp_path, with_node=True))
    result = _run(_agent("Run `gh pr view 12` and report the checks."), env)
    assert result.returncode == 2, (result.stdout, result.stderr)
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert "stand-in refusal naming onex scm pr-view" in decision["reason"]
    assert _calls(tmp_path) == ["--mode full"]


def test_agent_prompt_gh_read_hook_admits_what_the_node_admits(tmp_path: Path) -> None:
    env = _env(tmp_path, _registry(tmp_path, with_node=True))
    result = _run(
        _agent("Run `gh run view 5` is refused; use onex scm run-view instead."), env
    )
    assert (result.returncode, result.stdout) == (0, ""), result.stderr
    assert _calls(tmp_path) == ["--mode full"]


def test_agent_prompt_gh_read_hook_does_not_call_the_node_for_a_prompt_that_names_no_gh(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path, _registry(tmp_path, with_node=True))
    result = _run(_agent("Read onex scm pr-checks OmniNode-ai/omniclaude#7."), env)
    assert (result.returncode, result.stdout) == (0, ""), result.stderr
    assert _calls(tmp_path) == []


def test_agent_prompt_gh_read_hook_calls_the_node_for_a_workflow_script_file_that_names_gh(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path, _registry(tmp_path, with_node=True))
    script = tmp_path / "wf.js"
    script.write_text(
        f"await agent(`{ROUTE}\\ngh pr view 3`, {{ label: 'x', model: 'sonnet' }})\n"
    )
    result = _run(
        {"tool_name": "Workflow", "tool_input": {"scriptPath": str(script)}}, env
    )
    # The stand-in judges the payload only (it names the file, not its text), so it admits; the
    # real node reads the file. What this shows is that the hook read the file to decide to call it.
    assert (result.returncode, result.stdout) == (0, ""), result.stderr
    assert _calls(tmp_path) == ["--mode full"]
    clean = tmp_path / "clean.js"
    clean.write_text(
        f"await agent(`{ROUTE}\\nread onex scm pr-view`, {{ label: 'x', model: 'sonnet' }})\n"
    )
    (tmp_path / "node-calls.log").unlink()
    _run({"tool_name": "Workflow", "tool_input": {"scriptPath": str(clean)}}, env)
    assert _calls(tmp_path) == []


def test_agent_prompt_gh_read_hook_refuses_a_dispatch_the_node_cannot_judge(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path, _registry(tmp_path, with_node=False))
    result = _run(_agent("Run `gh pr view 12` and report the checks."), env)
    assert result.returncode == 2, (result.stdout, result.stderr)
    decision = json.loads(result.stdout)
    assert "could not judge" in decision["reason"]
    assert "No module named" in decision["reason"]


def test_agent_prompt_gh_read_hook_calls_the_nodes_runtime_module() -> None:
    """The seam the stand-in stands for: the module name the hook runs is the node's process entry."""
    text = HOOK.read_text(encoding="utf-8")
    assert (
        "omnimarket.nodes.node_agent_prompt_gh_read_guard_effect.runtime_agent_prompt_gh_read"
        in text
    )
