# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook cost budget, stated once (OMN-20109).

On 2026-09-29 about 10,000 hung hook processes exhausted the operator Mac's
per-user process limit and stopped every lane. Lane ruling-skill-diag-1810
measured the cost of ONE tool call at about 18 hook processes ALIVE AT ONCE, 63
hook Python processes at once across the session, and 60 to 175 s of hook time
per tool call under load. Nothing in CI ran the real hook entrypoints against
any budget, so nothing could have failed.

That measurement was a ``ps`` snapshot, and a snapshot undercounts a fork storm:
most hook processes live for milliseconds and are gone before the snapshot. The
metric this suite enforces is the one that drives the per-user process limit and
the fork rate, the number of processes a tool call EXECS, counted exactly for
everything the hooks start by name (PATH shims, see ``_harness._install_shims``)
plus the sampled tree. Measured with that instrument on 2026-09-29 the same
tool calls (Bash, Skill, Read) start 250, 151 and 83 processes on dev and 261, 167 and 91 with the fail-loud emit, an order of magnitude over the
snapshot number. Both are recorded here.

``test_hook_call_budget.py`` enforces ``CEILING_EXECS_PER_CALL`` and
``test_budget_record_only_ratchets_down`` pins the ratchet: a ceiling may only
tighten toward the target, never loosen past what was measured. Lower a ceiling
in the same change that lowers the cost.
"""

from __future__ import annotations

# The incident measurement (lane ruling-skill-diag-1810, 2026-09-29): a snapshot
# of processes alive at one moment. Recorded, not enforced: it is a different,
# weaker instrument than the exec count below.
INCIDENT_CONCURRENT_HOOK_PROCESSES_PER_CALL = 18
INCIDENT_HOOK_PYTHONS_AT_ONCE = 63
INCIDENT_HOOK_SECONDS_PER_CALL_UNDER_LOAD = (60, 175)

# What this harness measured on 2026-09-29 (lab host, sha at the head of the
# branch that added it, idle host): processes EXECED by the hooks of one whole
# tool call, PreToolUse phase plus PostToolUse phase.
# OMN-20114 (2026-09-29, lab h202, three runs each, highest kept): the hooks'
# path preamble became parameter expansions and each payload is read with one
# jq, which took the same calls from 261 / 166 / 90 on dev to 109 / 81 / 44.
# OMN-20118 (2026-09-30, lab h202, three runs each, highest kept): the seven
# Bash guards run from one entrypoint (one bash, at most one interpreter) and a
# bounded emit forks its writer: 109 / 81 / 44 to 91 / 74 / 44.
MEASURED_EXECS_PER_CALL = {"Bash": 91, "Skill": 74, "Read": 44}
# History of this instrument: 250 / 151 / 83 on dev before the OMN-20110
# foreground runner; 261 / 167 / 91 with it (the bounded runner's own
# interpreter start plus one process group per emit, paid to make every emit
# fail loudly instead of hanging); 109 / 81 / 44 after OMN-20114.

# The enforced ceiling, per tool. Measured plus a small headroom for the
# branches a hook takes only sometimes. It only ever moves down.
CEILING_EXECS_PER_CALL = {"Bash": 103, "Skill": 82, "Read": 50}

# The target every tool call is held to. A ceiling above this is debt. After
# OMN-20114 the remaining cost is one bash per registered hook (17 on a Bash
# call), about ten python interpreter starts per Bash call (the bounded emit
# runner plus the writer it starts, per emit) and the payload reads that remain;
# one entrypoint per event and a runner that does not start a second
# interpreter are what is left between here and the target.
TARGET_EXECS_PER_CALL = 60

# Python interpreter starts per tool call, by the shapes of
# tests/hooks_system/wall.py. After OMN-20114 these, not execs, were the wall
# time: 0.2 to 0.85 s each on the operator Mac idle, 5 to 8 s under contention.
# OMN-20118 (2026-09-30, lab h202, deterministic across runs): one interpreter
# for the seven Bash guards' decision cores, and every bounded emit forks its
# writer instead of starting a second interpreter.
PYTHON_STARTS_BEFORE_OMN_20118 = {
    "bash": 10,
    "bash-guarded": 17,
    "skill": 17,
    "read": 8,
}
CEILING_PYTHON_STARTS_PER_CALL = {"bash": 6, "bash-guarded": 7, "skill": 10, "read": 4}

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

# The longest a hook may wait on an emit before it must fail loudly. Operator
# ruling 2026-09-29: about 30 seconds ("we can titrate it because we can see
# errors"). Claude Code cancels a hook at 60 s, so a default above this ceiling
# can be cancelled by the harness before the hook reports anything.
EMIT_BUDGET_CEILING_SECONDS = 30.0
