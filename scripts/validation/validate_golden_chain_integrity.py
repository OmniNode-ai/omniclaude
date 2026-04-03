# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Validate golden chain registry integrity [OMN-7389].

Static analysis gate that verifies:
1. All 5 expected golden chains are defined
2. Each chain's head_topic resolves to a valid TopicBase entry
3. Each chain has a correlation_id assertion
4. No duplicate chain names or tail tables
5. Head topics use the onex.evt.* naming convention

Runs in CI without Kafka or DB — pure static validation.
"""

from __future__ import annotations

import sys

# The canonical set of golden chains. If a chain is added or removed,
# update this set AND the chain_registry.py definitions together.
EXPECTED_CHAINS = frozenset(
    {
        "registration",
        "pattern_learning",
        "delegation",
        "routing",
        "evaluation",
    }
)


def validate() -> list[str]:
    """Run all golden chain integrity checks. Returns list of error strings."""
    errors: list[str] = []

    # Import here so the script fails clearly if the module is broken
    try:
        from omniclaude.hooks.topics import TopicBase
        from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
            GOLDEN_CHAIN_DEFINITIONS,
        )
    except ImportError as e:
        return [f"Import failed: {e}"]

    defined_names = {c.name for c in GOLDEN_CHAIN_DEFINITIONS}

    # Check 1: All expected chains are defined
    missing = EXPECTED_CHAINS - defined_names
    if missing:
        errors.append(f"Missing expected chains: {sorted(missing)}")

    unexpected = defined_names - EXPECTED_CHAINS
    if unexpected:
        errors.append(
            f"Unexpected chains (update EXPECTED_CHAINS if intentional): {sorted(unexpected)}"
        )

    # Check 2: Head topics resolve to valid TopicBase entries
    valid_topics = {t.value for t in TopicBase}
    for chain in GOLDEN_CHAIN_DEFINITIONS:
        if chain.head_topic not in valid_topics:
            errors.append(
                f"Chain '{chain.name}': head_topic '{chain.head_topic}' "
                f"not found in TopicBase"
            )

    # Check 3: All chains have a correlation_id assertion
    for chain in GOLDEN_CHAIN_DEFINITIONS:
        corr_assertions = [a for a in chain.assertions if a.field == "correlation_id"]
        if len(corr_assertions) != 1:
            errors.append(
                f"Chain '{chain.name}': expected exactly 1 correlation_id assertion, "
                f"found {len(corr_assertions)}"
            )

    # Check 4: No duplicate chain names or tail tables
    names = [c.name for c in GOLDEN_CHAIN_DEFINITIONS]
    if len(names) != len(set(names)):
        dupes = [n for n in names if names.count(n) > 1]
        errors.append(f"Duplicate chain names: {sorted(set(dupes))}")

    tables = [c.tail_table for c in GOLDEN_CHAIN_DEFINITIONS]
    if len(tables) != len(set(tables)):
        dupes = [t for t in tables if tables.count(t) > 1]
        errors.append(f"Duplicate tail tables: {sorted(set(dupes))}")

    # Check 5: Head topics follow onex.evt.* convention
    for chain in GOLDEN_CHAIN_DEFINITIONS:
        if not chain.head_topic.startswith("onex.evt."):
            errors.append(
                f"Chain '{chain.name}': head_topic '{chain.head_topic}' "
                f"must start with 'onex.evt.'"
            )

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("GOLDEN CHAIN INTEGRITY: FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)
    else:
        print("GOLDEN CHAIN INTEGRITY: PASS (5/5 chains validated)")
        sys.exit(0)


if __name__ == "__main__":
    main()
