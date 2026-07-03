# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Parse the PRM trajectory store for per tool-call timing (OMN-13278).

The PostToolUse trajectory hook (OMN-10370) appends one JSON object per tool
call to a JSONL trajectory store under ``$ONEX_STATE_DIR``. Each line carries at
least ``session_id``, ``tool_name``, and a monotonically increasing
``timestamp``. Inter-call latency is reconstructed as the wall-clock gap between
consecutive calls within the same session — a proxy for "latency per tool-call"
that requires no new instrumentation.

The parser is defensive: malformed lines are skipped, and a missing store yields
an empty mapping. It never raises on bad telemetry.
"""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

_TIMESTAMP_KEYS = ("timestamp", "ts", "recorded_at", "emitted_at")


def _extract_epoch(entry: dict[str, object]) -> float | None:
    """Return a float epoch-seconds timestamp from a trajectory entry."""
    for key in _TIMESTAMP_KEYS:
        value = entry.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                from datetime import datetime  # noqa: PLC0415

                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def parse_latency_by_session_tool(
    trajectory_path: Path,
) -> dict[tuple[str, str], float]:
    """Reconstruct mean inter-call latency keyed by ``(session_id, tool_name)``.

    Args:
        trajectory_path: Path to the JSONL trajectory store. A missing file
            yields an empty mapping.

    Returns:
        Mapping of ``(session_id, tool_name)`` to mean latency in milliseconds.
        Only sessions with at least two timestamped calls contribute.
    """
    if not trajectory_path.exists():
        return {}

    # Per session: ordered list of (epoch_seconds, tool_name).
    by_session: dict[str, list[tuple[float, str]]] = defaultdict(list)
    with trajectory_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            session_id = entry.get("session_id")
            tool_name = entry.get("tool_name")
            epoch = _extract_epoch(entry)
            if not isinstance(session_id, str) or not isinstance(tool_name, str):
                continue
            if epoch is None:
                continue
            by_session[session_id].append((epoch, tool_name))

    # Sum of gaps and counts keyed by (session, tool) — gap is attributed to the
    # call that *completes* the gap (the later call).
    gap_sums: dict[tuple[str, str], float] = defaultdict(float)
    gap_counts: dict[tuple[str, str], int] = defaultdict(int)
    for session_id, calls in by_session.items():
        calls.sort(key=lambda item: item[0])
        for (prev_epoch, _prev_tool), (cur_epoch, cur_tool) in pairwise(calls):
            delta_ms = max(0.0, (cur_epoch - prev_epoch) * 1000.0)
            key = (session_id, cur_tool)
            gap_sums[key] += delta_ms
            gap_counts[key] += 1

    return {
        key: gap_sums[key] / gap_counts[key] for key in gap_sums if gap_counts[key] > 0
    }
