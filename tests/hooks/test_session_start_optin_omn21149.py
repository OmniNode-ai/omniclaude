# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21149: session start is opt-in, and the observer hooks never fail silently.

Operator ruling: "Session start should be optional and manual instead of automatically getting
wired in when I start the session." The session-start banners (session goal, workspace-sync and
host-drift, hook inventory) print only for a session that opted in, through a per-session marker
in the opt-in directory or ONEX_SESSION_OPTIN=1 at launch.

The same audit found the observer hooks (all-hooks capture, Stop content capture, output metadata)
exiting 1 with nothing on stderr when no interpreter resolved, because each sources common.sh with
stderr discarded and common.sh hard-failed for any hook missing from its advisory allowlist. The
harness showed that as "Failed with non-blocking status code: No stderr output" on every tool
call, Stop and PostToolBatch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN = _REPO_ROOT / "plugins" / "onex"
_SCRIPTS = _PLUGIN / "hooks" / "scripts"
_SESSION = "0b5e7c1a-21149-optin-test"
_BANNER_HOOKS = (
    ("session_start_goal_surface.sh", "[session-goal]"),
    ("session_start_workspace_sync.sh", "[workspace-sync]"),
    ("session_start_hook_parity.sh", "[hook-inventory]"),
)
_OBSERVER_HOOKS = (
    ("claude_hook_capture.sh", "Stop"),
    ("claude_hook_capture.sh", "PostToolBatch"),
    ("stop_content_capture.sh", "Stop"),
    ("post_tool_use_output_capture_metadata.sh", "PostToolUse"),
)


def _payload(event: str, session: str = _SESSION) -> str:
    return json.dumps(
        {
            "session_id": session,
            "hook_event_name": event,
            "source": "startup",
            "cwd": str(_REPO_ROOT),
            "tool_name": "Bash",
            "tool_input": {"command": "echo ok"},
            "tool_response": {"stdout": "ok"},
            "last_assistant_message": "done",
        }
    )


def _banner_env(tmp_path: Path, optin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("ONEX_SESSION_OPTIN", "OMNICLAUDE_SESSION_INTENT", "PYTHONPATH"):
        env.pop(key, None)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = str(home)
    env["OMNICLAUDE_MODE"] = "full"
    env["ONEX_SESSION_OPTIN_DIR"] = str(optin_dir)
    env["ONEX_STATE_DIR"] = str(tmp_path / "state")
    env["ONEX_HOOKS_STATE_DIR"] = str(tmp_path / "state" / "hooks")
    registry = tmp_path / "registry"
    registry.mkdir(exist_ok=True)
    env["OMNI_HOME"] = str(registry)
    env.pop("KNOWLEDGE_BASE_INTERNAL_PATH", None)
    # The hook-inventory hook then reports SKIPPED, a line it always prints.
    env["CLAUDE_PLUGIN_ROOT"] = str(tmp_path / "elsewhere")
    return env


def _run(
    script: Path, payload: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
        check=False,
        timeout=60,
    )


@pytest.mark.parametrize(("hook", "prefix"), _BANNER_HOOKS)
def test_banner_is_silent_for_a_session_that_never_opted_in(
    tmp_path: Path, hook: str, prefix: str
) -> None:
    env = _banner_env(tmp_path, tmp_path / "optin")
    result = _run(_SCRIPTS / hook, _payload("SessionStart"), env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", result.stdout


@pytest.mark.parametrize(("hook", "prefix"), _BANNER_HOOKS)
def test_banner_prints_for_a_session_with_its_marker(
    tmp_path: Path, hook: str, prefix: str
) -> None:
    optin = tmp_path / "optin"
    optin.mkdir()
    (optin / _SESSION).write_text("opted-in\n", encoding="utf-8")
    env = _banner_env(tmp_path, optin)
    result = _run(_SCRIPTS / hook, _payload("SessionStart"), env)
    assert result.returncode == 0, result.stderr
    assert prefix in result.stdout, result.stdout


@pytest.mark.parametrize(("hook", "prefix"), _BANNER_HOOKS)
def test_another_sessions_marker_does_not_opt_this_one_in(
    tmp_path: Path, hook: str, prefix: str
) -> None:
    optin = tmp_path / "optin"
    optin.mkdir()
    (optin / "some-other-session").write_text("opted-in\n", encoding="utf-8")
    env = _banner_env(tmp_path, optin)
    result = _run(_SCRIPTS / hook, _payload("SessionStart"), env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", result.stdout


@pytest.mark.parametrize(("hook", "prefix"), _BANNER_HOOKS)
def test_launch_env_opts_in_and_zero_forces_out(
    tmp_path: Path, hook: str, prefix: str
) -> None:
    optin = tmp_path / "optin"
    optin.mkdir()
    env = _banner_env(tmp_path, optin)
    env["ONEX_SESSION_OPTIN"] = "1"
    assert prefix in _run(_SCRIPTS / hook, _payload("SessionStart"), env).stdout

    (optin / _SESSION).write_text("opted-in\n", encoding="utf-8")
    env["ONEX_SESSION_OPTIN"] = "0"
    result = _run(_SCRIPTS / hook, _payload("SessionStart"), env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", result.stdout


def test_a_payload_id_that_is_not_a_plain_token_never_opts_in(tmp_path: Path) -> None:
    optin = tmp_path / "optin"
    optin.mkdir()
    env = _banner_env(tmp_path, optin)
    script = _SCRIPTS / "session_start_workspace_sync.sh"
    result = _run(script, _payload("SessionStart", session="../optin"), env)
    assert result.stdout == "", result.stdout


def _plugin_copy_without_python(tmp_path: Path) -> Path:
    """A copy of the plugin whose ../.. holds no .venv, so no interpreter resolves."""
    root = tmp_path / "isolated" / "plugins" / "onex"
    root.mkdir(parents=True)
    shutil.copytree(_PLUGIN / "hooks", root / "hooks")
    shutil.copytree(_PLUGIN / "lib", root / "lib")
    return root


@pytest.mark.parametrize(("hook", "event"), _OBSERVER_HOOKS)
def test_observer_hook_exits_zero_when_no_python_resolves(
    tmp_path: Path, hook: str, event: str
) -> None:
    plugin = _plugin_copy_without_python(tmp_path)
    env = os.environ.copy()
    for key in (
        "CLAUDE_PLUGIN_DATA",
        "ONEX_REGISTRY_ROOT",
        "OMNICLAUDE_PROJECT_ROOT",
        "PYTHONPATH",
        "OMNICLAUDE_SESSION_INTENT",
    ):
        env.pop(key, None)
    env["PLUGIN_PYTHON_BIN"] = str(tmp_path / "no-such-python")
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin)
    env["CLAUDE_PROJECT_DIR"] = str(_REPO_ROOT)
    env["OMNICLAUDE_MODE"] = "full"
    env["HOME"] = str(tmp_path / "home")
    env["ONEX_STATE_DIR"] = str(tmp_path / "state")
    # No uv on PATH, so the inline venv repair cannot build an interpreter either.
    env["PATH"] = "/usr/bin:/bin"
    result = _run(plugin / "hooks" / "scripts" / hook, _payload(event), env)
    assert result.returncode == 0, (
        f"{hook} on {event} exited {result.returncode} with stderr {result.stderr!r}; "
        "an observer must skip, never fail, when no interpreter resolves"
    )
