# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegate skill sets the model delegation tries first (OMN-21346).

A developer who finished onboarding chooses, from inside Claude Code, which of
their models delegation tries first, without going back to the terminal and
without re-running onboarding. The skill's procedure (`prompt.md`, section
"Choosing the model") names the commands it runs. This module reads those
commands out of the skill, runs them with the real `onex` CLI installed beside
this interpreter, in a scratch home that holds what onboarding leaves (two local
models, first tried first), and reads `onex models list` back.

No model is called and no key is read: choosing and listing touch only the
local routes file and the record of the choice.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROMPT = Path(__file__).resolve().parents[1] / "skills" / "delegate" / "prompt.md"
SKILL = Path(__file__).resolve().parents[1] / "skills" / "delegate" / "SKILL.md"

_FIRST = "model-a"
_SECOND = "model-b"

#: What onboarding leaves for two local models on one server: the second is
#: declared after the first, so the first is tried first.
_OVERLAY = "".join(
    f"""  - backend_id: {backend_id}
    endpoint_url: http://127.0.0.1:9/v1/chat/completions
    model_name: {model}
    provider: local
    tier: local
    timeout_ms: 300000
    max_tokens: 8192
    secret_ref: null
"""
    for backend_id, model in (("local-url", _FIRST), ("local-url-2", _SECOND))
)


def _skill_commands() -> list[str]:
    """The commands the skill's "Choosing the model" section runs, in order."""
    text = PROMPT.read_text(encoding="utf-8")
    section = text.split("## Choosing the model", 1)
    assert len(section) == 2, "prompt.md has no 'Choosing the model' section"
    block = re.search(r"```bash\n(.*?)```", section[1], re.DOTALL)
    assert block is not None, "the section names its commands in a bash block"
    return [line.strip() for line in block.group(1).splitlines() if line.strip()]


def _command(prefix: str, **values: str) -> list[str]:
    """The skill's command starting with ``prefix``, its placeholders filled in."""
    (line,) = [c for c in _skill_commands() if c.startswith(prefix)]
    for name, value in values.items():
        line = line.replace(f"<{name}>", value)
    assert "<" not in line, f"unfilled placeholder in {line!r}"
    return shlex.split(line)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    state = tmp_path / ".omninode" / "delegation"
    state.mkdir(parents=True)
    (state / "bifrost_overrides.yaml").write_text(
        "backends:\n" + _OVERLAY, encoding="utf-8"
    )
    return tmp_path


def _onex() -> str:
    found = Path(sys.executable).parent / "onex"
    assert found.exists(), f"no onex console script beside {sys.executable}"
    return str(found)


def _run(argv: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    assert argv[0] == "onex"
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [_onex(), *argv[1:]],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        timeout=300,
        check=False,
    )


def _listed(home: Path) -> list[dict[str, object]]:
    shown = _run([*_command("onex models list"), "--json"], home)
    assert shown.returncode == 0, shown.stderr
    return [
        json.loads(line) for line in shown.stdout.splitlines() if line.startswith("{")
    ]


def test_the_skill_names_list_choose_and_clear() -> None:
    commands = _skill_commands()
    assert "onex models list" in commands
    assert "onex models first <provider> <model>" in commands
    assert "onex models first --clear" in commands
    usage = SKILL.read_text(encoding="utf-8")
    assert "/onex:delegate models first" in usage


def test_choosing_through_the_skill_lists_that_model_first(home: Path) -> None:
    before = _listed(home)
    assert before[0]["provider"] != "local" or before[0]["tried_first"] is False

    chosen = _run(
        _command("onex models first <provider>", provider="local", model=_SECOND),
        home,
    )
    assert chosen.returncode == 0, chosen.stderr
    assert f"Delegation now tries Local URL {_SECOND} first" in chosen.stdout

    rows = _listed(home)
    assert rows[0]["provider"] == "local"
    assert rows[0]["tried_first"] is True
    assert rows[0]["models"] == [_SECOND, _FIRST]

    text = _run(_command("onex models list"), home)
    assert text.returncode == 0, text.stderr
    first_line = text.stdout.splitlines()[0]
    assert first_line.startswith("Local URL")
    assert f"tried first: {_SECOND}" in first_line

    cleared = _run(_command("onex models first --clear"), home)
    assert cleared.returncode == 0, cleared.stderr
    assert not any(row["tried_first"] for row in _listed(home))
