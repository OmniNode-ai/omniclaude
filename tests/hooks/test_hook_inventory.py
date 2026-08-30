# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the typed hook inventory and its parity gate (OMN-17020).

The defect these tests exist for is not "hooks.json was wrong". It is that
**nothing could tell**. OMN-13244 gutted ``hooks.json`` for a measurement
baseline with no expiry, no re-enable ticket and no inventory of what went
dark; ``pre_tool_use_overseer_foreground_block.sh`` then lay on disk,
unregistered, while the foreground rule it enforces was corrected by hand ~61
times over 16 of 18 days
(``docs/tracking/2026-08-29-beta-off-the-rails-analysis.md``, root cause RC-B).

OMN-17006 wrote the corrective rule (OWNER / REASON / EXPIRY / RESTORATION)
into the ``description`` of ``hooks.json`` and asserted its presence. This
ticket generalises it: the rule becomes typed per-disable data, and "which
hooks are supposed to be on" becomes a declaration a merge gate fails on.

The ticket's own done-proof is falsifiable in four directions, and each gets a
test here that mutates a scratch mirror of the tree rather than asserting a
property of the current one:

  1. Deregister a hook            -> the gate exits 1 naming it.
  2. Register an undeclared hook  -> the gate exits 1 naming it.
  3. Let a disable's review lapse -> the gate exits 1 naming its restoration.
  4. Clear a mask bit             -> ``--live`` reports the hook as dark,
                                     while the static gate stays green (the
                                     mask is a per-machine surface and must
                                     never become a merge gate).

A test that only asserted "the current tree is green" would have passed for
every one of the 18 days RC-B describes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_INVENTORY_REL = "plugins/onex/hooks/contracts/hook_inventory.yaml"
_HOOKS_JSON_REL = "plugins/onex/hooks/hooks.json"
_LIB_REL = "plugins/onex/hooks/lib/hook_inventory.py"
_VALIDATOR = _REPO_ROOT / "scripts" / "validation" / "validate_hook_inventory.py"


def _load_lib() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hook_inventory_under_test", _REPO_ROOT / _LIB_REL
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves annotations through
    # sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_LIB = _load_lib()


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A scratch tree the tests may break without touching the real repo.

    ``scripts/`` is symlinked rather than copied: the parity check only reads
    those files, and copying 100+ shell scripts per test would make the four
    falsifiable directions expensive enough that someone would delete them.
    """
    root = tmp_path / "mirror"
    (root / "plugins" / "onex" / "hooks" / "contracts").mkdir(parents=True)
    (root / "plugins" / "onex" / "hooks" / "lib").mkdir(parents=True)
    shutil.copy2(_REPO_ROOT / _INVENTORY_REL, root / _INVENTORY_REL)
    shutil.copy2(_REPO_ROOT / _HOOKS_JSON_REL, root / _HOOKS_JSON_REL)
    shutil.copy2(
        _HOOKS_DIR / "lib" / "hook_bits.sh",
        root / "plugins" / "onex" / "hooks" / "lib" / "hook_bits.sh",
    )
    shutil.copy2(_REPO_ROOT / _LIB_REL, root / _LIB_REL)
    (root / "plugins" / "onex" / "hooks" / "scripts").symlink_to(
        _HOOKS_DIR / "scripts", target_is_directory=True
    )
    return root


def _findings(root: Path, today: date | None = None) -> list[object]:
    inventory = _LIB.load_inventory(root / _INVENTORY_REL)
    return list(_LIB.check_parity(inventory, root, today or date(2026, 1, 1)))


def _codes(root: Path, today: date | None = None) -> list[str]:
    return [f.code for f in _findings(root, today)]


def _run_gate(
    root: Path, *extra: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    run_env = dict(os.environ)
    run_env.pop("PYTHONPATH", None)
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(root), *extra],
        capture_output=True,
        text=True,
        env=run_env,
        timeout=120,
        check=False,
    )


def _edit_hooks_json(root: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    path = root / _HOOKS_JSON_REL
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# The inventory itself
# ---------------------------------------------------------------------------


def test_inventory_parses_and_the_live_tree_is_green() -> None:
    """DoD 1: the manifest is generated from live state, so it starts green.

    This is the weakest test in the file and is deliberately first: it is the
    one an unchanged tree passes. The four mutation tests below are what give
    it meaning.
    """
    result = _run_gate(_REPO_ROOT)
    assert result.returncode == 0, (
        "The hook inventory must match the live hooks.json on an unmodified "
        f"tree.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_every_registered_hook_is_declared() -> None:
    """Nothing may be registered that the inventory does not name."""
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    registered = {
        reg.script for reg in _LIB.load_registrations(_REPO_ROOT / _HOOKS_JSON_REL)
    }
    declared = {hook.script for hook in inventory.expected}
    assert registered == declared, (
        "hooks.json and hook_inventory.yaml disagree about the registered set. "
        f"Registered-not-declared: {sorted(registered - declared)!r}; "
        f"declared-not-registered: {sorted(declared - registered)!r}."
    )


def test_every_enforcement_hook_carries_a_canary() -> None:
    """A17: a guard with no end-to-end canary is a guard nobody has watched fire.

    ``enforcement: true`` is a claim about refusal. The OMN-8928 claim gate
    made that claim, returned a correct deny from its Python, and still exited
    0 because the error-guard EXIT trap swallowed it. Only an end-to-end run
    of the registered script can tell those two apart.
    """
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    missing = [
        hook.script
        for hook in inventory.expected
        if hook.enforcement and hook.canary is None
    ]
    assert not missing, f"enforcement hooks with no canary: {missing!r}"

    passthrough = [
        hook.script
        for hook in inventory.expected
        if hook.enforcement
        and hook.canary is not None
        and hook.canary.kind == "pass_through"
    ]
    assert not passthrough, (
        "an enforcement hook whose canary only proves it does nothing is not "
        f"covered: {passthrough!r}"
    )


def test_every_observer_states_why_it_has_no_canary() -> None:
    """``enforcement: false`` is a claim too, and it needs a reason or a proof."""
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    bare = [
        hook.script
        for hook in inventory.expected
        if not hook.enforcement
        and hook.canary is None
        and hook.no_canary_reason is None
    ]
    assert not bare, (
        f"observers with neither a pass_through canary nor a no_canary_reason: {bare!r}"
    )


def test_every_disable_carries_the_four_omn_17006_fields() -> None:
    """DoD 4: the OMN-17006 description clause, generalised to typed data.

    OMN-13244's disable was indistinguishable from a decision because it
    recorded none of these. ``review_by`` is the one that does the work: it is
    an absolute date the gate compares against today, so a disable cannot
    outlive its own justification in silence.
    """
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    assert inventory.disabled, "the inventory must record the deliberate disables"
    for disabled in inventory.disabled:
        assert disabled.owner
        assert disabled.reason
        assert isinstance(disabled.review_by, date)
        assert disabled.restoration.kind in _LIB.RESTORATION_KINDS
        assert disabled.restoration.reenable_ticket.startswith("OMN-")
        assert disabled.restoration.action


def test_declared_disables_are_on_disk_and_unregistered() -> None:
    """The two halves of the inventory must not contradict each other."""
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    registered = {
        reg.script for reg in _LIB.load_registrations(_REPO_ROOT / _HOOKS_JSON_REL)
    }
    for disabled in inventory.disabled:
        assert (_HOOKS_DIR / "scripts" / disabled.script).is_file(), (
            f"{disabled.script} is declared a disable with restoration kind "
            f"{disabled.restoration.kind!r}, but is not on disk"
        )
        assert disabled.script not in registered, (
            f"{disabled.script} is declared disabled and is registered"
        )


def test_the_omn_8928_claim_pair_is_still_a_declared_disable() -> None:
    """The specific pair OMN-17005 owns must stay recorded, not merely absent.

    ``test_dispatch_claim_pair_is_not_registered`` in the OMN-13244 baseline
    test proves they are unregistered. That is not the same as proving anyone
    is accountable for them: absence with no record is precisely the state
    that produced RC-B.
    """
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    by_script = {d.script: d for d in inventory.disabled}
    for script in ("hook_dispatch_claim_pretool.sh", "hook_dispatch_claim_posttool.sh"):
        assert script in by_script, f"{script} is unregistered with no disable record"
        assert by_script[script].restoration.reenable_ticket == "OMN-17005"


# ---------------------------------------------------------------------------
# Strict parsing: a malformed inventory must raise, never default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drop_key",
    ["owner", "reason", "review_by", "restoration"],
)
def test_a_disable_missing_any_of_the_four_fields_is_rejected(
    mirror: Path, drop_key: str
) -> None:
    """No defaults. An inventory that tolerates a missing field is OMN-13244."""
    import yaml

    path = mirror / _INVENTORY_REL
    raw = yaml.safe_load(path.read_text())
    del raw["disabled_hooks"][0][drop_key]
    path.write_text(yaml.safe_dump(raw))

    with pytest.raises(_LIB.HookInventoryError) as excinfo:
        _LIB.load_inventory(path)
    assert drop_key in str(excinfo.value)


def test_a_relative_expiry_is_rejected(mirror: Path) -> None:
    """ "when we get round to it" is what OMN-13244 already had."""
    import yaml

    path = mirror / _INVENTORY_REL
    raw = yaml.safe_load(path.read_text())
    raw["disabled_hooks"][0]["review_by"] = "when OMN-17005 is decided"
    path.write_text(yaml.safe_dump(raw))

    with pytest.raises(_LIB.HookInventoryError) as excinfo:
        _LIB.load_inventory(path)
    assert "absolute ISO date" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Falsifiable direction 1 — deregister a hook, the gate fails naming it
# ---------------------------------------------------------------------------


def test_deregistering_a_hook_fails_the_gate_and_names_it(mirror: Path) -> None:
    """The RC-B direction. This is the whole ticket in one test.

    Removing the overseer foreground guard from hooks.json is exactly what
    OMN-13244 did. Before this gate, that produced no signal of any kind for
    16 of 18 days.
    """
    victim = "pre_tool_use_overseer_foreground_block.sh"

    def drop(data: dict) -> None:  # type: ignore[type-arg]
        data["hooks"]["PreToolUse"] = [
            group
            for group in data["hooks"]["PreToolUse"]
            if not any(victim in h["command"] for h in group["hooks"])
        ]

    _edit_hooks_json(mirror, drop)

    result = _run_gate(mirror)
    assert result.returncode == 1, f"gate did not fail: {result.stdout}{result.stderr}"
    assert "UNREGISTERED_EXPECTED" in result.stderr
    assert victim in result.stderr
    assert "OMN-13244" in result.stderr, (
        "the failure must say what this class of drift is, not merely that a "
        "set comparison failed"
    )


def test_deregistering_a_hook_leaves_the_others_green(mirror: Path) -> None:
    """One dark hook must not smear into a wall of findings nobody reads."""
    victim = "pre_tool_use_overseer_foreground_block.sh"

    def drop(data: dict) -> None:  # type: ignore[type-arg]
        data["hooks"]["PreToolUse"] = [
            group
            for group in data["hooks"]["PreToolUse"]
            if not any(victim in h["command"] for h in group["hooks"])
        ]

    _edit_hooks_json(mirror, drop)
    findings = _findings(mirror)
    assert [f.subject for f in findings] == [victim]


# ---------------------------------------------------------------------------
# Falsifiable direction 2 — register something nobody declared
# ---------------------------------------------------------------------------


def test_an_undeclared_registration_fails_the_gate(mirror: Path) -> None:
    """An inventory only stays honest if additions are also drift."""

    def add(data: dict) -> None:  # type: ignore[type-arg]
        data["hooks"]["PreToolUse"].append(
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_bash_guard.sh",
                    }
                ],
            }
        )

    _edit_hooks_json(mirror, add)

    result = _run_gate(mirror)
    assert result.returncode == 1
    assert "UNDECLARED_REGISTRATION" in result.stderr
    assert "pre_tool_use_bash_guard.sh" in result.stderr
    # It is also a declared disable, so the contradiction is reported too.
    assert "DISABLED_BUT_REGISTERED" in result.stderr


def test_changing_a_matcher_fails_the_gate(mirror: Path) -> None:
    """A widened matcher changes what a guard sees without touching its code."""

    def widen(data: dict) -> None:  # type: ignore[type-arg]
        for group in data["hooks"]["PreToolUse"]:
            if any(
                "pre_tool_use_overseer_foreground_block.sh" in h["command"]
                for h in group["hooks"]
            ):
                group["matcher"] = ".*"

    _edit_hooks_json(mirror, widen)
    assert "MATCHER_MISMATCH" in _codes(mirror)


def test_reordering_session_start_fails_the_gate(mirror: Path) -> None:
    """Order is behaviour: OMN-17168's goal block must print last."""

    def swap(data: dict) -> None:  # type: ignore[type-arg]
        hooks = data["hooks"]["SessionStart"][0]["hooks"]
        hooks[0], hooks[1] = hooks[1], hooks[0]

    _edit_hooks_json(mirror, swap)
    assert "ORDER_MISMATCH" in _codes(mirror)


# ---------------------------------------------------------------------------
# Falsifiable direction 3 — let a disable's review date pass
# ---------------------------------------------------------------------------


def test_a_lapsed_disable_fails_the_gate_and_names_its_restoration() -> None:
    """DoD's second done-proof: "let a disable's expiry pass ... or CI fails".

    The restoration action is not executed by the gate — no check can decide
    for OMN-17005 whether a per-lane claimant identity now exists. What the
    gate does is refuse to let the disable outlive its own review date in
    silence, and print the declared restoration so the next reader does not
    have to reconstruct it.
    """
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    latest = max(d.review_by for d in inventory.disabled)
    day_after = date.fromordinal(latest.toordinal() + 1)

    result = _run_gate(_REPO_ROOT, "--today", day_after.isoformat())
    assert result.returncode == 1, (
        "every disable's review date had passed and the gate still passed"
    )
    assert "DISABLE_REVIEW_LAPSED" in result.stderr
    for disabled in inventory.disabled:
        assert disabled.script in result.stderr
        assert disabled.restoration.reenable_ticket in result.stderr


def test_disables_are_within_review_today() -> None:
    """The live tree's disables have not silently expired."""
    findings = _findings(_REPO_ROOT, datetime.now(UTC).date())
    lapsed = [f for f in findings if f.code == "DISABLE_REVIEW_LAPSED"]
    assert not lapsed, [f.render() for f in lapsed]


def test_deleting_a_disabled_script_fails_the_gate(
    mirror: Path, tmp_path: Path
) -> None:
    """Deleting a disabled hook is the expiry branch, not a cleanup.

    OMN-17005's own expiry says the claim scripts get deleted if a per-lane
    identity cannot be produced — and that deletion must close the ticket in
    the same change. Silent deletion is how a decision becomes an accident.
    """
    # Replace the symlinked scripts dir with a real copy so one file can go.
    scripts_link = mirror / "plugins" / "onex" / "hooks" / "scripts"
    scripts_link.unlink()
    shutil.copytree(_HOOKS_DIR / "scripts", scripts_link)
    (scripts_link / "hook_dispatch_claim_posttool.sh").unlink()

    findings = _findings(mirror)
    assert [f.code for f in findings] == ["DISABLED_SCRIPT_DELETED"]
    assert findings[0].subject == "hook_dispatch_claim_posttool.sh"


# ---------------------------------------------------------------------------
# Falsifiable direction 4 — the ONEX_HOOKS_MASK surface
# ---------------------------------------------------------------------------


def test_a_cleared_mask_bit_is_reported_live_but_never_in_ci() -> None:
    """The second disable surface, and the boundary it must not cross.

    ``hooks.json`` is not the only way a hook goes dark: ``common.sh`` re-reads
    ``ONEX_HOOKS_MASK`` from ``~/.omnibase/.env`` under ``set -a``, so a
    cleared bit makes a fully registered guard a no-op. Building this inventory
    found exactly that — ``WORKTREE_GUARD`` absent from the operator Mac's live
    mask, i.e. ``pre_tool_use_worktree_guard.sh`` registered under the
    OMN-14330 carve-out and dark in practice.

    It is a per-machine fact, so it must NOT be a merge gate: a runner has no
    ``~/.omnibase/.env``, and a check that passes because its input is absent
    is worse than no check. This test pins both halves.
    """
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    bits = _LIB.defined_mask_bits(_REPO_ROOT / inventory.hook_bits)
    assert "WORKTREE_GUARD" in bits

    all_on = 0
    for value in bits.values():
        all_on |= value
    dark = all_on & ~bits["WORKTREE_GUARD"]

    reported = _LIB.mask_findings(inventory, _REPO_ROOT, hex(dark))
    assert [f.subject for f in reported] == ["pre_tool_use_worktree_guard.sh"]
    assert reported[0].code == "MASKED_OFF"

    # Same tree, same mask, static gate: green. The mask never fails CI.
    static = _run_gate(_REPO_ROOT, env={"ONEX_HOOKS_MASK": hex(dark)})
    assert static.returncode == 0, (
        "the static gate read the live mask; a GitHub runner has no "
        "~/.omnibase/.env, so that check would pass for the wrong reason there"
    )

    live = _run_gate(_REPO_ROOT, "--live", env={"ONEX_HOOKS_MASK": hex(dark)})
    assert live.returncode == 1
    assert "MASKED_OFF" in live.stderr


def test_an_absent_mask_reports_nothing_rather_than_everything() -> None:
    """No mask set means the default (all bits on), not "all hooks dark"."""
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    assert _LIB.mask_findings(inventory, _REPO_ROOT, None) == ()


def test_declared_mask_gate_calls_match_the_scripts_and_the_bit_table() -> None:
    """The mask declaration is checked against reality, not trusted.

    Four registered hooks call ``onex_hook_gate`` with a name that is not in
    ``hook_bits.sh``. ``hook_bits_bit_for_name`` returns non-zero for those,
    ``onex_hook_gate`` returns 0, and the hook runs unconditionally — they are
    ungated in practice. The inventory records that as
    ``mask.bit_defined: false`` rather than rounding it to "no gate", because
    the difference is the kind of fact this file exists to hold.
    """
    findings = _findings(_REPO_ROOT)
    mask_codes = [f for f in findings if f.code.startswith("MASK_")]
    assert not mask_codes, [f.render() for f in mask_codes]

    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    undefined = [
        hook.script
        for hook in inventory.expected
        if hook.mask.gate_call is not None and not hook.mask.bit_defined
    ]
    assert undefined, (
        "the inventory should still be recording the hooks whose gate call "
        "names an undefined bit; if that was fixed, update this test"
    )


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


def test_warn_only_never_fails(mirror: Path) -> None:
    """DoD 3's posture, proven on a broken tree rather than a clean one."""

    def drop(data: dict) -> None:  # type: ignore[type-arg]
        data["hooks"]["SessionEnd"] = []

    _edit_hooks_json(mirror, drop)

    strict = _run_gate(mirror)
    assert strict.returncode == 1

    warn = _run_gate(mirror, "--warn-only")
    assert warn.returncode == 0, (
        "the session-bootstrap posture must never block a session start"
    )
    assert "WARN" in warn.stderr
    assert "session_end_bus_mirror.sh" in warn.stderr


def test_generate_reproduces_the_registered_set() -> None:
    """DoD 1: the mechanical half is generated, not retyped.

    ``--generate`` is what makes "starts green" a property of the process
    rather than of one careful afternoon.
    """
    result = _run_gate(_REPO_ROOT, "--generate")
    assert result.returncode == 0, result.stderr
    for reg in _LIB.load_registrations(_REPO_ROOT / _HOOKS_JSON_REL):
        assert f'script: "{reg.script}"' in result.stdout
        assert f"order: {reg.order}" in result.stdout


def test_gate_reports_its_own_failure_distinctly(tmp_path: Path) -> None:
    """A gate that cannot run must say so with a different exit code than pass.

    Exit 2 (cannot run) is not exit 0 (clean). Collapsing them is how a check
    becomes decoration.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _run_gate(empty)
    assert result.returncode == 2
    assert "FATAL" in result.stderr


def test_hooks_json_description_names_the_inventory_as_authority() -> None:
    """The delegation of authority must live in the file a future edit touches.

    OMN-17006 put the STANDING RULE in ``hooks.json``'s own ``description``
    for exactly this reason: a rule stored anywhere else is a rule the next
    person editing this file does not read. The same applies to the inventory
    — a reader who opens ``hooks.json`` to add or remove a registration has to
    learn there that a second file must change too, or the gate will look
    arbitrary and the first instinct will be to route around it.
    """
    description = json.loads((_REPO_ROOT / _HOOKS_JSON_REL).read_text())["description"]

    assert "hook_inventory.yaml" in description, (
        "hooks.json's description must name the typed inventory as the record "
        "of what is registered and what is dark (OMN-17020)."
    )
    assert "OMN-17020" in description
    for phrase in ("owner", "review_by", "restoration"):
        assert phrase in description, (
            f"the description must say a disable needs {phrase!r} as typed data, "
            "not merely that a standing rule exists."
        )


# ---------------------------------------------------------------------------
# The third disable surface — OMNICLAUDE_MODE
# ---------------------------------------------------------------------------


def test_lite_mode_darkness_is_declared_and_reported() -> None:
    """`mode.sh` is a third way a registered hook does nothing, and it defaults ON.

    Found the hard way, mid-PR: three of these canaries passed on the operator
    Mac and failed on a CI runner with `exit 0` and empty output. The cause is
    not the mask and not `hooks.json` — ``mode.sh`` resolves ``lite`` for any
    cwd outside ``omni_home``/``omni_worktrees`` with no local
    ``omnibase_core``, which is the DEFAULT on a runner and in every external
    repo, and nine registered hooks exit 0 silently under it.

    Three of those nine are ENFORCEMENT guards — the Done-flip gate, the
    lane-liveness guard, and the Bash secret-redaction guard. In lite mode a
    session has none of them and nothing says so. That is worth more than a
    comment, so it is declared per hook and reported live.
    """
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    lite = {hook.script for hook in inventory.expected if hook.lite_mode_exit}
    enforcing_and_lite = {
        hook.script
        for hook in inventory.expected
        if hook.lite_mode_exit and hook.enforcement
    }

    assert enforcing_and_lite == {
        "pre_tool_use_done_flip_guard.sh",
        "pre_tool_use_lane_liveness_guard.sh",
        "post_tool_use_secret_redact_guard.sh",
    }, (
        "the set of enforcement guards that vanish in lite mode changed. That is "
        "a real change in what a lite-mode session is protected by — update this "
        f"test deliberately, with a reason. Found: {sorted(enforcing_and_lite)!r}"
    )

    # full mode: nothing to report.
    assert _LIB.mode_findings(inventory, "full") == ()
    assert _LIB.mode_findings(inventory, None) == ()

    # lite mode: every declared lite-exit hook, and the enforcement ones say so.
    findings = _LIB.mode_findings(inventory, "lite")
    assert {f.subject for f in findings} == lite
    assert all(f.code == "DARK_IN_LITE_MODE" for f in findings)
    for finding in findings:
        if finding.subject in enforcing_and_lite:
            assert "ENFORCEMENT hook" in finding.detail


def test_the_lite_mode_declaration_is_checked_against_the_script(mirror: Path) -> None:
    """A declaration nobody verifies is a comment. This one is verified.

    The check matches the early-exit *comparison*, not a mention of the
    function: ``session_start_hook_parity.sh`` itself calls ``omniclaude_mode``
    to report the mode and must not be counted as exiting on it.
    """
    import yaml

    path = mirror / _INVENTORY_REL
    raw = yaml.safe_load(path.read_text())
    for entry in raw["expected_hooks"]:
        if entry["script"] == "pre_tool_use_done_flip_guard.sh":
            entry["lite_mode_exit"] = False
    path.write_text(yaml.safe_dump(raw))

    codes = _codes(mirror)
    assert "LITE_MODE_EXIT_MISMATCH" in codes

    # And the reporter hook, which mentions the function without exiting on it,
    # is correctly declared as NOT exiting.
    inventory = _LIB.load_inventory(_REPO_ROOT / _INVENTORY_REL)
    reporter = next(
        h for h in inventory.expected if h.script == "session_start_hook_parity.sh"
    )
    assert reporter.lite_mode_exit is False
    assert (
        "omniclaude_mode"
        in (_HOOKS_DIR / "scripts" / "session_start_hook_parity.sh").read_text()
    )
