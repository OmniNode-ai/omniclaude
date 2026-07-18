# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression: keep omnimarket the SOLE owner of the foreign-domain delegation
pipeline topics — no omniclaude node contract may declare subscribe/publish
ownership of them.

Background (OMN-14771, S8 R-3 single-owner cleanup):
omniclaude previously carried a confirmed-dead, never-live-wired duplicate
``node_delegation_orchestrator`` whose ``contract.yaml`` declared
``onex.cmd.omnibase-infra.delegation-request.v1`` in its subscribe topics. The
S6/S8 single-owner boot gate (``omnibase_core`` routing_map_builder,
single-owner check) refuses two owners of an allowlisted topic and would crash
omninode-runtime boot the moment omniclaude and omnimarket were co-installed in
the same process. OMN-14584 deleted the duplicate directory and re-scoped the
omniclaude-side TopicBase members / allowlist entries to *reference-only* usage
(golden-chain head-topic metadata in
``node_golden_chain_payload_compute/chain_registry.py``).

The existing ``test_no_duplicate_node_contracts.py`` guards contract ``name:``
collisions, which is a *different* crash shape. It would NOT catch a future
omniclaude node that owns one of the infra delegation topics under a distinct
contract name — exactly the two-owner-on-one-topic condition the single-owner
boot gate rejects. This test closes that gap: it is the enforcement mechanism
for the R-3 sole-ownership invariant so the crash-class cannot be reintroduced.

Pure filesystem/YAML comparison, no external services — lives in tests/unit/.

Reference: a TopicBase member or a golden-chain ``head_topic=`` reference is a
non-owning metadata reference and is intentionally *allowed*; only a node
contract's ``event_bus`` subscribe/publish declaration constitutes ownership.
"""

from __future__ import annotations

from pathlib import Path

import yaml

OMNICLAUDE_NODES_DIR = (
    Path(__file__).parent.parent.parent / "src" / "omniclaude" / "nodes"
)

# Delegation pipeline topics owned exclusively by omnimarket's canonical
# node_delegation_orchestrator (omnibase-infra domain). omniclaude may
# *reference* these (golden-chain metadata) but must never *own* them via a
# node contract's event_bus subscribe/publish declaration.
FORBIDDEN_INFRA_DELEGATION_TOPICS = frozenset(
    {
        "onex.cmd.omnibase-infra.delegation-request.v1",
        "onex.cmd.omnibase-infra.delegation-inference-request.v1",
        "onex.evt.omnibase-infra.inference-response.v1",
        "onex.evt.omnibase-infra.routing-decision.v1",
        "onex.evt.omnibase-infra.delegation-completed.v1",
    }
)


def _owned_topics(node: object) -> set[str]:
    """Recursively collect every ``onex.*`` topic string declared anywhere in a
    contract's ``event_bus`` block.

    Covers every declaration shape observed across omniclaude contracts:
    ``subscribe``/``publish`` (with ``topic``/``success_topic``/
    ``failure_topic``), ``subscribe_topics``/``publish_topics`` lists,
    ``topics`` lists, and ``topic_base``.
    """
    found: set[str] = set()
    if isinstance(node, str):
        if node.startswith("onex."):
            found.add(node)
    elif isinstance(node, dict):
        for value in node.values():
            found |= _owned_topics(value)
    elif isinstance(node, list):
        for value in node:
            found |= _owned_topics(value)
    return found


def _contract_event_bus_topics(contract_path: Path) -> set[str]:
    raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return set()
    event_bus = raw.get("event_bus")
    if not isinstance(event_bus, dict):
        return set()
    return _owned_topics(event_bus)


def test_no_omniclaude_contract_owns_infra_delegation_topics() -> None:
    """No omniclaude node contract may own an omnimarket-owned delegation topic.

    A second owner of an allowlisted topic crashes omninode-runtime boot at the
    single-owner routing-map gate. Sole ownership must stay with omnimarket's
    node_delegation_orchestrator (OMN-14771 R-3).
    """
    violations: list[tuple[str, set[str]]] = []
    for contract in OMNICLAUDE_NODES_DIR.rglob("contract.yaml"):
        owned = _contract_event_bus_topics(contract)
        bad = owned & FORBIDDEN_INFRA_DELEGATION_TOPICS
        if bad:
            rel = contract.relative_to(OMNICLAUDE_NODES_DIR.parent.parent.parent)
            violations.append((str(rel), bad))

    assert not violations, (
        "omniclaude node contract(s) declare ownership of a foreign-domain "
        "delegation pipeline topic owned exclusively by omnimarket's "
        "node_delegation_orchestrator. Two owners of an allowlisted topic "
        "crash omninode-runtime boot at the single-owner routing-map gate "
        "(OMN-14771 R-3). Reference the topic via TopicBase / golden-chain "
        "head_topic metadata instead of declaring event_bus ownership.\n"
        + "\n".join(f"  {path}: {sorted(topics)}" for path, topics in violations)
    )


def test_detector_fires_on_a_synthetic_owner() -> None:
    """Non-vacuity guard: prove the extractor actually detects ownership.

    A green ``test_no_omniclaude_contract_owns_...`` could pass simply because
    the extractor never matches anything. This asserts the extractor DOES
    surface a forbidden topic when one is declared (exists-but-wrong), so the
    real assertion is meaningful rather than vacuously green.
    """
    synthetic_event_bus = {
        "subscribe_topics": [
            "onex.cmd.omnibase-infra.delegation-request.v1",
        ],
        "publish_topics": ["onex.evt.omniclaude.something-benign.v1"],
    }
    owned = _owned_topics(synthetic_event_bus)
    assert owned & FORBIDDEN_INFRA_DELEGATION_TOPICS == {
        "onex.cmd.omnibase-infra.delegation-request.v1"
    }
    # A purely omniclaude-domain topic must NOT be flagged.
    assert (
        "onex.evt.omniclaude.something-benign.v1"
        not in FORBIDDEN_INFRA_DELEGATION_TOPICS
    )
