# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Content-keyed worktree prune policy [OMN-16901, OMN-18370].

Pruning is keyed to **what the worktree HOLDS**, not to its ticket's state.
Operator ruling, 2026-09-14, recorded at ``docs/tracking/ROLLING_WORK_LEDGER.md``
line 7870: an empty or fully-merged worktree carries no work regardless of the
ticket, so the ticket being In Progress or Backlog does not block its removal.

A worktree is removable when, and only when, one of two limbs holds:

* **(a)** the working tree is clean, it is zero commits ahead of its base, and
  no ledger ``CLAIM`` is open on its ticket; or
* **(b)** the working tree is clean, its branch's pull request is **MERGED**,
  and no ledger ``CLAIM`` is open on its ticket.

Still protected, in both limbs: any uncommitted edit, any commit that is neither
in the base nor covered by a merged PR, any open ``CLAIM``. Pushing the branch to
origin is the only sanctioned way to clear an unmerged commit — this module never
launders one.

This **supersedes** the ticket-close-keyed rule the module shipped with. That
rule refused 186 provably-empty or provably-merged worktrees on 2026-09-14 (82 of
them under an In Progress ticket) while the host carried 751 of them; see
``knowledge-base-internal`` ``beta/tracking/2026-09-14-worktree-cleanup.md``
bucket A. The tracker's lifecycle state is still **observed and reported** as
triage context, but it decides nothing.

The predicate is two-part, and — since OMN-18370 AC-3 — **both halves are always
evaluated**:

1. :func:`is_prune_eligible` — **the trigger.** No live lane owns the worktree:
   the path carries an identifiable ticket (without one, "no open CLAIM" cannot
   be established at all) and that ticket has no ``CLAIM`` newer than its newest
   ``TERMINAL``.
2. :func:`is_prune_safe` — **the gate.** Working tree clean, nothing unmerged
   ahead of the base, no stash attributable to the branch.

A prior revision returned early when eligibility failed, so a worktree that was
both detached and dirty was counted under whichever reason fired first. Measured
on the same 2026-09-14 run: detached HEAD reported 40 against an actual 130, and
uncommitted changes reported 26 against an actual 158. Both halves now run for
every row and the reasons are the union.

Anything not ``PRUNE`` is ``TRIAGE`` — a report row carrying path, branch, ahead
count, dirty file count, PR state, and any matching ledger claim — except a row
whose facts could not be collected because a git probe **timed out**, which is
``TIMED_OUT`` and carries the host load reading that caused it. A timeout is not
a safety finding: it says nothing about the worktree, only about the host
(OMN-18370 AC-4).

Architecture note
-----------------
Every function here is **pure** — no git, no network, no filesystem, no clock —
so a future event hook can call the same predicate with no scheduler involved.
Fact collection lives in the caller (``scripts/worktree_auto_prune.py``), never
in here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumTicketLifecycle(StrEnum):
    """Tracker lifecycle of the ticket owning a worktree directory.

    **Reported, never decisive** since the 2026-09-14 ruling. It is kept because
    a triage row is easier to adjudicate when it says whether the ticket is
    still open — but no value here blocks or fires a removal.
    """

    DONE = "done"
    """Ticket completed."""

    CANCELED = "canceled"
    """Ticket canceled or duplicated."""

    OPEN = "open"
    """Any non-terminal tracker state (backlog, todo, in progress, in review)."""

    UNKNOWN = "unknown"
    """State could not be resolved (no tracker access, ticket not found)."""


class EnumBranchPrState(StrEnum):
    """State of the pull request opened from a worktree's branch.

    This is the fact limb (b) of the ruling turns on, and it is the only way to
    recognise a squash merge. ``git diff --quiet <base>...HEAD`` compares the
    branch against its **merge base**, so a squash-merged branch still shows its
    own diff there — the tree-diff signal cannot stand in for this one.
    """

    MERGED = "merged"
    """A pull request from this branch is merged."""

    NOT_MERGED = "not_merged"
    """A pull request exists from this branch and is open or closed unmerged."""

    NONE = "none"
    """The branch was searched for and has no pull request."""

    UNKNOWN = "unknown"
    """Not resolvable (no `gh`, an API failure, a detached HEAD). Fails closed:
    limb (b) is simply unavailable and the row falls back to limb (a)."""


class EnumPruneDisposition(StrEnum):
    """What the sweep does with a worktree."""

    PRUNE = "prune"
    """Eligible and safe: remove the worktree, delete the local branch."""

    TRIAGE = "triage"
    """Not prunable: emit a report row for human / friction-sweep adjudication."""

    TIMED_OUT = "timed_out"
    """A git probe timed out, so the facts were never collected [OMN-18370 AC-4].

    Distinct from ``TRIAGE`` on purpose: a timeout is a statement about host
    load, not about the worktree, and counting it as a safety finding
    misattributes a host problem to a lane's tree.
    """


class EnumPruneBlockReason(StrEnum):
    """Why a worktree was not pruned. Every blocked worktree names its reasons."""

    # --- eligibility (the trigger did not fire) ---
    NO_TICKET = "no_ticket"
    """Worktree directory carries no OMN-NNNN identifier.

    Ledger claims are ticket-keyed, so a path with no ticket cannot be shown to
    be free of an open ``CLAIM``. Fails closed rather than assuming absence.
    """

    OPEN_CLAIM = "open_claim"
    """A ledger CLAIM newer than the TERMINAL row: a live lane owns this."""

    # --- safety (the gate refused) ---
    DIRTY_TREE = "dirty_tree"
    """Uncommitted changes present. Never launderable by merged-ness."""

    AHEAD_UNMERGED = "ahead_unmerged"
    """Commits ahead of the base that are in neither the base nor a merged PR."""

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

    PROBE_TIMEOUT = "probe_timeout"
    """A git probe exceeded its time budget [OMN-18370 AC-4].

    Held apart from :data:`FACTS_UNREADABLE` because the cause is the host, not
    the worktree: on 2026-09-14 twenty removals timed out at host load 127 and
    were reported indistinguishably from real safety findings. A row carrying
    this reason is ``TIMED_OUT``, never ``TRIAGE``, and carries the load reading.
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
        ...,
        description=(
            "Tracker lifecycle state of the owning ticket. REPORTED CONTEXT "
            "ONLY — it blocks nothing and fires nothing (2026-09-14 ruling)."
        ),
    )
    ledger_has_terminal: bool = Field(
        ...,
        description=(
            "A TERMINAL row for this ticket exists in the work ledger. Reported "
            "in the evidence string; not a condition of eligibility."
        ),
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
            "net change over its merge base."
        ),
    )
    pr_state: EnumBranchPrState = Field(
        ...,
        description="Pull-request state of `branch`, the fact limb (b) turns on",
    )
    pr_head_oid: str | None = Field(
        ...,
        description=(
            "Head commit the merged pull request carried, or None when there is "
            "no merged PR or the field could not be read"
        ),
    )
    head_oid: str | None = Field(
        ...,
        description="This worktree's HEAD commit, or None when it could not be read",
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
    timed_out_probes: tuple[str, ...] = Field(
        default=(),
        description=(
            "Git probes that exceeded their time budget, named by command. Held "
            "apart from `unreadable_probes` because the cause is host load, not "
            "the worktree [OMN-18370 AC-4]."
        ),
    )
    load_average: float | None = Field(
        default=None,
        description=(
            "1-minute host load average read when a probe timed out; None when "
            "nothing timed out or the reading was unavailable"
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
        ...,
        description=(
            "Every reason the worktree was not pruned, from BOTH halves of the "
            "predicate — never only the first to fire [OMN-18370 AC-3]"
        ),
    )
    eligibility_evidence: str = Field(
        ..., description="Why no live lane owns this worktree; '' when one does"
    )
    safety_evidence: str = Field(
        ..., description="Why removal loses nothing; '' when the gate refused"
    )
    branch_content_preserved: bool = Field(
        ...,
        description=(
            "Every commit on the branch is already in the base or in a merged "
            "PR, so deleting the local branch destroys no unique record. This "
            "is what authorises the branch delete that follows removal; it is "
            "False whenever the safety gate refused [OMN-18370 AC-1/AC-2]."
        ),
    )
    dirty_file_count: int = Field(..., ge=0)
    commits_ahead: int = Field(..., ge=0)
    pr_state: EnumBranchPrState = Field(...)
    ledger_open_claim: str | None = Field(
        ..., description="The live claim that blocked this worktree, if any"
    )
    timed_out_probes: tuple[str, ...] = Field(
        default=(), description="Probes that exceeded their budget, named by command"
    )
    load_average: float | None = Field(
        default=None, description="Host load average at the time of the timeout"
    )


# ---------------------------------------------------------------------------
# Pure predicate — eligibility FIRES, safety GATES, both always evaluated
# ---------------------------------------------------------------------------


def is_prune_eligible(
    facts: ModelWorktreePruneFacts,
) -> tuple[bool, tuple[EnumPruneBlockReason, ...], str]:
    """Decide whether any live lane still owns this worktree.

    Under the 2026-09-14 ruling this half no longer consults the ticket's
    lifecycle at all. What it establishes is the ruling's shared precondition —
    *no open ``CLAIM``* — which both limbs require.

    Args:
        facts: Observed facts for one worktree.

    Returns:
        ``(eligible, block_reasons, evidence)``. ``evidence`` names what was
        established and is empty when eligibility did not fire.
    """
    reasons: list[EnumPruneBlockReason] = []

    if facts.ticket is None:
        # Ledger claims are ticket-keyed. With no ticket there is no way to show
        # the absence of an open CLAIM, and an unprovable absence is not one.
        reasons.append(EnumPruneBlockReason.NO_TICKET)

    if facts.ledger_open_claim:
        reasons.append(EnumPruneBlockReason.OPEN_CLAIM)

    if reasons:
        return False, tuple(reasons), ""

    evidence = f"no open ledger CLAIM for {facts.ticket}"
    if facts.ledger_has_terminal:
        evidence += " (newest row is TERMINAL)"
    evidence += f"; ticket state {facts.ticket_state.value} (reported, not decisive)"
    return True, (), evidence


def is_prune_safe(
    facts: ModelWorktreePruneFacts,
) -> tuple[bool, tuple[EnumPruneBlockReason, ...], str]:
    """Decide whether removing this worktree loses no work.

    Collects *every* violated condition rather than short-circuiting on the
    first, so a triage row tells the whole story in one pass.

    This is where the ruling's two limbs are distinguished: limb (a) is
    ``commits_ahead == 0``, limb (b) is a MERGED pull request whose head is this
    worktree's HEAD. A merged PR forgives ahead-ness **only** at the exact
    commit it merged: a local commit made after the merge is unmerged work, and
    the ruling protects it.

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

    if facts.timed_out_probes:
        reasons.append(EnumPruneBlockReason.PROBE_TIMEOUT)

    if facts.dirty_files:
        reasons.append(EnumPruneBlockReason.DIRTY_TREE)

    if facts.attributed_stash_count > 0:
        reasons.append(EnumPruneBlockReason.UNPUSHED_STASH)

    merged_pr_covers_head = (
        facts.pr_state is EnumBranchPrState.MERGED
        and facts.pr_head_oid is not None
        and facts.head_oid is not None
        and facts.pr_head_oid == facts.head_oid
    )
    # Ahead-ness is forgiven exactly three ways, each meaning the content is
    # already preserved somewhere other than this worktree: every ahead commit
    # has a content-equivalent in the base, the branch contributes no net tree
    # change over its merge base, or a merged pull request carries this exact
    # HEAD.
    content_already_preserved = (
        not facts.unmerged_ahead_commits
        or facts.tree_diff_vs_base_empty
        or merged_pr_covers_head
    )
    if facts.commits_ahead > 0 and not content_already_preserved:
        reasons.append(EnumPruneBlockReason.AHEAD_UNMERGED)

    if reasons:
        return False, tuple(reasons), ""

    base = facts.base_ref
    if facts.commits_ahead == 0:
        ahead_evidence = f"limb (a): 0 commits ahead of {base}"
    elif merged_pr_covers_head:
        ahead_evidence = (
            f"limb (b): {facts.commits_ahead} commit(s) ahead of {base}, and a "
            f"MERGED pull request carries this exact HEAD {facts.head_oid}"
        )
    elif not facts.unmerged_ahead_commits:
        ahead_evidence = (
            f"{facts.commits_ahead} commit(s) ahead of {base}, all content-equivalent "
            f"in {base} (git cherry reports no '+' commits)"
        )
    else:
        ahead_evidence = (
            f"{facts.commits_ahead} commit(s) ahead of {base} but tree-diff against "
            f"{base} is empty (content already in {base})"
        )

    return (
        True,
        (),
        f"clean working tree; {ahead_evidence}; no stash attributed to the branch",
    )


def classify_worktree_prune(
    facts: ModelWorktreePruneFacts,
) -> ModelWorktreePruneDecision:
    """Adjudicate one worktree: eligibility fires, safety gates, both reported.

    Both halves are always evaluated and their reasons unioned [OMN-18370
    AC-3]. The previous revision skipped the safety half whenever eligibility
    failed, which made the report's block-reason table undercount every safety
    class on exactly the rows that had more than one problem.

    Args:
        facts: Observed facts for one worktree.

    Returns:
        A frozen decision carrying the disposition, every block reason from both
        halves, and the evidence behind each.
    """
    eligible, eligibility_reasons, eligibility_evidence = is_prune_eligible(facts)
    safe, safety_reasons, safety_evidence = is_prune_safe(facts)

    reasons = (*eligibility_reasons, *safety_reasons)

    if EnumPruneBlockReason.PROBE_TIMEOUT in reasons:
        # A timeout says nothing about the worktree, so it is not reported as a
        # safety verdict [OMN-18370 AC-4].
        disposition = EnumPruneDisposition.TIMED_OUT
    elif eligible and safe:
        disposition = EnumPruneDisposition.PRUNE
    else:
        disposition = EnumPruneDisposition.TRIAGE

    return ModelWorktreePruneDecision(
        path=facts.path,
        ticket=facts.ticket,
        repo=facts.repo,
        branch=facts.branch,
        disposition=disposition,
        block_reasons=reasons,
        eligibility_evidence=eligibility_evidence if eligible else "",
        safety_evidence=safety_evidence if safe else "",
        # The branch may only be deleted when the safety gate PROVED the content
        # is preserved elsewhere. Eligibility (an open claim) does not bear on
        # whether the commits exist somewhere else, but a row that is not being
        # removed has no branch delete to authorise either.
        branch_content_preserved=bool(safe and eligible),
        dirty_file_count=len(facts.dirty_files),
        commits_ahead=facts.commits_ahead,
        pr_state=facts.pr_state,
        ledger_open_claim=facts.ledger_open_claim,
        timed_out_probes=facts.timed_out_probes,
        load_average=facts.load_average,
    )


# ---------------------------------------------------------------------------
# Partial-mutation debris predicate [OMN-16951]
#
# A distinct shape from the eligibility/safety predicate above: the worktree's
# `.git` link is already gone, so there is nothing for `git worktree remove` to
# resolve — plain removal can never succeed, and the classifier above never
# even sees these directories (its discovery keys off a `.git` glob). This
# predicate never re-derives eligibility; a debris directory with unverifiable
# content is never auto-removed.
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
