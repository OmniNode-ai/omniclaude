# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The unaccounted-script direction of hook inventory parity [OMN-17005].

``hook_inventory.yaml`` carries a third list, ``unregistered_scripts``: the
scripts on disk that no ``hooks.json`` event registers, each row naming its
kind, role, owner and the evidence that keeps it accounted. A script that is on
disk, registered nowhere and declared nowhere is the blind spot this closes.

The check lives here, not in ``hook_inventory.py``: that file is baselined by
the canonical-file-shape ratchet and may not grow. It reuses the lib's own
readers (registrations, script sources, reachability, refusal reading), so the
test and the pre-commit gate agree on what a registered or refusing script is.

Findings are asserted as (code, subject) records, never by matching rendered
text, so rewording a message cannot silently retire a control.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_INVENTORY_REL = "plugins/onex/hooks/contracts/hook_inventory.yaml"
_HOOKS_JSON_REL = "plugins/onex/hooks/hooks.json"
_LIB_REL = "plugins/onex/hooks/lib/hook_inventory.py"
_SCRIPTS_REL = "plugins/onex/hooks/scripts"

_UNACCOUNTED = "UNACCOUNTED_SCRIPT"
_DUPLICATE = "DUPLICATE_UNREGISTERED_ENTRY"
_STALE = "STALE_UNREGISTERED_ENTRY"
_ALSO_DECLARED = "UNREGISTERED_ENTRY_ALSO_DECLARED"
_ROLE_MISMATCH = "UNREGISTERED_ROLE_MISMATCH"
_MALFORMED = "MALFORMED_UNREGISTERED_ENTRY"

_KINDS = {"live", "library", "harness", "dormant"}
_ROLES = {"safety_gate", "recorder", "support"}

_TODAY = date(2026, 11, 15)


# ---------------------------------------------------------------------------
# Helpers, shaped on the undeclared-gate suite
# ---------------------------------------------------------------------------


def _load_lib(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_LIB = _load_lib(_REPO_ROOT / _LIB_REL, "hook_inventory_unaccounted_under_test")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A fully writable copy of the hook surface.

    These tests add, remove, and rewrite scripts and the inventory, so the
    copy must be real: a symlinked mirror would write the fixture into the
    repository.
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


class _Finding(NamedTuple):
    code: str
    subject: str


def _row_problem(row: dict[str, Any]) -> str | None:
    """Why a row is unusable, or None. Evidence fields depend on the kind."""
    if row.get("kind") not in _KINDS or row.get("role") not in _ROLES:
        return "kind or role not in the allowed set"
    if not all(str(row.get(k) or "").strip() for k in ("script", "owner", "note")):
        return "script, owner or note is blank"
    evidence, other = (
        ("removal_blocker", "referenced_from")
        if row["kind"] == "dormant"
        else ("referenced_from", "removal_blocker")
    )
    if not str(row.get(evidence) or "").strip() or other in row:
        return f"needs {evidence} and must not carry {other}"
    return None


def _unaccounted(root: Path) -> tuple[_Finding, ...]:
    """Every way a script on disk, or a row naming one, is not accounted for."""
    inventory = _LIB.load_inventory(root / _INVENTORY_REL)
    rows = _read_inventory(root).get("unregistered_scripts") or []
    scripts_dir = root / inventory.scripts_dir
    registered = {
        r.script for r in _LIB.load_registrations(root / inventory.hooks_json)
    }
    declared = {h.script for h in inventory.expected + inventory.disabled}
    sources = _LIB._script_sources(scripts_dir)
    refusing = _LIB.refusing_scripts(scripts_dir, sources)
    reachable = _LIB.scripts_reachable_from_registered(registered, scripts_dir, sources)
    listed = {row["script"] for row in rows}

    out = [
        _Finding(_UNACCOUNTED, name)
        for name in sorted(set(sources) - registered - declared - listed - reachable)
    ]
    seen: set[str] = set()
    for row in rows:
        name = row["script"]
        if _row_problem(row):
            out.append(_Finding(_MALFORMED, name))
        elif name in seen:
            out.append(_Finding(_DUPLICATE, name))
        elif name not in sources:
            out.append(_Finding(_STALE, name))
        elif name in registered | declared:
            out.append(_Finding(_ALSO_DECLARED, name))
        elif (row["role"] == "recorder" and name in refusing) or (
            row["role"] == "safety_gate" and name not in refusing
        ):
            out.append(_Finding(_ROLE_MISMATCH, name))
        seen.add(name)
    return tuple(out)


def _findings(root: Path) -> tuple[_Finding, ...]:
    return _unaccounted(root)


def _subjects(root: Path, kind: str) -> set[str]:
    return {f.subject for f in _findings(root) if f.code == kind}


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
# The real inventory accounts for every script
# ---------------------------------------------------------------------------


def test_the_real_inventory_accounts_for_every_script(tree: Path) -> None:
    """The merged tree is green: no unaccounted-script finding on the real data."""
    assert _read_inventory(tree).get("unregistered_scripts"), "no unregistered rows"
    assert _findings(tree) == ()


def test_inventory_validator_accepts_accounted_tree() -> None:
    """The pre-commit validator accepts the same tree checked for parity."""
    result = subprocess.run(
        [sys.executable, "scripts/validation/validate_hook_inventory.py"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _findings(_REPO_ROOT) == ()


def test_a_stray_script_is_reported_by_name_and_stops_when_removed(
    tree: Path,
) -> None:
    """The ticket's probe, run forwards and backwards.

    Add a harmless script declared in no list: the gate names it. Remove it:
    the gate stops naming it. The second half is what proves the finding is
    about that file rather than a constant the gate always emits.
    """
    name = "omn17005_stray_recorder.sh"
    assert name not in _subjects(tree, _UNACCOUNTED), "fixture name already present"

    _add_script(tree, name, "#!/usr/bin/env bash\nexit 0\n")
    assert name in _subjects(tree, _UNACCOUNTED)

    (tree / _SCRIPTS_REL / name).unlink()
    assert name not in _subjects(tree, _UNACCOUNTED)


def test_removing_a_listed_row_brings_its_finding_back(tree: Path) -> None:
    """A dormant declaration is load-bearing for the gate's silence.

    Deleting the row for a dormant script has to bring its UNACCOUNTED_SCRIPT
    finding straight back, or the declarations are passing for a reason other
    than correctness.
    """
    data = _read_inventory(tree)
    rows = data["unregistered_scripts"]
    target = next(row for row in rows if row["kind"] == "dormant")
    name = target["script"]
    assert name not in _subjects(tree, _UNACCOUNTED), "the named script is unaccounted"

    data["unregistered_scripts"] = [row for row in rows if row["script"] != name]
    _write_inventory(tree, data)

    assert name in _subjects(tree, _UNACCOUNTED)


def test_a_listed_script_that_is_gone_is_stale(tree: Path) -> None:
    """A listed script that is no longer on disk is a stale entry, not a pass."""
    data = _read_inventory(tree)
    name = data["unregistered_scripts"][0]["script"]
    (tree / _SCRIPTS_REL / name).unlink()
    assert name in _subjects(tree, _STALE)


def test_a_row_for_a_registered_script_is_reported(tree: Path) -> None:
    """A script that is registered in hooks.json must not also be unregistered."""
    name = sorted(_registered_scripts(tree))[0]
    data = _read_inventory(tree)
    row = dict(data["unregistered_scripts"][0])
    row["script"] = name
    data["unregistered_scripts"].append(row)
    _write_inventory(tree, data)
    assert name in _subjects(tree, _ALSO_DECLARED)


def test_a_duplicate_row_is_reported(tree: Path) -> None:
    """The same script listed twice is a duplicate, not a silent double."""
    data = _read_inventory(tree)
    row = dict(data["unregistered_scripts"][0])
    data["unregistered_scripts"].append(row)
    _write_inventory(tree, data)
    assert row["script"] in _subjects(tree, _DUPLICATE)


def test_role_must_match_what_the_script_can_do(tree: Path) -> None:
    """A role is a claim about refusal, and the gate checks it against the body.

    (a) A recorder that can refuse is a mismatch: these scripts cannot refuse.
    (b) A refusing script listed as a recorder is a mismatch: it can refuse.
    """
    data = _read_inventory(tree)
    rows = data["unregistered_scripts"]
    recorder = next(row for row in rows if row["role"] == "recorder")
    recorder["role"] = "safety_gate"
    _write_inventory(tree, data)
    assert recorder["script"] in _subjects(tree, _ROLE_MISMATCH)

    name = "omn17005_refusing_probe.sh"
    _add_script(tree, name, "#!/usr/bin/env bash\nset -euo pipefail\nexit 2\n")
    data = _read_inventory(tree)
    data["unregistered_scripts"].append(
        {
            "script": name,
            "kind": "dormant",
            "role": "recorder",
            "owner": "omniclaude hooks lane",
            "note": "fixture: a refusing script listed as a recorder",
            "removal_blocker": "fixture",
        }
    )
    _write_inventory(tree, data)
    assert name in _subjects(tree, _ROLE_MISMATCH)


def test_a_script_a_registered_hook_calls_is_not_reported(tree: Path) -> None:
    """The control that keeps the check from becoming noise.

    ``common.sh`` is reached from a registered hook and listed nowhere; it must
    not be reported, or the gate fires on every shared library.
    """
    assert "common.sh" not in _subjects(tree, _UNACCOUNTED)


def test_a_row_missing_its_evidence_is_malformed(tree: Path) -> None:
    """A live/library/harness row needs ``referenced_from``; a dormant row needs
    ``removal_blocker``; and a live row must not also carry ``removal_blocker``.
    """
    rows = _read_inventory(tree)["unregistered_scripts"]
    live = next(row for row in rows if row["kind"] in {"live", "library", "harness"})
    dormant = next(row for row in rows if row["kind"] == "dormant")
    assert _row_problem(live) is None and _row_problem(dormant) is None

    no_ref = {k: v for k, v in live.items() if k != "referenced_from"}
    no_blocker = {k: v for k, v in dormant.items() if k != "removal_blocker"}
    live_blocked = {**live, "removal_blocker": "fixture"}
    for broken in (no_ref, no_blocker, live_blocked):
        assert _row_problem(broken) is not None, broken

    data = _read_inventory(tree)
    data["unregistered_scripts"] = [no_ref] + [r for r in rows if r is not live]
    _write_inventory(tree, data)
    assert live["script"] in _subjects(tree, _MALFORMED)


def test_every_row_names_its_evidence_in_the_real_repo() -> None:
    """Each referenced_from path, read off the real repo, names the script.

    Comment lines are dropped before the search, so a mention that sits only in
    a comment is not evidence.
    """
    data = yaml.safe_load((_REPO_ROOT / _INVENTORY_REL).read_text(encoding="utf-8"))
    for entry in data["unregistered_scripts"]:
        if "referenced_from" not in entry:
            continue
        path = _REPO_ROOT / entry["referenced_from"]
        text = path.read_text(encoding="utf-8")
        text = "\n".join(line for line in text.splitlines() if line.lstrip()[:1] != "#")
        pattern = r"(?<![\w.\-])" + re.escape(entry["script"]) + r"(?![\w.])"
        assert re.search(pattern, text) is not None, (
            f"{entry['script']!r} is not named in {entry['referenced_from']!r}"
        )


def test_every_row_is_present_wired_and_owned() -> None:
    """Every row's file exists, is wired to the right list, and is owned.

    Expected rows are registered in hooks.json; disabled and unregistered rows
    are not; and every row of the three lists carries a non-blank owner.
    """
    data = yaml.safe_load((_REPO_ROOT / _INVENTORY_REL).read_text(encoding="utf-8"))
    registered = _registered_scripts(_REPO_ROOT)
    scripts_dir = _REPO_ROOT / _SCRIPTS_REL

    for row in data["expected_hooks"]:
        name = row["script"]
        assert (scripts_dir / name).is_file(), f"{name!r} is not on disk"
        assert name in registered, f"{name!r} is expected but not registered"

    for row in data["disabled_hooks"] + data["unregistered_scripts"]:
        name = row["script"]
        assert (scripts_dir / name).is_file(), f"{name!r} is not on disk"
        assert name not in registered, (
            f"{name!r} is listed unregistered but is registered"
        )

    for row in (
        data["expected_hooks"] + data["disabled_hooks"] + data["unregistered_scripts"]
    ):
        assert row["owner"].strip(), f"{row['script']!r} has a blank owner"


def test_the_dead_scripts_removed_by_the_review_stay_gone() -> None:
    """The thirteen scripts the review deleted are gone from disk and from the list."""
    names = [
        "file-path-convention-inject.sh",
        "post_tool_use_commit_verify.sh",
        "post_tool_use_env_var_sync.sh",
        "post_tool_use_kafka_poison_message_guard.sh",
        "post_tool_use_state_verify.sh",
        "post_tool_use_tsc_check.sh",
        "register-tab.sh",
        "epic_postaction_gate.sh",
        "epic_preflight_gate.sh",
        "pre_tool_use_changeset_guard.sh",
        "stop_failure_logger.sh",
        "codex_cost_wrapper.py",
        "post_tool_use_auto_hostile_review.sh",
    ]
    scripts_dir = _REPO_ROOT / _SCRIPTS_REL
    data = yaml.safe_load((_REPO_ROOT / _INVENTORY_REL).read_text(encoding="utf-8"))
    unregistered = {row["script"] for row in data["unregistered_scripts"]}
    for name in names:
        assert not (scripts_dir / name).exists(), f"{name!r} is back on disk"
        assert name not in unregistered, f"{name!r} is back in the unregistered list"
