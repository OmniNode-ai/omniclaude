# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for OMN-8012: Decimal JSON serialization in golden chain sweep."""

from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from omniclaude.nodes.node_golden_chain_publish_effect.models.model_chain_result import (
    ModelChainResult,
)
from omniclaude.nodes.node_golden_chain_status_reducer.models.model_sweep_summary import (
    ModelSweepSummary,
)
from omniclaude.nodes.node_golden_chain_sweep_orchestrator.node import _write_evidence


def _make_summary() -> ModelSweepSummary:
    return ModelSweepSummary(
        sweep_id="test-sweep-id",
        sweep_started_at="2026-04-11T00:00:00Z",
        sweep_completed_at="2026-04-11T00:00:01Z",
        overall_status="pass",
        pass_count=1,
        fail_count=0,
        timeout_count=0,
        error_count=0,
    )


@pytest.mark.unit
class TestDecimalJsonSerialization:
    """Decimal values from DB columns must not crash json.dumps."""

    def test_write_evidence_with_decimal_assertion_values_does_not_raise(self) -> None:
        """Assertion results containing Decimal (from NUMERIC DB columns) must serialize."""
        summary = _make_summary()
        chain_results = [
            ModelChainResult(
                chain_name="registration",
                correlation_id="golden-chain-registration-test",
                publish_status="ok",
                publish_latency_ms=12.3,
                projection_status="pass",
                projection_latency_ms=456.7,
                assertion_results=[
                    {
                        "field": "score",
                        "op": "gt",
                        "expected": 0,
                        "actual": Decimal("1.5"),
                        "passed": True,
                    }
                ],
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            _write_evidence(summary, chain_results, _state_dir=Path(tmp))
            artifact_path = (
                Path(tmp) / "2026-04-11" / "test-sweep-id" / "sweep_results.json"
            )
            assert artifact_path.exists(), "Evidence artifact was not written"
            data = json.loads(artifact_path.read_text())
            assert data["overall_status"] == "pass"
            assert float(
                data["chains"][0]["assertion_results"][0]["actual"]
            ) == pytest.approx(1.5)

    def test_write_evidence_no_assertion_results_does_not_raise(self) -> None:
        """Empty assertion results still write evidence without error."""
        summary = _make_summary()
        chain_results = [
            ModelChainResult(
                chain_name="delegation",
                correlation_id="golden-chain-delegation-test",
                publish_status="ok",
                projection_status="timeout",
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            _write_evidence(summary, chain_results, _state_dir=Path(tmp))
            artifact_path = (
                Path(tmp) / "2026-04-11" / "test-sweep-id" / "sweep_results.json"
            )
            assert artifact_path.exists()
