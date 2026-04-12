# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for node_golden_chain_payload_compute."""

from __future__ import annotations

import re

from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
    GOLDEN_CHAIN_DEFINITIONS,
    get_chain_definitions,
)
from omniclaude.nodes.node_golden_chain_payload_compute.node import build_payloads

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Chains that use correlation_id as DB lookup column
_CORR_ID_CHAINS = {"registration", "delegation", "routing", "evaluation"}
# Chains that use an alternate lookup column (no correlation_id in DB)
_ALT_LOOKUP_CHAINS = {"pattern_learning"}


class TestChainRegistry:
    """Tests for chain registry definitions."""

    def test_all_five_chains_defined(self) -> None:
        assert len(GOLDEN_CHAIN_DEFINITIONS) == 5
        names = {c.name for c in GOLDEN_CHAIN_DEFINITIONS}
        assert names == {
            "registration",
            "pattern_learning",
            "delegation",
            "routing",
            "evaluation",
        }

    def test_filter_returns_subset(self) -> None:
        filtered = get_chain_definitions(["registration", "routing"])
        assert len(filtered) == 2
        assert {c.name for c in filtered} == {"registration", "routing"}

    def test_filter_none_returns_all(self) -> None:
        result = get_chain_definitions(None)
        assert len(result) == 5

    def test_filter_unknown_returns_empty(self) -> None:
        result = get_chain_definitions(["nonexistent"])
        assert len(result) == 0

    def test_all_chains_have_head_topic(self) -> None:
        for chain in GOLDEN_CHAIN_DEFINITIONS:
            assert chain.head_topic.startswith("onex.evt."), (
                f"Chain {chain.name} has non-standard topic: {chain.head_topic}"
            )

    def test_all_chains_have_assertions(self) -> None:
        for chain in GOLDEN_CHAIN_DEFINITIONS:
            assert len(chain.assertions) > 0, f"Chain {chain.name} has no assertions"

    def test_correlation_id_chains_have_corr_assertion(self) -> None:
        for chain in GOLDEN_CHAIN_DEFINITIONS:
            if chain.name not in _CORR_ID_CHAINS:
                continue
            corr_assertions = [
                a for a in chain.assertions if a.field == "correlation_id"
            ]
            assert len(corr_assertions) == 1, (
                f"Chain {chain.name} must have exactly one correlation_id assertion"
            )

    def test_alt_lookup_chains_have_no_corr_assertion(self) -> None:
        for chain in GOLDEN_CHAIN_DEFINITIONS:
            if chain.name not in _ALT_LOOKUP_CHAINS:
                continue
            corr_assertions = [
                a for a in chain.assertions if a.field == "correlation_id"
            ]
            assert len(corr_assertions) == 0, (
                f"Chain {chain.name} has no correlation_id column but has a "
                f"correlation_id assertion"
            )

    def test_uuid_chains_have_flag_set(self) -> None:
        uuid_chains = {"registration", "routing"}
        for chain in GOLDEN_CHAIN_DEFINITIONS:
            if chain.name in uuid_chains:
                assert chain.correlation_id_is_uuid is True, (
                    f"Chain {chain.name} targets a UUID column"
                )
            else:
                assert chain.correlation_id_is_uuid is False, (
                    f"Chain {chain.name} should not use UUID correlation_id"
                )


class TestBuildPayloads:
    """Tests for the payload compute node."""

    def test_builds_all_five_payloads(self) -> None:
        payloads = build_payloads()
        assert len(payloads) == 5

    def test_uuid_chains_produce_valid_uuids(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            chain_def = next(
                c for c in GOLDEN_CHAIN_DEFINITIONS if c.name == p.chain_name
            )
            if chain_def.correlation_id_is_uuid:
                assert UUID_RE.match(p.correlation_id), (
                    f"Chain {p.chain_name} should produce UUID correlation_id, "
                    f"got: {p.correlation_id}"
                )

    def test_text_chains_produce_prefixed_ids(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            chain_def = next(
                c for c in GOLDEN_CHAIN_DEFINITIONS if c.name == p.chain_name
            )
            if not chain_def.correlation_id_is_uuid:
                assert p.correlation_id.startswith("golden-chain-"), (
                    f"Chain {p.chain_name} should produce prefixed correlation_id, "
                    f"got: {p.correlation_id}"
                )

    def test_correlation_ids_are_unique(self) -> None:
        payloads = build_payloads()
        ids = [p.correlation_id for p in payloads]
        assert len(ids) == len(set(ids))

    def test_fixture_contains_correlation_id(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            assert p.fixture["correlation_id"] == p.correlation_id

    def test_fixture_contains_emitted_at(self) -> None:
        payloads = build_payloads(emitted_at="2026-04-02T00:00:00Z")
        for p in payloads:
            assert p.fixture["emitted_at"] == "2026-04-02T00:00:00Z"

    def test_corr_id_assertions_resolve_sentinel(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            corr_assertions = [a for a in p.assertions if a.field == "correlation_id"]
            for a in corr_assertions:
                assert a.expected == p.correlation_id
                assert "__CORRELATION_ID__" not in str(a.expected)

    def test_alt_lookup_payloads_have_unique_fixture_values(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            if p.lookup_column == "correlation_id":
                continue
            # The lookup value should be unique (contains a UUID suffix)
            assert p.lookup_value != ""
            assert p.lookup_value == p.fixture[p.lookup_column]

    def test_lookup_column_matches_chain_definition(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            chain_def = next(
                c for c in GOLDEN_CHAIN_DEFINITIONS if c.name == p.chain_name
            )
            assert p.lookup_column == chain_def.lookup_column

    def test_filter_works(self) -> None:
        payloads = build_payloads(chain_filter=["registration"])
        assert len(payloads) == 1
        assert payloads[0].chain_name == "registration"

    def test_custom_timeout(self) -> None:
        payloads = build_payloads(timeout_ms=30000)
        for p in payloads:
            assert p.timeout_ms == 30000

    def test_explicit_emitted_at(self) -> None:
        ts = "2026-01-15T12:00:00Z"
        payloads = build_payloads(emitted_at=ts)
        for p in payloads:
            assert p.emitted_at == ts
