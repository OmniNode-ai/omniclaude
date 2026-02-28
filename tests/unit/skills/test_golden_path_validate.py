# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for golden-path-validate skill.

Tests cover:
- Assertion engine (eq, neq, gte, lte, in, contains)
- Timeout path (writes artifact with status: timeout)
- Correlation injection and filtering
- Evidence artifact fields
- schema_name handling (importable, not importable, absent)
- Artifact path date extraction from emitted_at
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from plugins.onex.skills.golden_path_validate.golden_path_runner import (
    AssertionEngine,
    EvidenceArtifact,
    GoldenPathRunner,
    _extract_artifact_date,
    _run_assertion,
)

# ---------------------------------------------------------------------------
# Assertion engine tests
# ---------------------------------------------------------------------------


class TestRunAssertion:
    """Tests for individual assertion evaluation."""

    def test_eq_pass(self) -> None:
        assert _run_assertion("eq", "hello", "hello") is True

    def test_eq_fail(self) -> None:
        assert _run_assertion("eq", "hello", "world") is False

    def test_neq_pass(self) -> None:
        assert _run_assertion("neq", "hello", "world") is True

    def test_neq_fail(self) -> None:
        assert _run_assertion("neq", "hello", "hello") is False

    def test_gte_pass_equal(self) -> None:
        assert _run_assertion("gte", 5, 5) is True

    def test_gte_pass_greater(self) -> None:
        assert _run_assertion("gte", 6, 5) is True

    def test_gte_fail(self) -> None:
        assert _run_assertion("gte", 4, 5) is False

    def test_lte_pass_equal(self) -> None:
        assert _run_assertion("lte", 5, 5) is True

    def test_lte_pass_less(self) -> None:
        assert _run_assertion("lte", 4, 5) is True

    def test_lte_fail(self) -> None:
        assert _run_assertion("lte", 6, 5) is False

    def test_in_pass(self) -> None:
        assert _run_assertion("in", "apple", ["apple", "banana"]) is True

    def test_in_fail(self) -> None:
        assert _run_assertion("in", "cherry", ["apple", "banana"]) is False

    def test_contains_pass(self) -> None:
        assert _run_assertion("contains", "hello world", "world") is True

    def test_contains_fail(self) -> None:
        assert _run_assertion("contains", "hello world", "foo") is False

    def test_contains_list_pass(self) -> None:
        assert _run_assertion("contains", ["a", "b", "c"], "b") is True

    def test_contains_list_fail(self) -> None:
        assert _run_assertion("contains", ["a", "b", "c"], "z") is False

    def test_unknown_op_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown assertion op"):
            _run_assertion("regex", "value", "pattern")


class TestAssertionEngine:
    """Tests for AssertionEngine.evaluate_all."""

    def test_all_pass(self) -> None:
        engine = AssertionEngine()
        assertions: list[dict[str, Any]] = [
            {"field": "status", "op": "eq", "expected": "ok", "actual": "ok"},
            {"field": "count", "op": "gte", "expected": 1, "actual": 5},
        ]
        results = engine.evaluate_all(assertions)
        assert all(r["passed"] for r in results)

    def test_mixed_pass_fail(self) -> None:
        engine = AssertionEngine()
        assertions: list[dict[str, Any]] = [
            {"field": "status", "op": "eq", "expected": "ok", "actual": "ok"},
            {"field": "count", "op": "eq", "expected": 99, "actual": 1},
        ]
        results = engine.evaluate_all(assertions)
        assert results[0]["passed"] is True
        assert results[1]["passed"] is False

    def test_empty_assertions(self) -> None:
        engine = AssertionEngine()
        results = engine.evaluate_all([])
        assert results == []


# ---------------------------------------------------------------------------
# Artifact path date extraction
# ---------------------------------------------------------------------------


class TestExtractArtifactDate:
    """Tests for date extraction from emitted_at timestamp."""

    def test_extracts_date_from_emitted_at(self) -> None:
        emitted_at = "2026-01-15T10:30:00Z"
        assert _extract_artifact_date(emitted_at) == "2026-01-15"

    def test_extracts_date_with_offset(self) -> None:
        emitted_at = "2026-03-22T23:59:59+00:00"
        assert _extract_artifact_date(emitted_at) == "2026-03-22"

    def test_fallback_on_invalid(self) -> None:
        # Should return today's date on invalid input rather than crash
        result = _extract_artifact_date("not-a-date")
        assert len(result) == 10  # YYYY-MM-DD format
        assert result.count("-") == 2


# ---------------------------------------------------------------------------
# EvidenceArtifact model
# ---------------------------------------------------------------------------


class TestEvidenceArtifact:
    """Tests for EvidenceArtifact Pydantic model."""

    def test_required_fields_present(self) -> None:
        artifact = EvidenceArtifact(
            node_id="test_node",
            ticket_id="OMN-2976",
            run_id="run-001",
            emitted_at="2026-02-28T10:00:00Z",
            status="pass",
            input_topic="onex.cmd.test.v1",
            output_topic="onex.evt.test.v1",
            latency_ms=42.5,
            correlation_id=str(uuid4()),
            consumer_group_id="golden-path-abc12345",
            schema_validation_status="not_declared",
            assertions=[],
            raw_output_preview="{}",
            kafka_offset=0,
            kafka_timestamp_ms=1_700_000_000_000,
        )
        assert artifact.status == "pass"
        assert artifact.latency_ms == 42.5

    def test_status_timeout(self) -> None:
        artifact = EvidenceArtifact(
            node_id="test_node",
            ticket_id="OMN-2976",
            run_id="run-001",
            emitted_at="2026-02-28T10:00:00Z",
            status="timeout",
            input_topic="onex.cmd.test.v1",
            output_topic="onex.evt.test.v1",
            latency_ms=30_000.0,
            correlation_id=str(uuid4()),
            consumer_group_id="golden-path-abc12345",
            schema_validation_status="not_declared",
            assertions=[],
            raw_output_preview="",
            kafka_offset=-1,
            kafka_timestamp_ms=-1,
        )
        assert artifact.status == "timeout"


# ---------------------------------------------------------------------------
# GoldenPathRunner — unit tests with mocked Kafka
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_decl() -> dict[str, Any]:
    return {
        "node_id": "test_node",
        "ticket_id": "OMN-2976",
        "input": {
            "topic": "onex.cmd.test.v1",
            "fixture": {"event_type": "test", "payload": {"key": "value"}},
        },
        "output": {
            "topic": "onex.evt.test.v1",
        },
        "timeout_ms": 5000,
        "assertions": [
            {"field": "status", "op": "eq", "expected": "ok"},
        ],
    }


@pytest.fixture
def decl_with_schema(minimal_decl: dict[str, Any]) -> dict[str, Any]:
    decl = dict(minimal_decl)
    decl["schema_name"] = "omnibase_core.models.model_onex_event.ModelOnexEvent"
    return decl


@pytest.fixture
def decl_with_bad_schema(minimal_decl: dict[str, Any]) -> dict[str, Any]:
    decl = dict(minimal_decl)
    decl["schema_name"] = "nonexistent.module.DoesNotExist"
    return decl


class TestGoldenPathRunnerTimeout:
    """Tests for timeout path."""

    @pytest.mark.unit
    async def test_timeout_writes_timeout_artifact(
        self,
        tmp_path: Path,
        minimal_decl: dict[str, Any],
    ) -> None:
        """When no matching event arrives within timeout, artifact status=timeout."""
        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        mock_consumer.getone = AsyncMock(side_effect=TimeoutError("timeout"))

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(minimal_decl)

        assert artifact.status == "timeout"
        assert artifact.node_id == "test_node"
        assert artifact.ticket_id == "OMN-2976"
        # Verify artifact was written to disk
        assert len(list(tmp_path.rglob("*.json"))) == 1


class TestGoldenPathRunnerCorrelation:
    """Tests for correlation ID injection and filtering."""

    @pytest.mark.unit
    async def test_correlation_id_injected_into_fixture(
        self,
        tmp_path: Path,
        minimal_decl: dict[str, Any],
    ) -> None:
        """Correlation ID must be injected into the published fixture."""
        captured_messages: list[bytes] = []

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        # Simulate timeout after capture
        mock_consumer.getone = AsyncMock(side_effect=TimeoutError("timeout"))

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        async def capture_send(topic: str, value: bytes) -> None:
            captured_messages.append(value)

        mock_producer.send_and_wait = capture_send

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(minimal_decl)

        assert len(captured_messages) == 1
        payload = json.loads(captured_messages[0])
        assert "correlation_id" in payload
        # The correlation_id in the fixture must match artifact's correlation_id
        assert payload["correlation_id"] == artifact.correlation_id

    @pytest.mark.unit
    async def test_non_matching_event_filtered(
        self,
        tmp_path: Path,
        minimal_decl: dict[str, Any],
    ) -> None:
        """Events with non-matching correlation_id are ignored; timeout if no match."""
        # Use a very short timeout so the deadline expires after the first wrong-corr message
        short_timeout_decl = dict(minimal_decl)
        short_timeout_decl["timeout_ms"] = 50  # 50ms — expires quickly

        wrong_corr_msg = MagicMock()
        wrong_corr_msg.value = json.dumps(
            {"correlation_id": str(uuid4()), "status": "ok"}
        ).encode()
        wrong_corr_msg.offset = 5
        wrong_corr_msg.timestamp = 1_700_000_000_000

        call_count = 0

        async def getone_side_effect() -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Return wrong-correlation message
                return wrong_corr_msg
            # Simulate waiting until the deadline expires
            await asyncio.sleep(0.1)  # sleep longer than timeout_ms=50ms
            return wrong_corr_msg  # unreachable in practice

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        mock_consumer.getone = getone_side_effect

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(short_timeout_decl)

        # Should timeout because the only real event had wrong correlation_id
        assert artifact.status == "timeout"


class TestGoldenPathRunnerSuccess:
    """Tests for successful event matching and assertion evaluation."""

    @pytest.mark.unit
    async def test_matching_event_produces_pass_artifact(
        self,
        tmp_path: Path,
        minimal_decl: dict[str, Any],
    ) -> None:
        """A matching event with all assertions passing produces status=pass."""
        captured_correlation_id: list[str] = []

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        async def capture_send(topic: str, value: bytes) -> None:
            payload = json.loads(value)
            captured_correlation_id.append(payload["correlation_id"])
            # Immediately make consumer return a matching message
            matching_msg = MagicMock()
            matching_msg.value = json.dumps(
                {
                    "correlation_id": payload["correlation_id"],
                    "status": "ok",
                }
            ).encode()
            matching_msg.offset = 10
            matching_msg.timestamp = 1_700_000_000_001
            mock_consumer.getone = AsyncMock(return_value=matching_msg)

        mock_producer.send_and_wait = capture_send

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(minimal_decl)

        assert artifact.status == "pass"
        assert artifact.kafka_offset == 10
        assert artifact.kafka_timestamp_ms == 1_700_000_000_001
        assert len(artifact.assertions) == 1
        assert artifact.assertions[0]["passed"] is True

    @pytest.mark.unit
    async def test_failed_assertion_produces_fail_artifact(
        self,
        tmp_path: Path,
    ) -> None:
        """A matching event with failing assertions produces status=fail."""
        decl = {
            "node_id": "test_node",
            "ticket_id": "OMN-2976",
            "input": {
                "topic": "onex.cmd.test.v1",
                "fixture": {"event_type": "test"},
            },
            "output": {"topic": "onex.evt.test.v1"},
            "timeout_ms": 5000,
            "assertions": [
                {"field": "status", "op": "eq", "expected": "success"},  # will fail
            ],
        }

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        async def capture_send(topic: str, value: bytes) -> None:
            payload = json.loads(value)
            matching_msg = MagicMock()
            matching_msg.value = json.dumps(
                {
                    "correlation_id": payload["correlation_id"],
                    "status": "error",  # assertion expects "success"
                }
            ).encode()
            matching_msg.offset = 5
            matching_msg.timestamp = 1_700_000_000_000
            mock_consumer.getone = AsyncMock(return_value=matching_msg)

        mock_producer.send_and_wait = capture_send

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(decl)

        assert artifact.status == "fail"
        assert artifact.assertions[0]["passed"] is False


class TestGoldenPathRunnerSchemaHandling:
    """Tests for schema_name handling in the runner."""

    @pytest.mark.unit
    async def test_schema_absent_produces_not_declared(
        self,
        tmp_path: Path,
        minimal_decl: dict[str, Any],
    ) -> None:
        """When schema_name is absent, schema_validation_status=not_declared."""
        # No schema_name in minimal_decl
        assert "schema_name" not in minimal_decl

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        async def capture_send(topic: str, value: bytes) -> None:
            payload = json.loads(value)
            matching_msg = MagicMock()
            matching_msg.value = json.dumps(
                {"correlation_id": payload["correlation_id"], "status": "ok"}
            ).encode()
            matching_msg.offset = 1
            matching_msg.timestamp = 1_700_000_000_000
            mock_consumer.getone = AsyncMock(return_value=matching_msg)

        mock_producer.send_and_wait = capture_send

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(minimal_decl)

        assert artifact.schema_validation_status == "not_declared"

    @pytest.mark.unit
    async def test_schema_not_importable_produces_skipped(
        self,
        tmp_path: Path,
        decl_with_bad_schema: dict[str, Any],
    ) -> None:
        """When schema_name is present but not importable, schema_validation_status=skipped."""
        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        async def capture_send(topic: str, value: bytes) -> None:
            payload = json.loads(value)
            matching_msg = MagicMock()
            matching_msg.value = json.dumps(
                {"correlation_id": payload["correlation_id"], "status": "ok"}
            ).encode()
            matching_msg.offset = 1
            matching_msg.timestamp = 1_700_000_000_000
            mock_consumer.getone = AsyncMock(return_value=matching_msg)

        mock_producer.send_and_wait = capture_send

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(decl_with_bad_schema)

        assert artifact.schema_validation_status == "skipped"

    @pytest.mark.unit
    async def test_schema_importable_and_valid_produces_pass(
        self,
        tmp_path: Path,
        decl_with_schema: dict[str, Any],
    ) -> None:
        """When schema_name is importable and event is valid, schema_validation_status=pass."""
        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        async def capture_send(topic: str, value: bytes) -> None:
            payload = json.loads(value)
            # Provide minimal valid event data for schema validation
            matching_msg = MagicMock()
            matching_msg.value = json.dumps(
                {
                    "correlation_id": payload["correlation_id"],
                    "status": "ok",
                }
            ).encode()
            matching_msg.offset = 1
            matching_msg.timestamp = 1_700_000_000_000
            mock_consumer.getone = AsyncMock(return_value=matching_msg)

        mock_producer.send_and_wait = capture_send

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        # Mock schema import to simulate an importable but flexible schema
        mock_schema_class = MagicMock()
        mock_schema_class.model_validate = MagicMock(return_value=MagicMock())

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner._import_schema_class",
                return_value=mock_schema_class,
            ),
        ):
            artifact = await runner.run(decl_with_schema)

        assert artifact.schema_validation_status == "pass"

    @pytest.mark.unit
    async def test_schema_importable_but_invalid_produces_fail(
        self,
        tmp_path: Path,
        decl_with_schema: dict[str, Any],
    ) -> None:
        """When schema_name is importable but event fails validation, status=fail."""
        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        async def capture_send(topic: str, value: bytes) -> None:
            payload = json.loads(value)
            matching_msg = MagicMock()
            matching_msg.value = json.dumps(
                {"correlation_id": payload["correlation_id"], "status": "ok"}
            ).encode()
            matching_msg.offset = 1
            matching_msg.timestamp = 1_700_000_000_000
            mock_consumer.getone = AsyncMock(return_value=matching_msg)

        mock_producer.send_and_wait = capture_send

        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        mock_schema_class = MagicMock()
        mock_schema_class.model_validate = MagicMock(side_effect=ValueError("invalid"))

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner._import_schema_class",
                return_value=mock_schema_class,
            ),
        ):
            artifact = await runner.run(decl_with_schema)

        assert artifact.schema_validation_status == "fail"


class TestGoldenPathRunnerArtifactPath:
    """Tests for artifact path using emitted_at date."""

    @pytest.mark.unit
    async def test_artifact_path_uses_emitted_at_date(
        self,
        tmp_path: Path,
        minimal_decl: dict[str, Any],
    ) -> None:
        """Artifact is stored under YYYY-MM-DD from emitted_at, not creation time."""
        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        mock_consumer.getone = AsyncMock(side_effect=TimeoutError("timeout"))

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(minimal_decl)

        # The artifact file should exist under the date from emitted_at
        date_str = _extract_artifact_date(artifact.emitted_at)
        expected_dir = tmp_path / "golden-path" / date_str
        json_files = list(expected_dir.rglob("*.json"))
        assert len(json_files) == 1

    @pytest.mark.unit
    async def test_artifact_fields_complete(
        self,
        tmp_path: Path,
        minimal_decl: dict[str, Any],
    ) -> None:
        """Evidence artifact contains all required fields."""
        runner = GoldenPathRunner(
            bootstrap_servers="localhost:29092",
            artifact_base_dir=str(tmp_path / "golden-path"),
        )

        mock_consumer = AsyncMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        mock_consumer.getone = AsyncMock(side_effect=TimeoutError("timeout"))

        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        with (
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch(
                "plugins.onex.skills.golden_path_validate.golden_path_runner.AIOKafkaProducer",
                return_value=mock_producer,
            ),
        ):
            artifact = await runner.run(minimal_decl)

        # Verify all required evidence artifact fields are present
        assert artifact.node_id
        assert artifact.ticket_id == "OMN-2976"
        assert artifact.run_id
        assert artifact.emitted_at
        assert artifact.status in {"pass", "fail", "timeout"}
        assert artifact.input_topic == "onex.cmd.test.v1"
        assert artifact.output_topic == "onex.evt.test.v1"
        assert isinstance(artifact.latency_ms, float)
        assert artifact.correlation_id
        assert artifact.consumer_group_id.startswith("golden-path-")
        assert artifact.schema_validation_status in {
            "pass",
            "fail",
            "skipped",
            "not_declared",
        }
        assert isinstance(artifact.assertions, list)
        assert isinstance(artifact.raw_output_preview, str)
        assert isinstance(artifact.kafka_offset, int)
        assert isinstance(artifact.kafka_timestamp_ms, int)
