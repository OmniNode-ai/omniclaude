# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook measurement harness (OMN-13278).

A read-only analytics surface that compares the cost/latency/outcome impact of
the omniclaude hook surface in two windows: ``hooks-off`` (the OMN-13244
baseline, where ``hooks.json`` is gutted) and ``hooks-on`` (any window where the
hook registrations are restored).

The harness deliberately reads **existing** telemetry surfaces rather than
introducing a new collection path:

* ``cost_records`` SQLite table (``$ONEX_STATE_DIR/hooks/cost_accounting.db``)
  written by the PostToolUse cost-accounting hook (OMN-10619) — gives per
  tool-call token counts and USD cost, tagged with ``session_id``.
* The PRM trajectory log (``$ONEX_STATE_DIR/hooks/logs/post-tool-use-trajectory.log``)
  and per-hook JSONL logs under ``$ONEX_STATE_DIR/hooks/logs/`` — give per
  tool-call timing and injection/escalation evidence (OMN-10370).

No bespoke REST endpoint is added. Window labelling is supplied by the caller
(the operator records the wall-clock boundary at which hooks were toggled), and
the canonical ``onex.evt.omniclaude.tool-executed.v1`` event stream remains the
authoritative downstream surface for any bus-side rollup.

Public API:
    * :class:`EnumHookWindow` — the two measurement windows.
    * :class:`ModelToolCallRecord` — one normalized tool-call observation.
    * :class:`ModelWindowMetrics` — aggregate metrics for one window.
    * :class:`ModelHookComparison` — the hooks-off vs hooks-on delta.
    * :func:`load_cost_records` — read normalized records from the cost DB.
    * :func:`aggregate_window` — roll records up into window metrics.
    * :func:`compare_windows` — produce the off-vs-on comparison.
"""

from __future__ import annotations

from omniclaude.hook_measurement.enums import EnumHookWindow, EnumTokenProvenance
from omniclaude.hook_measurement.metrics import (
    aggregate_window,
    compare_windows,
    load_cost_records,
)
from omniclaude.hook_measurement.models import (
    ModelHookComparison,
    ModelToolCallRecord,
    ModelWindowMetrics,
)

__all__ = [
    "EnumHookWindow",
    "EnumTokenProvenance",
    "ModelHookComparison",
    "ModelToolCallRecord",
    "ModelWindowMetrics",
    "aggregate_window",
    "compare_windows",
    "load_cost_records",
]
