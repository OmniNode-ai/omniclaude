# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the live golden-chain CI runner."""

from __future__ import annotations

import pytest

from omniclaude.hooks.topics import TopicBase
from scripts.ci import run_golden_chain_live as runner

pytestmark = pytest.mark.unit


@pytest.fixture
def captured_upserts(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_upsert(
        db_dsn: str,
        table: str,
        conflict_key: str,
        row: dict[str, object],
    ) -> None:
        calls.append(
            {
                "db_dsn": db_dsn,
                "table": table,
                "conflict_key": conflict_key,
                "row": row,
            }
        )

    monkeypatch.setattr(runner, "_upsert", fake_upsert)
    return calls


def test_project_envelope_ignores_unregistered_topic(
    captured_upserts: list[dict[str, object]],
) -> None:
    runner.project_envelope(
        {"event_type": "onex.evt.omniclaude.unregistered.v1", "payload": {}},
        "postgresql://example",
    )

    assert captured_upserts == []


@pytest.mark.parametrize(
    ("topic", "expected_table", "payload"),
    [
        (
            str(TopicBase.ROUTING_DECISION),
            "agent_routing_decisions",
            {
                "correlation_id": "00000000-0000-0000-0000-000000000001",
                "selected_agent": "golden-chain-test-agent",
                "confidence_score": "0.9500",
            },
        ),
        (
            str(TopicBase.PATTERN_STORED),
            "pattern_learning_artifacts",
            {
                "correlation_id": "golden-chain-pattern-1",
                "pattern_name": "golden-chain-test-pattern",
                "pattern_type": "golden-chain-test",
                "state": "stored",
            },
        ),
        (
            str(TopicBase.TASK_DELEGATED),
            "delegation_events",
            {
                "correlation_id": "golden-chain-delegation-1",
                "task_type": "golden-chain-test",
                "delegate_model": "golden-chain-test-model",
            },
        ),
        (
            str(TopicBase.LLM_ROUTING_DECISION),
            "llm_routing_decisions",
            {
                "correlation_id": "00000000-0000-0000-0000-000000000002",
                "selected_model": "golden-chain-test-model",
                "decision_method": "fallback",
            },
        ),
        (
            str(TopicBase.SESSION_OUTCOME_EVT),
            "session_outcomes",
            {
                "correlation_id": "golden-chain-evaluation-1",
                "session_id": "golden-chain-test-session",
                "outcome": "success",
            },
        ),
    ],
)
def test_project_envelope_materializes_registered_topics(
    captured_upserts: list[dict[str, object]],
    topic: str,
    expected_table: str,
    payload: dict[str, object],
) -> None:
    runner.project_envelope(
        {"event_type": topic, "payload": payload},
        "postgresql://example",
    )

    assert len(captured_upserts) == 1
    assert captured_upserts[0]["table"] == expected_table
