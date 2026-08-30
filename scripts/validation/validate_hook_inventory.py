#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hook inventory gate [OMN-17020].

Turns "which hooks are supposed to be registered?" from a question nobody in
the repo could answer into a failing check.

OMN-13244 unregistered the whole hook surface for a measurement baseline. The
change carried no expiry, no re-enable ticket and no inventory of what went
dark, so ``pre_tool_use_overseer_foreground_block.sh`` sat on disk, switched
off, while the foreground rule it enforces was corrected by hand ~61 times over
16 of 18 days (``docs/tracking/2026-08-29-beta-off-the-rails-analysis.md``,
root cause RC-B). Nothing failed, because nothing was checking.

Three modes:

``--repo-root <path>`` (default; what CI and the pre-commit hook run)
    Static parity between ``hook_inventory.yaml``, ``hooks.json`` and the
    scripts on disk. Fails CLOSED on any drift, naming the hook. Runs on a
    bare runner: it reads only files in the tree.

``--live``
    Adds the per-machine ``ONEX_HOOKS_MASK`` surface — a registered hook whose
    ``onex_hook_gate`` bit is cleared is dark with no repo-visible signal.
    Never a merge gate: a runner has no ``~/.omnibase/.env``, and a check that
    passes because its input is absent is worse than no check. This is the same
    boundary ``validate_hook_edge_lane.py --live`` draws.

``--generate``
    Emits the mechanical half of ``expected_hooks`` (script / event / matcher /
    order) from the live ``hooks.json``, so the inventory is generated from
    current state and starts green rather than being retyped.

``--warn-only`` downgrades every exit to 0 and is what the session-bootstrap
hook passes: a hook-manifest mismatch must not make the machine unusable.

Exit codes: ``0`` clean (or ``--warn-only``), ``1`` drift, ``2`` the gate
itself could not run.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

_HERE = Path(__file__).resolve()
_DEFAULT_REPO_ROOT = _HERE.parents[2]
_INVENTORY_REL = "plugins/onex/hooks/contracts/hook_inventory.yaml"
_LIB_REL = "plugins/onex/hooks/lib/hook_inventory.py"


def _load_lib(repo_root: Path) -> ModuleType:
    """Import the parity lib from the tree under test.

    ``--repo-root`` has to be able to point at a scratch copy — that is how
    this gate's own negative tests prove it fails on a deregistered hook — so
    the lib is loaded by path from that tree rather than imported by name.
    """
    lib_path = repo_root / _LIB_REL
    spec = importlib.util.spec_from_file_location("_onex_hook_inventory", lib_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {lib_path}")
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves its own annotations through
    # sys.modules[cls.__module__], which is None for a module loaded by path
    # alone (AttributeError: 'NoneType' object has no attribute '__dict__').
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _generate(repo_root: Path, lib: ModuleType) -> int:
    """Print the mechanical half of expected_hooks from the live hooks.json."""
    inventory_path = repo_root / _INVENTORY_REL
    hooks_json = repo_root / "plugins/onex/hooks/hooks.json"
    registrations = lib.load_registrations(hooks_json)
    stamp = datetime.now(UTC).date().isoformat()
    print(f"# generated from {hooks_json.relative_to(repo_root)} on {stamp}")
    print(f"# paste into {inventory_path.relative_to(repo_root)} and author the")
    print("# semantic fields (ticket, owner, purpose, enforcement, mask, canary).")
    for reg in registrations:
        matcher = "null" if reg.matcher is None else f'"{reg.matcher}"'
        print(f'  - script: "{reg.script}"')
        print(f'    event: "{reg.event}"')
        print(f"    matcher: {matcher}")
        print(f"    order: {reg.order}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_DEFAULT_REPO_ROOT,
        help="tree to validate (default: this repository)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="also report ONEX_HOOKS_MASK darkness on THIS machine (never CI)",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="report findings but always exit 0 (session-bootstrap posture)",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="emit the mechanical half of expected_hooks from the live hooks.json",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="override today's date when checking disable review dates (tests)",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    try:
        lib = _load_lib(repo_root)
    except Exception as exc:  # noqa: BLE001 - the gate must say why it cannot run
        print(f"hook-inventory: FATAL cannot load parity lib: {exc}", file=sys.stderr)
        return 2

    if args.generate:
        try:
            return _generate(repo_root, lib)
        except Exception as exc:  # noqa: BLE001
            print(f"hook-inventory: FATAL {exc}", file=sys.stderr)
            return 2

    try:
        inventory = lib.load_inventory(repo_root / _INVENTORY_REL)
        today = args.today or datetime.now(UTC).date()
        findings = list(lib.check_parity(inventory, repo_root, today))
        if args.live:
            findings.extend(
                lib.mask_findings(
                    inventory, repo_root, os.environ.get("ONEX_HOOKS_MASK")
                )
            )
    except Exception as exc:  # noqa: BLE001
        print(f"hook-inventory: FATAL {exc}", file=sys.stderr)
        return 0 if args.warn_only else 2

    if not findings:
        scope = "repo + live mask" if args.live else "repo"
        print(
            f"hook-inventory: OK — {len(inventory.expected)} expected hooks registered, "
            f"{len(inventory.disabled)} declared disables within review ({scope})."
        )
        return 0

    label = "WARN" if args.warn_only else "FAIL"
    print(f"hook-inventory: {label} — {len(findings)} finding(s):", file=sys.stderr)
    for finding in findings:
        print(f"  - {finding.render()}", file=sys.stderr)
    print(
        f"Authority: {_INVENTORY_REL} (OMN-17020). Every hook this plugin registers "
        "must be declared there, and every deliberate disable must carry owner, "
        "reason, review_by and restoration.",
        file=sys.stderr,
    )
    return 0 if args.warn_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
