# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the friction observer hook adapter."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add hooks/lib and _shared to path (mirrors hook PYTHONPATH setup)
_HOOKS_LIB = str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
_SHARED_PATH = str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
for p in [_HOOKS_LIB, _SHARED_PATH]:
    if p not in sys.path:
        sys.path.insert(0, p)

from friction_observer_adapter import observe_friction


@pytest.mark.unit
class TestObserveFriction:
    def test_skill_failed_records_friction(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        with patch("friction_observer_adapter._RULES", None):  # force reload
            result = observe_friction(
                event_type="skill.completed",
                payload={
                    "status": "failed",
                    "skill_name": "deploy",
                    "error": "CI red",
                },
                session_id="sess-test",
                source="claude_code_hook",
                registry_path=registry,
            )
        assert result is True
        lines = registry.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["surface"] == "tooling/skill-failed"
        assert record["severity"] == "medium"
        assert record["session_id"] == "sess-test"

    def test_unknown_event_records_via_wildcard(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        with patch("friction_observer_adapter._RULES", None):
            result = observe_friction(
                event_type="cursor.crash",
                payload={},
                session_id="sess-test",
                source="cursor",
                registry_path=registry,
            )
        assert result is True
        record = json.loads(registry.read_text().strip())
        assert record["surface"] == "unknown/unclassified"

    def test_recorded_timestamp_is_utc(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        with patch("friction_observer_adapter._RULES", None):
            observe_friction(
                event_type="budget.cap.hit",
                payload={"tokens_used": "100", "tokens_budget": "50"},
                session_id="sess-test",
                registry_path=registry,
            )
        record = json.loads(registry.read_text().strip())
        assert "+00:00" in record["timestamp"] or "Z" in record["timestamp"]

    def test_with_ticket_id(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        with patch("friction_observer_adapter._RULES", None):
            observe_friction(
                event_type="skill.completed",
                payload={
                    "status": "blocked",
                    "skill_name": "merge",
                    "blocked_reason": "conflict",
                },
                session_id="sess-test",
                ticket_id="OMN-5678",
                registry_path=registry,
            )
        record = json.loads(registry.read_text().strip())
        assert record["context_ticket_id"] == "OMN-5678"

    # --- Resilience tests (prove the adapter degrades gracefully) ---

    def test_kafka_unavailable_still_returns_true_if_ndjson_succeeded(
        self, tmp_path: Path
    ):
        """When Kafka/emit daemon is unavailable, adapter still returns True if NDJSON write worked."""
        registry = tmp_path / "friction.ndjson"
        # emit_client_wrapper is not importable in test context — the adapter's
        # try/except around the lazy import silently swallows the ImportError.
        with patch("friction_observer_adapter._RULES", None):
            result = observe_friction(
                event_type="skill.completed",
                payload={"status": "failed", "skill_name": "test"},
                session_id="sess-test",
                registry_path=registry,
            )
        assert result is True  # NDJSON succeeded -> success
        assert registry.exists()

    def test_record_friction_exception_returns_false(self, tmp_path: Path):
        """If record_friction() itself fails, adapter returns False."""
        with (
            patch("friction_observer_adapter._RULES", None),
            patch(
                "friction_observer_adapter.record_friction",
                side_effect=OSError("disk full"),
            ),
        ):
            result = observe_friction(
                event_type="skill.completed",
                payload={"status": "failed", "skill_name": "test"},
                session_id="sess-test",
                registry_path=tmp_path / "friction.ndjson",
            )
        assert result is False

    def test_malformed_contract_path_returns_false(self, tmp_path: Path):
        """If contract YAML is missing or broken, adapter returns False and logs."""
        with (
            patch(
                "friction_observer_adapter._CONTRACT_PATH",
                tmp_path / "nonexistent.yaml",
            ),
            patch("friction_observer_adapter._RULES", None),
        ):
            result = observe_friction(
                event_type="skill.completed",
                payload={"status": "failed"},
                session_id="sess-test",
                registry_path=tmp_path / "friction.ndjson",
            )
        assert result is False
