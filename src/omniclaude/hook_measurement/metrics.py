# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read + aggregate logic for the hook measurement harness (OMN-13278).

All functions here are pure with respect to their inputs: the only I/O is the
read-only open of the cost-accounting SQLite DB in :func:`load_cost_records`.
Aggregation and comparison operate on in-memory record lists so they are fully
unit-testable without any telemetry surface present.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from omniclaude.hook_measurement.enums import EnumHookWindow, EnumTokenProvenance
from omniclaude.hook_measurement.models import (
    ModelHookComparison,
    ModelToolCallRecord,
    ModelWindowMetrics,
)

# Columns selected from the cost_records table (OMN-10619 schema).
_COST_COLUMNS = (
    "recorded_at",
    "session_id",
    "tool_name",
    "is_delegated",
    "input_tokens",
    "output_tokens",
    "token_provenance",
    "actual_cost_usd",
    "baseline_cost_usd",
)


def _parse_recorded_at(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z``."""
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _coerce_provenance(raw: str | None) -> EnumTokenProvenance:
    if raw in (EnumTokenProvenance.MEASURED, EnumTokenProvenance.ESTIMATED):
        return EnumTokenProvenance(raw)
    return EnumTokenProvenance.UNKNOWN


def load_cost_records(
    db_path: Path,
    *,
    latency_by_session_tool: dict[tuple[str, str], float] | None = None,
) -> list[ModelToolCallRecord]:
    """Read normalized tool-call records from the cost-accounting SQLite DB.

    Args:
        db_path: Path to ``cost_accounting.db``. A missing file yields ``[]``
            (the surface is optional; absence is not an error).
        latency_by_session_tool: Optional mapping of ``(session_id, tool_name)``
            to a representative latency in ms, joined from the trajectory log.

    Returns:
        Records ordered by ``recorded_at`` ascending.
    """
    if not db_path.exists():
        return []

    latency_map = latency_by_session_tool or {}
    columns = ", ".join(_COST_COLUMNS)
    # Read-only connection; never mutate the live telemetry DB. This is a
    # read-only adapter bootstrap over an external on-disk telemetry surface
    # (the cost-accounting hook's DB), not an injectable repository.
    uri = f"file:{db_path}?mode=ro"
    records: list[ModelToolCallRecord] = []
    with sqlite3.connect(uri, uri=True) as conn:  # di-ok
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            f"SELECT {columns} FROM cost_records ORDER BY recorded_at ASC"  # noqa: S608
        ):
            session_id = row["session_id"]
            tool_name = row["tool_name"]
            latency = None
            if session_id is not None:
                latency = latency_map.get((session_id, tool_name))
            records.append(
                ModelToolCallRecord(
                    recorded_at=_parse_recorded_at(row["recorded_at"]),
                    session_id=session_id,
                    tool_name=tool_name,
                    is_delegated=bool(row["is_delegated"]),
                    input_tokens=int(row["input_tokens"] or 0),
                    output_tokens=int(row["output_tokens"] or 0),
                    token_provenance=_coerce_provenance(row["token_provenance"]),
                    actual_cost_usd=float(row["actual_cost_usd"] or 0.0),
                    baseline_cost_usd=float(row["baseline_cost_usd"] or 0.0),
                    latency_ms=latency,
                )
            )
    return records


def split_by_boundary(
    records: Sequence[ModelToolCallRecord],
    boundary: datetime,
) -> tuple[list[ModelToolCallRecord], list[ModelToolCallRecord]]:
    """Partition records into (hooks_off, hooks_on) about a toggle boundary.

    Records strictly before ``boundary`` are the hooks-off window (the
    OMN-13244 baseline); records at or after ``boundary`` are hooks-on.
    """
    off: list[ModelToolCallRecord] = []
    on: list[ModelToolCallRecord] = []
    for record in records:
        if record.recorded_at < boundary:
            off.append(record)
        else:
            on.append(record)
    return off, on


def aggregate_window(
    window: EnumHookWindow,
    records: Sequence[ModelToolCallRecord],
) -> ModelWindowMetrics:
    """Roll a list of tool-call records up into window metrics."""
    count = len(records)
    if count == 0:
        return ModelWindowMetrics(
            window=window,
            tool_call_count=0,
            turn_count=0,
            total_tokens=0,
            total_cost_usd=0.0,
            mean_tokens_per_call=0.0,
            mean_tokens_per_turn=0.0,
            mean_latency_ms=None,
            delegated_call_count=0,
            measured_token_fraction=0.0,
        )

    total_tokens = sum(r.total_tokens for r in records)
    total_cost = sum(r.actual_cost_usd for r in records)
    sessions = {r.session_id for r in records if r.session_id is not None}
    turn_count = len(sessions)
    delegated = sum(1 for r in records if r.is_delegated)
    measured = sum(
        1 for r in records if r.token_provenance is EnumTokenProvenance.MEASURED
    )
    latencies = [r.latency_ms for r in records if r.latency_ms is not None]
    mean_latency = sum(latencies) / len(latencies) if latencies else None

    return ModelWindowMetrics(
        window=window,
        tool_call_count=count,
        turn_count=turn_count,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        mean_tokens_per_call=total_tokens / count,
        # Divide by sessions when known; fall back to call count as a
        # conservative per-turn proxy when no session ids were resolved.
        mean_tokens_per_turn=total_tokens / turn_count
        if turn_count
        else total_tokens / count,
        mean_latency_ms=mean_latency,
        delegated_call_count=delegated,
        measured_token_fraction=measured / count,
    )


def _ratio(on: float, off: float) -> float | None:
    return on / off if off else None


def _fraction(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def compare_windows(
    hooks_off: ModelWindowMetrics,
    hooks_on: ModelWindowMetrics,
) -> ModelHookComparison:
    """Produce the hooks-off vs hooks-on comparison object."""
    latency_delta: float | None = None
    if hooks_off.mean_latency_ms is not None and hooks_on.mean_latency_ms is not None:
        latency_delta = hooks_on.mean_latency_ms - hooks_off.mean_latency_ms

    return ModelHookComparison(
        hooks_off=hooks_off,
        hooks_on=hooks_on,
        tokens_per_turn_delta=(
            hooks_on.mean_tokens_per_turn - hooks_off.mean_tokens_per_turn
        ),
        tokens_per_turn_ratio=_ratio(
            hooks_on.mean_tokens_per_turn, hooks_off.mean_tokens_per_turn
        ),
        tokens_per_call_delta=(
            hooks_on.mean_tokens_per_call - hooks_off.mean_tokens_per_call
        ),
        latency_per_call_delta_ms=latency_delta,
        delegated_fraction_off=_fraction(
            hooks_off.delegated_call_count, hooks_off.tool_call_count
        ),
        delegated_fraction_on=_fraction(
            hooks_on.delegated_call_count, hooks_on.tool_call_count
        ),
    )
