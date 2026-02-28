# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Golden Path Validator — warm-subscribe Kafka test runner with evidence artifacts.

Executes a golden path event chain test using real Kafka/Redpanda.
Takes a golden_path declaration, warm-subscribes to the output topic, emits
a fixture with an injected correlation ID, waits for a matching output event,
validates field assertions, and writes an unsigned evidence artifact.

Usage::

    from plugins.onex.skills.golden_path_validate.golden_path_runner import GoldenPathRunner

    runner = GoldenPathRunner(bootstrap_servers="192.168.86.200:29092")  # onex-allow-internal-ip
    artifact = await runner.run(decl)

Declaration format::

    {
        "node_id": "node_my_compute",
        "ticket_id": "OMN-2976",
        "input": {
            "topic": "onex.cmd.my_node.v1",
            "fixture": {"event_type": "process", "payload": {"key": "value"}}
        },
        "output": {
            "topic": "onex.evt.my_node.v1"
        },
        "timeout_ms": 10000,
        "assertions": [
            {"field": "status", "op": "eq", "expected": "ok"}
        ],
        "schema_name": "omnibase_core.models.model_my_event.ModelMyEvent"  # optional
    }

Evidence artifact path::

    {artifact_base_dir}/{YYYY-MM-DD}/{run_id}/{node_id}.json

The YYYY-MM-DD is extracted from emitted_at — used by close-day to detect today's runs.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evidence Artifact model
# ---------------------------------------------------------------------------


class EvidenceArtifact(BaseModel):
    """Unsigned evidence artifact written after each golden-path run.

    All fields are required. Artifact is serialized to JSON and written to::

        {artifact_base_dir}/{YYYY-MM-DD}/{run_id}/{node_id}.json

    The YYYY-MM-DD is extracted from emitted_at (not the current wall-clock time)
    so that close-day can correctly detect today's runs even when the runner is
    invoked near midnight.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str = Field(..., description="Identifier for the node under test")
    ticket_id: str = Field(..., description="Linear ticket ID (e.g. OMN-2976)")
    run_id: str = Field(..., description="Unique run identifier (uuid4-based)")
    emitted_at: str = Field(
        ..., description="ISO-8601 timestamp when fixture was emitted"
    )
    status: str = Field(..., description="Overall result: pass | fail | timeout")
    input_topic: str = Field(
        ..., description="Kafka topic the fixture was published to"
    )
    output_topic: str = Field(
        ..., description="Kafka topic polled for the output event"
    )
    latency_ms: float = Field(
        ...,
        description="Milliseconds between emit and matching event receipt; -1 on timeout",
    )
    correlation_id: str = Field(
        ..., description="UUID injected into fixture and used to filter output events"
    )
    consumer_group_id: str = Field(
        ..., description="Kafka consumer group used during this run"
    )
    schema_validation_status: str = Field(
        ...,
        description="pass | fail | skipped | not_declared",
    )
    assertions: list[dict[str, Any]] = Field(
        ...,
        description="Per-assertion results with field, op, expected, actual, passed",
    )
    raw_output_preview: str = Field(
        ...,
        description="First 500 chars of the raw output event JSON; empty on timeout",
    )
    kafka_offset: int = Field(
        ...,
        description="Kafka partition offset of the matching output event; -1 on timeout",
    )
    kafka_timestamp_ms: int = Field(
        ...,
        description="Kafka broker-assigned timestamp of the output event; -1 on timeout",
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _extract_artifact_date(emitted_at: str) -> str:
    """Extract YYYY-MM-DD from an ISO-8601 emitted_at string.

    Falls back to today's date when the string cannot be parsed.

    Args:
        emitted_at: ISO-8601 datetime string (e.g. "2026-02-28T10:30:00Z").

    Returns:
        Date string in YYYY-MM-DD format.
    """
    # Fast path: ISO-8601 always starts with YYYY-MM-DD
    if len(emitted_at) >= 10 and emitted_at[4] == "-" and emitted_at[7] == "-":  # noqa: PLR2004
        date_part = emitted_at[:10]
        # Validate it looks like a date (YYYY-MM-DD)
        if len(date_part) == 10 and date_part.count("-") == 2:  # noqa: PLR2004
            try:
                # Use timezone-aware parse to avoid DTZ007
                datetime.fromisoformat(emitted_at.replace("Z", "+00:00"))
                return date_part
            except (ValueError, AttributeError):
                pass
    logger.warning("Could not parse emitted_at=%r; falling back to today", emitted_at)
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _run_assertion(op: str, actual: Any, expected: Any) -> bool:
    """Evaluate a single assertion.

    Args:
        op: Assertion operator. One of: eq, neq, gte, lte, in, contains.
        actual: The actual value from the output event.
        expected: The expected value from the declaration.

    Returns:
        True if the assertion passes.

    Raises:
        ValueError: When the operator is not recognized.
    """
    result: bool
    match op:
        case "eq":
            result = bool(actual == expected)
        case "neq":
            result = bool(actual != expected)
        case "gte":
            result = bool(actual >= expected)
        case "lte":
            result = bool(actual <= expected)
        case "in":
            result = bool(actual in expected)
        case "contains":
            result = bool(expected in actual)
        case _:
            raise ValueError(f"Unknown assertion op: {op!r}")
    return result


def _import_schema_class(schema_name: str) -> type[Any] | None:
    """Attempt to import a Pydantic model class by dotted name.

    Args:
        schema_name: Fully qualified class name, e.g.
            "omnibase_core.models.model_foo.ModelFoo".

    Returns:
        The class if importable, None otherwise (with a warning logged).
    """
    parts = schema_name.rsplit(".", maxsplit=1)
    if len(parts) != 2:  # noqa: PLR2004
        logger.warning(
            "schema_name %r is not a dotted module.ClassName path", schema_name
        )
        return None
    module_path, class_name = parts
    try:
        module = importlib.import_module(module_path)
        cls: type[Any] = getattr(module, class_name)
        return cls
    except (ImportError, AttributeError) as exc:
        warnings.warn(
            f"schema_name {schema_name!r} is not importable: {exc}. "
            "Skipping schema validation.",
            stacklevel=2,
        )
        return None


def _get_nested(data: dict[str, Any], field_path: str) -> Any:
    """Resolve a dot-separated field path from a nested dict.

    Args:
        data: The event payload dict.
        field_path: Dot-separated key path (e.g. "payload.status").

    Returns:
        The resolved value, or None if any key is missing.
    """
    parts = field_path.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------


class AssertionEngine:
    """Evaluates a list of assertion declarations against an output event.

    Each assertion dict must have:
      - ``field``: dot-separated path into the event payload
      - ``op``: one of eq, neq, gte, lte, in, contains
      - ``expected``: expected value
      - ``actual``: resolved actual value (injected before calling evaluate_all)

    Returns a list of result dicts (same keys + ``passed`` bool).
    """

    def evaluate_all(self, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Evaluate all assertions.

        Args:
            assertions: List of assertion dicts. Each must have ``field``,
                ``op``, ``expected``, and ``actual`` keys.

        Returns:
            List of result dicts with the same keys plus a ``passed`` bool.
        """
        results: list[dict[str, Any]] = []
        for assertion in assertions:
            result = dict(assertion)
            try:
                result["passed"] = _run_assertion(
                    assertion["op"],
                    assertion.get("actual"),
                    assertion["expected"],
                )
            except (ValueError, TypeError) as exc:
                result["passed"] = False
                result["error"] = str(exc)
            results.append(result)
        return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_DEFAULT_ARTIFACT_BASE_DIR = str(Path.home() / ".claude" / "golden-path")
_DEFAULT_BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "192.168.86.200:29092",  # onex-allow-internal-ip
)


class GoldenPathRunner:
    """Executes a golden path event chain test using real Kafka/Redpanda.

    Workflow:
    1. Warm-subscribe to output topic (before producing — avoids race)
    2. Emit fixture with injected correlation_id to input topic
    3. Poll for matching output event (filtered by correlation_id)
    4. Validate assertions against the event payload
    5. Optionally validate against a Pydantic schema (schema_name)
    6. Write evidence artifact to disk

    Args:
        bootstrap_servers: Kafka bootstrap servers string.
        artifact_base_dir: Base directory for evidence artifacts.
            Defaults to ``~/.claude/golden-path``.
    """

    def __init__(
        self,
        bootstrap_servers: str = _DEFAULT_BOOTSTRAP_SERVERS,
        artifact_base_dir: str = _DEFAULT_ARTIFACT_BASE_DIR,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._artifact_base_dir = Path(artifact_base_dir)
        self._assertion_engine = AssertionEngine()

    async def run(self, decl: dict[str, Any]) -> EvidenceArtifact:
        """Execute the golden path run for the given declaration.

        Args:
            decl: Golden path declaration dict. Required keys:
                - node_id (str)
                - ticket_id (str)
                - input.topic (str)
                - input.fixture (dict)
                - output.topic (str)
                - timeout_ms (int, default 10000)
                - assertions (list[dict])
                Optional:
                - schema_name (str): dotted Pydantic model class

        Returns:
            EvidenceArtifact written to disk.
        """
        run_id = str(uuid4())
        correlation_id = str(uuid4())
        consumer_group_id = f"golden-path-{correlation_id[:8]}"

        node_id: str = decl["node_id"]
        ticket_id: str = decl["ticket_id"]
        input_topic: str = decl["input"]["topic"]
        output_topic: str = decl["output"]["topic"]
        timeout_ms: int = decl.get("timeout_ms", 10_000)
        timeout_s: float = timeout_ms / 1000.0
        assertion_decls: list[dict[str, Any]] = decl.get("assertions", [])
        schema_name: str | None = decl.get("schema_name")

        emitted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        # Build fixture payload with injected correlation_id
        fixture: dict[str, Any] = dict(decl["input"].get("fixture", {}))
        fixture["correlation_id"] = correlation_id

        # Step 1: Warm subscription (subscribe before producing)
        consumer = AIOKafkaConsumer(
            output_topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=consumer_group_id,
            auto_offset_reset="latest",
            enable_auto_commit=False,
        )
        producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
        )

        artifact: EvidenceArtifact
        emit_time: float | None = None

        try:
            await consumer.start()
            await asyncio.sleep(1.0)  # wait for partition assignment

            await producer.start()

            # Step 2: Emit fixture with injected correlation_id
            fixture_bytes = json.dumps(fixture).encode()
            import time as _time

            emit_ns = _time.monotonic()
            await producer.send_and_wait(input_topic, value=fixture_bytes)

            # Step 3: Poll for matching output event
            matched_event: dict[str, Any] | None = None
            kafka_offset: int = -1
            kafka_timestamp_ms: int = -1

            deadline = asyncio.get_event_loop().time() + timeout_s
            timed_out = False

            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    msg = await asyncio.wait_for(
                        consumer.getone(), timeout=min(remaining, 2.0)
                    )
                except TimeoutError:
                    if asyncio.get_event_loop().time() >= deadline:
                        timed_out = True
                        break
                    continue

                try:
                    event_data: dict[str, Any] = json.loads(msg.value)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if event_data.get("correlation_id") == correlation_id:
                    matched_event = event_data
                    kafka_offset = msg.offset
                    kafka_timestamp_ms = msg.timestamp
                    break

            recv_ns = _time.monotonic()
            latency_ms = (recv_ns - emit_ns) * 1000.0

            if timed_out or matched_event is None:
                # Timeout path: artifact with status=timeout
                artifact = self._build_artifact(
                    node_id=node_id,
                    ticket_id=ticket_id,
                    run_id=run_id,
                    emitted_at=emitted_at,
                    status="timeout",
                    input_topic=input_topic,
                    output_topic=output_topic,
                    latency_ms=latency_ms,
                    correlation_id=correlation_id,
                    consumer_group_id=consumer_group_id,
                    schema_validation_status="not_declared",
                    assertions=[],
                    raw_output_preview="",
                    kafka_offset=-1,
                    kafka_timestamp_ms=-1,
                )
                self._write_artifact(artifact)
                return artifact

            # Step 4: Run assertions
            enriched_assertions = [
                {**a, "actual": _get_nested(matched_event, a["field"])}
                for a in assertion_decls
            ]
            assertion_results = self._assertion_engine.evaluate_all(enriched_assertions)
            all_assertions_pass = all(r["passed"] for r in assertion_results)

            # Step 5: Schema validation
            schema_validation_status = _validate_schema(schema_name, matched_event)

            # Determine overall status
            if schema_validation_status == "fail":
                overall_status = "fail"
            elif all_assertions_pass:
                overall_status = "pass"
            else:
                overall_status = "fail"

            raw_preview = json.dumps(matched_event)[:500]

            artifact = self._build_artifact(
                node_id=node_id,
                ticket_id=ticket_id,
                run_id=run_id,
                emitted_at=emitted_at,
                status=overall_status,
                input_topic=input_topic,
                output_topic=output_topic,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
                consumer_group_id=consumer_group_id,
                schema_validation_status=schema_validation_status,
                assertions=assertion_results,
                raw_output_preview=raw_preview,
                kafka_offset=kafka_offset,
                kafka_timestamp_ms=kafka_timestamp_ms,
            )
            self._write_artifact(artifact)
            return artifact

        finally:
            try:
                await consumer.stop()
            except Exception:
                pass
            try:
                await producer.stop()
            except Exception:
                pass

    def _build_artifact(
        self,
        *,
        node_id: str,
        ticket_id: str,
        run_id: str,
        emitted_at: str,
        status: str,
        input_topic: str,
        output_topic: str,
        latency_ms: float,
        correlation_id: str,
        consumer_group_id: str,
        schema_validation_status: str,
        assertions: list[dict[str, Any]],
        raw_output_preview: str,
        kafka_offset: int,
        kafka_timestamp_ms: int,
    ) -> EvidenceArtifact:
        return EvidenceArtifact(
            node_id=node_id,
            ticket_id=ticket_id,
            run_id=run_id,
            emitted_at=emitted_at,
            status=status,
            input_topic=input_topic,
            output_topic=output_topic,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
            consumer_group_id=consumer_group_id,
            schema_validation_status=schema_validation_status,
            assertions=assertions,
            raw_output_preview=raw_output_preview,
            kafka_offset=kafka_offset,
            kafka_timestamp_ms=kafka_timestamp_ms,
        )

    def _write_artifact(self, artifact: EvidenceArtifact) -> None:
        """Write artifact to disk at the canonical path.

        Path: {artifact_base_dir}/{YYYY-MM-DD}/{run_id}/{node_id}.json

        The date component is extracted from artifact.emitted_at.
        """
        date_str = _extract_artifact_date(artifact.emitted_at)
        artifact_dir = self._artifact_base_dir / date_str / artifact.run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{artifact.node_id}.json"
        artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        logger.info(
            "Golden path artifact written: %s (status=%s)",
            artifact_path,
            artifact.status,
        )


# ---------------------------------------------------------------------------
# Schema validation helper (module-level for testability)
# ---------------------------------------------------------------------------


def _validate_schema(schema_name: str | None, event_data: dict[str, Any]) -> str:
    """Validate event_data against the given Pydantic model class name.

    Args:
        schema_name: Fully qualified class name or None.
        event_data: The parsed event payload dict.

    Returns:
        "not_declared" if schema_name is None.
        "skipped" if schema_name is not importable.
        "pass" if model_validate succeeds.
        "fail" if model_validate raises.
    """
    if schema_name is None:
        return "not_declared"

    schema_cls = _import_schema_class(schema_name)
    if schema_cls is None:
        return "skipped"

    try:
        validator = getattr(schema_cls, "model_validate", None)
        if validator is not None:
            validator(event_data)
        else:
            # Fall back for non-Pydantic classes: try direct instantiation
            schema_cls(**event_data)
        return "pass"
    except Exception as exc:
        logger.warning("Schema validation failed for %s: %s", schema_name, exc)
        return "fail"
