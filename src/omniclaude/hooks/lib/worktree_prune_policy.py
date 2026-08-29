# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Ticket-close-keyed worktree prune policy [OMN-16901].

Pruning is keyed to the **TICKET CLOSING**, not to a PR merging. A ticket spans
multiple PRs and OCC companions, and worktrees are keyed by ticket directory
(``omni_worktrees/<OMN-XXXX>/<repo>``), so a PR merge is an *input to the safety
check* — it is what makes the tree-diff against ``dev`` empty — while ticket
completion is what *fires* eligibility.

The predicate is therefore two-part, and the two halves are evaluated in order:

1. :func:`is_prune_eligible` — **the trigger.** The worktree's ticket resolves to
   a ticket in a terminal state (``Done`` / ``Canceled``), or, when that state
   cannot be resolved, the rolling work ledger shows a ``TERMINAL`` row for the
   ticket with no newer open ``CLAIM``. A ticket still open or In Progress is
   **never** prune-eligible, however clean its worktree looks.
2. :func:`is_prune_safe` — **the gate**, applied only after eligibility passes.
   Working tree clean, nothing unmerged ahead of the base branch, no stash
   attributable to the branch.

Anything that is not ``PRUNE`` is ``TRIAGE``: a report row carrying path, branch,
ahead count, dirty file count, and any matching ledger claim, so a human or the
morning friction sweep adjudicates it. Nothing is ever silently dropped, and
nothing outside ``PRUNE`` is ever deleted.

Precedence note (a real interpretation decision, recorded on purpose)
--------------------------------------------------------------------
The eligibility rule reads "Linear terminal **OR** ledger ``TERMINAL`` with no
newer open ``CLAIM``", and also "tickets still open are NEVER eligible". Those
two sentences collide when the tracker says *open* and the ledger says
``TERMINAL``. The "NEVER" clause is the absolute one, so an explicitly-open
ticket loses to it and the ledger fallback applies only when the tracker state is
:data:`EnumTicketLifecycle.UNKNOWN`. That resolution fails closed in both
directions: an unresolvable ticket with no ``TERMINAL`` row is not eligible
either.

Architecture note
-----------------
The daily sweep that calls this module is the **executor / backstop, not the
design**. The intended end-state is event-driven: auto-close flips a ticket to
``Done`` and prune eligibility follows mechanically from that flip (the
OMN-16821 flip-predicate chain). Every function here is consequently **pure** —
no git, no network, no filesystem — so a future event hook can call the same
predicate with no scheduler involved. Fact collection lives in the caller
(``scripts/worktree_auto_prune.py``), never in here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumTicketLifecycle(StrEnum):
    """Terminal-vs-open lifecycle of the ticket owning a worktree directory."""

    DONE = "done"
    """Ticket completed. Prune-eligible."""

    CANCELED = "canceled"
    """Ticket canceled or duplicated. Prune-eligible."""

    OPEN = "open"
    """Any non-terminal tracker state (backlog, todo, in progress, in review).

    Never prune-eligible, regardless of how clean the worktree is.
    """

    UNKNOWN = "unknown"
    """State could not be resolved (no tracker access, ticket not found).

    Falls back to the ledger ``TERMINAL`` row; fails closed when there is none.
    """


class EnumPruneDisposition(StrEnum):
    """What the sweep does with a worktree."""

    PRUNE = "prune"
    """Eligible and safe: remove the worktree, delete the local branch."""

    TRIAGE = "triage"
    """Not prunable: emit a report row for human / friction-sweep adjudication."""


class EnumPruneBlockReason(StrEnum):
    """Why a worktree was not pruned. Every blocked worktree names its reasons."""

    # --- eligibility (the trigger did not fire) ---
    NO_TICKET = "no_ticket"
    """Worktree directory carries no OMN-NNNN identifier."""

    TICKET_NOT_CLOSED = "ticket_not_closed"
    """Ticket is explicitly open / In Progress. The absolute line."""

    TICKET_UNRESOLVED = "ticket_unresolved"
    """Ticket state unknown and no ledger TERMINAL row. Fails closed."""

    OPEN_CLAIM = "open_claim"
    """A ledger CLAIM newer than the TERMINAL row: a live lane owns this."""

    # --- safety (the gate refused) ---
    DIRTY_TREE = "dirty_tree"
    """Uncommitted changes present. Never launderable by merged-ness."""

    AHEAD_UNMERGED = "ahead_unmerged"
    """Commits ahead of the base that are neither in it nor content-equivalent."""

    UNPUSHED_STASH = "unpushed_stash"
    """A stash entry attributable to this worktree's branch."""

    DETACHED_HEAD = "detached_head"
    """No branch to reason about; ahead-ness cannot be proven."""

    BASE_REF_UNRESOLVED = "base_ref_unresolved"
    """Neither origin/dev nor origin/main resolved. Fails closed."""

    FACTS_UNREADABLE = "facts_unreadable"
    """A git probe failed, so at least one safety fact is UNKNOWN, not clean.

    A failed ``git status --porcelain`` returns empty stdout, which is
    indistinguishable from a clean tree if the exit code is discarded. An empty
    result is not evidence of absence — here the difference is deleting live
    work — so any unreadable probe fails the gate closed.
    """

    PARTIAL_MUTATION_DEBRIS = "partial_mutation_debris"
    """The worktree's ``.git`` link is gone but its directory was not fully
    removed [OMN-16951]. Plain ``git worktree remove`` can never succeed here —
    there is no linked ``.git`` for git to resolve from the worktree side. See
    :func:`classify_partial_mutation_debris`.
    """


class EnumDebrisRemediation(StrEnum):
    """What the auto-prune sweep may do about one partial-mutation debris row.

    Conservative by construction: the only automated action stronger than
    reporting is ``git worktree prune`` (administrative-record-only, never
    touches the directory) plus removing the leftover directory, and even that
    fires only when :func:`classify_partial_mutation_debris` has already proven
    every remaining file's content is a blob already in the owning clone.
    """

    AUTO_REMOVABLE = "auto_removable"
    """The owning clone's administrative record is ``prunable`` AND every
    remaining file's content is byte-identical to a blob already in that
    clone's object database. Safe to ``git worktree prune`` + remove the
    directory.
    """

    TRIAGE = "triage"
    """Not provably safe — report for human adjudication. Never removed."""


class ModelPartialMutationDebrisFacts(BaseModel):
    """Observed facts about a worktree directory whose ``.git`` link is gone.

    Every field is an observation, never a judgement — collected by the caller
    (``scripts/worktree_auto_prune.py``) from the filesystem and from the
    owning clone's ``git worktree list`` / object database.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(
        ..., min_length=1, description="Absolute path to the leftover directory"
    )
    ticket: str | None = Field(
        ..., description="OMN-NNNN owning ticket, or None when the path carries none"
    )
    repo: str = Field(..., min_length=1, description="Directory name (the repo slug)")
    owning_clone: str | None = Field(
        ...,
        description=(
            "Canonical clone whose `git worktree list` still references this "
            "path, or None when no known clone's registry does"
        ),
    )
    worktree_list_state: str | None = Field(
        ...,
        description=(
            "Raw annotation from the owning clone's `git worktree list "
            "--porcelain` for this path (e.g. 'prunable ...'), '' when the "
            "record is clean, or None when there is no owning clone"
        ),
    )
    file_count: int = Field(
        ..., ge=0, description="Regular files remaining under the directory"
    )
    unreachable_files: tuple[str, ...] = Field(
        ...,
        description=(
            "Relative paths whose content is NOT a blob already present in "
            "the owning clone's object database. Empty means every remaining "
            "file (there may be zero) is proven reachable."
        ),
    )


class ModelPartialMutationDebrisDecision(BaseModel):
    """The adjudicated disposition of one partial-mutation debris directory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., min_length=1)
    ticket: str | None = Field(...)
    repo: str = Field(..., min_length=1)
    block_reasons: tuple[EnumPruneBlockReason, ...] = Field(
        ...,
        description="Always (PARTIAL_MUTATION_DEBRIS,) — this classifier has one reason",
    )
    remediation: EnumDebrisRemediation = Field(...)
    evidence: str = Field(
        ..., description="Why the remediation was chosen — names every fact used"
    )


class ModelWorktreePruneFacts(BaseModel):
    """Collected, already-observed facts about one worktree.

    Every field is an observation, never a judgement. The caller collects these
    from git / the tracker / the ledger; this module only decides.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., min_length=1, description="Absolute path to the worktree")
    ticket: str | None = Field(
        ..., description="OMN-NNNN owning ticket, or None when the path carries none"
    )
    repo: str = Field(..., min_length=1, description="Repository name")
    branch: str | None = Field(
        ..., description="Checked-out branch, or None on a detached HEAD"
    )
    ticket_state: EnumTicketLifecycle = Field(
        ..., description="Tracker lifecycle state of the owning ticket"
    )
    ledger_has_terminal: bool = Field(
        ..., description="A TERMINAL row for this ticket exists in the work ledger"
    )
    ledger_open_claim: str | None = Field(
        ...,
        description="Text of a CLAIM row newer than the newest TERMINAL row, if any",
    )
    base_ref: str | None = Field(
        ...,
        description="Resolved base ref (e.g. 'origin/dev'), or None when unresolvable",
    )
    dirty_files: tuple[str, ...] = Field(
        ..., description="Paths reported by `git status --porcelain`"
    )
    commits_ahead: int = Field(
        ..., ge=0, description="Commit count from `git rev-list --count <base>..HEAD`"
    )
    unmerged_ahead_commits: tuple[str, ...] = Field(
        ...,
        description=(
            "Ahead commits with no content-equivalent in the base — the '+' lines "
            "of `git cherry <base> HEAD`. Empty means every ahead commit already "
            "landed in the base (typically via cherry-pick or rebase)."
        ),
    )
    tree_diff_vs_base_empty: bool = Field(
        ...,
        description=(
            "`git diff --quiet <base>...HEAD` succeeded — the branch contributes no "
            "net change over its merge base. This is the shape a squash merge "
            "leaves behind once the squash lands in the base."
        ),
    )
    attributed_stash_count: int = Field(
        ..., ge=0, description="Stash entries whose subject names this branch"
    )
    unreadable_probes: tuple[str, ...] = Field(
        ...,
        description=(
            "Git probes that did not complete successfully, named by command. "
            "Non-empty means at least one safety fact below is UNKNOWN rather "
            "than observed, and the gate must refuse."
        ),
    )


class ModelWorktreePruneDecision(BaseModel):
    """The adjudicated disposition of one worktree, with its evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., min_length=1)
    ticket: str | None = Field(...)
    repo: str = Field(..., min_length=1)
    branch: str | None = Field(...)
    disposition: EnumPruneDisposition = Field(...)
    block_reasons: tuple[EnumPruneBlockReason, ...] = Field(
        ..., description="Every reason the worktree was not pruned, not just the first"
    )
    eligibility_evidence: str = Field(
        ..., description="Why the owning ticket counts as closed; '' when it does not"
    )
    safety_evidence: str = Field(
        ...,
        description=(
            "Why removal is safe; '' when the safety gate was never reached "
            "(eligibility failed) or refused"
        ),
    )
    dirty_file_count: int = Field(..., ge=0)
    commits_ahead: int = Field(..., ge=0)
    ledger_open_claim: str | None = Field(
        ..., description="The live claim that blocked this worktree, if any"
    )


# ---------------------------------------------------------------------------
# Pure predicate — eligibility FIRES, safety GATES
# ---------------------------------------------------------------------------

_TERMINAL_TICKET_STATES: frozenset[EnumTicketLifecycle] = frozenset(
    {EnumTicketLifecycle.DONE, EnumTicketLifecycle.CANCELED}
)


def is_prune_eligible(
    facts: ModelWorktreePruneFacts,
) -> tuple[bool, tuple[EnumPruneBlockReason, ...], str]:
    """Decide whether the owning ticket's closure fires prune eligibility.

    Args:
        facts: Observed facts for one worktree.

    Returns:
        ``(eligible, block_reasons, evidence)``. ``evidence`` names the closure
        that fired eligibility and is empty when it did not fire.
    """
    reasons: list[EnumPruneBlockReason] = []

    if facts.ticket is None:
        reasons.append(EnumPruneBlockReason.NO_TICKET)

    # A live lane re-claiming the ticket outranks any closure: a TERMINAL row
    # followed by a newer CLAIM means work resumed on this ticket.
    if facts.ledger_open_claim:
        reasons.append(EnumPruneBlockReason.OPEN_CLAIM)

    if facts.ticket_state is EnumTicketLifecycle.OPEN:
        # The absolute line — an explicitly-open ticket is never eligible, and a
        # ledger TERMINAL row does not override it.
        reasons.append(EnumPruneBlockReason.TICKET_NOT_CLOSED)
    elif (
        facts.ticket_state is EnumTicketLifecycle.UNKNOWN
        and not facts.ledger_has_terminal
        # NO_TICKET already says the ticket could not be identified; adding
        # TICKET_UNRESOLVED on top of it is noise, not a second finding.
        and facts.ticket is not None
    ):
        reasons.append(EnumPruneBlockReason.TICKET_UNRESOLVED)

    if reasons:
        return False, tuple(reasons), ""

    if facts.ticket_state in _TERMINAL_TICKET_STATES:
        evidence = f"ticket {facts.ticket} state={facts.ticket_state.value}"
        if facts.ledger_has_terminal:
            evidence += "; ledger TERMINAL row present, no newer open CLAIM"
        return True, (), evidence

    return (
        True,
        (),
        (
            f"ticket {facts.ticket} state unresolved; ledger TERMINAL row present "
            "with no newer open CLAIM"
        ),
    )


def is_prune_safe(
    facts: ModelWorktreePruneFacts,
) -> tuple[bool, tuple[EnumPruneBlockReason, ...], str]:
    """Decide whether removing an already-eligible worktree loses no work.

    Collects *every* violated condition rather than short-circuiting on the
    first, so a triage row tells the whole story in one pass.

    Args:
        facts: Observed facts for one worktree.

    Returns:
        ``(safe, block_reasons, evidence)``. ``evidence`` states why removal
        loses nothing and is empty when the gate refused.
    """
    reasons: list[EnumPruneBlockReason] = []

    if facts.branch is None:
        reasons.append(EnumPruneBlockReason.DETACHED_HEAD)

    if facts.base_ref is None:
        reasons.append(EnumPruneBlockReason.BASE_REF_UNRESOLVED)

    if facts.unreadable_probes:
        # Before reading any fact below: a probe that failed produced empty
        # output, not a clean observation. Refuse rather than infer.
        reasons.append(EnumPruneBlockReason.FACTS_UNREADABLE)

    if facts.dirty_files:
        reasons.append(EnumPruneBlockReason.DIRTY_TREE)

    if facts.attributed_stash_count > 0:
        reasons.append(EnumPruneBlockReason.UNPUSHED_STASH)

    # Ahead-ness is forgiven exactly two ways, both of which mean the content is
    # already in the base: no ahead commit lacks a content-equivalent there, or
    # the branch contributes no net tree change over its merge base (the shape a
    # squash merge leaves behind).
    content_already_in_base = (
        not facts.unmerged_ahead_commits or facts.tree_diff_vs_base_empty
    )
    if facts.commits_ahead > 0 and not content_already_in_base:
        reasons.append(EnumPruneBlockReason.AHEAD_UNMERGED)

    if reasons:
        return False, tuple(reasons), ""

    base = facts.base_ref
    if facts.commits_ahead == 0:
        ahead_evidence = f"0 commits ahead of {base}"
    elif not facts.unmerged_ahead_commits:
        ahead_evidence = (
            f"{facts.commits_ahead} commit(s) ahead of {base}, all content-equivalent "
            f"in {base} (git cherry reports no '+' commits)"
        )
    else:
        ahead_evidence = (
            f"{facts.commits_ahead} commit(s) ahead of {base} but tree-diff against "
            f"{base} is empty (squash-merged: content already in {base})"
        )

    return (
        True,
        (),
        f"clean working tree; {ahead_evidence}; no stash attributed to the branch",
    )


def classify_worktree_prune(
    facts: ModelWorktreePruneFacts,
) -> ModelWorktreePruneDecision:
    """Adjudicate one worktree: eligibility fires, safety gates.

    Args:
        facts: Observed facts for one worktree.

    Returns:
        A frozen decision carrying the disposition, every block reason, and the
        evidence behind each half of the predicate. The safety gate is not
        evaluated at all when eligibility fails — safety is never a substitute
        for a closed ticket.
    """
    eligible, eligibility_reasons, eligibility_evidence = is_prune_eligible(facts)

    if not eligible:
        return ModelWorktreePruneDecision(
            path=facts.path,
            ticket=facts.ticket,
            repo=facts.repo,
            branch=facts.branch,
            disposition=EnumPruneDisposition.TRIAGE,
            block_reasons=eligibility_reasons,
            eligibility_evidence="",
            safety_evidence="",
            dirty_file_count=len(facts.dirty_files),
            commits_ahead=facts.commits_ahead,
            ledger_open_claim=facts.ledger_open_claim,
        )

    safe, safety_reasons, safety_evidence = is_prune_safe(facts)

    return ModelWorktreePruneDecision(
        path=facts.path,
        ticket=facts.ticket,
        repo=facts.repo,
        branch=facts.branch,
        disposition=(
            EnumPruneDisposition.PRUNE if safe else EnumPruneDisposition.TRIAGE
        ),
        block_reasons=safety_reasons,
        eligibility_evidence=eligibility_evidence,
        safety_evidence=safety_evidence,
        dirty_file_count=len(facts.dirty_files),
        commits_ahead=facts.commits_ahead,
        ledger_open_claim=facts.ledger_open_claim,
    )


# ---------------------------------------------------------------------------
# Partial-mutation debris predicate [OMN-16951]
#
# A distinct shape from the eligibility/safety predicate above: the worktree's
# `.git` link is already gone, so there is nothing for `git worktree remove` to
# resolve — plain removal can never succeed, and the classifier above never
# even sees these directories (its discovery keys off a `.git` glob). This
# predicate never re-derives ticket eligibility; a debris directory with
# unverifiable content is never auto-removed regardless of ticket state.
# ---------------------------------------------------------------------------


def classify_partial_mutation_debris(
    facts: ModelPartialMutationDebrisFacts,
) -> ModelPartialMutationDebrisDecision:
    """Adjudicate one `.git`-gone leftover directory.

    Auto-removal fires on exactly one conjunction, both halves provable from
    ``facts`` alone: the owning clone's administrative record must already say
    ``prunable`` (git itself agrees the worktree is gone), AND every remaining
    file's content must be a blob already in that clone's object database (so
    nothing unique is lost). Any other case — no owning clone found, the
    record not prunable, or even one file that cannot be proven reachable —
    is TRIAGE. This is deliberately the only auto-removable case; the
    conjunction is never weakened to "most files reachable" or "probably the
    same repo".

    Args:
        facts: Observed facts for one leftover directory.

    Returns:
        A frozen decision naming the remediation and the evidence behind it.
    """
    is_prunable = bool(
        facts.worktree_list_state and "prunable" in facts.worktree_list_state
    )
    content_reachable = not facts.unreachable_files

    if is_prunable and content_reachable:
        evidence = (
            f"no .git link; owning clone {facts.owning_clone!r} worktree-list "
            f"state {facts.worktree_list_state!r}; {facts.file_count} "
            "remaining file(s) all content-reachable as blobs already in the "
            "repo"
        )
        return ModelPartialMutationDebrisDecision(
            path=facts.path,
            ticket=facts.ticket,
            repo=facts.repo,
            block_reasons=(EnumPruneBlockReason.PARTIAL_MUTATION_DEBRIS,),
            remediation=EnumDebrisRemediation.AUTO_REMOVABLE,
            evidence=evidence,
        )

    parts: list[str] = []
    if facts.owning_clone is None:
        parts.append("no owning clone's worktree-list references this path")
    elif not is_prunable:
        parts.append(
            f"owning clone {facts.owning_clone!r} worktree-list state "
            f"{facts.worktree_list_state!r} is not 'prunable'"
        )
    if not content_reachable:
        shown = ", ".join(facts.unreachable_files[:5])
        more = "…" if len(facts.unreachable_files) > 5 else ""
        parts.append(
            f"{len(facts.unreachable_files)} file(s) not reachable as a blob "
            f"already in the repo: {shown}{more}"
        )
    evidence = "no .git link; " + "; ".join(parts)

    return ModelPartialMutationDebrisDecision(
        path=facts.path,
        ticket=facts.ticket,
        repo=facts.repo,
        block_reasons=(EnumPruneBlockReason.PARTIAL_MUTATION_DEBRIS,),
        remediation=EnumDebrisRemediation.TRIAGE,
        evidence=evidence,
    )
