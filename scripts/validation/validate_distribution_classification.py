#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""TEMPORARY Phase-0 migration gate (OMN-14687, epic OMN-14686).

Fail-closed check that EVERY filesystem-discovered plugin component (skill,
hook script, agent config) is classified in ``plugins/distribution_manifest.yaml``
with a valid exposure. Its sole job is to prevent an UNCLASSIFIED plugin
component from being added while the minimal-plugin migration is in flight.

This gate is INTERIM. Phase 3 replaces it with the permanent, typed
distribution-contract validators (frozen extra-forbidden Pydantic models) and
retires this file (plan step: Phase 3 "retire the temporary Phase 0
unclassified-component rule once these permanent checks are blocking").

Discovery MUST match the inventory scanner so a component cannot be discovered
by one and missed by the other: skill discovery is imported from
``validate_full_market_skill_inventory`` (DRY, single source of truth).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Reuse the canonical SKILL.md discovery so the two gates cannot drift.
from validate_full_market_skill_inventory import discover_skill_files  # noqa: E402

VALID_EXPOSURES = {"stable", "beta", "hidden", "retired"}


def _repo_root() -> Path:
    # scripts/validation/<this file> -> repo root is two parents up.
    return _HERE.parent.parent


def discover_components(repo_root: Path) -> set[str]:
    """Return the id of every distributable plugin component on disk."""
    ids: set[str] = set()

    skills_root = repo_root / "plugins" / "onex" / "skills"
    if skills_root.exists():
        for skill_file in discover_skill_files(skills_root):
            ids.add(skill_file.parent.relative_to(skills_root).as_posix())

    hooks_dir = repo_root / "plugins" / "onex" / "hooks" / "scripts"
    if hooks_dir.exists():
        for sh in sorted(hooks_dir.glob("*.sh")):
            ids.add(f"hooks/scripts/{sh.name}")

    agents_dir = repo_root / "plugins" / "onex" / "agents" / "configs"
    if agents_dir.exists():
        for ay in sorted(agents_dir.glob("*.yaml")):
            ids.add(f"agents/configs/{ay.name}")

    return ids


def load_manifest(repo_root: Path) -> dict:
    path = repo_root / "plugins" / "distribution_manifest.yaml"
    if not path.exists():
        print(f"ERROR: distribution manifest not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main(argv: list[str] | None = None) -> int:
    repo_root = _repo_root()
    manifest = load_manifest(repo_root)
    components = manifest.get("components") or []

    classified: dict[str, str] = {}
    bad_exposure: list[tuple[str, str]] = []
    for entry in components:
        cid = entry.get("id")
        exposure = entry.get("exposure")
        if cid is None:
            print("ERROR: manifest component with no id", file=sys.stderr)
            return 1
        classified[cid] = exposure
        if exposure not in VALID_EXPOSURES:
            bad_exposure.append((cid, str(exposure)))

    discovered = discover_components(repo_root)
    unclassified = sorted(discovered - set(classified))
    stale = sorted(set(classified) - discovered)

    failed = False

    if unclassified:
        failed = True
        print(
            f"ERROR: {len(unclassified)} plugin component(s) are NOT classified in "
            "plugins/distribution_manifest.yaml (add each with a valid exposure "
            "stable|beta|hidden|retired):",
            file=sys.stderr,
        )
        for cid in unclassified:
            print(f"  - {cid}", file=sys.stderr)

    if bad_exposure:
        failed = True
        print("ERROR: manifest components with invalid exposure:", file=sys.stderr)
        for cid, exp in bad_exposure:
            print(f"  - {cid}: {exp!r}", file=sys.stderr)

    # Stable-package invariant (plan rule 2): exactly one stable skill, `delegate`.
    stable_ids = sorted(c for c, e in classified.items() if e == "stable")
    if stable_ids != ["delegate"]:
        failed = True
        print(
            f"ERROR: stable exposure must be exactly ['delegate']; got {stable_ids}",
            file=sys.stderr,
        )

    if stale:
        # Advisory only: a manifest entry whose path no longer exists. Does not
        # block (deletions are legitimate); surfaced so the manifest can be pruned.
        print(
            f"NOTE: {len(stale)} manifest entr(y|ies) no longer on disk (prune when convenient): "
            + ", ".join(stale[:10])
            + (" ..." if len(stale) > 10 else "")
        )

    if failed:
        return 1

    print(
        "validate_distribution_classification: OK — "
        f"{len(discovered)} discovered component(s) all classified "
        f"({len(components)} manifest entries)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
