# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook cost budget, stated once (OMN-20109).

On 2026-09-29 about 10,000 hung hook processes exhausted the operator Mac's
per-user process limit and stopped every lane. Lane ruling-skill-diag-1810
measured the cost of ONE tool call at about 18 hook processes, 63 hook Python
processes at once across the session, and 60 to 175 s of hook time per tool
call under load. Nothing in CI ran the real hook entrypoints against any
budget, so nothing could have failed.

This file is the record. ``test_hook_call_budget.py`` enforces ``CEILING_*`` and
``test_budget_record`` pins the ratchet: the ceiling may only tighten toward the
target, never loosen past what was measured.

The process counts are a LOWER BOUND: they come from sampling the process table
while the hooks run (see ``_harness.ProcessLedger``), and a process that lives
for less than one sampling interval can be missed. A lower bound is the safe
direction for a ceiling test only when the ceiling is set from the same
instrument, which is why ``CEILING_PROCESSES_PER_TOOL_CALL`` is measured with the
harness and not copied from the incident number.
"""

from __future__ import annotations

# The incident measurement (lane ruling-skill-diag-1810, 2026-09-29).
MEASURED_PROCESSES_PER_TOOL_CALL = 18
MEASURED_HOOK_PYTHONS_AT_ONCE = 63
MEASURED_HOOK_SECONDS_PER_TOOL_CALL_UNDER_LOAD = (60, 175)

# The target the hook edge is held to. A ceiling above this is debt.
TARGET_PROCESSES_PER_TOOL_CALL = 8

# The enforced ceiling. Starts at the measurement and only ever moves down.
CEILING_PROCESSES_PER_TOOL_CALL = 18

# Wall time budgets, seconds. Claude Code gives a hook 60 s before it cancels it,
# and a tool call that spends 60 s in hooks is the incident. These are set an
# order of magnitude under that on an idle host.
BUDGET_SECONDS_PER_HOOK = 5.0
BUDGET_SECONDS_PER_TOOL_CALL = 10.0
# 40 hooks at once, so the per-hook wall time stretches with contention. Still
# far under the 60 s harness cancel.
BUDGET_SECONDS_PER_HOOK_UNDER_CONCURRENCY = 20.0

# After every hook has exited, nothing the hooks started may still be running
# once this many seconds have passed. Detached children are allowed to finish
# their work, not to hang.
SETTLE_SECONDS = 15.0

# A hook with a broken emit path must give up and say so inside this window.
BUDGET_SECONDS_BROKEN_EMIT = 10.0

# Concurrency width for the parallel test.
CONCURRENT_INVOCATIONS = 40
