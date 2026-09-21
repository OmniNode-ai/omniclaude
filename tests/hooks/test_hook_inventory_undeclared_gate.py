# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The third parity direction: a gate-shaped script declared nowhere [OMN-18530].

``hook_inventory.yaml`` checked parity in two directions. Everything declared
had to be registered and present; everything registered had to be declared. A
script named in neither half was invisible to both, and 34 gate-shaped scripts
were sitting in that blind spot with nobody owning them.

The tests here hold the new kind to the shape the ticket asks for, and the
three that matter most are the ones that keep it from becoming noise:

* a real named dark script produces a finding (:func:`test_a_named_dark_gate_
  script_is_reported_when_its_declaration_is_removed`),
* a library a registered hook calls does NOT (:func:`test_no_script_reachable_
  from_a_registered_hook_is_reported`), and
* an observer that cannot refuse does NOT
  (:func:`test_a_script_that_cannot_refuse_is_not_reported`).

A kind that fires on the first and not the other two separates an undeclared
gate from a called module, which is the whole discrimination the gate exists to
make. Findings are asserted as parsed records — code and subject — never by
matching the rendered sentence, so rewording a message cannot silently retire a
control.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_INVENTORY_REL = "plugins/onex/hooks/contracts/hook_inventory.yaml"
_HOOKS_JSON_REL = "plugins/onex/hooks/hooks.json"
_LIB_REL = "plugins/onex/hooks/lib/hook_inventory.py"
_SCRIPTS_REL = "plugins/onex/hooks/scripts"
_VALIDATOR = _REPO_ROOT / "scripts" / "validation" / "validate_hook_inventory.py"

#: The kind this ticket adds. Named once so a rename breaks every test at the
#: same place rather than leaving some of them passing against a dead string.
_KIND = "UNDECLARED_GATE_SCRIPT"
_EVENT_KEY_KIND = "EVENT_KEY_ABSENT"

#: The triage ticket every placeholder declaration this change lands points at.
_TRIAGE_TICKET = "OMN-18531"

#: One real, named, gate-shaped script that is dark today. The ticket's probe
#: asks for a fixture; this is the fixture being an actual member of the
#: population rather than a synthetic stand-in for one.
_NAMED_DARK_GATE = "pre_tool_use_dispatch_guard.sh"

#: A real library that a registered hook sources. It carries no refusal of its
#: own, and it is reached from a registered root, so it fails BOTH halves of
#: the match — the control for AC2.
_NAMED_REACHABLE_LIBRARY = "common.sh"


def _load_lib(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_LIB = _load_lib(_REPO_ROOT / _LIB_REL, "hook_inventory_undeclared_under_test")

_TODAY = date(2026, 9, 21)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A fully writable copy of the hook surface.

    The sibling suite symlinks ``scripts/`` to keep the copy cheap. These tests
    ADD and REMOVE scripts, so the directory has to be real: a symlinked mirror
    would write the fixture into the repository.
    """
    root = tmp_path / "tree"
    (root / "plugins" / "onex" / "hooks" / "contracts").mkdir(parents=True)
    (root / "plugins" / "onex" / "hooks" / "lib").mkdir(parents=True)
    shutil.copy2(_REPO_ROOT / _INVENTORY_REL, root / _INVENTORY_REL)
    shutil.copy2(_REPO_ROOT / _HOOKS_JSON_REL, root / _HOOKS_JSON_REL)
    shutil.copy2(_REPO_ROOT / _LIB_REL, root / _LIB_REL)
    shutil.copy2(
        _HOOKS_DIR / "lib" / "hook_bits.sh",
        root / "plugins" / "onex" / "hooks" / "lib" / "hook_bits.sh",
    )
    shutil.copytree(_HOOKS_DIR / "scripts", root / _SCRIPTS_REL)
    return root


def _findings(root: Path, today: date = _TODAY) -> tuple[Any, ...]:
    inventory = _LIB.load_inventory(root / _INVENTORY_REL)
    return tuple(_LIB.check_parity(inventory, root, today))


def _subjects(root: Path, kind: str, today: date = _TODAY) -> set[str]:
    return {f.subject for f in _findings(root, today) if f.code == kind}


def _read_inventory(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / _INVENTORY_REL).read_text(encoding="utf-8"))


def _write_inventory(root: Path, data: dict[str, Any]) -> None:
    (root / _INVENTORY_REL).write_text(yaml.safe_dump(data), encoding="utf-8")


def _add_script(root: Path, name: str, body: str) -> None:
    path = root / _SCRIPTS_REL / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _registered_scripts(root: Path) -> set[str]:
    data = json.loads((root / _HOOKS_JSON_REL).read_text(encoding="utf-8"))
    return {
        entry["command"].rsplit("/", 1)[-1]
        for groups in data["hooks"].values()
        for group in groups
        for entry in group["hooks"]
    }


# ---------------------------------------------------------------------------
# AC1 — the kind fires, and it names the file
# ---------------------------------------------------------------------------


def test_a_gate_shaped_script_declared_nowhere_is_reported_by_name(
    tree: Path,
) -> None:
    """The ticket's probe, run forwards and backwards.

    Add a gate-shaped script declared in neither list: the gate names it.
    Remove it: the gate stops naming it. The second half is what proves the
    finding is about that file rather than a constant the gate always emits.
    """
    name = "pre_tool_use_omn18530_probe_guard.sh"
    assert name not in _subjects(tree, _KIND), "fixture name already present"

    _add_script(
        tree,
        name,
        '#!/usr/bin/env bash\nset -euo pipefail\nif [[ "${1:-}" == "bad" ]]; then\n'
        '  echo "refused" >&2\n  exit 2\nfi\nexit 0\n',
    )
    assert name in _subjects(tree, _KIND)

    (tree / _SCRIPTS_REL / name).unlink()
    assert name not in _subjects(tree, _KIND)


def test_a_named_dark_gate_script_is_reported_when_its_declaration_is_removed(
    tree: Path,
) -> None:
    """A real member of the population, not a synthetic one.

    This change declares all 34 as placeholders so the merged tree is green.
    Deleting one declaration has to bring its finding straight back, or the
    declarations are load-bearing for the gate's silence rather than for its
    correctness.
    """
    assert _NAMED_DARK_GATE not in _subjects(tree, _KIND)

    data = _read_inventory(tree)
    before = len(data["disabled_hooks"])
    data["disabled_hooks"] = [
        row for row in data["disabled_hooks"] if row["script"] != _NAMED_DARK_GATE
    ]
    assert len(data["disabled_hooks"]) == before - 1, "the named script is declared"
    _write_inventory(tree, data)

    assert _NAMED_DARK_GATE in _subjects(tree, _KIND)


def test_the_gate_refuses_rather_than_printing_and_passing(tree: Path) -> None:
    """Exit status, not output. A gate that prints a finding and exits 0 is a report."""
    _add_script(
        tree,
        "pre_tool_use_omn18530_refusal_probe.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 2\n",
    )
    result = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(tree)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "pre_tool_use_omn18530_refusal_probe.sh" in result.stderr
    assert _KIND in result.stderr


# ---------------------------------------------------------------------------
# AC2 — the control that separates an undeclared gate from a called module
# ---------------------------------------------------------------------------


def test_no_script_reachable_from_a_registered_hook_is_reported(tree: Path) -> None:
    """Every callee of a live hook, measured off the tree rather than listed."""
    scripts_dir = tree / _SCRIPTS_REL
    reachable = _LIB.scripts_reachable_from_registered(
        _registered_scripts(tree), scripts_dir
    )
    assert reachable, "reachability found nothing, so this control proves nothing"
    assert _NAMED_REACHABLE_LIBRARY in reachable

    reported = _subjects(tree, _KIND)
    assert not (reachable & reported), sorted(reachable & reported)


def test_a_refusing_library_called_by_a_registered_hook_is_not_reported(
    tree: Path,
) -> None:
    """The positive control for the reachability half.

    A script that CAN refuse and is undeclared, differing from a real finding
    in one fact only: something registered calls it. It must not be reported,
    and severing the call must report it — otherwise the exclusion is passing
    for a reason other than reachability.
    """
    library = "omn18530_probe_library.sh"
    _add_script(
        tree,
        library,
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 2\n",
    )
    assert library in _subjects(tree, _KIND), "unreached, it is a finding"

    caller = sorted(_registered_scripts(tree))[0]
    caller_path = tree / _SCRIPTS_REL / caller
    original = caller_path.read_text(encoding="utf-8")
    caller_path.write_text(
        original + f'\n"${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/{library}" || true\n',
        encoding="utf-8",
    )
    assert library not in _subjects(tree, _KIND), "reached, it is a callee"

    caller_path.write_text(original, encoding="utf-8")
    assert library in _subjects(tree, _KIND), "call severed, it is a finding again"


def test_a_mention_in_a_comment_is_not_a_call(tree: Path) -> None:
    """Comments in this tree name guards constantly; prose is not reachability."""
    library = "omn18530_probe_mentioned.sh"
    _add_script(tree, library, "#!/usr/bin/env bash\nexit 2\n")
    caller = sorted(_registered_scripts(tree))[0]
    caller_path = tree / _SCRIPTS_REL / caller
    caller_path.write_text(
        caller_path.read_text(encoding="utf-8")
        + f"\n# see ${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/{library} for the rule\n",
        encoding="utf-8",
    )
    assert library in _subjects(tree, _KIND)


def test_a_call_carrying_a_trailing_comment_is_still_a_call(tree: Path) -> None:
    """Comment stripping drops whole-line comments only, never code.

    The reachability pass removes lines whose first non-space character opens a
    comment. A line that runs code and then comments on it is code, and
    dropping it would turn a real call into a missed one, which reports a live
    callee as a dark gate.
    """
    library = "omn18530_probe_trailing.sh"
    _add_script(tree, library, "#!/usr/bin/env bash\nexit 2\n")
    assert library in _subjects(tree, _KIND)

    caller_path = tree / _SCRIPTS_REL / sorted(_registered_scripts(tree))[0]
    caller_path.write_text(
        caller_path.read_text(encoding="utf-8")
        + f'\n"${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/{library}"  # shared utils\n',
        encoding="utf-8",
    )
    assert library not in _subjects(tree, _KIND)


def test_sourcing_a_library_does_not_make_the_caller_a_gate(tree: Path) -> None:
    """Refusal propagates through ``exec``, never through ``source``.

    Sourcing pulls in function definitions. An ``exit 2`` inside one of them
    fires only if something calls it, so treating every sourcing script as
    refusal-capable infers a refusal that may be unreachable. ``exec`` carries
    no such doubt: the process becomes the target.
    """
    library = "omn18530_probe_sourced_lib.sh"
    _add_script(
        tree,
        library,
        "#!/usr/bin/env bash\nomn18530_refuse() {\n  exit 2\n}\n",
    )
    sourcer = "omn18530_probe_sourcer.sh"
    _add_script(
        tree,
        sourcer,
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'source "${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/{library}"\nexit 0\n',
    )
    reported = _subjects(tree, _KIND)
    assert library in reported, "the library itself carries the refusal literal"
    assert sourcer not in reported, "sourcing it does not make the caller a gate"

    execer = "omn18530_probe_execer.sh"
    _add_script(
        tree,
        execer,
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'exec "${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/{library}"\n',
    )
    assert execer in _subjects(tree, _KIND), "exec replaces the process, so it does"


def test_a_script_that_cannot_refuse_is_not_reported(tree: Path) -> None:
    """An observer is not a gate. This is the other half of the discrimination."""
    observer = "post_tool_use_omn18530_probe_observer.sh"
    _add_script(
        tree,
        observer,
        '#!/usr/bin/env bash\nset -euo pipefail\necho "observed" >>/dev/null\nexit 0\n',
    )
    assert observer not in _subjects(tree, _KIND)


def test_a_wrapper_that_execs_a_refusing_guard_is_reported(tree: Path) -> None:
    """Delegation carries refusal; plain invocation does not.

    ``subagent_skip_token_surface_guard.sh`` is twelve lines that ``exec`` the
    shared guard, and it is a real member of the 34. A harness that merely runs
    guards as subprocesses is not.
    """
    scripts_dir = tree / _SCRIPTS_REL
    refusing = _LIB.refusing_scripts(scripts_dir)
    assert "subagent_skip_token_surface_guard.sh" in refusing
    closure = _LIB.delegation_closure(
        scripts_dir, "subagent_skip_token_surface_guard.sh"
    )
    # The closure is transitive and therefore also carries what the guard
    # itself sources. What matters is the hop that supplies the refusal: the
    # wrapper has no `exit 2` of its own and inherits one from here.
    assert "skip_token_surface_guard.sh" in closure
    assert "exit 2" in (scripts_dir / "skip_token_surface_guard.sh").read_text()
    assert (
        "exit 2"
        not in (scripts_dir / "subagent_skip_token_surface_guard.sh").read_text()
    )
    assert "test-hooks.sh" not in refusing


# ---------------------------------------------------------------------------
# AC4 — the absent Stop key
# ---------------------------------------------------------------------------


def test_hooks_json_carries_no_stop_key_today() -> None:
    """The premise the next test rests on, asserted rather than assumed."""
    data = json.loads((_REPO_ROOT / _HOOKS_JSON_REL).read_text(encoding="utf-8"))
    assert "Stop" not in data["hooks"]
    on_disk = [
        path.name
        for path in sorted((_REPO_ROOT / _SCRIPTS_REL).iterdir())
        if path.is_file() and _LIB.event_for_script_name(path.name) == "Stop"
    ]
    assert on_disk, "no Stop-shaped scripts, so the absent key costs nothing"


def test_a_stop_shaped_expected_hook_is_reported_while_no_stop_key_exists(
    tree: Path,
) -> None:
    """Declaring a Stop hook expected, with no Stop key, must not read as green.

    ``UNREGISTERED_EXPECTED`` alone says "re-register it", which reads as a
    one-line addition to a group that does not exist. The finding has to name
    the missing key, or the triage writes a row under a key the harness never
    reads and records the hook as restored.
    """
    data = _read_inventory(tree)
    data["disabled_hooks"] = [
        row for row in data["disabled_hooks"] if row["script"] != "stop_quality_gate.sh"
    ]
    data["expected_hooks"].append(
        {
            "script": "stop_quality_gate.sh",
            "event": "Stop",
            "matcher": None,
            "order": 0,
            "ticket": _TRIAGE_TICKET,
            "owner": "omniclaude hooks lane",
            "purpose": "fixture: a Stop-shaped hook declared expected",
            "enforcement": False,
            "lite_mode_exit": False,
            "mask": {"gate_call": None, "bit_defined": False},
            "canary": None,
            "no_canary_reason": "fixture",
        }
    )
    _write_inventory(tree, data)

    findings = _findings(tree)
    named = [f for f in findings if f.code == _EVENT_KEY_KIND]
    assert [f.subject for f in named] == ["stop_quality_gate.sh"]
    assert "Stop" in named[0].detail


def test_the_event_key_kind_is_silent_when_the_key_exists(tree: Path) -> None:
    """The negative control: add the key, the finding goes away."""
    data = _read_inventory(tree)
    data["disabled_hooks"] = [
        row for row in data["disabled_hooks"] if row["script"] != "stop_quality_gate.sh"
    ]
    data["expected_hooks"].append(
        {
            "script": "stop_quality_gate.sh",
            "event": "Stop",
            "matcher": None,
            "order": 0,
            "ticket": _TRIAGE_TICKET,
            "owner": "omniclaude hooks lane",
            "purpose": "fixture: a Stop-shaped hook declared expected",
            "enforcement": False,
            "lite_mode_exit": False,
            "mask": {"gate_call": None, "bit_defined": False},
            "canary": None,
            "no_canary_reason": "fixture",
        }
    )
    _write_inventory(tree, data)

    hooks_json = tree / _HOOKS_JSON_REL
    payload = json.loads(hooks_json.read_text(encoding="utf-8"))
    payload["hooks"]["Stop"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/stop_quality_gate.sh",
                }
            ]
        }
    ]
    hooks_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert not [f for f in _findings(tree) if f.code == _EVENT_KEY_KIND]


# ---------------------------------------------------------------------------
# AC3 — nothing else moved
# ---------------------------------------------------------------------------


def test_the_original_defect_is_still_caught(tree: Path) -> None:
    """Negative control for the change as a whole.

    OMN-13244 deregistered a declared hook and nothing noticed. That is the
    defect this gate exists for, and adding a kind must not cost it.
    """
    hooks_json = tree / _HOOKS_JSON_REL
    payload = json.loads(hooks_json.read_text(encoding="utf-8"))
    dropped = payload["hooks"]["PreToolUse"][0]["hooks"].pop(0)
    hooks_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    script = dropped["command"].rsplit("/", 1)[-1]

    assert script in _subjects(tree, "UNREGISTERED_EXPECTED")


def test_the_two_new_kinds_are_the_only_addition_on_the_live_tree() -> None:
    """Every other kind still reports exactly nothing on the real tree."""
    codes = {f.code for f in _findings(_REPO_ROOT)}
    assert not codes - {_KIND, _EVENT_KEY_KIND}, sorted(codes)


# ---------------------------------------------------------------------------
# AC6 / AC7 — the merged tree, and what the declarations are allowed to say
# ---------------------------------------------------------------------------


def test_the_live_tree_is_green(tree: Path) -> None:
    """Whatever the kind matches, this change declares. Merged dev stays green."""
    result = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--repo-root", str(_REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_placeholder_declaration_is_a_triage_not_a_verdict() -> None:
    """AC7, read off the file.

    A placeholder that says ``re_register`` has taken the decision OMN-18531
    exists to take, and a placeholder that says ``delete`` has taken a worse
    one. Each carries an owner, a review date inside the following sprint, and
    the ticket that replaces it.
    """
    data = yaml.safe_load((_REPO_ROOT / _INVENTORY_REL).read_text(encoding="utf-8"))
    placeholders = [
        row
        for row in data["disabled_hooks"]
        if row["restoration"]["reenable_ticket"] == _TRIAGE_TICKET
    ]
    assert len(placeholders) == 34, len(placeholders)

    for row in placeholders:
        where = row["script"]
        assert row["restoration"]["kind"] == "triage", where
        assert row["owner"].strip(), where
        assert row["reason"].strip(), where
        review = row["review_by"]
        review = review if isinstance(review, date) else date.fromisoformat(review)
        assert date(2026, 9, 28) <= review <= date(2026, 10, 5), (where, review)


def test_the_placeholders_cover_exactly_what_the_kind_matches(tree: Path) -> None:
    """No placeholder declares a script the kind would not have flagged.

    A declaration for something the gate never matched is an owner assigned to
    a script nobody needs to triage, and it makes the 34 unverifiable.
    """
    data = _read_inventory(tree)
    placeholders = {
        row["script"]
        for row in data["disabled_hooks"]
        if row["restoration"]["reenable_ticket"] == _TRIAGE_TICKET
    }
    data["disabled_hooks"] = [
        row
        for row in data["disabled_hooks"]
        if row["restoration"]["reenable_ticket"] != _TRIAGE_TICKET
    ]
    _write_inventory(tree, data)

    assert _subjects(tree, _KIND) == placeholders


# ---------------------------------------------------------------------------
# AC8 — the gate blocks a merge, and the surface it blocks is named
# ---------------------------------------------------------------------------

_GATE_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "hook-inventory-gate.yml"
_GATE_CONTEXT = "Hook Inventory Gate"


def test_the_gate_job_name_is_the_context_name() -> None:
    """The check-run name the summary layer reasons about is this literal."""
    workflow = yaml.safe_load(_GATE_WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["jobs"]["hook-inventory-gate"]["name"] == _GATE_CONTEXT


def test_the_gate_is_swept_by_the_ci_summary_default_deny_layer() -> None:
    """AC8, held against the mechanism that actually blocks the merge.

    ``Hook Inventory Gate`` is not a branch-protection context (64 contexts on
    ``dev``, read live 2026-09-21, and it is not among them). It blocks anyway,
    through the L5 default-deny sweep OMN-18970 landed under this same epic:
    CI Summary walks every external check-run on the head, and a name in
    neither :data:`EXPECTED_EXTERNAL_CONTEXTS` nor
    :data:`EXTERNAL_SWEEP_EXCLUSIONS` must conclude ``success`` or CI Summary —
    which IS required — fails.

    This test is the thing that keeps that true. Adding the gate to the
    exclusion registry would silently return it to advisory, and that is
    exactly the move this ticket exists to prevent.
    """
    gate = _load_lib(
        _REPO_ROOT / "scripts" / "ci" / "ci_summary_gate.py",
        "ci_summary_gate_under_test",
    )
    assert _GATE_CONTEXT not in gate.EXTERNAL_SWEEP_EXCLUSIONS
    assert _GATE_CONTEXT not in gate.EXPECTED_EXTERNAL_CONTEXTS
    assert frozenset({"success"}) == gate.SWEEP_GOOD_CONCLUSIONS
