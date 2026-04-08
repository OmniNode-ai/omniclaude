# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for wire schema validation in golden path runner (OMN-7374).

Validates:
- wire_schema_match assertion type
- _validate_wire_schema with real and missing contracts
- Field-level mismatch detail messages
- Integration with AssertionEngine
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from plugins.onex.skills._golden_path_validate.golden_path_runner import (
    AssertionEngine,
    EvidenceArtifact,
    _validate_wire_schema,
)


@pytest.fixture
def tmp_contract(tmp_path: Path) -> Path:
    """Create a minimal wire schema contract YAML for testing."""
    contract = {
        "topic": "onex.evt.test.routing-decision.v1",
        "schema_version": "1.0.0",
        "ticket": "OMN-7374",
        "description": "Test wire schema contract",
        "producer": {
            "repo": "omniclaude",
            "file": "plugins/onex/hooks/lib/route_via_events_wrapper.py",
            "function": "_build_routing_decision_payload",
        },
        "consumer": {
            "repo": "omnibase_infra",
            "file": "src/omnibase_infra/services/observability/consumer.py",
            "model": "ModelRoutingDecision",
        },
        "required_fields": [
            {"name": "id", "type": "uuid"},
            {"name": "correlation_id", "type": "uuid"},
            {"name": "selected_agent", "type": "string"},
            {"name": "confidence_score", "type": "float"},
            {"name": "created_at", "type": "datetime"},
        ],
        "optional_fields": [
            {"name": "domain", "type": "string", "nullable": True},
            {"name": "routing_reason", "type": "string", "nullable": True},
        ],
        "renamed_fields": [
            {
                "producer_name": "confidence",
                "canonical_name": "confidence_score",
                "shim_status": "active",
                "retirement_ticket": "OMN-TEST",
            },
        ],
    }
    contract_path = tmp_path / "routing_decision_v1.yaml"
    contract_path.write_text(yaml.dump(contract), encoding="utf-8")
    return contract_path


@pytest.mark.unit
class TestValidateWireSchema:
    """Tests for _validate_wire_schema function."""

    def test_not_declared_when_path_is_none(self) -> None:
        status, mismatches = _validate_wire_schema(None, {"foo": "bar"})
        assert status == "not_declared"
        assert mismatches == []

    def test_skipped_when_path_does_not_exist(self) -> None:
        status, mismatches = _validate_wire_schema(
            "/nonexistent/contract.yaml", {"foo": "bar"}
        )
        assert status == "skipped"
        assert mismatches == []

    def test_pass_when_all_required_fields_present(self, tmp_contract: Path) -> None:
        event = {
            "id": "abc-123",
            "correlation_id": "def-456",
            "selected_agent": "agent-api-architect",
            "confidence_score": 0.92,
            "created_at": "2026-04-08T00:00:00Z",
        }
        status, mismatches = _validate_wire_schema(str(tmp_contract), event)
        assert status == "pass"
        assert mismatches == []

    def test_fail_when_required_field_missing(self, tmp_contract: Path) -> None:
        event = {
            "id": "abc-123",
            "correlation_id": "def-456",
            # missing: selected_agent, confidence_score, created_at
        }
        status, mismatches = _validate_wire_schema(str(tmp_contract), event)
        assert status == "fail"
        assert len(mismatches) == 3
        missing_fields = {m["field"] for m in mismatches}
        assert missing_fields == {"selected_agent", "confidence_score", "created_at"}

    def test_field_level_detail_messages(self, tmp_contract: Path) -> None:
        event = {"id": "abc-123"}  # missing 4 required fields
        status, mismatches = _validate_wire_schema(str(tmp_contract), event)
        assert status == "fail"
        for mismatch in mismatches:
            assert "field" in mismatch
            assert "detail" in mismatch
            assert "Required field" in mismatch["detail"]
            assert "missing from event payload" in mismatch["detail"]

    def test_active_rename_alias_accepted(self, tmp_contract: Path) -> None:
        """Producer emitting 'confidence' (alias) instead of 'confidence_score' should pass."""
        event = {
            "id": "abc-123",
            "correlation_id": "def-456",
            "selected_agent": "agent-api-architect",
            "confidence": 0.92,  # alias for confidence_score
            "created_at": "2026-04-08T00:00:00Z",
        }
        status, mismatches = _validate_wire_schema(str(tmp_contract), event)
        assert status == "pass"
        assert mismatches == []

    def test_skipped_when_no_required_fields(self, tmp_path: Path) -> None:
        contract = {
            "topic": "test.topic",
            "schema_version": "1.0.0",
            "producer": {"repo": "test", "file": "test.py", "function": "test"},
            "consumer": {"repo": "test", "file": "test.py", "model": "Test"},
            "required_fields": [],
        }
        path = tmp_path / "empty_contract.yaml"
        path.write_text(yaml.dump(contract), encoding="utf-8")
        status, mismatches = _validate_wire_schema(str(path), {"foo": "bar"})
        assert status == "skipped"

    def test_skipped_when_yaml_invalid(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("not: [valid: yaml: {{", encoding="utf-8")
        status, mismatches = _validate_wire_schema(str(path), {"foo": "bar"})
        assert status == "skipped"


@pytest.mark.unit
class TestAssertionEngineWireSchema:
    """Tests for wire_schema_match assertion type in AssertionEngine."""

    def test_wire_schema_match_pass(self, tmp_contract: Path) -> None:
        engine = AssertionEngine()
        event_data = {
            "id": "abc-123",
            "correlation_id": "def-456",
            "selected_agent": "agent-api-architect",
            "confidence_score": 0.92,
            "created_at": "2026-04-08T00:00:00Z",
        }
        assertions: list[dict[str, Any]] = [
            {
                "op": "wire_schema_match",
                "contract_path": str(tmp_contract),
                "event_data": event_data,
            }
        ]
        results = engine.evaluate_all(assertions)
        assert len(results) == 1
        assert results[0]["passed"] is True
        assert results[0]["wire_schema_status"] == "pass"

    def test_wire_schema_match_fail(self, tmp_contract: Path) -> None:
        engine = AssertionEngine()
        event_data = {"id": "abc-123"}  # missing fields
        assertions: list[dict[str, Any]] = [
            {
                "op": "wire_schema_match",
                "contract_path": str(tmp_contract),
                "event_data": event_data,
            }
        ]
        results = engine.evaluate_all(assertions)
        assert len(results) == 1
        assert results[0]["passed"] is False
        assert results[0]["wire_schema_status"] == "fail"
        assert len(results[0]["wire_schema_mismatches"]) > 0
        assert "error" in results[0]

    def test_wire_schema_alongside_regular_assertions(self, tmp_contract: Path) -> None:
        engine = AssertionEngine()
        event_data = {
            "id": "abc-123",
            "correlation_id": "def-456",
            "selected_agent": "agent-api-architect",
            "confidence_score": 0.92,
            "created_at": "2026-04-08T00:00:00Z",
        }
        assertions: list[dict[str, Any]] = [
            {
                "op": "eq",
                "field": "selected_agent",
                "expected": "agent-api-architect",
                "actual": "agent-api-architect",
            },
            {
                "op": "wire_schema_match",
                "contract_path": str(tmp_contract),
                "event_data": event_data,
            },
        ]
        results = engine.evaluate_all(assertions)
        assert len(results) == 2
        assert results[0]["passed"] is True  # regular eq assertion
        assert results[1]["passed"] is True  # wire schema assertion


@pytest.mark.unit
class TestEvidenceArtifactWireSchemaFields:
    """Tests that EvidenceArtifact includes wire schema fields."""

    def test_default_wire_schema_fields(self) -> None:
        artifact = EvidenceArtifact(
            node_id="test",
            ticket_id="OMN-7374",
            run_id="run-1",
            emitted_at="2026-04-08T00:00:00Z",
            status="pass",
            input_topic="in",
            output_topic="out",
            latency_ms=100.0,
            correlation_id="cid",
            consumer_group_id="gid",
            schema_validation_status="not_declared",
            assertions=[],
            raw_output_preview="{}",
            kafka_offset=0,
            kafka_timestamp_ms=0,
        )
        assert artifact.wire_schema_validation_status == "not_declared"
        assert artifact.wire_schema_mismatches == []

    def test_wire_schema_fail_fields(self) -> None:
        mismatches = [
            {
                "field": "selected_agent",
                "detail": "Required field 'selected_agent' missing",
            }
        ]
        artifact = EvidenceArtifact(
            node_id="test",
            ticket_id="OMN-7374",
            run_id="run-1",
            emitted_at="2026-04-08T00:00:00Z",
            status="fail",
            input_topic="in",
            output_topic="out",
            latency_ms=100.0,
            correlation_id="cid",
            consumer_group_id="gid",
            schema_validation_status="pass",
            wire_schema_validation_status="fail",
            wire_schema_mismatches=mismatches,
            assertions=[],
            raw_output_preview="{}",
            kafka_offset=0,
            kafka_timestamp_ms=0,
        )
        assert artifact.wire_schema_validation_status == "fail"
        assert len(artifact.wire_schema_mismatches) == 1
        assert artifact.wire_schema_mismatches[0]["field"] == "selected_agent"
