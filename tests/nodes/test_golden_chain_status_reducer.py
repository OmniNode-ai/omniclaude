# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for node_golden_chain_status_reducer."""

from __future__ import annotations

from omniclaude.nodes.node_golden_chain_publish_effect.models.model_chain_result import (
    ModelChainResult,
)
from omniclaude.nodes.node_golden_chain_status_reducer.node import reduce_results


def _make_result(
    name: str = "test",
    publish_status: str = "ok",
    projection_status: str = "pass",
    **kwargs: object,
) -> ModelChainResult:
    return ModelChainResult(
        chain_name=name,
        correlation_id=f"golden-chain-{name}-abc123",
        publish_status=publish_status,
        projection_status=projection_status,
        **kwargs,
    )


class TestReduceResults:
    """Tests for the status reducer node."""

    def test_all_pass(self) -> None:
        results = [
            _make_result("a", projection_status="pass"),
            _make_result("b", projection_status="pass"),
        ]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert summary.overall_status == "pass"
        assert summary.pass_count == 2
        assert summary.fail_count == 0

    def test_all_fail(self) -> None:
        results = [
            _make_result("a", projection_status="fail"),
            _make_result("b", projection_status="fail"),
        ]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert summary.overall_status == "fail"
        assert summary.fail_count == 2
        assert summary.pass_count == 0

    def test_partial_failure(self) -> None:
        results = [
            _make_result("a", projection_status="pass"),
            _make_result("b", projection_status="fail"),
        ]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert summary.overall_status == "partial"
        assert summary.pass_count == 1
        assert summary.fail_count == 1

    def test_timeout_counts_as_non_pass(self) -> None:
        results = [
            _make_result("a", projection_status="pass"),
            _make_result("b", projection_status="timeout"),
        ]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert summary.overall_status == "partial"
        assert summary.timeout_count == 1

    def test_publish_error_overrides_status(self) -> None:
        results = [
            _make_result("a", publish_status="error", projection_status="pass"),
        ]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert summary.overall_status == "fail"
        assert summary.error_count == 1

    def test_sweep_id_generated(self) -> None:
        results = [_make_result("a")]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert len(summary.sweep_id) > 0

    def test_custom_sweep_id(self) -> None:
        results = [_make_result("a")]
        summary = reduce_results(
            results,
            sweep_started_at="2026-04-02T00:00:00Z",
            sweep_id="custom-id",
        )
        assert summary.sweep_id == "custom-id"

    def test_chain_summaries_match_input(self) -> None:
        results = [
            _make_result("alpha", projection_status="pass", publish_latency_ms=50.0),
            _make_result("beta", projection_status="fail", projection_latency_ms=120.0),
        ]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert len(summary.chains) == 2
        assert summary.chains[0].name == "alpha"
        assert summary.chains[0].status == "pass"
        assert summary.chains[1].name == "beta"
        assert summary.chains[1].status == "fail"

    def test_empty_results(self) -> None:
        summary = reduce_results([], sweep_started_at="2026-04-02T00:00:00Z")
        assert summary.overall_status == "pass"
        assert summary.pass_count == 0

    def test_mixed_statuses(self) -> None:
        results = [
            _make_result("a", projection_status="pass"),
            _make_result("b", projection_status="fail"),
            _make_result("c", projection_status="timeout"),
            _make_result("d", publish_status="error", projection_status="error"),
        ]
        summary = reduce_results(results, sweep_started_at="2026-04-02T00:00:00Z")
        assert summary.overall_status == "partial"
        assert summary.pass_count == 1
        assert summary.fail_count == 1
        assert summary.timeout_count == 1
        assert summary.error_count == 1
