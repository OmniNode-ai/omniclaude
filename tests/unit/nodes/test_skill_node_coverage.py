# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Enforce 1:1 mapping between plugin skills and ONEX orchestrator nodes.

Normalizes names to hyphenated form on both sides to handle any mixed
underscore/hyphen directory naming conventions.
"""

from pathlib import Path

import pytest

from omniclaude.runtime.wiring_dispatchers import load_skill_contracts


def _normalize(name: str) -> str:
    """Canonical slug: always hyphens, never underscores."""
    return name.replace("_", "-")


def _get_skills() -> set[str]:
    skills_dir = Path("plugins/onex/skills")
    return {
        _normalize(d.name)
        for d in skills_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    }


def _get_node_skills() -> set[str]:
    nodes_dir = Path("src/omniclaude/nodes")
    result = set()
    for d in nodes_dir.iterdir():
        if (
            d.is_dir()
            and d.name.startswith("node_skill_")
            and d.name.endswith("_orchestrator")
        ):
            snake = d.name[len("node_skill_") : -len("_orchestrator")]
            result.add(_normalize(snake))
    return result


@pytest.mark.unit
def test_all_skills_have_nodes() -> None:
    missing = _get_skills() - _get_node_skills()
    assert not missing, (
        f"{len(missing)} skill(s) missing a node:\n"
        + "\n".join(f"  - {s}" for s in sorted(missing))
        + "\n\nFix: uv run python scripts/generate_skill_node.py --all"
    )


@pytest.mark.unit
def test_no_orphaned_nodes() -> None:
    orphans = _get_node_skills() - _get_skills()
    assert not orphans, (
        f"{len(orphans)} orphaned node(s) with no matching skill:\n"
        + "\n".join(f"  - {s}" for s in sorted(orphans))
    )


@pytest.mark.unit
def test_all_skill_node_contracts_parse() -> None:
    """Every skill node contract.yaml must parse at 100% — treat < 100% as generator bug.

    Uses an independent file count (glob) as the denominator rather than relying
    on load_skill_contracts's internal 'total' counter, whose semantics might change.
    """
    contracts_root = Path("src/omniclaude/nodes")

    # Independent discovery — do not rely on loader's internal counter
    discovered = list(contracts_root.glob("node_skill_*/contract.yaml"))
    discovered_count = len(discovered)

    # load_skill_contracts uses yaml.safe_load + Pydantic validation
    # It raises ContractLoadError if parse rate < 80%, but we want 100%
    contracts, _ = load_skill_contracts(contracts_root)

    assert len(contracts) == discovered_count, (
        f"Generator produced malformed contracts: "
        f"{discovered_count - len(contracts)}/{discovered_count} failed to parse.\n"
        f"This is a generator bug. Check docs/templates/skill_node_contract.yaml.template."
    )
