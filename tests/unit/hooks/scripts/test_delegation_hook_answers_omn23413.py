# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegation hook answers a delegated task with the user's models (OMN-23413).

Found 2026-11-13: the runner classified a task, printed "DELEGATED: <task>
routed to <tier>" and exited, so the shell hook exited 2 and Claude Code
blocked the subagent. No model was called; nothing was delegated. Failure
modes, each caught below:

  H1  a delegatable task is blocked with a routing label and no answer.
  H2  `onex delegate` failing still blocks the subagent (it must pass through).
  H3  `onex delegate` hanging past the limit still blocks (it must pass through).
  H4  no `onex` on PATH still blocks (it must pass through).
  The stand-in `onex` sits beside the Python that runs the hook, where the
  node looks first (an install's own onex, not Claude Code's PATH: seen
  2026-11-13, a launcher's older onex knew no Reflection AI).
  H5  Claude Code's hook timeout is shorter than the time a delegation needs.
  H6  a re-install keeps an older entry, so a new timeout never reaches Claude Code.
  H7  the classified task type is not passed on, so `onex delegate` guesses one:
      a prose question was judged as code_generation and vetoed for not
      compiling as Python (run e45088c5, 2026-11-13).

The answer parsing, the gateway check and the limit live in omnimarket's
node_hook_delegate_effect, whose own tests (N1-N8) cover them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[4]
_RUNNER = _REPO / "plugins" / "onex" / "hooks" / "lib" / "delegation_hook_runner.py"
_REGISTRATION = _REPO / "plugins" / "onex" / "hooks" / "hooks-delegation.v1.json"
_TASK = {
    "session_id": "answers-test",
    "hook_event_name": "PreToolUse",
    "tool_name": "Agent",
    "tool_input": {
        "subagent_type": "general-purpose",
        "description": "summarise",
        "prompt": "Write one sentence explaining what a Python list comprehension is.",
    },
}
_ANSWER = "A list comprehension builds a list from an iterable in one expression."


def _install(bin_dir: Path) -> Path:
    """An install's bin folder: the Python that runs the hook links here."""
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    return bin_dir


def _fake_onex(tmp_path: Path, body: str) -> Path:
    """A stand-in `onex` beside the hook's Python; ``body`` is the shell it runs."""
    bin_dir = _install(tmp_path / "bin")
    onex = bin_dir / "onex"
    onex.write_text(f"#!/bin/sh\n{body}\n")
    onex.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, path: str, limit: str = "30") -> list[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    python = Path(path.split(":", maxsplit=1)[0]) / "python"
    result = subprocess.run(
        [str(python), str(_RUNNER)],
        input=json.dumps(_TASK),
        env={
            "HOME": str(home),
            "PATH": path,
            "ONEX_HOOK_DELEGATE_TIMEOUT_S": limit,
            "PYTHONPATH": os.pathsep.join(sys.path),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_a_delegated_task_comes_back_with_the_models_answer(tmp_path: Path) -> None:
    """H1."""
    document = {
        "run_id": "553d07cd-b177-4615-84db-0508eb99f3be",
        "result": {"response": _ANSWER, "model_name": "Qwen3.8-27B"},
    }
    bin_dir = _fake_onex(tmp_path, f"echo '{json.dumps(document)}'")
    lines = _run(tmp_path, f"{bin_dir}:/usr/bin:/bin")
    assert lines[0].startswith("DELEGATED: ")
    assert "answered by Qwen3.8-27B" in lines[0]
    assert "553d07cd" in lines[0]
    assert _ANSWER in lines


def test_a_failed_delegation_passes_the_task_through(tmp_path: Path) -> None:
    """H2."""
    bin_dir = _fake_onex(tmp_path, "echo 'no model answered' >&2; exit 1")
    lines = _run(tmp_path, f"{bin_dir}:/usr/bin:/bin")
    assert lines[0] == "not_delegatable:failed"


def test_a_delegation_past_the_limit_passes_the_task_through(tmp_path: Path) -> None:
    """H3."""
    bin_dir = _fake_onex(tmp_path, "sleep 10")
    lines = _run(tmp_path, f"{bin_dir}:/usr/bin:/bin", limit="1")
    assert lines[0] == "not_delegatable:timed_out"


def test_no_onex_on_path_passes_the_task_through(tmp_path: Path) -> None:
    """H4."""
    empty = _install(tmp_path / "empty")  # a Python, and no onex anywhere
    lines = _run(tmp_path, f"{empty}:/usr/bin:/bin")
    assert lines[0] == "not_delegatable:no_onex"


def test_claude_code_waits_long_enough_for_a_delegation() -> None:
    """H5: the registered hook timeout covers the runner's default limit."""
    registration = json.loads(_REGISTRATION.read_text())
    hook = registration["hooks"]["PreToolUse"][0]["hooks"][0]
    script = (
        _REPO / "plugins/onex/hooks/scripts/pre_tool_use_delegation.sh"
    ).read_text()
    assert hook.get("timeout", 60) >= 240
    assert "ONEX_HOOK_DELEGATE_TIMEOUT_S" in script


def test_reinstalling_updates_an_existing_hook_to_the_current_one(
    tmp_path: Path,
) -> None:
    """H6: a re-install left an older entry for the same command in place, so the
    new timeout never reached Claude Code (seen in a real install, 2026-11-13)."""
    home = tmp_path / "home"
    config = tmp_path / "claude"
    home.mkdir()
    config.mkdir()
    tools = tmp_path / "tools"  # the installer checks that Claude Code is installed
    tools.mkdir()
    (tools / "claude").write_text("#!/bin/sh\necho '2.1.300 (Claude Code)'\n")
    (tools / "claude").chmod(0o755)
    import shutil as _shutil

    if _shutil.which("jq"):
        (tools / "jq").symlink_to(_shutil.which("jq"))
    env = {
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(config),
        "PATH": f"{tools}:/usr/bin:/bin",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    install = [
        "bash",
        str(_REPO / "scripts" / "install-delegation.sh"),
        "--apply",
        "--skip-pip",
        "--python",
        sys.executable,
        "--from-source",
        str(_REPO),
    ]
    first = subprocess.run(
        install, env=env, capture_output=True, text=True, check=False
    )
    assert first.returncode == 0, first.stdout + first.stderr
    settings_path = config / "settings.json"
    settings = json.loads(settings_path.read_text())
    for group in settings["hooks"]["PreToolUse"]:
        for hook in group["hooks"]:
            hook.pop("timeout", None)  # as an install from before the timeout
    settings_path.write_text(json.dumps(settings))
    again = subprocess.run(
        install, env=env, capture_output=True, text=True, check=False
    )
    assert again.returncode == 0, again.stdout + again.stderr
    groups = json.loads(settings_path.read_text())["hooks"]["PreToolUse"]
    delegation = [
        hook
        for group in groups
        for hook in group["hooks"]
        if "pre_tool_use_delegation.sh" in hook["command"]
    ]
    assert len(delegation) == 1
    assert delegation[0].get("timeout") == 300


def test_the_classified_task_type_is_passed_to_onex_delegate(tmp_path: Path) -> None:
    """H7."""
    document = {"run_id": "r1", "result": {"response": _ANSWER, "model_name": "m"}}
    argv_file = tmp_path / "argv"
    bin_dir = _fake_onex(
        tmp_path, f'printf "%s\\n" "$@" > {argv_file}; echo \'{json.dumps(document)}\''
    )
    lines = _run(tmp_path, f"{bin_dir}:/usr/bin:/bin")
    assert lines[0].startswith("DELEGATED: research ")
    argv = argv_file.read_text().splitlines()
    assert argv[argv.index("--task-type") + 1] == "research"
