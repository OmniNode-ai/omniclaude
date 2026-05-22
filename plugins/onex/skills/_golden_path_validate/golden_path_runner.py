# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Golden path wire schema validation helpers.

Provides EvidenceArtifact, AssertionEngine, _validate_wire_schema, and
_validate_schema for use by golden path test infrastructure.

GoldenPathRunner was removed (zero importers; depended on deleted shared_lib).
"""

from __future__ import annotations

import importlib
import logging
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evidence Artifact model
# ---------------------------------------------------------------------------


class EvidenceArtifact(BaseModel):
    """Unsigned evidence artifact written after each golden-path run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str = Field(..., description="Identifier for the node under test")
    ticket_id: str = Field(..., description="Linear ticket ID (e.g. OMN-2976)")
    run_id: str = Field(..., description="Unique run identifier (uuid4-based)")
    emitted_at: str = Field(
        ..., description="ISO-8601 timestamp when fixture was emitted"
    )
    status: str = Field(
        ..., description="Overall result: pass | fail | timeout | error"
    )
    error_reason: str | None = Field(
        default=None,
        description="Machine-readable error reason when status=error",
    )
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
    wire_schema_validation_status: str = Field(
        default="not_declared",
        description="pass | fail | skipped | not_declared — wire schema contract validation (OMN-7374)",
    )
    wire_schema_mismatches: list[dict[str, str]] = Field(
        default_factory=list,
        description="Field-level wire schema mismatches: [{field, detail}]",
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
    """Extract YYYY-MM-DD from an ISO-8601 emitted_at string."""
    if len(emitted_at) >= 10 and emitted_at[4] == "-" and emitted_at[7] == "-":  # noqa: PLR2004
        date_part = emitted_at[:10]
        if len(date_part) == 10 and date_part.count("-") == 2:  # noqa: PLR2004
            try:
                datetime.fromisoformat(emitted_at.replace("Z", "+00:00"))
                return date_part
            except (ValueError, AttributeError):
                pass
    logger.warning("Could not parse emitted_at=%r; falling back to today", emitted_at)
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _run_assertion(op: str, actual: Any, expected: Any) -> bool:
    """Evaluate a single assertion."""
    result: bool = False
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
    """Attempt to import a Pydantic model class by dotted name."""
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
    """Resolve a dot-separated field path from a nested dict."""
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
    """Evaluates a list of assertion declarations against an output event."""

    def evaluate_all(self, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Evaluate all assertions."""
        results: list[dict[str, Any]] = []
        for assertion in assertions:
            result = dict(assertion)
            if assertion.get("op") == "wire_schema_match":
                status, mismatches = _validate_wire_schema(
                    assertion.get("contract_path"),
                    assertion.get("event_data", {}),
                )
                result["passed"] = status == "pass"
                result["wire_schema_status"] = status
                result["wire_schema_mismatches"] = mismatches
                if mismatches:
                    result["error"] = "; ".join(m["detail"] for m in mismatches)
            else:
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
# Schema validation helpers (module-level for testability)
# ---------------------------------------------------------------------------


def _validate_wire_schema(
    contract_path: str | None, event_data: dict[str, Any]
) -> tuple[str, list[dict[str, str]]]:
    """Validate event_data against a wire schema contract YAML (OMN-7374)."""
    if contract_path is None:
        return "not_declared", []

    path = Path(contract_path)
    if not path.exists():
        logger.warning(
            "Wire schema contract not found: %s; skipping validation", contract_path
        )
        return "skipped", []

    try:
        import yaml

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning("Wire schema contract is not a dict: %s", contract_path)
            return "skipped", []
    except Exception as exc:
        logger.warning("Failed to load wire schema contract %s: %s", contract_path, exc)
        return "skipped", []

    required_fields = data.get("required_fields", [])
    if not required_fields:
        logger.warning("Wire schema contract has no required_fields: %s", contract_path)
        return "skipped", []

    renamed_fields = data.get("renamed_fields", [])
    active_renames: dict[str, str] = {}
    for rf in renamed_fields:
        if isinstance(rf, dict) and rf.get("shim_status") == "active":
            active_renames[rf["producer_name"]] = rf["canonical_name"]

    canonical_to_aliases: dict[str, set[str]] = {}
    for producer_name, canonical_name in active_renames.items():
        canonical_to_aliases.setdefault(canonical_name, set()).add(producer_name)

    mismatches: list[dict[str, str]] = []
    event_keys = set(event_data.keys())

    for field_def in required_fields:
        if not isinstance(field_def, dict):
            continue
        field_name = field_def.get("name", "")
        if not field_name:
            continue

        if field_name in event_keys:
            continue

        aliases = canonical_to_aliases.get(field_name, set())
        if aliases & event_keys:
            continue

        mismatches.append(
            {
                "field": field_name,
                "detail": (
                    f"Required field '{field_name}' declared in wire schema contract "
                    f"but missing from event payload"
                ),
            }
        )

    if mismatches:
        return "fail", mismatches
    return "pass", []


def _validate_schema(schema_name: str | None, event_data: dict[str, Any]) -> str:
    """Validate event_data against the given Pydantic model class name."""
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
            schema_cls(**event_data)
        return "pass"
    except Exception as exc:
        logger.warning("Schema validation failed for %s: %s", schema_name, exc)
        return "fail"
