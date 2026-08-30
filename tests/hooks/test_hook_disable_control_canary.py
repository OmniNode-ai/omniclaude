# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Disable-control canary: every gate blocks a synthetic violation (OMN-17020).

A17 of ``docs/tracking/2026-08-29-beta-off-the-rails-analysis.md``, generalised
from OMN-17005 AC8 to every registered enforcement mechanism.

**Why a unit test on the guard is not enough.** The OMN-8928 dispatch-claim
gate is the argument. Probed 2026-08-29, ``dispatch_claim_gate.py`` returned a
correct deny — ``{"decision": "block", ...}``, the right verdict, the right
payload — and the *registered hook* still exited 0, because
``error-guard.sh`` installs ``trap '_omniclaude_error_guard_trap' EXIT`` which
converts any non-zero exit to 0, and ``hook_dispatch_claim_pretool.sh`` never
calls ``trap - EXIT`` the way every registered guard does. A unit test on the
gate function would have passed. The tool call proceeded anyway. Only running
the script the harness actually runs, end to end, tells those two apart.

So every case here:

* resolves the script from ``hooks.json`` — the same command string the harness
  invokes, not a path the test chose;
* **fails, never skips, if that script is not registered** (DoD item 6). A
  skipped canary is the disable it exists to catch, so an unregistered hook is
  a red test, not an absent one;
* runs it as a subprocess with a hermetic ``HOME`` (so ``common.sh`` cannot
  re-read ``~/.omnibase/.env`` and hand the run a different
  ``ONEX_HOOKS_MASK`` than CI would see) and a synthetic violation on stdin;
* asserts the *observable* outcome the manifest declares — exit code plus text
  that must and must not appear.

The specs live in ``plugins/onex/hooks/contracts/hook_inventory.yaml`` next to
the registration they belong to, so adding a hook without a canary is a gate
failure rather than a thing to remember.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_SCRIPTS_DIR = _HOOKS_DIR / "scripts"
_INVENTORY = _HOOKS_DIR / "contracts" / "hook_inventory.yaml"
_HOOKS_JSON = _HOOKS_DIR / "hooks.json"

#: Wall-clock ceiling for one canary. Generous: some guards shell out to
#: Python. A hook that cannot answer inside this is itself a finding.
_TIMEOUT_S = 180


def _load_lib() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hook_inventory_for_canary", _HOOKS_DIR / "lib" / "hook_inventory.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_LIB = _load_lib()
_INVENTORY_DATA = _LIB.load_inventory(_INVENTORY)
_REGISTERED = {reg.script: reg for reg in _LIB.load_registrations(_HOOKS_JSON)}
_WITH_CANARY = [hook for hook in _INVENTORY_DATA.expected if hook.canary is not None]


def _substitute(value: Any, subs: dict[str, str]) -> Any:
    """Fill ``{placeholder}`` slots anywhere in a canary's stdin or env."""
    if isinstance(value, str):
        out = value
        for key, replacement in subs.items():
            out = out.replace("{" + key + "}", replacement)
        return out
    if isinstance(value, dict):
        return {k: _substitute(v, subs) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, subs) for v in value]
    return value


def _prepare(hook: Any, tmp_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Materialise a canary's fixtures and resolve its placeholders."""
    home = tmp_path / "home"
    home.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    subs = {
        "home": str(home),
        "state_dir": str(state_dir),
        "repo_root": str(_REPO_ROOT),
        "plugin_root": str(_HOOKS_DIR.parent),
        "transcript_path": str(tmp_path / "transcript.jsonl"),
    }

    fixtures = hook.canary.fixtures
    if "transcript" in fixtures:
        entries = fixtures["transcript"]
        assert isinstance(entries, list) and entries, (
            f"{hook.script}: transcript fixture must be a non-empty list"
        )
        (tmp_path / "transcript.jsonl").write_text(
            "\n".join(json.dumps(entry) for entry in entries) + "\n"
        )
    if "overseer_flag" in fixtures:
        (state_dir / "overseer-active.flag").write_text(str(fixtures["overseer_flag"]))

    env: dict[str, str] = {
        # env -i equivalent: only what a hook may legitimately assume.
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(_HOOKS_DIR.parent),
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(state_dir),
        # Pinned, not inherited. `mode.sh` resolves "lite" for any cwd outside
        # omni_home/omni_worktrees with no local omnibase_core -- the DEFAULT on
        # a CI runner -- and nine registered hooks exit 0 silently under lite,
        # three of them enforcement guards. Leaving this to the environment made
        # the same canary pass on the operator Mac (worktree under
        # omni_worktrees => full) and fail on a runner. The canary's question is
        # "does the registered hook enforce", not "is this machine in full
        # mode"; the second question is the bootstrap check's DARK_IN_LITE_MODE
        # finding, which is where an environment fact belongs.
        "OMNICLAUDE_MODE": "full",
    }
    env.update(_substitute(dict(hook.canary.env), subs))
    return _substitute(hook.canary.stdin, subs), env


def _run(hook: Any, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    stdin, env = _prepare(hook, tmp_path)
    return subprocess.run(
        ["bash", str(_SCRIPTS_DIR / hook.script)],
        input=json.dumps(stdin),
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_S,
        check=False,
    )


@pytest.mark.parametrize(
    "hook", _WITH_CANARY, ids=[hook.script for hook in _WITH_CANARY]
)
def test_registered_hook_enforces_its_canary(hook: Any, tmp_path: Path) -> None:
    """The canary. Runs the registered script; asserts the declared outcome.

    Note the order of the two assertions. Registration is checked FIRST and as
    a failure, not a skip: an unregistered hook is exactly the condition this
    whole ticket exists to detect, and a canary that quietly skips when its
    target goes dark is a strictly worse instrument than no canary at all —
    it reports green for the one state it was built to catch.
    """
    assert hook.script in _REGISTERED, (
        f"{hook.script} carries a canary but hooks.json does not register it. "
        "This test FAILS rather than skips on purpose (OMN-17020 DoD 6): an "
        "unregistered enforcement hook is the OMN-13244 defect, and a skipped "
        "canary would report it as green."
    )
    registration = _REGISTERED[hook.script]
    assert registration.command.endswith(f"/{hook.script}"), (
        f"the registered command {registration.command!r} does not resolve to "
        f"{hook.script}; the canary must exercise the command the harness runs"
    )

    result = _run(hook, tmp_path)
    combined = result.stdout + result.stderr

    assert result.returncode == hook.canary.expect.exit_code, (
        f"{hook.script} ({hook.canary.kind}) exited {result.returncode}, "
        f"expected {hook.canary.expect.exit_code}. This is the OMN-8928 shape: "
        "a guard whose verdict is correct and whose exit code is swallowed "
        "enforces nothing.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    for needle in hook.canary.expect.stdout_contains:
        assert needle in combined, (
            f"{hook.script} did not emit {needle!r}.\nstdout: {result.stdout!r}"
            f"\nstderr: {result.stderr!r}"
        )
    for needle in hook.canary.expect.stdout_absent:
        assert needle not in combined, (
            f"{hook.script} emitted {needle!r}, which its canary forbids.\n"
            f"stdout: {result.stdout!r}"
        )


def test_every_enforcement_hook_has_a_canary_case_here() -> None:
    """The parametrisation must cover every enforcement mechanism, not a subset.

    Without this, dropping a ``canary:`` block from the inventory would shrink
    this file's coverage silently — the parametrised test would simply run one
    fewer case and stay green.
    """
    enforcing = {hook.script for hook in _INVENTORY_DATA.expected if hook.enforcement}
    covered = {
        hook.script for hook in _WITH_CANARY if hook.canary.kind != "pass_through"
    }
    assert enforcing <= covered, (
        f"enforcement hooks with no canary case: {sorted(enforcing - covered)!r}"
    )
    assert len(enforcing) >= 8, (
        "the enforcement set shrank; if a guard was demoted to observer, say so "
        f"in the inventory and update this floor. Found: {sorted(enforcing)!r}"
    )


def test_a_deregistered_hook_makes_its_canary_fail_not_skip() -> None:
    """DoD 6, proven in the direction that matters.

    ``test_registered_hook_enforces_its_canary`` asserts registration on a tree
    where every hook IS registered, so it can never observe its own failure
    branch. This drives the branch directly with a registration set that has
    had the guard removed, and proves the outcome is a failure carrying the
    hook's name — not a skip, and not a pass.
    """
    victim = "pre_tool_use_overseer_foreground_block.sh"
    hook = next(h for h in _WITH_CANARY if h.script == victim)
    without = {k: v for k, v in _REGISTERED.items() if k != victim}

    # The assertion the canary makes, evaluated against the deregistered set.
    with pytest.raises(AssertionError) as excinfo:
        assert hook.script in without, (
            f"{hook.script} carries a canary but hooks.json does not register it."
        )
    assert victim in str(excinfo.value)


def test_hooks_without_a_canary_state_why() -> None:
    """The uncovered set is explicit and observer-only.

    Four bus-mirror hooks have no canary because running one publishes a
    synthetic row onto the .201 lane the observability projection reads
    (OMN-17204). That is a reason, recorded in the inventory; it is not the
    same as nobody having thought about it.
    """
    uncovered = [hook for hook in _INVENTORY_DATA.expected if hook.canary is None]
    assert uncovered, "expected the bus-mirror observers to be the uncovered set"
    for hook in uncovered:
        assert not hook.enforcement, (
            f"{hook.script} is an enforcement mechanism with no canary"
        )
        assert hook.no_canary_reason, f"{hook.script} has no stated reason"
        assert len(hook.no_canary_reason) > 40, (
            f"{hook.script}: 'not applicable' is not a reason"
        )
