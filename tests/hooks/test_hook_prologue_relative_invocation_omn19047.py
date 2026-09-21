# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A hook resolves its own path before it moves the working directory [OMN-19047].

Every hook in this tree begins by working out where it lives, because it has
to source its siblings and its library directory from there. Many of them also
stabilise the working directory, because the session directory can live on a
volume that disconnects and CPython aborts at startup when ``os.getcwd()``
fails. Both are correct. The order is not free.

``BASH_SOURCE[0]`` is whatever string the caller used, and the caller is
entitled to use a relative one -- the prologue's own comment says it handles
that case. Resolving it after a ``cd`` resolves it against the wrong
directory. ``realpath`` then fails, the ``python3`` fallback does NOT stat the
path so it cheerfully returns ``$HOME`` joined to the relative path, and the
``cd`` into that phantom directory on the next line exits 1 under
``set -euo pipefail``.

Nothing noticed for seven months. error-guard's EXIT trap swallows the failure
and exits 0 to protect the harness, so the caller sees a hook that ran and did
nothing. On 2026-09-21 a triage pass invoked 17 dark scripts by relative path
and produced 17 identical swallowed crashes.

Two tests, doing different jobs:

* :func:`test_no_hook_moves_the_working_directory_before_resolving_itself` is
  the ratchet. It is static, it covers every script in the directory, and it
  is the one that would have caught this.
* :func:`test_every_declared_hook_survives_relative_invocation` is the proof.
  It actually runs them, and it reads the verdict off error-guard's log rather
  than the exit code, because the exit code is 0 by design on this path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"
_SCRIPTS_REL = "plugins/onex/hooks/scripts"
_HOOKS_JSON = _REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json"
_INVENTORY = (
    _REPO_ROOT / "plugins" / "onex" / "hooks" / "contracts" / "hook_inventory.yaml"
)

#: The self-resolution statement every affected script opens with.
_SELF_RESOLUTION = re.compile(r"_SELF=\"\$\(realpath ")

#: A ``cd`` that changes the working directory for the rest of the script.
#: Matched at statement position only. A ``cd`` inside ``$(...)`` runs in a
#: subshell and cannot move this shell, and those are exactly how the
#: resolution itself is written, so folding them in would flag the fix.
_LEADING_CD = re.compile(r"^\s*cd\s+\S")

#: error-guard's documented refusal code. A guard that refuses a tool call
#: exits 2 after clearing the EXIT trap, so 2 is a pass, not a failure.
_BLOCK_CODE = 2


def _script_names() -> list[str]:
    return sorted(
        p.name for p in _SCRIPTS_DIR.iterdir() if p.is_file() and p.suffix == ".sh"
    )


def _declared_scripts() -> list[str]:
    """Every script the inventory declares, expected or disabled.

    This is the population, not ``hooks.json`` alone. Only 3 of the 30
    registered hooks carried the defect, while 23 of the 68 declared ones did:
    a test scoped to the registered set would have passed over this and is the
    reason the operator's first read of the incident was that dark scripts do
    not matter.
    """
    inventory = yaml.safe_load(_INVENTORY.read_text(encoding="utf-8"))
    names = {
        row["script"]
        for key in ("expected_hooks", "disabled_hooks")
        for row in (inventory.get(key) or [])
    }
    registered = {
        hook["command"].rsplit("/", 1)[-1]
        for groups in json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))[
            "hooks"
        ].values()
        for group in groups
        for hook in group.get("hooks", [])
    }
    return sorted(n for n in names | registered if (_SCRIPTS_DIR / n).is_file())


def _payload_for(script: str) -> str:
    """A canned harness payload shaped for the event the filename declares."""
    base = {
        "session_id": "omn19047-smoke",
        "transcript_path": "/dev/null",
        "cwd": str(_REPO_ROOT),
    }
    if script.startswith(("pre_tool_use", "pre-tool-use")):
        base |= {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/dev/null"},
        }
    elif script.startswith(("post_tool_use", "post-tool-use")):
        base |= {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/dev/null"},
            "tool_response": {"output": ""},
        }
    elif script.startswith(("user_prompt", "user-prompt")):
        base |= {"hook_event_name": "UserPromptSubmit", "prompt": "hello"}
    elif script.startswith(("session_start", "session-start")):
        base |= {"hook_event_name": "SessionStart", "source": "startup"}
    elif script.startswith(("session_end", "session-end")):
        base |= {"hook_event_name": "SessionEnd", "reason": "clear"}
    elif script.startswith(("subagent_stop", "subagent-stop")):
        base |= {"hook_event_name": "SubagentStop", "stop_hook_active": False}
    elif script.startswith("stop"):
        base |= {"hook_event_name": "Stop", "stop_hook_active": False}
    elif script.startswith("notification"):
        base |= {"hook_event_name": "Notification", "message": "idle"}
    else:
        base |= {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}}
    return json.dumps(base)


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


def test_no_hook_moves_the_working_directory_before_resolving_itself() -> None:
    """Static, whole-directory, and the control that was missing.

    Asserted over every script rather than the declared ones, because a script
    acquires the defect when it is written, long before anybody decides
    whether it should be registered.
    """
    offenders: list[str] = []
    for name in _script_names():
        lines = (_SCRIPTS_DIR / name).read_text(encoding="utf-8").splitlines()
        resolution = next(
            (i for i, text in enumerate(lines) if _SELF_RESOLUTION.search(text)), None
        )
        if resolution is None:
            continue
        first_cd = next(
            (i for i, text in enumerate(lines) if _LEADING_CD.match(text)), None
        )
        if first_cd is not None and first_cd < resolution:
            offenders.append(
                f"{name}: cd at line {first_cd + 1}, _SELF at line {resolution + 1}"
            )
    assert offenders == [], (
        "these scripts change the working directory before resolving "
        "BASH_SOURCE[0], so a relative invocation resolves against the wrong "
        "directory and the script exits 1 into error-guard:\n  "
        + "\n  ".join(offenders)
    )


def test_the_realpath_fallback_refuses_a_path_that_does_not_exist() -> None:
    """``os.path.realpath`` does not stat, so the fallback has to.

    Without this the fallback answers for a file that is not there, and the
    failure surfaces one line later as a ``cd`` into a directory nobody can
    name. That indirection is why the incident read as a plugin problem.
    """
    stale = [
        name
        for name in _script_names()
        if "print(os.path.realpath(sys.argv[1]))"
        in (_SCRIPTS_DIR / name).read_text(encoding="utf-8")
    ]
    assert stale == [], (
        "these scripts fall back to a realpath that never checks existence, so "
        "they return a phantom path instead of failing: " + ", ".join(stale)
    )


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", _declared_scripts())
def test_every_declared_hook_survives_relative_invocation(
    script: str, tmp_path: Path
) -> None:
    """Run it the way the triage pass ran it, and read error-guard's log.

    The exit code is deliberately not the assertion. error-guard's EXIT trap
    converts any non-zero exit to 0 so the harness never sees a hook fault,
    which is correct behaviour and also the reason this went unnoticed. The
    log it writes on the way past is the only honest signal, so the test
    points ``_ERROR_GUARD_LOG_DIR`` at a temporary directory and asserts
    nothing lands in it.
    """
    guard_log = tmp_path / "error-guard"
    # The state tree a live session already has. A hook appending to a log
    # under a directory that does not exist is an absent fixture, not a
    # defect, and leaving it absent would make this test red for the wrong
    # reason on every machine.
    state = tmp_path / "state"
    for sub in ("logs", "hooks/logs", "hooks/lanes"):
        (state / sub).mkdir(parents=True, exist_ok=True)
    env = os.environ | {
        "_ERROR_GUARD_LOG_DIR": str(guard_log),
        "ONEX_STATE_DIR": str(state),
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "CLAUDE_PLUGIN_ROOT": str(_REPO_ROOT / "plugins" / "onex"),
        "OMNICLAUDE_MODE": "full",
        # Supplied by the harness in a real session; unrelated to this defect.
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
    }
    # No alert channel: a crash must not try to reach Slack from a test.
    for leaked in ("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID"):
        env.pop(leaked, None)

    completed = subprocess.run(  # noqa: S603
        ["bash", f"{_SCRIPTS_REL}/{script}"],
        check=False,
        cwd=_REPO_ROOT,
        input=_payload_for(script),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    errors = guard_log / "errors.log"
    swallowed = errors.read_text(encoding="utf-8") if errors.is_file() else ""
    assert "HOOK FAILURE" not in swallowed, (
        f"{script} crashed under relative invocation and error-guard swallowed "
        f"it:\n{swallowed}\nstderr:\n{completed.stderr[-2000:]}"
    )
    assert completed.returncode in (0, _BLOCK_CODE), (
        f"{script} exited {completed.returncode}; expected 0 or the documented "
        f"block code {_BLOCK_CODE}\nstderr:\n{completed.stderr[-2000:]}"
    )
