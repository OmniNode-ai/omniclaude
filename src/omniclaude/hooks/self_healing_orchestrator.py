# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Self-healing orchestration wrapper (OMN-7259, Workstream B Phase 3).

Combines Phase 1 stall recovery (agent_healthcheck) with Phase 2 dispatch
enforcement (dispatch-mode guardrail) into a single orchestration entrypoint.

Responsibilities:
- Accept a list of ticket IDs or an epic ID
- Group tickets by repo
- Dispatch via TeamCreate (enforced, not suggested)
- Monitor workers; auto-recover stalls (max 2 redispatches per task)
- Log all events to $ONEX_STATE_DIR/dispatch-log/{YYYY-MM-DD}.ndjson

All public functions are pure or I/O-isolated. Logging is best-effort — it
never raises to callers.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TICKET_PATTERN: Final[re.Pattern[str]] = re.compile(r"\bOMN-(\d+)\b")

# Canonical repo names from the OmniNode registry (CLAUDE.md § Repository Registry).
REGISTRY_REPOS: Final[frozenset[str]] = frozenset(
    {
        "omniclaude",
        "omnibase_core",
        "omnibase_infra",
        "omnibase_spi",
        "omnidash",
        "omnigemini",
        "omniintelligence",
        "omnimemory",
        "omninode_infra",
        "omnimarket",
        "omniweb",
        "onex_change_control",
        "omnibase_compat",
    }
)

MAX_REDISPATCHES: Final[int] = 2
_UNASSIGNED_REPO: Final[str] = "unassigned"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TicketRef:
    """A parsed ticket reference with an optional repo hint."""

    ticket_id: str
    repo: str = _UNASSIGNED_REPO

    def __post_init__(self) -> None:
        if not _TICKET_PATTERN.fullmatch(self.ticket_id):
            raise ValueError(f"Invalid ticket ID: {self.ticket_id!r}")
        if self.repo not in REGISTRY_REPOS and self.repo != _UNASSIGNED_REPO:
            raise ValueError(f"Unknown repo: {self.repo!r}")


@dataclass
class DispatchGroup:
    """All tickets destined for one repo."""

    repo: str
    tickets: list[TicketRef] = field(default_factory=list)
    redispatch_counts: dict[str, int] = field(default_factory=dict)

    def increment_redispatch(self, ticket_id: str) -> int:
        count = self.redispatch_counts.get(ticket_id, 0) + 1
        self.redispatch_counts[ticket_id] = count
        return count


@dataclass(frozen=True)
class OrchestratorResult:
    """Summary returned after an orchestration run."""

    run_id: str
    epic_id: str | None
    groups: list[DispatchGroup]
    total_tickets: int
    stalls_recovered: int
    escalated: list[str]  # ticket IDs that exceeded max redispatches
    log_path: str


# ---------------------------------------------------------------------------
# Ticket grouping
# ---------------------------------------------------------------------------


def parse_ticket_ids(raw: list[str]) -> list[TicketRef]:
    """Validate and convert raw strings like 'OMN-1234' into TicketRef objects."""
    refs: list[TicketRef] = []
    for item in raw:
        item = item.strip()
        if _TICKET_PATTERN.fullmatch(item):
            refs.append(TicketRef(ticket_id=item))
        else:
            raise ValueError(f"Not a valid ticket ID: {item!r}")
    return refs


def group_by_repo(
    tickets: list[TicketRef],
    repo_hints: dict[str, str] | None = None,
) -> list[DispatchGroup]:
    """Assign tickets to repo groups.

    repo_hints maps ticket_id -> repo name for callers who already know the
    target repo. Tickets without a hint land in the ``unassigned`` group.
    """
    hints = repo_hints or {}
    buckets: dict[str, list[TicketRef]] = defaultdict(list)

    for ref in tickets:
        repo = hints.get(ref.ticket_id, ref.repo)
        if repo not in REGISTRY_REPOS:
            repo = _UNASSIGNED_REPO
        buckets[repo].append(TicketRef(ticket_id=ref.ticket_id, repo=repo))

    return [
        DispatchGroup(repo=repo, tickets=refs) for repo, refs in sorted(buckets.items())
    ]


# ---------------------------------------------------------------------------
# Dispatch enforcement
# ---------------------------------------------------------------------------


def build_team_dispatch_prompt(group: DispatchGroup, epic_id: str | None) -> str:
    """Return the prompt string for a TeamCreate worker targeting one repo group."""
    ticket_list = ", ".join(t.ticket_id for t in group.tickets)
    epic_clause = f" (epic: {epic_id})" if epic_id else ""
    return (
        f"Work the following tickets in repo {group.repo}{epic_clause}: {ticket_list}. "
        "Use /onex:ticket_pipeline for each ticket. "
        "Report completion for each ticket with dod_evidence before exiting."
    )


def build_stall_recovery_prompt(
    group: DispatchGroup,
    stalled_ticket_id: str,
    attempt: int,
    completed_tickets: list[str],
) -> str:
    """Return the narrowed-scope prompt for a stall-recovery redispatch."""
    remaining = [
        t.ticket_id for t in group.tickets if t.ticket_id not in completed_tickets
    ]
    return (
        f"Recovery redispatch #{attempt} for {stalled_ticket_id} in repo {group.repo}. "
        f"Remaining tickets (do ONLY these): {', '.join(remaining)}. "
        "Do NOT redo already-completed tickets. "
        "If stuck on the same step again, write a diagnosis doc under "
        "$ONEX_STATE_DIR/friction/ and stop."
    )


# ---------------------------------------------------------------------------
# Stall detection helpers
# ---------------------------------------------------------------------------


def exceeds_max_redispatches(group: DispatchGroup, ticket_id: str) -> bool:
    return group.redispatch_counts.get(ticket_id, 0) > MAX_REDISPATCHES


# ---------------------------------------------------------------------------
# Structured event logging
# ---------------------------------------------------------------------------


def _log_dir() -> Path:
    state_dir = os.environ.get("ONEX_STATE_DIR")
    if state_dir:
        return Path(state_dir) / "dispatch-log"
    return Path.home() / ".onex_state" / "dispatch-log"


def _log_file() -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return _log_dir() / f"{today}.ndjson"


def log_event(event: str, **fields: object) -> None:
    """Append one NDJSON event to the daily dispatch log. Best-effort; never raises."""
    try:
        log_file = _log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        entry: dict[str, object] = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "event": event,
            **fields,
        }
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except (OSError, TypeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Orchestration entry point
# ---------------------------------------------------------------------------


def orchestrate(
    ticket_ids: list[str],
    *,
    epic_id: str | None = None,
    repo_hints: dict[str, str] | None = None,
    run_id: str | None = None,
) -> OrchestratorResult:
    """Plan a self-healing orchestration run and return a structured result.

    This function performs the planning phase only (grouping + log emission).
    Actual TeamCreate dispatch and monitoring happen in the caller (the skill
    entrypoint or orchestration layer), which calls the helpers above.

    Args:
        ticket_ids: Raw ticket ID strings, e.g. ["OMN-1234", "OMN-5678"].
        epic_id: Optional Linear epic ID to include in worker prompts.
        repo_hints: Optional mapping of ticket_id -> repo name.
        run_id: Unique run identifier for correlation. Auto-generated if absent.

    Returns:
        OrchestratorResult with the planned dispatch groups and log path.
    """
    effective_run_id = run_id or _generate_run_id()
    tickets = parse_ticket_ids(ticket_ids)
    if not tickets:
        log_event(
            "orchestration_rejected",
            run_id=effective_run_id,
            epic_id=epic_id,
            reason="no_ticket_ids",
        )
        raise ValueError("No ticket IDs provided for orchestration")

    groups = group_by_repo(tickets, repo_hints)

    log_event(
        "orchestration_planned",
        run_id=effective_run_id,
        epic_id=epic_id,
        ticket_count=len(tickets),
        group_count=len(groups),
        repos=[g.repo for g in groups],
    )

    return OrchestratorResult(
        run_id=effective_run_id,
        epic_id=epic_id,
        groups=groups,
        total_tickets=len(tickets),
        stalls_recovered=0,
        escalated=[],
        log_path=str(_log_file()),
    )


def record_stall_recovery(
    group: DispatchGroup,
    ticket_id: str,
    run_id: str,
    completed_tickets: list[str],
) -> tuple[bool, int]:
    """Record a stall and decide whether to redispatch or escalate.

    Returns ``(should_redispatch, attempt_number)``. ``should_redispatch``
    is False when the ticket has exceeded MAX_REDISPATCHES.
    """
    attempt = group.increment_redispatch(ticket_id)
    if attempt > MAX_REDISPATCHES:
        log_event(
            "escalated_to_blocked",
            run_id=run_id,
            ticket_id=ticket_id,
            attempt_count=attempt,
        )
        return False, attempt

    log_event(
        "stall_recovery_dispatched",
        run_id=run_id,
        ticket_id=ticket_id,
        redispatch_attempt=attempt,
        max_redispatches=MAX_REDISPATCHES,
        completed_tickets=completed_tickets,
    )
    return True, attempt


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_run_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"orch-{ts}-{uuid4().hex[:8]}"


__all__ = [
    "REGISTRY_REPOS",
    "MAX_REDISPATCHES",
    "TicketRef",
    "DispatchGroup",
    "OrchestratorResult",
    "parse_ticket_ids",
    "group_by_repo",
    "build_team_dispatch_prompt",
    "build_stall_recovery_prompt",
    "exceeds_max_redispatches",
    "log_event",
    "orchestrate",
    "record_stall_recovery",
]
