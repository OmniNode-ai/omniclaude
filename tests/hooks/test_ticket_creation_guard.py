# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Ticket-creation admission gate: the checker and the registered hook (OMN-17942).

Two layers, both load-bearing, for the reasons OMN-17499's suite states.

The **checker** cases pin the admission rules themselves — which field is
missing, whether the binding line is a real line or an incidental substring,
and which shapes are refused rather than assumed clean.

The **hook** cases run the registered script end to end as a subprocess. That
is not redundant with the checker cases: OMN-8928 is the counterexample this
plugin's canary harness exists for — its Python returned a correct
``{"decision": "block"}`` and the registered hook still exited 0, because
``error-guard.sh`` installs an EXIT trap that converts a non-zero exit to 0 and
that script never called ``trap - EXIT``. A unit test on the decision core
would have passed. Only running the command the harness runs tells the two
apart.

Why the gate exists at all, measured over Linear 2026-08-22 → 2026-09-04:
1553 tickets created in 14 days (~111/day) against ~35/day closed; 1537 of them
under the single API identity every lane writes as; 398 never touched again;
779 never left Backlog; 343 unclassifiable by title. The control in place was
prose in CLAUDE.md and in the dispatch briefs. It is the same memory-class
control that failed 41 times in one session in OMN-17499, and here it failed
about 1500 times in a fortnight.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_GUARD_PY = _HOOKS_DIR / "lib" / "ticket_creation_guard.py"
_HOOK_SCRIPT = _HOOKS_DIR / "scripts" / "pre_tool_use_ticket_creation_gate.sh"
_HOOKS_JSON = _HOOKS_DIR / "hooks.json"
_INVENTORY = _HOOKS_DIR / "contracts" / "hook_inventory.yaml"
_POLICY_JSON = _HOOKS_DIR / "config" / "ticket_creation_policy.json"

#: The borrowed mask bit. Its namesake script must stay unregistered — see
#: test_the_borrowed_mask_bit_gates_only_this_guard.
_GATE_BIT_NAME: Final[str] = "LINEAR_DONE_VERIFY"
_GATE_BIT: Final[int] = 0x80000000000

_TIMEOUT_S = 120


def _load_guard() -> ModuleType:
    """Load the decision core by path, not by package name.

    The hook runs the file as a plain script from the plugin cache, where no
    ``plugins`` package exists (the OMN-16983 lesson). Loading it the same way
    keeps the test honest about what actually runs.
    """
    spec = importlib.util.spec_from_file_location("ticket_creation_guard", _GUARD_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_GUARD = _load_guard()
POLICY = _GUARD.load_policy()


def _check(tool_input: dict[str, Any]) -> list[Any]:
    return list(_GUARD.check_save_issue(tool_input, POLICY))


def _codes(tool_input: dict[str, Any]) -> set[str]:
    return {f.code for f in _check(tool_input)}


_GOOD_DESCRIPTION = (
    "Gate: OMN-16729 AC-5\n"
    "\n"
    "The board grows faster than any projection can classify it, so the manual\n"
    "sweep cannot be retired until admission is controlled.\n"
)


def _create(**overrides: Any) -> dict[str, Any]:
    """A well-formed CREATE payload, with named fields overridden."""
    payload: dict[str, Any] = {
        "team": "Omninode",
        "title": "Refuse a Linear create with no binding",
        "parentId": "OMN-16729",
        "project": "7ab68a44-653e-40e1-a770-b5e6a964b159",
        "description": _GOOD_DESCRIPTION,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The shipped policy is config, not a Python literal
# ---------------------------------------------------------------------------


def test_policy_ships_as_json_next_to_the_model_guards_allowlist() -> None:
    assert _POLICY_JSON.is_file(), (
        f"{_POLICY_JSON} is missing. The vocabulary is config so that changing "
        "admission policy is a config edit reviewable in one place, not a "
        "Python literal a reader has to infer the rule from."
    )
    json.loads(_POLICY_JSON.read_text(encoding="utf-8"))


def test_policy_is_read_from_config_not_hardcoded(tmp_path: Path) -> None:
    override = tmp_path / "policy.json"
    override.write_text(
        json.dumps(
            {
                "criterion_ids": ["C1"],
                "epic_markers": ["issue_class: epic"],
                "residual_title_terms": ["nit"],
                "in_progress_state_names": ["in progress"],
            }
        ),
        encoding="utf-8",
    )
    policy = _GUARD.load_policy(override)
    assert policy.criterion_ids == frozenset({"C1"})
    assert policy.residual_title_terms == ("nit",)
    assert policy.in_progress_state_names == frozenset({"in progress"})


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ("{}", "no keys at all"),
        ('{"criterion_ids": []}', "missing epic_markers and residual terms"),
        (
            '{"criterion_ids": ["C1"], "epic_markers": [], "residual_title_terms": ["nit"]}',
            "an empty epic_markers list makes the epic escape unreachable, "
            "which is a policy change disguised as a blank",
        ),
        (
            '{"criterion_ids": "C1", "epic_markers": ["e"], "residual_title_terms": ["nit"]}',
            "criterion_ids is not a list",
        ),
        ("not json at all", "unparseable"),
    ],
)
def test_malformed_policy_raises_rather_than_defaulting(
    tmp_path: Path, payload: str, why: str
) -> None:
    """A policy that cannot be read must not silently become a permissive one.

    The failure mode this refuses is the one that makes a gate report green
    while enforcing nothing.
    """
    bad = tmp_path / "policy.json"
    bad.write_text(payload, encoding="utf-8")
    with pytest.raises(_GUARD.PolicyError):
        _GUARD.load_policy(bad)


def test_shipped_residual_vocabulary_covers_the_named_terms() -> None:
    terms = set(POLICY.residual_title_terms)
    for expected in ("follow-up", "residual", "nit", "minor", "cleanup", "noted"):
        assert expected in terms, f"{expected!r} missing from the shipped vocabulary"


# ---------------------------------------------------------------------------
# Updates are never gated
# ---------------------------------------------------------------------------


def test_an_update_is_never_gated() -> None:
    """`save_issue` with an `id` edits an existing row and creates nothing.

    Gating it would block every state flip, every description repair and every
    parent re-link the board-truth work depends on.
    """
    assert (
        _check(
            {
                "id": "OMN-17942",
                "state": "In Progress",
                "description": "no Gate line, no parent, no project",
            }
        )
        == []
    )


def test_an_update_that_removes_the_parent_is_still_not_gated() -> None:
    assert _check({"id": "OMN-17942", "parentId": None}) == []


# ---------------------------------------------------------------------------
# The four admission rules
# ---------------------------------------------------------------------------


def test_a_well_formed_create_is_allowed() -> None:
    assert _check(_create()) == []


def test_create_without_a_parent_is_refused() -> None:
    assert "missing_parent" in _codes(_create(parentId=None))


def test_create_with_no_parent_key_at_all_is_refused() -> None:
    payload = _create()
    del payload["parentId"]
    assert "missing_parent" in _codes(payload)


def test_create_with_a_blank_parent_is_refused() -> None:
    assert "missing_parent" in _codes(_create(parentId="   "))


def test_an_epic_marker_in_the_description_substitutes_for_a_parent() -> None:
    payload = _create()
    del payload["parentId"]
    payload["description"] = "issue_class: epic\n\n" + _GOOD_DESCRIPTION
    assert "missing_parent" not in _codes(payload)


def test_the_epic_marker_must_be_its_own_line() -> None:
    """Rule 15 of the workspace doctrine, applied here.

    A gate that substring-matches fires on prose that merely mentions the
    trigger — and, the direction that matters, PASSES on prose that mentions
    it while meaning nothing. "this is not an issue_class: epic, it is a
    child" would otherwise open the parent escape.
    """
    payload = _create()
    del payload["parentId"]
    payload["description"] = (
        "This row is not an issue_class: epic, it is a child of the epic.\n\n"
        + _GOOD_DESCRIPTION
    )
    assert "missing_parent" in _codes(payload)


def test_create_without_a_project_is_refused() -> None:
    payload = _create()
    del payload["project"]
    assert "missing_project" in _codes(payload)


def test_create_with_a_null_project_is_refused() -> None:
    assert "missing_project" in _codes(_create(project=None))


def test_the_projectid_spelling_is_accepted_too() -> None:
    """The MCP surface's field is `project`; `projectId` is what the REST API
    and half the internal prose call it. Both name the same requirement, and a
    guard that refuses one spelling teaches lanes to work around it rather than
    to name a project."""
    payload = _create()
    del payload["project"]
    payload["projectId"] = "7ab68a44-653e-40e1-a770-b5e6a964b159"
    assert "missing_project" not in _codes(payload)


def test_create_without_a_gate_line_is_refused() -> None:
    assert "missing_gate_line" in _codes(
        _create(description="Some work that should happen.\n")
    )


def test_create_with_no_description_at_all_is_refused() -> None:
    payload = _create()
    del payload["description"]
    assert "missing_gate_line" in _codes(payload)


@pytest.mark.parametrize(
    "line",
    [
        "Gate: C1",
        "Gate: OMN-16729 AC-5",
        "Gate: OMN-16106 AC-12",
        "Gate: live-gate defect: kb-doc-gate",
        "Gate: live-gate defect: deploy-gate / deploy-gate",
        "  Gate: OMN-16729 AC-5",
    ],
)
def test_every_accepted_binding_form_passes(line: str) -> None:
    assert "missing_gate_line" not in _codes(
        _create(description=f"{line}\n\nWhy this is the binding.\n")
    )


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("Gate: C99", "a criterion id that is not in the shipped set"),
        ("Gate: OMN-16729", "a parent with no acceptance-criterion ordinal"),
        ("Gate: OMN-16729 AC-", "an empty ordinal"),
        ("Gate: AC-5", "an ordinal with no parent"),
        ("Gate: live-gate defect:", "a defect with no check named"),
        ("Gate: because it seemed useful", "free text"),
        ("Gate:", "the keyword alone"),
    ],
)
def test_a_gate_line_that_binds_to_nothing_is_refused(line: str, why: str) -> None:
    assert "missing_gate_line" in _codes(_create(description=f"{line}\n\nbody\n")), (
        f"expected a refusal for {why}"
    )


def test_the_gate_line_must_be_a_line_not_a_substring() -> None:
    """The same rule-15 failure, on the binding half.

    "the ticket carries no Gate: OMN-1 AC-1 line" would otherwise satisfy the
    gate by describing its own absence — a gate firing green on documentation
    about the gate, which is exactly the OCC#7213 shape.
    """
    assert "missing_gate_line" in _codes(
        _create(description="This row carries no Gate: OMN-16729 AC-5 binding yet.\n")
    )


def test_a_bulleted_gate_line_is_refused() -> None:
    """The OCC `Evidence-Ticket:` convention is unbulleted for the same reason:
    a bullet is how a line ends up inside a checklist that nothing binds."""
    assert "missing_gate_line" in _codes(
        _create(description="- Gate: OMN-16729 AC-5\n\nbody\n")
    )


# ---------------------------------------------------------------------------
# Residual-shaped titles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Follow-up: tighten the selector",
        "follow up on the review thread",
        "Residual from OMN-17499: the fork case",
        "nit: rename the fixture",
        "Minor cleanup in the hooks dir",
        "Cleanup: delete the dead branch",
        "Noted during review — the log line is duplicated",
    ],
)
def test_a_residual_shaped_title_is_refused(title: str) -> None:
    assert "residual_title" in _codes(_create(title=title))


def test_a_residual_shaped_title_is_allowed_when_it_binds_to_a_live_gate_defect() -> (
    None
):
    """The one exemption, and the reason it exists.

    A live gate that is broken is not a residual — it is a control reporting
    green while enforcing nothing, and the standing rule to comment on the
    parent instead of filing would bury it. The exemption is deliberately
    narrow: a criterion id or a parent AC does NOT unlock a residual title.
    """
    assert "residual_title" not in _codes(
        _create(
            title="Follow-up: kb-doc-gate passes a renamed file",
            description="Gate: live-gate defect: kb-doc-gate\n\nbody\n",
        )
    )


def test_a_criterion_binding_does_not_unlock_a_residual_title() -> None:
    assert "residual_title" in _codes(
        _create(
            title="nit: rename the fixture",
            description="Gate: C1\n\nbody\n",
        )
    )


def test_a_parent_ac_binding_does_not_unlock_a_residual_title() -> None:
    assert "residual_title" in _codes(
        _create(
            title="Residual: the fork case",
            description="Gate: OMN-16729 AC-5\n\nbody\n",
        )
    )


def test_residual_terms_match_on_word_boundaries_not_inside_other_words() -> None:
    """`minor` must not fire on `minority`, and `nit` must not fire on
    `initialise` or `monitor`. A gate that refuses correct work teaches lanes
    to route around it, which costs more than the tickets it stops."""
    for title in (
        "Monitor the queue depth for the delegation lane",
        "Initialise the tenant credential chain",
        "Report the minority-class routing split",
    ):
        assert "residual_title" not in _codes(_create(title=title)), title


# ---------------------------------------------------------------------------
# Fail-closed on a malformed call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool_input", "why"),
    [
        ({}, "no fields at all"),
        ({"title": "x"}, "a create with nothing but a title"),
        ({"id": "", "title": "x"}, "an id that is present but blank"),
        ({"id": 17942, "title": "x"}, "an id that is not a string"),
        ({"title": None, "parentId": "OMN-1", "project": "p"}, "a null title"),
        ({"title": 3, "parentId": "OMN-1", "project": "p"}, "a non-string title"),
        (
            {"title": "x", "parentId": "OMN-1", "project": "p", "description": 7},
            "a non-string description",
        ),
    ],
)
def test_an_unevaluable_create_is_refused(tool_input: dict[str, Any], why: str) -> None:
    assert _check(tool_input), f"expected a refusal for {why}"


def test_a_template_create_with_no_description_is_refused() -> None:
    """A `template` fills the body server-side, so the guard cannot see whether
    a binding line is in it. Refusing is the fail-closed reading: a create
    whose text the guard never sees is unverified, not clean."""
    codes = _codes(
        {
            "team": "Omninode",
            "title": "From a template",
            "parentId": "OMN-16729",
            "project": "7ab68a44",
            "template": "Bug report",
        }
    )
    assert "missing_gate_line" in codes


def test_the_block_reason_names_the_missing_field_and_the_fix() -> None:
    reason = _GUARD.render_block_reason(_check(_create(parentId=None)), POLICY)
    assert "parentId" in reason
    assert "OMN-17942" in reason
    assert _GATE_BIT_NAME in reason, (
        "the refusal must name its own disable switch, or a lane blocked by a "
        "guard it thinks is wrong has no route except to work around it"
    )


def test_the_block_reason_lists_every_failing_rule_at_once() -> None:
    """One refusal per call, naming everything wrong with it.

    A guard that reports one missing field per attempt turns a single fix into
    four round trips, and each round trip is a chance for the lane to give up
    and file the ticket from somewhere the gate does not see.
    """
    reason = _GUARD.render_block_reason(
        _check({"title": "nit: a thing", "team": "Omninode"}), POLICY
    )
    for expected in ("parentId", "project", "Gate:"):
        assert expected in reason


# ---------------------------------------------------------------------------
# The registered hook, end to end
# ---------------------------------------------------------------------------


def _registered_command() -> str:
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for group in data["hooks"]["PreToolUse"]
        for hook in group["hooks"]
    ]
    matching = [c for c in commands if c.endswith("/" + _HOOK_SCRIPT.name)]
    assert matching, (
        f"hooks.json does not register {_HOOK_SCRIPT.name}. This test FAILS "
        "rather than skips on purpose: an unregistered enforcement hook is "
        "exactly the OMN-13244 defect, and a skipped check reports it as green."
    )
    return str(matching[0])


def _matcher_for_registered_hook() -> str:
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    for group in data["hooks"]["PreToolUse"]:
        for hook in group["hooks"]:
            if hook["command"].endswith("/" + _HOOK_SCRIPT.name):
                return str(group["matcher"])
    raise AssertionError(f"{_HOOK_SCRIPT.name} is not registered")


def _hook_ledger(tmp_path: Path) -> Path:
    """Where the guard's log lines actually land.

    `onex-paths.sh` *exports* ONEX_HOOK_LOG unconditionally as
    ``$ONEX_STATE_DIR/logs/hooks.log``, overwriting whatever the caller set. So
    a caller-supplied ONEX_HOOK_LOG is not honoured, and asserting against one
    would test a file no hook on this machine ever writes. The state-dir path is
    the shared hook ledger every sibling guard logs to; that is the surface
    these tests read.
    """
    return tmp_path / "state" / "logs" / "hooks.log"


def _run_hook(
    payload: dict[str, Any], tmp_path: Path, *, mask: str | None = None
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(_HOOKS_DIR.parent),
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        # Pinned, not inherited: mode.sh resolves "lite" for some cwds, and the
        # question here is whether the hook enforces, not what mode the host is
        # in.
        "OMNICLAUDE_MODE": "full",
    }
    if mask is not None:
        env["ONEX_HOOKS_MASK"] = mask
    return subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_S,
        check=False,
    )


def test_hook_script_is_registered_and_executable() -> None:
    assert _registered_command().endswith("/" + _HOOK_SCRIPT.name)
    assert os.access(_HOOK_SCRIPT, os.X_OK), f"{_HOOK_SCRIPT} is not executable"


def test_the_matcher_covers_the_linear_write_surface() -> None:
    matcher = _matcher_for_registered_hook()
    assert "save_issue" in matcher, (
        "mcp__linear-server__save_issue is the create path every lane writes "
        f"through; the registered matcher {matcher!r} does not cover it"
    )


def test_jq_is_available() -> None:
    """The hook renders its decision with ``jq -n``, as every sibling guard
    does. Asserted rather than skipped around: without jq the block payload
    never reaches stdout, the script exits non-zero, and ``error-guard.sh``
    converts that to exit 0 — a silent fail-OPEN."""
    assert shutil.which("jq") is not None


def test_the_borrowed_mask_bit_gates_only_this_guard() -> None:
    """`LINEAR_DONE_VERIFY` must remain a one-control switch.

    This guard borrows that bit because a dedicated one is not mintable here:
    `EnumHookBit` lives in omnibase_core, all 60 default-mask ordinals are
    allocated, 60-62 are the disabled-by-default trio, and
    knowledge-base-internal `reference/hook-bitmask-bit-governance.md` rule 7
    forbids ordinal 63 outright.

    The borrow is only honest while the bit's namesake script stays
    unregistered. `pre_tool_use_linear_done_verify.sh` is on disk and dark
    under the OMN-13244 baseline — its merged-PR semantics were folded into
    `pre_tool_use_done_flip_guard.sh` by OMN-13856 — so today
    `onex hooks disable LINEAR_DONE_VERIFY` disables exactly this guard. If
    someone re-registers it, that one command silently turns off two controls,
    which is the quiet switch-mismatch the OMN-17020 inventory exists to
    refuse.
    """
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    registered = {
        hook["command"].rsplit("/", 1)[-1]
        for group in data["hooks"].get("PreToolUse", [])
        for hook in group["hooks"]
    }
    assert "pre_tool_use_linear_done_verify.sh" not in registered, (
        "pre_tool_use_linear_done_verify.sh has been registered, so "
        "LINEAR_DONE_VERIFY now gates two controls. Either mint this guard its "
        "own EnumHookBit (an omnibase_core change plus the architecture review "
        "knowledge-base-internal reference/hook-bitmask-bit-governance.md rule "
        "7 requires), or move one of the two to a different bit. Do not leave "
        "two guards behind one switch."
    )


def test_the_hook_is_declared_in_the_typed_inventory() -> None:
    """OMN-17020: a registration hooks.json carries and the inventory does not
    is exactly the drift the hook-inventory gate fails closed on."""
    inventory = yaml.safe_load(_INVENTORY.read_text(encoding="utf-8"))
    entries = [
        h for h in inventory["expected_hooks"] if h["script"] == _HOOK_SCRIPT.name
    ]
    assert entries, f"{_HOOK_SCRIPT.name} is not declared in {_INVENTORY}"
    entry = entries[0]
    assert entry["ticket"] == "OMN-17942"
    assert entry["event"] == "PreToolUse"
    assert entry["enforcement"] is True
    assert entry["mask"]["gate_call"] == _GATE_BIT_NAME
    assert entry["mask"]["bit_defined"] is True
    assert entry["canary"]["kind"] == "block"


def test_registered_hook_blocks_a_create_with_no_binding(tmp_path: Path) -> None:
    """The OMN-8928 shape: a correct verdict whose exit code is swallowed
    enforces nothing. Assert the exit code and the payload, from the command
    the harness actually runs."""
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {
                "team": "Omninode",
                "title": "Some work that occurred to a lane",
                "description": "It would be good to do this.\n",
            },
        },
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, (
        f"expected a block (exit 2), got {result.returncode}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert '"decision": "block"' in combined
    assert "parentId" in combined
    assert "project" in combined
    assert "Gate:" in combined
    assert _GATE_BIT_NAME in combined


def test_registered_hook_blocks_a_residual_title(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {
                "team": "Omninode",
                "title": "Follow-up: tighten the selector",
                "parentId": "OMN-16729",
                "project": "7ab68a44",
                "description": "Gate: OMN-16729 AC-5\n\nbody\n",
            },
        },
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, combined
    assert "residual" in combined.lower()


def test_registered_hook_allows_a_well_formed_create(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": _create(),
        },
        tmp_path,
    )
    assert result.returncode == 0, (
        f"a well-formed create was refused.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )


def test_registered_hook_allows_an_update(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {"id": "OMN-17942", "state": "In Progress"},
        },
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_registered_hook_blocks_an_unparseable_payload(tmp_path: Path) -> None:
    """Only the Linear write surface reaches this hook, so refusing an
    unreadable payload cannot strand any other tool."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input="{not json",
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "CLAUDE_PLUGIN_ROOT": str(_HOOKS_DIR.parent),
            "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "OMNICLAUDE_MODE": "full",
        },
        timeout=_TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_registered_hook_passes_through_another_tool(tmp_path: Path) -> None:
    """A tool other than the Linear write surface is passed through untouched,
    so a bug in this guard can never brick unrelated traffic."""
    result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_disable_switch_allows_and_logs_a_notice(tmp_path: Path) -> None:
    """`onex hooks disable LINEAR_DONE_VERIFY` clears the bit in the mask.

    A disabled guard must still leave a trace. The OMN-13244 history is a hook
    going dark with no repo-visible signal for months; a silent `exit 0` here
    would reproduce it one mask edit at a time.
    """
    disabled = hex(0xFFFFFFFFFFFFFFF & ~_GATE_BIT)
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {"team": "Omninode", "title": "no binding at all"},
        },
        tmp_path,
        mask=disabled,
    )
    assert result.returncode == 0, (
        "the mask bit is cleared, so the guard must not refuse.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    log = _hook_ledger(tmp_path).read_text(encoding="utf-8")
    assert _GATE_BIT_NAME in log
    assert "DISABLED" in log


def test_a_refusal_is_recorded_in_the_hook_log(tmp_path: Path) -> None:
    """The model gate logs its refusals; so does this one. A refusal nobody can
    count is a control nobody can measure, and the measurement is the whole
    reason this gate exists."""
    _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {"team": "Omninode", "title": "no binding at all"},
        },
        tmp_path,
    )
    log = _hook_ledger(tmp_path).read_text(encoding="utf-8")
    assert "BLOCKED" in log
    assert "ticket-creation-gate" in log


# ---------------------------------------------------------------------------
# Rule 5 — a create that STARTS In Progress needs an executable probe
# ---------------------------------------------------------------------------
#
# Why: the scheduled evidence closer (OMN-16106) re-runs `onex skill dod_verify`
# against the checks a ticket's OCC contract declares. A ticket whose definition
# of done is prose declares no check it can run, so it is structurally
# unreachable by every closing mechanism and can only ever be closed by a person
# reading it — four such tickets sit In Progress in the 2026-08-31 sprint. The
# probe line is the one thing that must exist at the START for a ticket to be
# mechanically closeable at the end.

_PROBE = "Probe: uv run pytest tests/hooks/test_ticket_creation_guard.py -q => exits 0"


def _in_progress(**overrides: Any) -> dict[str, Any]:
    payload = _create(state="In Progress")
    payload.update(overrides)
    return payload


def test_in_progress_create_without_a_probe_is_refused() -> None:
    codes = {finding.code for finding in _check(_in_progress())}
    assert "missing_probe_line" in codes


def test_in_progress_create_with_a_probe_is_admitted() -> None:
    payload = _in_progress(description=f"{_GOOD_DESCRIPTION}\n{_PROBE}\n")
    assert _check(payload) == []


@pytest.mark.parametrize(
    "state_value",
    ["In Progress", "in progress", "  IN-PROGRESS  ", "started", "inprogress"],
)
def test_every_configured_in_progress_spelling_fires(state_value: str) -> None:
    codes = {finding.code for finding in _check(_create(state=state_value))}
    assert "missing_probe_line" in codes


@pytest.mark.parametrize("field", ["state", "stateId", "status", "statusType"])
def test_the_rule_reads_every_state_spelling_the_write_surface_accepts(
    field: str,
) -> None:
    codes = {finding.code for finding in _check(_create(**{field: "In Progress"}))}
    assert "missing_probe_line" in codes


def test_a_backlog_create_needs_no_probe() -> None:
    """Rule 5 is scoped to work claimed to be in flight, not to every create.

    A probe demanded at filing time for work nobody has scoped yet is a field a
    lane fills in with something plausible to get past the check.
    """
    assert _check(_create(state="Backlog")) == []
    assert _check(_create()) == []


def test_a_state_uuid_is_not_classified_and_not_refused() -> None:
    """The one fail-OPEN direction, bounded to rule 5 and stated on purpose.

    This module has no workspace lookup, so it cannot resolve a state uuid.
    Refusing on one would make every id-shaped create unfileable; the refusal
    it does make is on a create that says, in words, that it starts In Progress.
    """
    payload = _create(stateId="f1a2b3c4-0000-4d5e-8f90-abcdefabcdef")
    assert _check(payload) == []


def test_a_probe_missing_its_expected_observation_is_refused() -> None:
    """A command with no expected observation is adjudicated by a human read."""
    payload = _in_progress(
        description=f"{_GOOD_DESCRIPTION}\nProbe: uv run pytest tests/unit -q\n"
    )
    codes = {finding.code for finding in _check(payload)}
    assert "malformed_probe_line" in codes


@pytest.mark.parametrize(
    "probe_body",
    ["=> exits 0", "uv run pytest -q =>", "   =>   "],
)
def test_a_probe_with_a_blank_half_is_refused(probe_body: str) -> None:
    payload = _in_progress(description=f"{_GOOD_DESCRIPTION}\nProbe: {probe_body}\n")
    codes = {finding.code for finding in _check(payload)}
    assert "malformed_probe_line" in codes


def test_a_bulleted_probe_does_not_count() -> None:
    """CLAUDE.md rule 15: a bullet is how a line lands inside a checklist.

    The line must bind, not appear in a list of things someone might do.
    """
    payload = _in_progress(description=f"{_GOOD_DESCRIPTION}\n- {_PROBE}\n")
    codes = {finding.code for finding in _check(payload)}
    assert "missing_probe_line" in codes


def test_prose_mentioning_a_probe_does_not_satisfy_the_rule() -> None:
    """The direction that matters for an admission gate.

    A substring rule *passes* on prose that mentions the trigger while meaning
    the opposite — "this ticket has no Probe: line yet" would satisfy it.
    """
    payload = _in_progress(
        description=(
            f"{_GOOD_DESCRIPTION}\n"
            "This ticket has no Probe: line yet because the deliverable is prose.\n"
        )
    )
    codes = {finding.code for finding in _check(payload)}
    assert "malformed_probe_line" in codes or "missing_probe_line" in codes


def test_one_well_formed_probe_among_several_lines_satisfies_the_rule() -> None:
    """Matches how several `Gate:` lines are treated — the strongest one wins."""
    payload = _in_progress(
        description=f"{_GOOD_DESCRIPTION}\nProbe: an example with no arrow\n{_PROBE}\n"
    )
    assert _check(payload) == []


def test_an_update_that_moves_a_ticket_to_in_progress_is_still_not_gated() -> None:
    """The transition surface this module deliberately does not cover.

    A ticket created in Backlog and moved to In Progress later moves by an
    UPDATE, and updates are never gated here. Recording it as a test so the
    scope of rule 5 is a pinned fact rather than a claim in a docstring — if a
    later change starts gating updates, this test is the one that has to be
    deliberately rewritten.
    """
    assert _check({"id": "OMN-16106", "state": "In Progress"}) == []


def test_the_shipped_policy_configures_the_in_progress_vocabulary() -> None:
    assert POLICY.in_progress_state_names
    assert "in progress" in POLICY.in_progress_state_names


def test_a_policy_missing_the_in_progress_vocabulary_is_refused(
    tmp_path: Path,
) -> None:
    """No default in code: an unreadable policy refuses, never widens."""
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    del raw["in_progress_state_names"]
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(_GUARD.PolicyError):
        _GUARD.load_policy(bad)
