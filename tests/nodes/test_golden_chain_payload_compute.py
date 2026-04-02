# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for node_golden_chain_payload_compute."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
    GOLDEN_CHAIN_DEFINITIONS,
    get_chain_definitions,
)
from omniclaude.nodes.node_golden_chain_payload_compute.node import build_payloads


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
            assert len(chain.assertions) > 0, (
                f"Chain {chain.name} has no assertions"
            )

    def test_all_chains_have_correlation_id_assertion(self) -> None:
        for chain in GOLDEN_CHAIN_DEFINITIONS:
            corr_assertions = [
                a for a in chain.assertions if a.field == "correlation_id"
            ]
            assert len(corr_assertions) == 1, (
                f"Chain {chain.name} must have exactly one correlation_id assertion"
            )


class TestBuildPayloads:
    """Tests for the payload compute node."""

    def test_builds_all_five_payloads(self) -> None:
        payloads = build_payloads()
        assert len(payloads) == 5

    def test_correlation_id_has_prefix(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            assert p.correlation_id.startswith("golden-chain-"), (
                f"Payload {p.chain_name} has wrong prefix: {p.correlation_id}"
            )

    def test_correlation_id_contains_chain_name(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            assert p.chain_name in p.correlation_id

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

    def test_assertions_resolve_sentinel(self) -> None:
        payloads = build_payloads()
        for p in payloads:
            corr_assertion = next(
                a for a in p.assertions if a.field == "correlation_id"
            )
            # The sentinel __CORRELATION_ID__ should be resolved
            assert corr_assertion.expected == p.correlation_id
            assert "__CORRELATION_ID__" not in str(corr_assertion.expected)

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
