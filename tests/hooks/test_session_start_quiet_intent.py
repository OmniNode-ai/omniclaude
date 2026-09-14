# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The four SessionStart hooks consult the session intent [OMN-18368].

Before this ticket there were two silencing mechanisms and neither reached these
four scripts for the case that matters. The plugin mode resolves to ``full`` for
any session opened inside the workspace, which is exactly the re-authentication
session that wants no output; and the hook bitmask has a per-hook gate function
that none of the four session-start scripts calls. The only off switch was
editing the hook manifest, which is a plugin change.

This module pins the third axis. For each of the four hooks:

* under the ``quiet`` intent it writes **zero bytes** to stdout and stderr, and
  does no work whose side effects would outlive the session;
* under the ``normal`` intent its output is unchanged — each case below drives
  the hook into a deterministic, non-empty output state and asserts that state
  survives.

One exception is asserted rather than left implicit: the workspace-sync hook's
load-path ALARM prints under **every** intent. That alarm reports that the tree
these hooks are loaded from is stale or bare, which means every guard merged
since is dark on this session. Silence is the failure mode it exists to break,
so an intent cannot suppress it — and a session that asked for quiet gets
exactly that one blocker and nothing else, which is the plan's stated falsifier.

Hermetic: no case reads the developer's ``~/.config``, the real state directory,
or the real knowledge-base clone. The ALARM case builds its own bare git tree
and copies the plugin's own scripts into it, so the hook under test is the real
script, run from a tree whose git state the test controls.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN = _REPO_ROOT / "plugins" / "onex"
_SCRIPTS = _PLUGIN / "hooks" / "scripts"

_BUS_MIRROR = _SCRIPTS / "session_start_bus_mirror.sh"
_GOAL_SURFACE = _SCRIPTS / "session_start_goal_surface.sh"
_WORKSPACE_SYNC = _SCRIPTS / "session_start_workspace_sync.sh"
_HOOK_PARITY = _SCRIPTS / "session_start_hook_parity.sh"

_ALL_FOUR = [_BUS_MIRROR, _GOAL_SURFACE, _WORKSPACE_SYNC, _HOOK_PARITY]

_STDIN = '{"session_id":"sess-intent-01","cwd":"/tmp"}'


def _plant_plugin_tree(tmp_path: Path, *, bare: bool) -> Path:
    """Copy the real plugin scripts into a git tree whose state we control.

    The workspace-sync hook's load-path alarm reads the git configuration of the
    tree it is executing from. That tree is this checkout, which the test does
    not own: a CI checkout can legitimately sit behind its upstream, and then
    the alarm fires and every silence assertion reads as a failure of the intent
    gate. Planting a copy makes the git state an input of the test.
    """
    root = tmp_path / "planted"
    dest = root / "plugins" / "onex"
    dest.mkdir(parents=True)
    shutil.copytree(_PLUGIN / "lib", dest / "lib")
    (dest / "hooks").mkdir()
    shutil.copytree(_PLUGIN / "hooks" / "scripts", dest / "hooks" / "scripts")
    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n"
        f"\tbare = {'true' if bare else 'false'}\n"
    )
    return root


def _planted_script(tmp_path: Path, *, bare: bool) -> Path:
    root = _plant_plugin_tree(tmp_path, bare=bare)
    return (
        root
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "session_start_workspace_sync.sh"
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    """An environment with every surface these hooks read pointed at tmp_path."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    state = tmp_path / "state"
    (state / "hooks").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for var in (
        "OMNICLAUDE_SESSION_INTENT",
        "KNOWLEDGE_BASE_INTERNAL_PATH",
        "OMNI_HOME",
        "CLAUDE_PLUGIN_ROOT",
        "CLAUDE_PROJECT_DIR",
    ):
        env.pop(var, None)
    env["HOME"] = str(home)
    env["ONEX_HOOKS_STATE_DIR"] = str(state / "hooks")
    env["ONEX_STATE_DIR"] = str(state)
    # Pin mode so a lite-mode early exit cannot be mistaken for intent working.
    env["OMNICLAUDE_MODE"] = "full"
    return env


def _run(
    script: Path,
    env: dict[str, str],
    *,
    intent: str | None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env)
    if intent is not None:
        run_env["OMNICLAUDE_SESSION_INTENT"] = intent
    return subprocess.run(
        ["bash", str(script)],
        input=_STDIN,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=run_env,
        cwd=str(cwd) if cwd else None,
    )


def _assert_silent(result: subprocess.CompletedProcess[str], script: Path) -> None:
    assert result.stdout == "", (
        f"{script.name} printed to stdout under the quiet intent. A session "
        f"opened only to re-authenticate must see nothing.\n{result.stdout}"
    )
    assert result.stderr == "", (
        f"{script.name} printed to stderr under the quiet intent.\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"{script.name} must still exit 0 under quiet — silencing output is not "
        f"licence to fail a session start. stderr:\n{result.stderr}"
    )


# --------------------------------------------------------------------------- #
# Every hook is silent under quiet, in one shared environment
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("script", _ALL_FOUR, ids=lambda p: p.stem)
def test_quiet_intent_produces_zero_bytes(tmp_path: Path, script: Path) -> None:
    """The headline property, asserted against each of the four real scripts."""
    if script == _WORKSPACE_SYNC:
        # This hook's load-path ALARM reads the git state of the tree it runs
        # from, which is this checkout — a shared input the test does not own,
        # and one CI can legitimately leave behind its upstream. Run the real
        # script from a planted tree whose git state the test controls, so a
        # non-empty result means the intent gate failed and nothing else.
        script = _planted_script(tmp_path, bare=False)
    env = _base_env(tmp_path)
    # Drive every hook into the state where it has the most to say, so a silent
    # result is the intent working and not an unrelated early exit.
    kb = tmp_path / "kb"
    (kb / "beta").mkdir(parents=True)
    ts = (datetime.now(UTC) - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (kb / "beta" / "GOAL.md").write_text(f"---\nstate_as_of: {ts}\n---\n| 1 | row |\n")
    env["KNOWLEDGE_BASE_INTERNAL_PATH"] = str(kb)
    env["OMNI_HOME"] = str(tmp_path / "registry")
    (tmp_path / "registry").mkdir(exist_ok=True)
    status = Path(env["ONEX_HOOKS_STATE_DIR"]) / "workspace-reconcile.status"
    status.write_text("DRIFT: a clone is not pulled\n")

    _assert_silent(_run(script, env, intent="quiet"), script)


# --------------------------------------------------------------------------- #
# Under normal, each hook's output is unchanged
# --------------------------------------------------------------------------- #


def test_goal_surface_prints_the_goal_under_normal(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    kb = tmp_path / "kb"
    (kb / "beta").mkdir(parents=True)
    ts = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (kb / "beta" / "GOAL.md").write_text(
        f"---\nstate_as_of: {ts}\n---\n| 1 | staging repin | HOLD |\n"
    )
    env["KNOWLEDGE_BASE_INTERNAL_PATH"] = str(kb)

    result = _run(_GOAL_SURFACE, env, intent="normal")

    assert result.returncode == 0, result.stderr
    assert ts in result.stdout, f"normal output changed:\n{result.stdout}"
    assert "staging repin" in result.stdout, f"normal output changed:\n{result.stdout}"


def test_goal_surface_prints_the_unset_block_under_normal(tmp_path: Path) -> None:
    """The fail-fast config path is part of 'unchanged under normal' too."""
    env = _base_env(tmp_path)
    result = _run(_GOAL_SURFACE, env, intent="normal")
    assert result.returncode == 0, result.stderr
    assert "KNOWLEDGE_BASE_INTERNAL_PATH" in result.stdout


def test_workspace_sync_prints_its_line_under_normal(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["OMNI_HOME"] = str(tmp_path / "registry")
    (tmp_path / "registry").mkdir(exist_ok=True)
    status = Path(env["ONEX_HOOKS_STATE_DIR"]) / "workspace-reconcile.status"
    status.write_text("clones/venv: in sync as of 2026-09-14T00:00:00Z\n")

    result = _run(_WORKSPACE_SYNC, env, intent="normal")

    assert result.returncode == 0, result.stderr
    assert "clones/venv: in sync" in result.stdout, (
        f"normal output changed:\n{result.stdout}"
    )


def test_hook_parity_prints_its_skip_block_under_normal(tmp_path: Path) -> None:
    """With no resolvable tree the parity hook names the missing variable.

    That block is deterministic, unlike a real parity run, which is why it is
    the case used to prove normal output survives the intent gate.
    """
    env = _base_env(tmp_path)
    plugin_root = tmp_path / "not-a-plugin" / "plugins" / "onex"
    plugin_root.mkdir(parents=True)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    result = _run(_HOOK_PARITY, env, intent="normal")

    assert result.returncode == 0, result.stderr
    assert "[hook-inventory]" in result.stdout, (
        f"normal output changed:\n{result.stdout}"
    )
    assert "OMNI_HOME" in result.stdout


def test_hook_parity_is_silent_under_quiet_in_the_same_state(tmp_path: Path) -> None:
    """The same environment as the case above, with only the intent changed."""
    env = _base_env(tmp_path)
    plugin_root = tmp_path / "not-a-plugin" / "plugins" / "onex"
    plugin_root.mkdir(parents=True)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    _assert_silent(_run(_HOOK_PARITY, env, intent="quiet"), _HOOK_PARITY)


def test_bus_mirror_does_no_work_under_quiet(tmp_path: Path) -> None:
    """Silence is not enough for a hook that never printed anything anyway.

    The bus mirror's observable is its log directory, which it creates before it
    dispatches. Under quiet it must return before that, so the directory is the
    proof that the intent gate sits ahead of the work and not merely ahead of a
    print the hook does not do.
    """
    env = _base_env(tmp_path)
    log_dir = Path(env["ONEX_STATE_DIR"]) / "hooks" / "logs"
    shutil.rmtree(log_dir, ignore_errors=True)

    _assert_silent(_run(_BUS_MIRROR, env, intent="quiet"), _BUS_MIRROR)

    assert not log_dir.exists(), (
        "The bus mirror created its log directory under the quiet intent, so the "
        "intent gate is placed after the work it is meant to skip."
    )


# --------------------------------------------------------------------------- #
# The one exception: a blocker still prints under quiet
# --------------------------------------------------------------------------- #


def test_load_path_alarm_prints_under_quiet(tmp_path: Path) -> None:
    """Merged-but-dark hooks are the one thing quiet may not hide.

    This is the plan's falsifier for step 1: the same session that prints zero
    lines when healthy prints exactly the blocker when the tree these hooks load
    from cannot have received a merged change.
    """
    script = _planted_script(tmp_path, bare=True)
    env = _base_env(tmp_path)
    env["OMNI_HOME"] = str(tmp_path / "registry")
    (tmp_path / "registry").mkdir(exist_ok=True)
    status = Path(env["ONEX_HOOKS_STATE_DIR"]) / "workspace-reconcile.status"
    status.write_text("clones/venv: in sync as of 2026-09-14T00:00:00Z\n")

    result = _run(script, env, intent="quiet")

    assert result.returncode == 0, result.stderr
    assert "ALARM" in result.stdout, (
        "A quiet session must still be told that the tree its hooks load from is "
        f"bare, because every guard merged since is dark on it.\n{result.stdout}"
    )
    assert "core.bare=true" in result.stdout
    assert "in sync" not in result.stdout, (
        "Quiet prints the blocker and nothing else — the routine status line "
        f"must still be suppressed.\n{result.stdout}"
    )


def test_healthy_planted_tree_is_silent_under_quiet(tmp_path: Path) -> None:
    """The positive control for the case above: same fixture, not bare.

    Without this, the ALARM assertion would pass just as well against a hook
    that printed unconditionally.
    """
    script = _planted_script(tmp_path, bare=False)
    env = _base_env(tmp_path)
    env["OMNI_HOME"] = str(tmp_path / "registry")
    (tmp_path / "registry").mkdir(exist_ok=True)
    status = Path(env["ONEX_HOOKS_STATE_DIR"]) / "workspace-reconcile.status"
    status.write_text("clones/venv: in sync as of 2026-09-14T00:00:00Z\n")

    _assert_silent(_run(script, env, intent="quiet"), script)


def test_planted_bare_tree_alarms_under_normal_too(tmp_path: Path) -> None:
    """Positive control on the other axis: the alarm is not quiet-only."""
    script = _planted_script(tmp_path, bare=True)
    env = _base_env(tmp_path)
    env["OMNI_HOME"] = str(tmp_path / "registry")
    (tmp_path / "registry").mkdir(exist_ok=True)

    result = _run(script, env, intent="normal")

    assert "ALARM" in result.stdout, result.stdout


# --------------------------------------------------------------------------- #
# The tick intent
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "script", [_GOAL_SURFACE, _WORKSPACE_SYNC, _HOOK_PARITY], ids=lambda p: p.stem
)
def test_tick_intent_prints_nothing_to_the_transcript(
    tmp_path: Path, script: Path
) -> None:
    """A scheduled workflow's session has a receipt; it does not need a banner."""
    if script == _WORKSPACE_SYNC:
        script = _planted_script(tmp_path, bare=False)
    env = _base_env(tmp_path)
    kb = tmp_path / "kb"
    (kb / "beta").mkdir(parents=True)
    (kb / "beta" / "GOAL.md").write_text("| 1 | row |\n")
    env["KNOWLEDGE_BASE_INTERNAL_PATH"] = str(kb)
    env["OMNI_HOME"] = str(tmp_path / "registry")
    (tmp_path / "registry").mkdir(exist_ok=True)
    status = Path(env["ONEX_HOOKS_STATE_DIR"]) / "workspace-reconcile.status"
    status.write_text("clones/venv: in sync as of 2026-09-14T00:00:00Z\n")

    result = _run(script, env, intent="tick")

    assert result.stdout == "", f"{script.name} under tick:\n{result.stdout}"
    assert result.returncode == 0, result.stderr


def test_bus_mirror_still_records_under_tick(tmp_path: Path) -> None:
    """Tick is workspace process, so the session event is still mirrored.

    This is the asymmetry that makes the bus mirror's intent consultation real
    rather than a copy of the other three: quiet skips the work, tick does not.
    """
    env = _base_env(tmp_path)
    log_dir = Path(env["ONEX_STATE_DIR"]) / "hooks" / "logs"
    shutil.rmtree(log_dir, ignore_errors=True)

    result = _run(_BUS_MIRROR, env, intent="tick")

    assert result.returncode == 0, result.stderr
    assert log_dir.exists(), (
        "Under tick the bus mirror must do its work — a scheduled session is "
        "still this workspace's process."
    )


# --------------------------------------------------------------------------- #
# Every registered SessionStart hook, not only the four that exist today
# --------------------------------------------------------------------------- #


def test_every_registered_session_start_hook_consults_the_intent() -> None:
    """A fifth hook added later must not reopen the hole this ticket closed.

    The four cases above prove behaviour for the four scripts registered today.
    This one reads the registration surface itself, so a hook added to the
    SessionStart chain that never consults the resolver fails here rather than
    printing over a session that asked for silence.
    """
    import json

    hooks_json = _PLUGIN / "hooks" / "hooks.json"
    registered = json.loads(hooks_json.read_text())["hooks"]["SessionStart"]
    commands = [
        entry["command"]
        for matcher in registered
        for entry in matcher.get("hooks", [])
        if entry.get("type") == "command"
    ]
    assert commands, "precondition: SessionStart has registered command hooks"

    missing: list[str] = []
    for command in commands:
        name = command.rsplit("/", 1)[-1]
        script = _SCRIPTS / name
        assert script.is_file(), f"registered SessionStart hook not on disk: {name}"
        body = script.read_text()
        if "lib/intent.sh" not in body:
            missing.append(name)

    assert not missing, (
        "These SessionStart hooks do not consult the session-intent resolver, so "
        "a session opened with the quiet intent would still see their output: "
        + ", ".join(missing)
    )
