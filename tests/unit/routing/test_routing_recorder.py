# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for routing decision recorder.

OMN-7035: Verify routing decisions are recorded to NDJSON with all required
fields and that Kafka emission is fail-open.
"""

from __future__ import annotations

import json

import pytest

from omniclaude.routing.routing_recorder import ModelRoutingDecision, RoutingRecorder


@pytest.mark.unit
class TestRoutingRecorder:
    """Test routing decision recording to append-only NDJSON."""

    def test_routing_decision_recorded(self, tmp_path: object) -> None:
        """Routing decision written to disk with all required fields."""
        recorder = RoutingRecorder(state_dir=str(tmp_path))
        recorder.record(
            task_id="task-1",
            dispatch_surface="local_llm",
            agent_model="qwen3-14b",
            rationale="Mechanical verification, read-only, bounded context",
            fallback="claude-opus-4-6",
        )
        decisions = recorder.read_all()
        assert len(decisions) == 1

        d = decisions[0]
        assert d.task_id == "task-1"
        assert d.intended_surface == "local_llm"
        assert d.executed_surface == "local_llm"
        assert d.agent_model == "qwen3-14b"
        assert d.rationale == "Mechanical verification, read-only, bounded context"
        assert d.fallback == "claude-opus-4-6"
        assert d.reroute_reason is None
        assert d.schema_version == "1.0.0"
        assert d.created_at

    def test_fallback_records_different_executed_surface(
        self, tmp_path: object
    ) -> None:
        """When fallback triggers, executed_surface differs from intended."""
        recorder = RoutingRecorder(state_dir=str(tmp_path))
        recorder.record(
            task_id="task-2",
            dispatch_surface="local_llm",
            executed_surface="team_worker",
            agent_model="claude-opus-4-6",
            rationale="Local LLM unreachable, escalated",
            fallback="claude-opus-4-6",
            reroute_reason="Connection timeout to local LLM",
        )
        decisions = recorder.read_all()
        assert len(decisions) == 1
        assert decisions[0].intended_surface == "local_llm"
        assert decisions[0].executed_surface == "team_worker"
        assert decisions[0].reroute_reason == "Connection timeout to local LLM"

    def test_append_only_multiple_records(self, tmp_path: object) -> None:
        """Multiple records append to the same file without overwriting."""
        recorder = RoutingRecorder(state_dir=str(tmp_path))
        for i in range(3):
            recorder.record(
                task_id=f"task-{i}",
                dispatch_surface="team_worker",
                agent_model="claude-opus-4-6",
                rationale=f"Reason {i}",
            )
        decisions = recorder.read_all()
        assert len(decisions) == 3
        assert [d.task_id for d in decisions] == [
            "task-0",
            "task-1",
            "task-2",
        ]

    def test_read_all_returns_empty_when_no_file(self, tmp_path: object) -> None:
        """read_all returns empty list when decisions file does not exist."""
        recorder = RoutingRecorder(state_dir=str(tmp_path))
        assert recorder.read_all() == []

    def test_ndjson_format_valid(self, tmp_path: object) -> None:
        """Each line in the NDJSON file is valid JSON."""
        recorder = RoutingRecorder(state_dir=str(tmp_path))
        recorder.record(
            task_id="task-fmt",
            dispatch_surface="headless_claude",
            agent_model="claude-opus-4-6",
            rationale="Headless session",
        )
        ndjson_path = tmp_path / "routing" / "decisions.ndjson"  # type: ignore[operator]
        lines = ndjson_path.read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["task_id"] == "task-fmt"  # raw JSON dict access intentional

    def test_model_routing_decision_frozen(self) -> None:
        """ModelRoutingDecision is immutable."""
        decision = ModelRoutingDecision(
            task_id="t1",
            intended_surface="local_llm",
            executed_surface="local_llm",
            agent_model="qwen3-14b",
            rationale="test",
        )
        with pytest.raises(Exception):
            decision.task_id = "t2"  # type: ignore[misc]
