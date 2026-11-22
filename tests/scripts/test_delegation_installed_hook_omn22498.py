# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The installed delegation hook script runs as the native mod invokes it (OMN-22498, OMN-23413).

``scripts/install-delegation.sh --apply`` copies the hook tree under
``~/.omninode/delegation`` and registers the native plugin; nothing is written
into ``~/.claude/settings.json``. The native mod (``native_delegation.ts``) runs
``hooks/scripts/pre_tool_use_delegation.sh`` with ``PLUGIN_PYTHON_BIN`` taken
from the plugin's ``hooks/delegation-runtime.json``, with no
``CLAUDE_PLUGIN_ROOT``, from the customer's own project. These tests install
into a scratch HOME (stub claude CLI) and run the installed script exactly that
way: they cover the shell/runner boundary of the installed copy and the switch.
They do not read a registration; the registration call and the marketplace it
names are covered by ``test_native_delegation_install.py`` (stub CLI, and the
real CLI where one is installed).

Failure modes:
  F1. A helper the hook sources (error-guard.sh and what it loads) is not
      copied, so the hook dies before doing anything (exit 1 under /bin/bash
      3.2) or its gate function is undefined and it passes everything through.
  F2. The routing runner (hooks/lib/delegation_hook_runner.py) or the helpers
      the hook resolves relative to itself (mode.sh, repo_guard.sh) are not
      installed, so the hook never reaches a routing decision.
  F3. The installed copy ignores the switch: with bit 11 off it still routes.
  F5. `onex hooks disable` saves the mask in ~/.omnibase/.env; the installed
      hook ignored it, because only common.sh reads that file.
  F4. No Python is found: the installed script gets no interpreter from its
      environment, so the installer's binding (delegation-runtime.json, which
      the native mod passes as PLUGIN_PYTHON_BIN) must name a usable one. The
      test environment sets none of its own.
  F6. The scenario is not the customer's: a python3 on the caller's PATH that
      imports a dev-workspace omnibase_core makes mode.sh resolve to full, so
      the lite default is never exercised (dod-closeout-sweep, 2026-11-11). The
      hook runs with a customer PATH, and a control asserts that mode.sh
      resolves to lite in that same environment.
  F7. The real `onex hooks disable` / `onex hooks enable` do not reach the
      installed hook: the switch is saved somewhere the hook never reads.

"Reached the routing runner" is read from the hook's own log: it writes
``PASS tool=...`` or ``BLOCK tool=...`` after the runner returned, and
``WARN: runner exited N`` when the runner started but exited non-zero (a cold
start can pass the hook's 5 s limit, as on a hosted runner). Each proves the
installed copy found its Python and its runner. The failures above write
``WARN: no Python found`` or ``WARN: runner not found``, or no log at all.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "scripts" / "install-delegation.sh"

_DEFAULT_MASK = 0xFFFFFFFFFFFFFFF
_BIT_11 = 0x800

_AGENT_CALL = json.dumps(
    {
        "tool_name": "Agent",
        "session_id": "omn22498-installed",
        "tool_input": {"prompt": "write a haiku", "subagent_type": "general-purpose"},
    }
)


def _install(tmp_path: Path) -> Path:
    """Run the real installer into a scratch HOME and return that HOME."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    claude = stub_bin / "claude"
    claude.write_text('#!/usr/bin/env bash\necho "claude 2.1.326-stub"\n')
    claude.chmod(0o755)
    env = {
        "HOME": str(home),
        "PATH": f"{stub_bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "TMPDIR": str(tmp_path),
    }
    proc = subprocess.run(
        ["bash", str(_INSTALLER), "--apply", "--skip-pip", "--python", sys.executable],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return home


def _installed_pre_tool_command(home: Path) -> str:
    """The command the native mod runs, built from the installed binding.

    Not read from any registration: registration and Claude's cache loading are
    covered by test_native_delegation_install.
    """
    plugin = home / ".omninode/delegation/plugin/plugins/onex"
    runtime = json.loads((plugin / "hooks/delegation-runtime.json").read_text())
    return shlex.join(
        [
            "env",
            f"PLUGIN_PYTHON_BIN={runtime['python']}",
            str(plugin / "hooks/scripts/pre_tool_use_delegation.sh"),
        ]
    )


def _customer_path(tmp_path: Path) -> str:
    """A customer's PATH (F6): system dirs plus jq, and no dev-workspace python3.

    The hook needs jq; the installed command carries its own interpreter (F4).
    """
    bin_dir = tmp_path / "customer-bin"
    if not bin_dir.exists():
        bin_dir.mkdir()
        jq = shutil.which("jq")
        assert jq, "jq is required by the delegation hook"
        (bin_dir / "jq").symlink_to(jq)
    return f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"


def _customer_env(tmp_path: Path, home: Path) -> tuple[dict[str, str], Path]:
    """The environment Claude Code gives a customer's hook, and the project dir."""
    project = tmp_path / "customer-project"
    project.mkdir(exist_ok=True)
    (project / "README.md").write_text("a customer's own project\n")
    env = {
        "HOME": str(home),
        "PATH": _customer_path(tmp_path),
        "TMPDIR": str(tmp_path),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    return env, project


def _installed_mode(tmp_path: Path, home: Path) -> str:
    """What the installed mode.sh resolves to in the customer environment."""
    env, project = _customer_env(tmp_path, home)
    mode_sh = (
        home
        / ".omninode"
        / "delegation"
        / "plugin"
        / "plugins"
        / "onex"
        / "lib"
        / "mode.sh"
    )
    assert mode_sh.is_file(), f"installer did not copy mode.sh to {mode_sh}"
    proc = subprocess.run(
        ["/bin/bash", "-c", f'source "{mode_sh}"; omniclaude_mode'],
        capture_output=True,
        text=True,
        cwd=str(project),
        env=env,
        check=True,
        timeout=60,
    )
    return proc.stdout.strip()


def _run_installed(
    tmp_path: Path, home: Path, mask: int | None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the installed hook; mask None leaves ONEX_HOOKS_MASK out of its env."""
    env, project = _customer_env(tmp_path, home)
    state = Path(env["ONEX_STATE_DIR"])
    if mask is not None:
        env["ONEX_HOOKS_MASK"] = hex(mask)
    command = _installed_pre_tool_command(home)
    proc = subprocess.run(
        ["/bin/bash", "-c", command],
        input=_AGENT_CALL + "\n",
        capture_output=True,
        text=True,
        cwd=str(project),
        env=env,
        check=False,
        timeout=60,
    )
    return proc, state / "hooks" / "logs" / "pre-tool-delegation.log"


def _log_text(log: Path) -> str:
    return log.read_text() if log.exists() else ""


@pytest.mark.unit
def test_delegation_not_lite_mode_resolves_lite_in_customer_env(
    tmp_path: Path,
) -> None:
    """F6 control: the customer scenario really is lite mode, so a routed call
    below proves the lite default does not silence an installed hook."""
    home = _install(tmp_path)
    assert _installed_mode(tmp_path, home) == "lite"


@pytest.mark.unit
def test_delegation_not_lite_installed_hook_reaches_the_routing_runner(
    tmp_path: Path,
) -> None:
    """F1, F2, F4, F6: in lite mode, the installed copy, run as Claude Code
    runs it, routes the call."""
    home = _install(tmp_path)
    assert _installed_mode(tmp_path, home) == "lite", "scenario must be lite mode"
    proc, log = _run_installed(tmp_path, home, _DEFAULT_MASK)
    text = _log_text(log)
    assert proc.returncode in (0, 2), proc.stderr
    reached = any(
        marker in text
        for marker in ("PASS tool=Agent", "BLOCK tool=Agent", "WARN: runner exited")
    )
    assert reached, f"runner never reached; log={text!r} stderr={proc.stderr!r}"
    assert "no Python found" not in text, text
    assert "runner not found" not in text, text


@pytest.mark.unit
def test_delegation_not_lite_installed_hook_bit_off_passes_through(
    tmp_path: Path,
) -> None:
    """F3: the switch holds on the installed copy."""
    home = _install(tmp_path)
    proc, log = _run_installed(tmp_path, home, _DEFAULT_MASK & ~_BIT_11)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _AGENT_CALL
    text = _log_text(log)
    assert "PASS tool=" not in text and "BLOCK tool=" not in text, text


def _save_mask(home: Path, mask: int) -> None:
    """Write the mask the way `onex hooks disable|enable` saves it."""
    env_file = home / ".omnibase" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(f"ONEX_HOOKS_MASK={hex(mask)}\n")


def _reached_runner(text: str) -> bool:
    return any(
        marker in text
        for marker in ("PASS tool=Agent", "BLOCK tool=Agent", "WARN: runner exited")
    )


@pytest.mark.unit
def test_delegation_switch_saved_by_onex_hooks_disable_holds(tmp_path: Path) -> None:
    """F5: `onex hooks disable` saves the mask in ~/.omnibase/.env, and Claude
    Code runs the installed hook with no ONEX_HOOKS_MASK in its environment.
    The saved bit-11-off mask must stop the hook before the router."""
    home = _install(tmp_path)
    _save_mask(home, _DEFAULT_MASK & ~_BIT_11)
    proc, log = _run_installed(tmp_path, home, None)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _AGENT_CALL
    assert not _reached_runner(_log_text(log)), _log_text(log)


@pytest.mark.unit
def test_delegation_switch_saved_enable_still_routes(tmp_path: Path) -> None:
    """Control for F5: a saved all-on mask still reaches the router."""
    home = _install(tmp_path)
    _save_mask(home, _DEFAULT_MASK)
    _proc, log = _run_installed(tmp_path, home, None)
    assert _reached_runner(_log_text(log)), _log_text(log)


def _onex_hooks(tmp_path: Path, home: Path, verb: str) -> None:
    """Run the real `onex hooks <verb> post_skill_delegation_enforcer` as the
    customer would, saving the switch under the scratch HOME."""
    onex = Path(sys.executable).parent / "onex"
    assert onex.is_file(), f"onex CLI not installed beside {sys.executable}"
    env = {
        "HOME": str(home),
        "PATH": _customer_path(tmp_path),
        "TMPDIR": str(tmp_path),
    }
    proc = subprocess.run(
        [str(onex), "hooks", verb, "post_skill_delegation_enforcer"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, f"onex hooks {verb}: {proc.stdout}{proc.stderr}"


@pytest.mark.unit
def test_delegation_switch_onex_hooks_cli_round_trip(tmp_path: Path) -> None:
    """F7, AC1 both halves: `onex hooks disable` turns the installed hook off
    (call passed through unchanged, router never reached), then `onex hooks
    enable` turns it back on (router reached). Claude Code passes no
    ONEX_HOOKS_MASK, so only the switch the CLI saved can decide."""
    home = _install(tmp_path)

    _onex_hooks(tmp_path, home, "disable")
    proc, log = _run_installed(tmp_path, home, None)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _AGENT_CALL
    off_log = _log_text(log)
    assert "PASS tool=" not in off_log and "BLOCK tool=" not in off_log, off_log
    assert not _reached_runner(off_log), off_log

    _onex_hooks(tmp_path, home, "enable")
    _proc, log = _run_installed(tmp_path, home, None)
    on_log = _log_text(log)
    # On means a routing decision, not just a runner call: a runner that
    # returns nothing makes the hook log "PASS tool=Agent result=" and must
    # fail here. "WARN: runner exited" is the hosted cold-start case the
    # other tests accept (the runner started past the hook's 5 s limit).
    routed = "BLOCK tool=Agent" in on_log and "result=DELEGATED:" in on_log
    # A classified task whose model is unavailable also proves the enabled
    # hook ran. Failure must pass through; real answering has its own journey.
    routed = routed or any(
        f"PASS tool=Agent result=not_delegatable:{reason}" in on_log
        for reason in ("failed", "timed_out", "no_onex", "no_answer")
    )
    assert routed or "WARN: runner exited" in on_log, on_log


@pytest.mark.unit
@pytest.mark.parametrize("history", ["accepted", "empty", "malformed"])
def test_paused_installed_hook_preserves_context_without_delegation(tmp_path, history):
    """Native OFF removes every entry point and preserves legacy pending history.

    Native answers already live in Claude's transcript (real CLI history proof).
    Pending classic exchanges are kept on disk for a later native re-enable.
    """
    home = _install(tmp_path)
    env, project = _customer_env(tmp_path, home)
    env["ONEX_HOOKS_MASK"] = "0"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "omnimarket/src")
    state = Path(env["ONEX_STATE_DIR"])
    seed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from omnimarket.nodes.node_hook_delegate_effect.handlers.handler_prompt_delegate import HandlerPromptDelegate as H; H._record('history-off', 'Earlier question', 'Accepted answer marker', 'fixture-model', 'history-run-marker')",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert seed.returncode == 0, seed.stderr
    saved = next((state / "claude_prompt_history").glob("*.json"))
    if history == "empty":
        saved.write_text("[]")
    elif history == "malformed":
        saved.write_text("not JSON")
    before = saved.read_bytes()
    env["PATH"] = str(tmp_path / "bin") + os.pathsep + env["PATH"]
    paused = subprocess.run(
        ["/bin/bash", str(_INSTALLER), "--pause", "--python", sys.executable],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert paused.returncode == 0, paused.stdout + paused.stderr
    settings = home / ".claude/settings.json"
    current = json.loads(settings.read_text()) if settings.exists() else {}
    commands = [
        h["command"]
        for g in current.get("hooks", {}).get("UserPromptSubmit", [])
        for h in g["hooks"]
    ]
    assert commands == [], current
    assert (
        current.get("enabledPlugins", {}).get("onex-delegation@onex-delegation-local")
        is not True
    )
    assert saved.read_bytes() == before
    removed = subprocess.run(
        ["/bin/bash", str(_INSTALLER), "--uninstall", "--python", sys.executable],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not settings.exists() or "--history-only" not in settings.read_text()
    (tmp_path / "off-history-proof.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "history": history,
                "pending_history_preserved": True,
                "full_uninstall": True,
            }
        )
    )
