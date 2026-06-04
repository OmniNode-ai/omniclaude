# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the live golden-chain sweep CLI entrypoint."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_golden_chain_status_reducer.models.model_sweep_summary import (
    ModelSweepSummary,
)
from omniclaude.nodes.node_golden_chain_sweep_orchestrator import __main__ as cli

pytestmark = pytest.mark.unit


def _summary(
    *,
    overall_status: str,
    fail_count: int = 0,
    timeout_count: int = 0,
    error_count: int = 0,
) -> ModelSweepSummary:
    return ModelSweepSummary(
        sweep_id="sweep-test",
        sweep_started_at="2026-06-04T00:00:00Z",
        sweep_completed_at="2026-06-04T00:00:01Z",
        overall_status=overall_status,
        pass_count=5 if overall_status == "pass" else 4,
        fail_count=fail_count,
        timeout_count=timeout_count,
        error_count=error_count,
        chains=(),
    )


def test_cli_returns_zero_for_clean_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_sweep(*args: object, **kwargs: object) -> ModelSweepSummary:
        return _summary(overall_status="pass")

    monkeypatch.setattr(cli, "run_sweep", fake_run_sweep)

    result = cli.main(
        [
            "--bootstrap-servers",
            "localhost:9092",
            "--db-dsn",
            "postgresql://example",
        ]
    )

    assert result == 0


def test_cli_returns_nonzero_for_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_sweep(*args: object, **kwargs: object) -> ModelSweepSummary:
        return _summary(overall_status="partial", timeout_count=1)

    monkeypatch.setattr(cli, "run_sweep", fake_run_sweep)

    result = cli.main(
        [
            "--bootstrap-servers",
            "localhost:9092",
            "--db-dsn",
            "postgresql://example",
        ]
    )

    assert result == 1
