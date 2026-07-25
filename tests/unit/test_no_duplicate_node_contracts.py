# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression: prevent omniclaude-side node contracts whose `name:` collides
with omnimarket's contracts (the duplicate-local-ingress-route crash that
prevented omninode-runtime from booting before OMN-10865).

The runtime auto-wiring layer aliases every discovered node by its
contract `name:`. If two contracts share a name across packages, wiring
raises `ValueError: Duplicate local ingress route alias '<name>'`.

This test inspects every omniclaude contract.yaml and fails if it declares a
`name:` that lives in the omnimarket-side nodes package — the known
collision shape that crashes boot. Pure filesystem/YAML comparison, no
external services — lives in tests/unit/ (not tests/integration/, which
carries a hard Kafka-broker-reachability precondition unrelated to this
check).

OMN-14584: generalizes omnibase_infra's
``tests/integration/test_no_duplicate_node_contracts.py`` (the original
OMN-10865 regression test) to omniclaude. That test only ever checked
omnibase_infra vs omnimarket; it did not catch omniclaude's own
``node_delegation_orchestrator`` — a real, distinct second implementation
declaring the identical bare contract name — because omniclaude was never
co-installed with omnimarket in the same runtime process (confirmed via the
live `.201` stability-test introspection manifest showing only omnimarket's
copy registered). That made it a *dormant* landmine rather than a live crash:
this test exists so a future package co-installation surfaces the collision
here, in CI, instead of as a runtime boot crash.
"""

from __future__ import annotations

from pathlib import Path

import yaml

OMNICLAUDE_NODES_DIR = (
    Path(__file__).parent.parent.parent / "src" / "omniclaude" / "nodes"
)

# OMN-14592 baseline freeze: a second real, pre-existing cross-package
# duplicate (node_skill_dispatch_engine_orchestrator, genuinely declared in
# both omnimarket and omniclaude src/) was found by this test the moment it
# was written — mirrors the runtime_profiles_allowlist.yaml OMN-13288
# pattern one directory over (scripts/validation/): freeze what already
# exists so the gate blocks NEW collisions without being permanently red on
# an already-known, already-tracked one. Remove this entry when OMN-14592
# resolves the duplicate.
_KNOWN_COLLISIONS_BASELINE = frozenset({"node_skill_dispatch_engine_orchestrator"})


def _read_contract_name(contract_path: Path) -> str | None:
    raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    return name if isinstance(name, str) else None


def _omnimarket_node_dir() -> Path | None:
    """Locate the omnimarket nodes directory if the package is importable.

    Returns None if omnimarket isn't on sys.path in this test environment
    (in which case we skip — the runtime wiring check is the source of
    truth for the duplicate-alias error).
    """
    try:
        import omnimarket  # type: ignore[import-not-found]
    except ImportError:
        return None
    pkg_root = Path(omnimarket.__file__).parent
    nodes_dir = pkg_root / "nodes"
    return nodes_dir if nodes_dir.is_dir() else None


def test_no_omniclaude_contract_name_collides_with_omnimarket() -> None:
    import pytest

    market_dir = _omnimarket_node_dir()
    if market_dir is None:
        pytest.skip("omnimarket not importable in this environment")

    market_names: dict[str, Path] = {}
    for contract in market_dir.rglob("contract.yaml"):
        name = _read_contract_name(contract)
        if name:
            market_names.setdefault(name, contract)

    omniclaude_collisions: list[tuple[str, Path, Path]] = []
    for contract in OMNICLAUDE_NODES_DIR.rglob("contract.yaml"):
        name = _read_contract_name(contract)
        if name and name in market_names and name not in _KNOWN_COLLISIONS_BASELINE:
            omniclaude_collisions.append((name, contract, market_names[name]))

    assert not omniclaude_collisions, (
        "Duplicate contract `name:` between omniclaude and omnimarket "
        "will crash omninode-runtime boot with `ValueError: Duplicate local "
        "ingress route alias '<name>'` if the two packages are ever "
        "co-installed. Pick one owner per node.\n"
        "Collisions: "
        + "\n".join(
            f"  {name}: {oc.relative_to(OMNICLAUDE_NODES_DIR.parent.parent.parent)} vs {mc}"
            for name, oc, mc in omniclaude_collisions
        )
    )
