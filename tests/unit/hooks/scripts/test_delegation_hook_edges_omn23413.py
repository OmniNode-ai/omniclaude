# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Edge cases of the two delegation hooks (OMN-23413, Amendment 11).

Delegation is two hooks under one switch: the prompt hook (UserPromptSubmit)
and the subagent hook (PreToolUse ^(Agent|Task)$). Both run
pre_tool_use_delegation.sh; ONEX_DELEGATION_HOOK labels each row, since the
operator ruling of 2026-10-01 admits no new scripts. Failure modes:

  H1  Claude Code's settings cannot tell the two hooks apart.
  H2  a labelled hook does not do its job (prompt block, subagent exit 2), or
      its log line does not name it.
  H3  without jq the prompt hook prints its input, which Claude Code adds to the
      conversation: the whole envelope, prompt and transcript path included.
  H4  a secret said earlier in the session reaches the delegated model inside
      the recent conversation, because only the new prompt was checked; or,
      over-correcting, one email address in the session stops all delegation.
  H5  a sensitivity gate that is missing or raises lets the text through.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.hooks.scripts.test_prompt_delegation_ac33_omn23413 import (
    _ANSWER,
    _calls,
    _doc,
    _fake_onex,
    _plugin_with_stub_runner,
    _prompt,
    _run,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[4]
_PLUGIN = _REPO / "plugins" / "onex"
_MANIFEST = _PLUGIN / "hooks" / "hooks-delegation.v1.json"
_SCRIPT = "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_delegation.sh"
_AGENT = {
    "session_id": "edges",
    "hook_event_name": "PreToolUse",
    "tool_name": "Agent",
    "tool_input": {"prompt": "How do TCP and UDP differ?", "description": "q"},
}


def _commands(event: str) -> list[tuple[str | None, str]]:
    rows = json.loads(_MANIFEST.read_text())["hooks"][event]
    return [(g.get("matcher"), h["command"]) for g in rows for h in g["hooks"]]


# --- H1, H2: each hook is labelled -----------------------------------------------


def test_each_delegation_hook_is_labelled_in_claude_settings() -> None:
    """H1."""
    assert _commands("UserPromptSubmit") == [
        (None, f"ONEX_DELEGATION_HOOK=prompts {_SCRIPT}")
    ]
    assert _commands("PreToolUse") == [
        ("^(Agent|Task)$", f"ONEX_DELEGATION_HOOK=subagents {_SCRIPT}")
    ]


def _tools_without(tmp_path: Path, *missing: str) -> Path:
    """A PATH folder holding every /usr/bin and /bin tool except ``missing``."""
    tools = tmp_path / "tools-without"
    tools.mkdir(exist_ok=True)
    for folder in ("/usr/bin", "/bin"):
        for entry in Path(folder).iterdir():
            target = tools / entry.name
            if entry.name in missing or target.exists():
                continue
            target.symlink_to(entry)
    return tools


def _hook(
    tmp_path: Path,
    plugin: Path,
    label: str | None,
    payload: dict,
    *,
    path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the hook as its settings row does: ONEX_DELEGATION_HOOK=label script."""
    home = tmp_path / "home"
    marker = home / ".omninode" / "delegation" / "hooks-delegation.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}")
    if path is None:
        tools = tmp_path / "tools"
        tools.mkdir(exist_ok=True)
        jq = shutil.which("jq")
        assert jq, "jq is required by the hook"
        if not (tools / "jq").exists():
            (tools / "jq").symlink_to(jq)
        path = f"{tools}:/usr/bin:/bin"
    return subprocess.run(
        ["/bin/bash", str(plugin / "hooks" / "scripts" / "pre_tool_use_delegation.sh")],
        input=json.dumps(payload) + "\n",
        env={
            "HOME": str(home),
            "PATH": path,
            "TMPDIR": str(tmp_path),
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "ONEX_HOOKS_MASK": "0xffffffff",
            "PLUGIN_PYTHON_BIN": sys.executable,
            "CLAUDE_PLUGIN_ROOT": str(plugin),
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            **({"ONEX_DELEGATION_HOOK": label} if label else {}),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_the_prompt_hook_blocks_with_the_delegated_answer(tmp_path: Path) -> None:
    """H2: the prompts row prints the runner's block unchanged and is named in the log."""
    block = json.dumps({"decision": "block", "reason": _ANSWER})
    plugin = _plugin_with_stub_runner(tmp_path, block + "\n")
    proc = _hook(tmp_path, plugin, "prompts", _prompt("How do TCP and UDP differ?"))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"decision": "block", "reason": _ANSWER}
    log = (
        tmp_path / "state" / "hooks" / "logs" / "pre-tool-delegation.log"
    ).read_text()
    assert "[pre_tool_use_delegation.sh[prompts]] PROMPT" in log


def test_the_subagent_hook_blocks_with_exit_2(tmp_path: Path) -> None:
    """H2: the subagents row hands the answer back in place of the subagent."""
    plugin = _plugin_with_stub_runner(
        tmp_path, f"DELEGATED: research answered by m (run r-agent)\n{_ANSWER}\n"
    )
    proc = _hook(tmp_path, plugin, "subagents", _AGENT)
    assert proc.returncode == 2
    assert _ANSWER in proc.stderr


# --- H3: no jq ---------------------------------------------------------------


@pytest.mark.parametrize("label", ["prompts", None])
def test_without_jq_a_prompt_prints_nothing(tmp_path: Path, label: str | None) -> None:
    """H3: never the envelope; the prompt goes to Claude as typed."""
    plugin = _plugin_with_stub_runner(tmp_path, "unused\n")
    tools = _tools_without(tmp_path, "jq")
    payload = _prompt("How do TCP and UDP differ?", transcript=tmp_path / "t.jsonl")
    proc = _hook(tmp_path, plugin, label, payload, path=str(tools))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_without_jq_a_subagent_call_still_passes_through(tmp_path: Path) -> None:
    """H3 control: the tool call is echoed and runs natively."""
    plugin = _plugin_with_stub_runner(tmp_path, "unused\n")
    tools = _tools_without(tmp_path, "jq")
    proc = _hook(tmp_path, plugin, "subagents", _AGENT, path=str(tools))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == _AGENT


# --- H4: a secret earlier in the session ---------------------------------------


def _transcript(tmp_path: Path, *user_lines: str) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"type": "user", "message": {"content": line}})
            for line in user_lines
        )
        + "\n"
    )
    return path


def test_a_secret_earlier_in_the_session_is_never_sent(tmp_path: Path) -> None:
    """H4: the prompt is delegated without the sensitive conversation."""
    bin_dir = _fake_onex(tmp_path, [_doc(_ANSWER, "r-secret")])
    secret = "password=" + "hunter2-" + "x" * 8
    transcript = _transcript(tmp_path, f"my db login is {secret}", "now about TCP")
    out = json.loads(
        _run(
            tmp_path,
            _prompt("How do TCP and UDP differ?", transcript=transcript),
            bin_dir,
        )
    )
    assert out["decision"] == "block"
    (argv,) = _calls(tmp_path)
    sent = " ".join(argv)
    assert "hunter2" not in sent
    assert "now about TCP" not in sent  # the whole excerpt is withheld
    assert "How do TCP and UDP differ?" in sent


def test_a_clean_session_is_delegated_with_its_conversation(tmp_path: Path) -> None:
    """H4 control: ordinary conversation still goes with the prompt."""
    bin_dir = _fake_onex(tmp_path, [_doc(_ANSWER, "r-clean")])
    transcript = _transcript(tmp_path, "we were talking about networking")
    out = json.loads(
        _run(
            tmp_path,
            _prompt("How do TCP and UDP differ?", transcript=transcript),
            bin_dir,
        )
    )
    assert out["decision"] == "block"
    (argv,) = _calls(tmp_path)
    assert "we were talking about networking" in " ".join(argv)


def test_a_secret_in_the_prompt_itself_keeps_it_with_claude(tmp_path: Path) -> None:
    """H4 control: the prompt's own secret still sends nothing."""
    bin_dir = _fake_onex(tmp_path, [_doc(_ANSWER, "r-own")])
    prompt = "is this ok: password=" + "hunter2-" + "x" * 8
    assert _run(tmp_path, _prompt(prompt), bin_dir) == ""
    assert _calls(tmp_path) == []


# --- H5: the gate fails closed --------------------------------------------------


def _runner_module():
    path = _PLUGIN / "hooks" / "lib" / "delegation_hook_runner.py"
    spec = importlib.util.spec_from_file_location("delegation_hook_runner_edges", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_missing_gate_keeps_text_with_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """H5."""
    runner = _runner_module()
    monkeypatch.setattr(runner, "_import_gate", lambda: None)
    assert runner._sensitive("what is TCP?") is True
    assert runner._sensitive("") is False


def test_a_gate_that_raises_keeps_text_with_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H5."""
    runner = _runner_module()

    class _Broken:
        def check(self, _text: str) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_import_gate", _Broken)
    assert runner._sensitive("what is TCP?") is True
