# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One switch for Claude Code delegation (OMN-22498).

The dormant delegation hook set (``hooks-delegation.v1.json``) is installed on
a customer machine by ``scripts/install-delegation.sh``. These tests run the
real hook scripts with a stub routing runner, so they prove the hook's own
gating, not the router.

Failure modes each test is written against:

AC1, the switch (``-k delegation_switch``)
  F1. The hook gates on a name that is not a hook bit, and ``onex_hook_gate``
      lets an unknown name through, so ``onex hooks disable`` cannot turn it off.
  F2. With the bit off the hook still reaches the router, or alters the call.
  F3. With the bit on the hook no longer reaches the router, or reaches it but
      its exit 2 (block the native call) is turned into exit 0 by
      error-guard.sh's EXIT trap, so Claude Code runs the agent anyway.
  F4. A neighbouring bit (12, POST_TOOL_DELEGATION_COUNTER) also turns it off,
      so the switch is not the one named bit.
  F5. The PostToolUse cost-accounting hook stays on with the bit off.

AC3, the lite default (``-k delegation_not_lite``)
  F6. On a customer install (no dev workspace, a project that is not an
      OmniNode repo) the lite default or the repo guard silences the hook, or
      the lite default silences cost accounting, which carries the delegated
      result back.
  F7. The lite protection is dropped for a plugin user who never installed the
      delegation hooks.
  F8. A customer who switched the bit off still reaches the router.

AC4, no stub in the hook set (``-k delegation_hook_set_no_stub``)
  F9.  The prompt classifier stub is still registered.
  F10. Any registered script only exits 0.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN = _REPO_ROOT / "plugins" / "onex"
_PRE_HOOK = _PLUGIN / "hooks" / "scripts" / "pre_tool_use_delegation.sh"
_COST_HOOK = _PLUGIN / "hooks" / "scripts" / "post_tool_use_cost_accounting.sh"
_MODE_SH = _PLUGIN / "lib" / "mode.sh"
_HOOK_SET = _PLUGIN / "hooks" / "hooks-delegation.v1.json"

# The contract default mask (all 60 default bits on), as in hook_bits.sh.
_DEFAULT_MASK = 0xFFFFFFFFFFFFFFF
_BIT_11 = 0x800  # POST_SKILL_DELEGATION_ENFORCER, borrowed as the switch
_BIT_12 = 0x1000  # POST_TOOL_DELEGATION_COUNTER, a neighbour (control)

_AGENT_CALL = json.dumps(
    {
        "tool_name": "Agent",
        "session_id": "omn22498-test",
        "tool_input": {"prompt": "write a haiku", "subagent_type": "general-purpose"},
    }
)

_STUB_RUNNER = """\
import os, pathlib, sys
sys.stdin.read()
pathlib.Path(os.environ["OMN22498_RUNNER_MARKER"]).write_text("called")
print("DELEGATED: stub")
"""


def _mask(cleared: int = 0) -> str:
    return hex(_DEFAULT_MASK & ~cleared)


def _stub_plugin_root(tmp_path: Path) -> Path:
    """A plugin root whose routing runner only records that it was called."""
    root = tmp_path / "plugin"
    lib = root / "hooks" / "lib"
    lib.mkdir(parents=True)
    (lib / "delegation_hook_runner.py").write_text(_STUB_RUNNER)
    return root


def _base_env(tmp_path: Path, *, mask: str, home: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        # error-guard.sh logs under ${TMPDIR}; keep it inside the test.
        "TMPDIR": str(tmp_path),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "ONEX_HOOKS_MASK": mask,
        "CLAUDE_PLUGIN_ROOT": str(_stub_plugin_root(tmp_path)),
        "PLUGIN_PYTHON_BIN": sys.executable,
        "OMN22498_RUNNER_MARKER": str(tmp_path / "runner-called"),
    }


def _run(
    script: Path, env: dict[str, str], cwd: Path, payload: str = _AGENT_CALL
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        input=payload + "\n",
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        check=False,
        timeout=30,
    )


def _dev_workspace_env(tmp_path: Path, mask: str) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = _base_env(tmp_path, mask=mask, home=home)
    env["OMNICLAUDE_MODE"] = "full"
    env["CLAUDE_PROJECT_DIR"] = str(_REPO_ROOT)
    return env


def _customer_env(
    tmp_path: Path, mask: str, *, installed: bool
) -> tuple[dict[str, str], Path]:
    """A customer machine: no dev workspace, a project that is not OmniNode's."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    if installed:
        install_root = home / ".omninode" / "delegation"
        install_root.mkdir(parents=True)
        (install_root / "hooks-delegation.json").write_text("{}")
    project = tmp_path / "customer-project"
    project.mkdir()
    (project / "README.md").write_text("a customer's own project\n")
    env = _base_env(tmp_path, mask=mask, home=home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["PATH"] = _customer_path(tmp_path)
    return env, project


def _customer_path(tmp_path: Path) -> str:
    """A customer's PATH: system dirs plus jq, and no python3 that imports a
    dev-workspace omnibase_core, which would make mode.sh resolve to full and
    leave the lite default unexercised (dod-closeout-sweep, 2026-11-11)."""
    bin_dir = tmp_path / "customer-bin"
    bin_dir.mkdir()
    jq = shutil.which("jq")
    assert jq, "jq is required by the delegation hook"
    (bin_dir / "jq").symlink_to(jq)
    return f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"


def _runner_called(tmp_path: Path) -> bool:
    return (tmp_path / "runner-called").exists()


# ---------------------------------------------------------------------------
# AC1: one named bit switches the hook on and off
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_delegation_switch_bit_on_reaches_the_router(tmp_path: Path) -> None:
    """F3: with the default mask the Agent call is routed."""
    proc = _run(_PRE_HOOK, _dev_workspace_env(tmp_path, _mask()), _REPO_ROOT)
    assert proc.returncode == 2, proc.stderr
    assert "DELEGATED: stub" in proc.stderr
    assert _runner_called(tmp_path)


@pytest.mark.unit
def test_delegation_switch_bit_11_off_passes_the_call_through_unchanged(
    tmp_path: Path,
) -> None:
    """F1, F2: clearing bit 11 leaves the call untouched and never routes it."""
    proc = _run(_PRE_HOOK, _dev_workspace_env(tmp_path, _mask(_BIT_11)), _REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _AGENT_CALL
    assert not _runner_called(tmp_path)


@pytest.mark.unit
def test_delegation_switch_neighbouring_bit_off_still_routes(tmp_path: Path) -> None:
    """F4: only bit 11 is the switch; clearing bit 12 changes nothing."""
    proc = _run(_PRE_HOOK, _dev_workspace_env(tmp_path, _mask(_BIT_12)), _REPO_ROOT)
    assert proc.returncode == 2, proc.stderr
    assert _runner_called(tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cleared", "expect_work"), [(0, True), (_BIT_11, False)], ids=["on", "off"]
)
def test_delegation_switch_cost_accounting_follows_bit_11(
    tmp_path: Path, cleared: int, expect_work: bool
) -> None:
    """F5: cost accounting does its work only while bit 11 is on.

    Its first action after the gates is to open its log, so the log's existence
    is the observable. The "on" case is the positive control that the log is
    written at all in this environment.
    """
    env = _dev_workspace_env(tmp_path, _mask(cleared))
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN)
    proc = _run(_COST_HOOK, env, _REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    log = tmp_path / "state" / "hooks" / "logs" / "cost-accounting.log"
    assert log.exists() is expect_work


# ---------------------------------------------------------------------------
# AC3: a customer install is not silenced by the lite default
# ---------------------------------------------------------------------------


def _resolved_mode(env: dict[str, str], cwd: Path) -> str:
    proc = subprocess.run(
        ["bash", "-c", f'source "{_MODE_SH}"; omniclaude_mode'],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        check=True,
    )
    return proc.stdout.strip()


@pytest.mark.unit
def test_delegation_not_lite_installed_customer_reaches_the_router(
    tmp_path: Path,
) -> None:
    """F6: an installed customer's Agent call is routed in lite mode."""
    env, project = _customer_env(tmp_path, _mask(), installed=True)
    assert _resolved_mode(env, project) == "lite", "scenario must be lite mode"
    proc = _run(_PRE_HOOK, env, project)
    assert proc.returncode == 2, proc.stderr
    assert _runner_called(tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize("installed", [True, False], ids=["installed", "plugin-only"])
def test_delegation_not_lite_cost_accounting_runs_for_installed_customer(
    tmp_path: Path, installed: bool
) -> None:
    """F6, F7: cost accounting runs for an installed customer, and only then."""
    env, project = _customer_env(tmp_path, _mask(), installed=installed)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN)
    assert _resolved_mode(env, project) == "lite", "scenario must be lite mode"
    proc = _run(_COST_HOOK, env, project)
    assert proc.returncode == 0, proc.stderr
    log = tmp_path / "state" / "hooks" / "logs" / "cost-accounting.log"
    assert log.exists() is installed


@pytest.mark.unit
def test_delegation_not_lite_without_install_stays_silent(tmp_path: Path) -> None:
    """F7: a plugin user who never installed delegation keeps the lite no-op."""
    env, project = _customer_env(tmp_path, _mask(), installed=False)
    assert _resolved_mode(env, project) == "lite", "scenario must be lite mode"
    proc = _run(_PRE_HOOK, env, project)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _AGENT_CALL
    assert not _runner_called(tmp_path)


@pytest.mark.unit
def test_delegation_not_lite_customer_with_bit_off_passes_through(
    tmp_path: Path,
) -> None:
    """F8: the switch still wins on a customer install."""
    env, project = _customer_env(tmp_path, _mask(_BIT_11), installed=True)
    proc = _run(_PRE_HOOK, env, project)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _AGENT_CALL
    assert not _runner_called(tmp_path)


# ---------------------------------------------------------------------------
# AC4: the installed hook set registers no script that only exits 0
# ---------------------------------------------------------------------------

_INERT_LINES = {"exit 0", "cat", "exit", "true", ":"}


def _only_exits_zero(script_text: str) -> bool:
    """True when every executable line of a shell script is a no-op exit."""
    lines = []
    for raw in script_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.fullmatch(r"set\s+-[euxo]+(\s+pipefail)?", line):
            continue
        lines.append(line)
    return all(line in _INERT_LINES for line in lines)


def _registered_scripts() -> list[Path]:
    data = json.loads(_HOOK_SET.read_text())
    scripts = []
    for groups in data["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                command = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(_PLUGIN))
                scripts.append(Path(command.split()[0]))
    return scripts


@pytest.mark.unit
def test_delegation_hook_set_no_stub_detector_flags_a_stub() -> None:
    """Positive control: the detector recognises a stub and passes real code."""
    stub = "#!/usr/bin/env bash\n# placeholder\nexit 0\n"
    assert _only_exits_zero(stub)
    assert not _only_exits_zero(_PRE_HOOK.read_text())


@pytest.mark.unit
def test_delegation_hook_set_no_stub_registers_no_inert_script() -> None:
    """F9, F10: every script the hook set names exists and does real work."""
    scripts = _registered_scripts()
    assert scripts, "the hook set registers no scripts"
    assert not any(s.name == "user_prompt_delegation_classifier.sh" for s in scripts)
    for script in scripts:
        assert script.is_file(), f"registered script missing: {script}"
        assert not _only_exits_zero(script.read_text()), f"inert stub: {script.name}"
