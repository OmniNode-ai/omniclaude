# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLI entrypoint for the hook measurement harness (OMN-13278).

Usage::

    python -m omniclaude.hook_measurement.cli \\
        --boundary 2026-06-18T17:00:00Z \\
        [--state-dir $ONEX_STATE_DIR] \\
        [--json]

The ``--boundary`` is the wall-clock instant at which the hook surface was
toggled from off to on (the operator records this when re-registering hooks).
Records before the boundary form the hooks-off (OMN-13244 baseline) window;
records at or after it form the hooks-on window. Output is a human-readable
table by default, or a JSON dump of :class:`ModelHookComparison` with ``--json``.

This reads only existing telemetry surfaces (the cost-accounting SQLite DB and
the PRM trajectory store). It never writes, deploys, or mutates anything.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from omniclaude.hook_measurement.enums import EnumHookWindow
from omniclaude.hook_measurement.metrics import (
    aggregate_window,
    compare_windows,
    load_cost_records,
    split_by_boundary,
)
from omniclaude.hook_measurement.models import ModelHookComparison
from omniclaude.hook_measurement.trajectory import parse_latency_by_session_tool

_COST_DB_RELPATH = ("hooks", "cost_accounting.db")
_TRAJECTORY_RELPATH = ("hooks", "logs", "post-tool-use-trajectory.jsonl")


def _resolve_state_dir(explicit: str | None) -> Path:
    raw = explicit or os.environ.get("ONEX_STATE_DIR", "")
    if not raw.strip():
        msg = "ONEX_STATE_DIR is not set; pass --state-dir explicitly."
        raise SystemExit(msg)
    return Path(raw).expanduser().resolve()


def build_comparison(
    state_dir: Path,
    boundary: datetime,
) -> ModelHookComparison:
    """Load telemetry, split about ``boundary``, and compare the two windows."""
    cost_db = state_dir.joinpath(*_COST_DB_RELPATH)
    trajectory = state_dir.joinpath(*_TRAJECTORY_RELPATH)
    latency_map = parse_latency_by_session_tool(trajectory)
    records = load_cost_records(cost_db, latency_by_session_tool=latency_map)
    off_records, on_records = split_by_boundary(records, boundary)
    off_metrics = aggregate_window(EnumHookWindow.HOOKS_OFF, off_records)
    on_metrics = aggregate_window(EnumHookWindow.HOOKS_ON, on_records)
    return compare_windows(off_metrics, on_metrics)


def _format_table(comparison: ModelHookComparison) -> str:
    off = comparison.hooks_off
    on = comparison.hooks_on
    lines = [
        "Hook measurement comparison (OMN-13278)",
        "=" * 48,
        f"{'metric':<28}{'hooks_off':>10}{'hooks_on':>10}",
        f"{'tool calls':<28}{off.tool_call_count:>10}{on.tool_call_count:>10}",
        f"{'turns (sessions)':<28}{off.turn_count:>10}{on.turn_count:>10}",
        f"{'tokens/turn':<28}{off.mean_tokens_per_turn:>10.1f}{on.mean_tokens_per_turn:>10.1f}",
        f"{'tokens/call':<28}{off.mean_tokens_per_call:>10.1f}{on.mean_tokens_per_call:>10.1f}",
        f"{'delegated calls':<28}{off.delegated_call_count:>10}{on.delegated_call_count:>10}",
        "-" * 48,
        f"tokens/turn delta (on-off): {comparison.tokens_per_turn_delta:+.1f}",
    ]
    if comparison.tokens_per_turn_ratio is not None:
        lines.append(
            f"tokens/turn ratio (on/off): {comparison.tokens_per_turn_ratio:.3f}"
        )
    if comparison.latency_per_call_delta_ms is not None:
        lines.append(
            f"latency/call delta (on-off): {comparison.latency_per_call_delta_ms:+.1f} ms"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse args, build the comparison, and print it."""
    parser = argparse.ArgumentParser(
        prog="omniclaude.hook_measurement.cli",
        description="Compare hooks-off vs hooks-on telemetry windows (OMN-13278).",
    )
    parser.add_argument(
        "--boundary",
        required=True,
        help="ISO-8601 toggle instant; records before it are hooks-off.",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override ONEX_STATE_DIR (defaults to the env var).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the comparison as JSON instead of a table.",
    )
    args = parser.parse_args(argv)

    boundary = datetime.fromisoformat(args.boundary.replace("Z", "+00:00"))
    state_dir = _resolve_state_dir(args.state_dir)
    comparison = build_comparison(state_dir, boundary)

    if args.json:
        sys.stdout.write(comparison.model_dump_json(indent=2) + "\n")
    else:
        sys.stdout.write(_format_table(comparison) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
