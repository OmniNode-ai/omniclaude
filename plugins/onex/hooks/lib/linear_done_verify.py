#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Linear Done-state PR verification [OMN-8415].

Cross-checks Linear ticket Done-state transitions against the state of any
GitHub PRs referenced in the ticket description. If any referenced PR is still
open or blocked, the transition is rejected — catching the OMN-8375 class of
failure where a ticket was marked Done while its PR was still BLOCKED.

Parent: OMN-8407 (Overseer verification).

Usage (from shell wrapper, reads PreToolUse JSON on stdin):

    echo '<tool_json>' | python3 linear_done_verify.py

Exit codes:
    0 — allow the tool call
    2 — block the tool call (with JSON decision on stderr)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

# States that require merged-PR proof before the transition is allowed.
# These represent successful completion ("the work shipped").
DONE_STATES = {"done", "complete", "completed", "closed"}

# States that close a ticket WITHOUT shipping the underlying work
# (cancel / duplicate / won't-do bucket). These do not require merged-PR
# proof — the whole point of cancelling is that no PR will land.
# Without this distinction, the hook misfires on tickets whose descriptions
# happen to contain `PR #N` strings inside markdown code blocks (OMN-10047).
CANCEL_STATES = {"canceled", "cancelled", "duplicate", "won't do", "wont do"}

# Bare PR shorthand — `PR #123` / `pull #123` / `pull request #123`
# (case-insensitive, optional `:`/`-`/whitespace between the token and `#`).
# OMN-15025: the prior pattern (`#123` not preceded by a word char) matched
# ANY bare `#<digits>` in prose — "CLAUDE.md Rule #4", "cause #2 is always
# mislabelled" — as an unresolvable PR reference and false-blocked the
# Done-flip. Requiring an adjacent PR/pull token is option 1 from OMN-15025's
# fix-direction list: it kills the prose false-positives while a description
# that cites its real PR ONLY as an un-anchored bare number (never merged into
# this pattern) still can't silently ALLOW — decide() only treats
# `no_pr_references` as non-blocking when it *also* clears the OCC-receipt /
# exempt-label paths below, so dropping a bare match falls through to that
# fail-closed check rather than skipping verification.
# Also matches `https://github.com/<owner>/<repo>/pull/<num>` via _PR_URL_RE.
_PR_NUMBER_RE = re.compile(
    r"\b(?:pr|pull(?:\s+request)?)\b[:\s-]*#(\d+)\b", re.IGNORECASE
)
_PR_URL_RE = re.compile(
    r"https?://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)",
    re.IGNORECASE,
)

BLOCKING_MERGE_STATES = {"BLOCKED", "DIRTY", "BEHIND"}

DEFAULT_OWNER = "OmniNode-ai"

# OMN-14882: Linear's rich-text layer rewrites a pasted
# `github.com/<owner>/<repo>/pull/<N>` URL into its own internal embed at save
# time, deleting the literal `github.com` substring `_PR_URL_RE` requires.
# Two rewritten shapes have been observed live, both an XML-ish
# `<pull-request href="...">owner/repo#N</pull-request>` tag (current) and a
# `[owner/repo#N](https://linear.app/.../review/...)` markdown link (older) —
# but in both the real citation survives as plain `owner/repo#N` text inside
# the tag/link. Scoped to `DEFAULT_OWNER` (the only org this workspace's
# tickets cite) so an unrelated `path/to/file#42`-shaped string in prose is
# never mistaken for a PR reference.
_PR_OWNER_REPO_HASH_RE = re.compile(
    rf"\b({re.escape(DEFAULT_OWNER)}/[\w.-]+)#(\d+)\b",
    re.IGNORECASE,
)

# OMN-18747: anchors that resolve a bare `PR #N` to a repository the ticket
# itself names. The gate refused OMN-18086 on `?#2504: PR #2504 has no
# associated repo` although that ticket cites `OmniNode-ai/omnimarket#2504` in
# full in its carrier block and writes `omnimarket` one word before the bare
# form on the acceptance line. Failing closed on a genuinely unresolvable
# reference is correct and is unchanged; only a reference the ticket
# unambiguously pins is resolved, and two anchors that disagree stay refused.
#
# `_ANCHOR_WORD_RE` reads the last word on the line before the `PR`/`pull`
# token. A word is accepted as a repository name only when the ticket already
# spells it as `owner/repo` somewhere (`by_name` below), or when it has this
# org's repository-name shape — the same `DEFAULT_OWNER` scoping
# `_PR_OWNER_REPO_HASH_RE` already relies on. Ordinary prose words that
# commonly precede the token ("the", "a", "merged", "that") match neither and
# are rejected, so "Fixed in the PR #2504" stays unresolvable.
_ANCHOR_WORD_RE = re.compile(r"([A-Za-z][\w.-]*)[^\w]*$")
_ORG_REPO_NAME_RE = re.compile(r"^(?:omni|onex|knowledge-base)[\w.-]*$", re.IGNORECASE)

# OMN-18749: a CLOSED-unmerged citation can never become merged, so a gate that
# treats it like an OPEN one holds its ticket forever and recommends the one
# thing that cannot happen. Two live holds: two closed proof pull requests whose
# work landed in a third, and a pull request closed by an accidental branch
# rename whose work landed in its successor.
#
# Such a citation is satisfied ONLY by a successor THE TICKET DECLARES, on one
# line naming both sides, and only when that successor is verified MERGED. The
# phrase set is deliberately directional -- everything here reads
# "<the closed one> <phrase> <the successor>" -- because a symmetric verb such
# as "replaces" would bind the pair backwards and mark the merged pull request
# superseded by the closed one.
#
# Rejected alternatives, recorded because both look easier: a comment is read by
# neither gate, and a successor that vouches for itself in its own body is
# written by the same lane that wants the close.
_SUPERSESSION_PHRASE_RE = re.compile(
    r"\b(?:super[sc]eded\s+by|replaced\s+by|re-?landed\s+as|landed\s+as|"
    r"closed\s+in\s+favou?r\s+of)\b",
    re.IGNORECASE,
)

# OMN-13856 (the OMN-14642 refusal): a bare ``#N`` inside a CLOSED PR's own
# closing note. On GitHub a bare number in a PR comment means a PR in the same
# repository, so it resolves to the closed PR's repo. The lookbehind keeps the
# ``#N`` of an ``owner/repo#N`` citation from matching twice.
_NOTE_BARE_REF_RE = re.compile(r"(?<![\w/])#(\d+)\b")

# OMN-13856 (the OMN-13907 refusal): a no-PR housekeeping ticket whose DoD is a
# live-state readback (worktrees removed, a lane stopped, a record deleted) has
# no PR to cite and no node_dod_verify contract to receipt. The marker is the
# sanctioned carrier for that readback. Like the deploy-readback marker it must
# carry evidence: a dated readback no older than the window below, and the
# probe that produced it, quoted in backticks. It is honoured only on a ticket
# that cites no PR at all; see done_flip_guard.decide.
_COMMIT_SHA_RE = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")

LIVE_STATE_MARKER_KEYS = frozenset({"live-state-proven", "live_state_proven"})
LIVE_STATE_MAX_AGE_DAYS = 7
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_BACKTICK_PROBE_RE = re.compile(r"`[^`\n]*\S[^`\n]*`")

# Evidence-companion repos whose PRs are WEAK close-signals (OMN-14641,
# deliverable 3). An ``onex_change_control`` OCC / evidence-companion PR neither
# satisfies nor blocks a *product* ticket's Done — it is a receipt companion,
# not the shipped work. Filter these out of the merge-check ref set so a merged
# OCC receipt never *by itself* flips a product ticket Done, and an open OCC
# receipt never blocks a legitimately-merged product ticket.
_WEAK_SIGNAL_REPOS = {"onex_change_control"}

# Scratch/throwaway PR annotation vocabulary (OMN-14792). A PR reference on a
# line explicitly labelled as a scratch / live-mint / throwaway / do-not-merge
# artifact is NOT a DoD-implementing citation — it is a disposable test PR
# (e.g. a live-readback mint PR that is intentionally closed, never merged).
# Matched only for the *scoped* implementing-PR scan (the deploy-readback path);
# the unconditional ``verify`` path is intentionally left untouched. The tokens
# are deliberately specific phrases — bare ``test`` is excluded so that an
# ordinary implementing PR line such as "added tests in <url>" is never
# mistaken for a scratch reference.
_SCRATCH_ANNOTATION_RE = re.compile(
    r"\b(scratch|throwaway|live[-\s]?mint|readback[-\s]?pr|"
    r"do[-\s]?not[-\s]?merge|dnm|test[-\s]?pr|test[-\s]?only)\b",
    re.IGNORECASE,
)

# Deploy-readback evidence marker keys (OMN-14792). A runtime-deploy ticket's
# DoD is a live readback (an effects image rebuilt to dev-tip + a clean probe
# read off the deployed bytes), NOT a merged product PR — ``node_dod_verify``
# structurally skips such tickets (memory
# ``reference_dod_verify_cannot_close_deploy_tickets``) and they close via an
# operator deliberate-Done. This marker is the sanctioned deploy-proof signal
# the Done-flip guard accepts in lieu of a merged PR.
DEPLOY_READBACK_MARKER_KEYS = frozenset(
    {"deploy-readback-proven", "deploy_readback_proven"}
)


@dataclass
class PRRef:
    number: int
    repo: str | None = None  # "owner/repo" when known; else None
    # True when `repo` came from a bare `#N` + `default_repo` fallback rather
    # than an explicit `owner/repo#N` shorthand or full GitHub URL citation
    # (OMN-15782). An explicit citation is authoritative about its repo; a
    # bare-number fallback is only a guess and must not be trusted the same
    # way when classifying weak-signal (onex_change_control) refs.
    bare: bool = False
    # Repositories the ticket anchors this number to when it anchors it to more
    # than one (OMN-18747). Populated only on an unresolved ref, and reported in
    # the refusal so the drafter is told which citation to make explicit rather
    # than that the reference is simply unresolvable.
    anchor_candidates: tuple[str, ...] = ()
    # OMN-13856: a commit SHA named on the same line as an otherwise unanchored
    # bare `PR #N` ("activating commit `8a4fe66b` (PR #257)"). Populated only
    # when the ref has no repository; see _resolve_commit_anchored_refs.
    commit_anchor: str = ""


@dataclass
class PRStatus:
    ref: PRRef
    state: str  # OPEN, CLOSED, MERGED
    merge_state: str  # CLEAN, BLOCKED, DIRTY, BEHIND, UNKNOWN, etc.
    error: str | None = None
    # "owner/repo#N" of a MERGED successor this ticket declared for a
    # CLOSED-unmerged citation (OMN-18749). Set by :func:`verify` only, only
    # after the successor's own probe came back MERGED, and never for an OPEN
    # or unreadable citation. Empty means no proven supersession, which is
    # what every caller constructing a status directly gets.
    superseded_by: str = ""
    # OMN-13856: the PR title, and, for a CLOSED-unmerged PR only, the PR body
    # and its conversation comments, all read by REST in :func:`fetch_pr_status`.
    # A closing note is where a lane records "superseded by #N" when it closes
    # a PR in favour of a recut; :func:`_apply_declared_supersessions` reads it.
    title: str = ""
    closing_notes: tuple[str, ...] = ()
    # OMN-13856: the merge commit of a MERGED PR, read by REST. Used only to
    # match a commit-anchored bare reference; see _resolve_commit_anchored_refs.
    merge_commit_sha: str = ""

    @property
    def is_blocking(self) -> bool:
        if self.error:
            return True
        if self.state == "MERGED":
            return False
        if self.superseded_by:
            return False
        if self.state == "OPEN":
            return True
        # CLOSED-without-merge counts as blocking (unmerged)
        if self.state == "CLOSED":
            return True
        return True


@dataclass
class VerificationResult:
    allowed: bool
    reason: str = ""
    pr_statuses: list[PRStatus] = field(default_factory=list)


def parse_pr_refs(
    text: str,
    default_repo: str | None = None,
    anchor_text: str | None = None,
) -> list[PRRef]:
    """Extract PR references from a ticket description.

    Finds both `#123` shorthand and full `https://github.com/owner/repo/pull/N`
    URLs. Bare `#N` references use `default_repo` if provided.

    OMN-18747: when no `default_repo` is configured, a bare `#N` is resolved
    against the ticket's OWN citations before being reported unresolvable — a
    qualified `owner/repo#N` (or pull URL) of the same number elsewhere in the
    body, or the repository named in the sentence carrying the reference. See
    :func:`_resolve_bare_ref_repo`. This never re-points a reference that
    `default_repo` already resolved, and a reference with no anchor, or with two
    anchors that disagree, stays unresolved and therefore blocking.

    OMN-18749: `anchor_text` lets a caller parse a FRAGMENT of a ticket while
    resolving its bare references against the WHOLE ticket. A supersession
    declaration is read one line at a time, and the citation that anchors a
    number usually sits in another paragraph; without this the fragment would
    lose every anchor the full body supplies. It affects anchoring only —
    references are still read from `text` alone.
    """
    refs: dict[tuple[str, int], PRRef] = {}

    for url_match in _PR_URL_RE.finditer(text):
        owner = url_match.group(1)
        repo_name = url_match.group(2)
        num = int(url_match.group(3))
        full_repo = f"{owner}/{repo_name}"
        refs[(full_repo, num)] = PRRef(number=num, repo=full_repo)

    # OMN-14882: Linear-rewritten `<pull-request>...</pull-request>` tags and
    # `[owner/repo#N](...)` markdown-link embeds — see _PR_OWNER_REPO_HASH_RE.
    for owner_repo_match in _PR_OWNER_REPO_HASH_RE.finditer(text):
        full_repo = owner_repo_match.group(1)
        num = int(owner_repo_match.group(2))
        key = (full_repo, num)
        if key in refs:
            continue
        refs[key] = PRRef(number=num, repo=full_repo)

    # OMN-18747: anchors are read from the qualified citations collected above,
    # so they are the ticket's own explicit statements about where a PR lives.
    by_number: dict[int, set[str]] = {}
    by_name: dict[str, str | None] = {}
    anchor_keys: list[tuple[str, int]] = list(refs)
    if anchor_text is not None and anchor_text != text:
        anchor_keys = [
            (ref.repo, ref.number)
            for ref in parse_pr_refs(anchor_text, default_repo=default_repo)
            if ref.repo is not None and not ref.bare
        ]
    for full_repo, num in anchor_keys:
        by_number.setdefault(num, set()).add(full_repo)
        name = full_repo.rsplit("/", 1)[-1].lower()
        if name in by_name and by_name[name] != full_repo:
            by_name[name] = None  # same repo name under two owners — ambiguous
        else:
            by_name.setdefault(name, full_repo)

    repo_key = default_repo or ""
    for num_match in _PR_NUMBER_RE.finditer(text):
        num = int(num_match.group(1))
        resolved = default_repo
        candidates: tuple[str, ...] = ()
        if resolved is None:
            resolved, candidates = _resolve_bare_ref_repo(
                text, num, num_match.start(), by_number, by_name
            )
        key = (resolved or repo_key, num)
        if key in refs:
            continue
        refs[key] = PRRef(
            number=num,
            repo=resolved,
            # An anchor-resolved repo is an explicit citation in the ticket, not
            # the `default_repo` guess `bare` marks (OMN-15782).
            bare=resolved is None or resolved == default_repo,
            anchor_candidates=candidates,
            commit_anchor=(
                _line_commit_anchor(text, num_match.start())
                if resolved is None and not candidates
                else ""
            ),
        )

    return list(refs.values())


def _line_commit_anchor(text: str, match_start: int) -> str:
    """Return the one commit SHA named on the line of a match, or "" (OMN-13856).

    A SHA is 7-40 lowercase hex characters containing at least one digit (so
    hex-spelled words such as "defaced" never qualify). A line naming two
    different SHAs is ambiguous and yields "". Pure function.
    """
    line_start = text.rfind("\n", 0, match_start) + 1
    line_end = text.find("\n", match_start)
    line = text[line_start : line_end if line_end != -1 else len(text)]
    shas = {m.group(0).lower() for m in _COMMIT_SHA_RE.finditer(line)}
    return next(iter(shas)) if len(shas) == 1 else ""


def _resolve_commit_anchored_refs(refs: list[PRRef], fetcher: Any) -> list[PRStatus]:
    """Fetch every ref, resolving commit-anchored bare refs first (OMN-13856).

    The OMN-14642 refusal: the ticket's incident narrative reads "Activating
    commit: `8a4fe66b` (PR #257, ...)". Nothing anchored #257 to a repository,
    so the guard refused it as an unverifiable citation, although the line
    names the very commit the PR merged as. Here such a ref is looked up as
    PR #N in each repository the ticket's OTHER citations name, and it resolves
    to the one candidate whose MERGED merge commit starts with that SHA. This
    is a verified anchor, not a waiver: the ref is then reported as that merged
    PR. No match, more than one match, or no candidate repository at all
    leaves the ref unresolved, and it refuses exactly as before.
    """
    candidate_repos = sorted(
        {r.repo for r in refs if r.repo is not None and not r.commit_anchor}
    )
    statuses: list[PRStatus] = []
    for ref in refs:
        if ref.repo is None and ref.commit_anchor and candidate_repos:
            matches = []
            for repo in candidate_repos:
                probe = fetcher(PRRef(number=ref.number, repo=repo))
                if (
                    not probe.error
                    and probe.state == "MERGED"
                    and probe.merge_commit_sha.lower().startswith(ref.commit_anchor)
                ):
                    matches.append(probe)
            if len(matches) == 1:
                statuses.append(matches[0])
                continue
        statuses.append(fetcher(ref))
    return statuses


def _inline_repo_anchor(
    text: str,
    match_start: int,
    by_name: dict[str, str | None],
) -> str | None:
    """Return the repository named immediately before a `PR #N` token, if any.

    OMN-18747. Reads the last word on the same line ahead of the match — the
    ``omnimarket`` in "Implemented in omnimarket PR #2504". Pure function.
    """
    line_start = text.rfind("\n", 0, match_start) + 1
    word_match = _ANCHOR_WORD_RE.search(text[line_start:match_start])
    if word_match is None:
        return None
    name = word_match.group(1).rstrip("._-")
    if not name:
        return None
    known = by_name.get(name.lower(), "")
    if known:
        return known
    if known is None:
        return None  # the name is spelled under two owners in this ticket
    if _ORG_REPO_NAME_RE.match(name):
        return f"{DEFAULT_OWNER}/{name}"
    return None


def _resolve_bare_ref_repo(
    text: str,
    number: int,
    match_start: int,
    by_number: dict[int, set[str]],
    by_name: dict[str, str | None],
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve a bare ``#N`` against the ticket's own citations (OMN-18747).

    Returns ``(repo, ambiguous_candidates)``. ``repo`` is set only when the
    ticket pins the number unambiguously: a qualified citation of the SAME
    number elsewhere in the body, or the repository named in the sentence
    carrying the reference. When both anchors exist the in-sentence name
    decides, which lets it pick one of several same-number citations. When the
    two anchors disagree, or when several same-number citations exist with no
    in-sentence name, the reference stays unresolved and every candidate is
    returned so the refusal can name them. A reference with no anchor at all
    resolves to ``(None, ())`` — exactly today's fail-closed behaviour.

    Pure function.
    """
    candidates = set(by_number.get(number, ()))
    inline = _inline_repo_anchor(text, match_start, by_name)
    if inline is not None:
        if not candidates or inline in candidates:
            return inline, ()
        return None, tuple(sorted(candidates | {inline}))
    if len(candidates) == 1:
        return next(iter(candidates)), ()
    if candidates:
        return None, tuple(sorted(candidates))
    return None, ()


@dataclass
class SupersessionDeclaration:
    """One ticket-declared supersession of a CLOSED-unmerged citation."""

    closed: PRRef
    # The successor named on the right of the phrase, or None when the right
    # side carries no reference that resolves to a repo. None is NOT "no
    # declaration" — it is a declaration whose successor cannot be checked,
    # which still refuses, and says why (OMN-18749).
    successor: PRRef | None
    line: str


def parse_supersession_declarations(
    text: str,
    default_repo: str | None = None,
) -> dict[tuple[str | None, int], SupersessionDeclaration]:
    """Read every ``<closed> <phrase> <successor>`` line the ticket declares.

    Keyed by the CLOSED citation's ``(repo, number)``, which is the key
    :func:`verify` looks a blocking status up by. Several closed references may
    share one line — the two-proof-pull-requests-one-successor shape — and each
    binds to the same successor.

    A line whose right side carries no reference at all is not a declaration
    and is ignored: "superseded by later work" names nothing to verify. A line
    whose right side names something unresolvable IS a declaration, recorded
    with ``successor=None`` so the refusal can say the successor could not be
    resolved rather than that none was offered.

    Pure function. It proves nothing on its own — the successor's merge state
    is established by a probe in :func:`verify`.
    """
    declarations: dict[tuple[str | None, int], SupersessionDeclaration] = {}
    for line in text.splitlines():
        phrase = _SUPERSESSION_PHRASE_RE.search(line)
        if phrase is None:
            continue
        left = parse_pr_refs(
            line[: phrase.start()], default_repo=default_repo, anchor_text=text
        )
        right = parse_pr_refs(
            line[phrase.end() :], default_repo=default_repo, anchor_text=text
        )
        if not left or not right:
            continue
        successor = right[0]
        for closed in left:
            declarations[(closed.repo, closed.number)] = SupersessionDeclaration(
                closed=closed,
                successor=successor if successor.repo is not None else None,
                line=line.strip(),
            )
    return declarations


def is_weak_signal_ref(
    ref: PRRef,
    prober: Callable[[int], bool] | None = None,
) -> bool:
    """Return True if a PR reference is a WEAK close-signal (OMN-14641).

    Currently: any ``onex_change_control`` PR — OCC receipts / evidence
    companions. These never gate a product ticket's Done in either direction.

    OMN-15782 (spelling invariance): an explicitly-qualified reference
    (``owner/repo#N`` or a full GitHub URL) is authoritative about its own
    repo and is classified directly. A *bare* ``#N`` reference (``ref.bare``)
    resolves its ``repo`` from the ticket's ``default_repo`` fallback — which
    may be unset (``None``) or set to a *different* product repo than the PR
    actually lives in. Previously that fallback repo string was trusted
    as-is, so the identical ``onex_change_control`` PR classified weak when
    spelled ``owner/repo#N`` but non-weak (an unresolvable/blocking product
    dependency) when spelled bare ``#N`` — a drafting-choice-dependent
    verdict, not a property of the PR (live incident: OMN-15722). When the
    direct repo string doesn't already resolve weak and the ref is bare,
    ``prober`` — when supplied — is consulted with the PR number to check
    onex_change_control membership directly before falling back to
    "not weak". ``prober`` defaults to ``None`` (no live lookup, preserving
    the prior fallback behavior and function purity) — callers on a live
    path must pass a real prober (see :func:`probe_occ_membership`) to get
    the fix; :func:`verify` is wired to it from :func:`main`.
    """
    repo = (ref.repo or "").rsplit("/", 1)[-1].strip().lower()
    if repo in _WEAK_SIGNAL_REPOS:
        return True
    if ref.bare and prober is not None:
        return prober(ref.number)
    return False


def probe_occ_membership(number: int, timeout: float = 15.0) -> bool:
    """Live check: does PR ``number`` exist in ``onex_change_control``?

    Production prober for :func:`is_weak_signal_ref` (OMN-15782) — resolves
    the spelling-dependent gap for *bare* refs whose repo did not already
    resolve directly to a weak-signal repo (see ``PRRef.bare``). One extra
    REST ``gh api`` call per unresolved bare ref; explicitly-qualified refs
    never reach this (repo already known, no probe needed). Any error (gh
    unavailable, timeout, PR not found) is treated as "not a member" —
    fail-closed toward "not weak" so this can never *waive* a genuine
    blocking product PR, only correctly filter a genuine OCC one.
    """
    occ_repo = next(iter(_WEAK_SIGNAL_REPOS))
    repo = f"{DEFAULT_OWNER}/{occ_repo}"
    # REST, not GraphQL (OMN-13856): see _gh_api_json.
    data, error = _gh_api_json(f"repos/{repo}/pulls/{number}", timeout)
    return error is None and isinstance(data, dict)


def is_exempt(description: str, labels: list[str] | None) -> bool:
    """Return True if the ticket opts out of PR verification.

    Exemption signals:
        - Label `close-if-done` (or `close-if-done: true`)
        - Frontmatter/body line `close-if-done: true`
    """
    if labels:
        for label in labels:
            normalized = label.strip().lower()
            if normalized in {"close-if-done", "close-if-done: true"}:
                return True

    for line in description.splitlines():
        stripped = line.strip().lower().lstrip("-*# ").strip()
        if stripped in {"close-if-done: true", "close_if_done: true"}:
            return True

    return False


def is_done_state(state_value: str) -> bool:
    """Return True if the target state requires merged-PR verification.

    Only the success-bucket Done states count. Cancel/Duplicate/Won't-do
    transitions are NOT verified against PR state — they explicitly close
    a ticket without shipping work. See OMN-10047.
    """
    return state_value.strip().lower() in DONE_STATES


def is_cancel_state(state_value: str) -> bool:
    """Return True if the target state is in the cancel/duplicate bucket.

    These states close a ticket without requiring merged-PR proof.
    """
    return state_value.strip().lower() in CANCEL_STATES


def _gh_api_json(path: str, timeout: float) -> tuple[Any, str | None]:
    """Run ``gh api <path>`` (REST) and return ``(parsed_json, error)``.

    OMN-13856 (the OMN-14652 refusal): PR state used to be read through
    ``gh pr view``, which is GraphQL. GraphQL and REST are separate quota
    buckets, and on 2026-09-25 GraphQL was exhausted while REST had thousands of
    calls left, so two merged PRs came back as errors and a verified-done ticket
    was refused. REST answers every field this guard needs. A failure is
    returned as an error string, never as a state, so callers still fail closed.
    """
    cmd = ["gh", "api", path]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"Timeout querying {path}"
    except FileNotFoundError:
        return None, "gh CLI not available in PATH"
    if proc.returncode != 0:
        return None, f"gh api {path} failed: {proc.stderr.strip()}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"Could not parse gh output: {exc}"


def fetch_pr_status(ref: PRRef, timeout: float = 15.0) -> PRStatus:
    """Query GitHub for PR state by REST (``gh api repos/<repo>/pulls/<N>``).

    A CLOSED-unmerged PR also carries its body and conversation comments as
    ``closing_notes``, so a "superseded by" note can be checked. A failure to
    read the comments leaves only the body, which can keep a citation
    blocking but never clears one.
    """
    repo = ref.repo
    if not repo:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=(
                f"PR #{ref.number} has no associated repo; cannot verify. "
                + (
                    # OMN-18747: the ticket anchors the number to more than one
                    # repo, so say which ones rather than asking for a URL the
                    # drafter has arguably already supplied twice over.
                    "This ticket anchors it to more than one repo ("
                    + ", ".join(ref.anchor_candidates)
                    + "); cite the one you mean as owner/repo#N."
                    if ref.anchor_candidates
                    else "Include a full GitHub URL in the ticket DoD."
                )
            ),
        )

    data, error = _gh_api_json(f"repos/{repo}/pulls/{ref.number}", timeout)
    if error is not None or not isinstance(data, dict):
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=f"PR state read failed for {repo}#{ref.number}: "
            + (error or "unexpected response shape"),
        )

    raw_state = str(data.get("state", "")).lower()
    if data.get("merged") is True:
        state = "MERGED"
    elif raw_state == "open":
        state = "OPEN"
    elif raw_state == "closed":
        state = "CLOSED"
    else:
        state = "UNKNOWN"

    closing_notes: tuple[str, ...] = ()
    if state == "CLOSED":
        notes = [str(data.get("body") or "")]
        comments, comments_error = _gh_api_json(
            f"repos/{repo}/issues/{ref.number}/comments?per_page=100", timeout
        )
        if comments_error is None and isinstance(comments, list):
            notes.extend(
                str(c.get("body") or "") for c in comments if isinstance(c, dict)
            )
        closing_notes = tuple(n for n in notes if n)

    return PRStatus(
        ref=ref,
        state=state,
        merge_state=str(data.get("mergeable_state") or "UNKNOWN").upper(),
        title=str(data.get("title") or ""),
        closing_notes=closing_notes,
        merge_commit_sha=str(data.get("merge_commit_sha") or "")
        if state == "MERGED"
        else "",
    )


def classify_blocking(status: PRStatus) -> bool:
    """Return True if this PR should block a Done transition.

    OMN-18749: a CLOSED-unmerged citation carrying a proven ``superseded_by``
    does not block. The proof is established in :func:`verify`, which is the
    only writer of that field; this function stays a pure reader so the guard's
    own re-classification (the OMN-15712 filter) cannot disagree with it.
    """
    if status.error:
        return True
    if status.state == "MERGED":
        return False
    if status.superseded_by:
        return False
    if status.state == "OPEN":
        return True
    if status.state == "CLOSED":
        return True  # closed-without-merge
    if status.merge_state in BLOCKING_MERGE_STATES:
        return True
    return False


def parse_note_successor(note: str, closed_repo: str) -> PRRef | None:
    """Return the successor a CLOSED PR's own note names, or None (OMN-13856).

    Reads the first line of ``note`` carrying a supersession phrase, and takes
    the first PR reference to the right of the phrase: a pull URL, an
    ``owner/repo#N`` citation, or a bare ``#N`` (which GitHub resolves to the
    closed PR's own repository). A line naming no reference ("superseded by
    later work") names nothing to verify and yields None. Pure function.
    """
    for line in note.splitlines():
        phrase = _SUPERSESSION_PHRASE_RE.search(line)
        if phrase is None:
            continue
        right = line[phrase.end() :]
        found: list[tuple[int, PRRef]] = []
        for m in _PR_URL_RE.finditer(right):
            found.append(
                (
                    m.start(),
                    PRRef(number=int(m.group(3)), repo=f"{m.group(1)}/{m.group(2)}"),
                )
            )
        for m in _PR_OWNER_REPO_HASH_RE.finditer(right):
            found.append((m.start(), PRRef(number=int(m.group(2)), repo=m.group(1))))
        for m in _NOTE_BARE_REF_RE.finditer(right):
            found.append((m.start(), PRRef(number=int(m.group(1)), repo=closed_repo)))
        if found:
            return min(found, key=lambda item: item[0])[1]
    return None


def _names_ticket(title: str, ticket_id: str) -> bool:
    return bool(re.search(rf"\b{re.escape(ticket_id)}\b", title, re.IGNORECASE))


def _apply_declared_supersessions(
    statuses: list[PRStatus],
    declarations: dict[tuple[str | None, int], SupersessionDeclaration],
    fetcher: Any,
    ticket_id: str | None = None,
) -> None:
    """Record a PROVEN supersession on each eligible status, in place.

    OMN-18749. Eligible means CLOSED, unmerged and readable: an OPEN citation
    can still merge and must keep blocking on its own account, and an errored
    probe is "I could not check", which never resolves to "so I will ignore
    it". The successor is probed through the same fetcher as every other
    citation, and only a MERGED verdict counts — an open, closed or unreadable
    successor leaves the citation blocking, as does one that resolves to no
    repository.

    OMN-13856 adds a second source for the declaration: the closed PR's OWN
    closing note (its body or a conversation comment), which is where a lane
    records the recut when it closes a PR in favour of another. It is weaker
    than a ticket declaration, because it is not written on the ticket, so it
    carries one more condition: the MERGED successor must name ``ticket_id`` in
    its title, which is what binds the successor's work to THIS ticket rather
    than to whatever the note happens to point at. With no ``ticket_id`` the
    note is not read at all. The declaration still reads in one direction only
    ("<this closed PR> superseded by <successor>"), since it is the closed PR's
    own note; a successor vouching for itself is never read.
    """
    by_key = {(s.ref.repo, s.ref.number): s for s in statuses}
    for status in statuses:
        if status.error or status.state != "CLOSED" or status.ref.repo is None:
            continue
        declaration = declarations.get((status.ref.repo, status.ref.number))
        from_note = False
        successor: PRRef | None = None
        if declaration is not None:
            successor = declaration.successor
        elif ticket_id:
            for note in status.closing_notes:
                successor = parse_note_successor(note, status.ref.repo)
                if successor is not None:
                    from_note = True
                    break
        if successor is None:
            continue
        successor_status = by_key.get((successor.repo, successor.number))
        if successor_status is None:
            # The successor need not itself be a cited product PR — it is
            # commonly named only on the declaration line — so probe it.
            successor_status = fetcher(successor)
        if successor_status.error or successor_status.state != "MERGED":
            continue
        if from_note and not _names_ticket(successor_status.title, ticket_id or ""):
            continue
        status.superseded_by = f"{successor.repo}#{successor.number}"


def _closed_unmerged_remedy(
    status: PRStatus,
    declaration: SupersessionDeclaration | None,
) -> str:
    """The actionable half of a CLOSED-unmerged refusal (OMN-18749)."""
    citation = f"{status.ref.repo}#{status.ref.number}"
    if declaration is None:
        return (
            f"closed without merging, so merging it is not possible. If the "
            f"work landed elsewhere, declare that on one line of the ticket "
            f"description — `{citation} superseded by OmniNode-ai/<repo>#<N>` "
            f"— or in a comment on the closed PR (`Superseded by #<N>`, whose "
            f"title must carry this ticket's id); either way that successor "
            f"must itself be merged. If nothing replaced "
            f"it, this is abandoned work and the citation belongs off the "
            f"ticket."
        )
    if declaration.successor is None:
        return (
            f"closed without merging, and the successor declared for it "
            f"resolves to no repository. Spell it as `OmniNode-ai/<repo>#<N>` "
            f"or a full GitHub URL on the declaration line: "
            f"{declaration.line!r}"
        )
    successor = f"{declaration.successor.repo}#{declaration.successor.number}"
    return (
        f"closed without merging, and its declared successor {successor} is "
        f"not merged either. A chain of unmerged pull requests is still "
        f"unlanded work."
    )


def verify(
    description: str,
    labels: list[str] | None,
    default_repo: str | None = None,
    fetcher: Any = fetch_pr_status,
    prober: Callable[[int], bool] | None = None,
    ticket_id: str | None = None,
) -> VerificationResult:
    """Run the full verification against a ticket description.

    Returns allowed=True if the transition should proceed, allowed=False with a
    reason string describing the blocking PRs otherwise.

    OMN-14641: the cited-PR merge check runs BEFORE the ``close-if-done``
    exemption. The label was previously a blanket merge-check bypass — a ticket
    carrying it could flip Done with its linked product PR still OPEN (the
    OMN-14582 false-Done). The exemption now applies *only* when no product PR
    is cited (decision-only tickets, epic roll-ups); it can never waive an
    open/unmerged cited PR.

    ``prober`` (OMN-15782) is forwarded to :func:`is_weak_signal_ref` so a
    bare ``#N`` reference to a genuine ``onex_change_control`` PR classifies
    weak the same as the fully-qualified spelling. Defaults to ``None`` (no
    live lookup) for test/pure-function callers; :func:`main` passes the real
    :func:`probe_occ_membership` on the live path.

    ``ticket_id`` (OMN-13856) enables supersession read from a closed PR's own
    closing note; see :func:`_apply_declared_supersessions`. Without it only a
    ticket-declared supersession counts.

    OMN-13856 (the OMN-14642 refusal): a bare ``PR #N`` with no other anchor
    is resolved through the commit SHA its own line names, when it names one;
    see :func:`_resolve_commit_anchored_refs`. Otherwise it still refuses, the
    OMN-15025 / OMN-18747 fail-closed shape.
    """
    # Product PR references only — weak-signal (onex_change_control) refs are
    # filtered out so an OCC evidence companion never gates a product Done.
    refs = [
        ref
        for ref in parse_pr_refs(description, default_repo=default_repo)
        if not is_weak_signal_ref(ref, prober=prober)
    ]

    if refs:
        statuses = _resolve_commit_anchored_refs(refs, fetcher)
        declarations = parse_supersession_declarations(
            description, default_repo=default_repo
        )
        _apply_declared_supersessions(
            statuses, declarations, fetcher, ticket_id=ticket_id
        )
        blocking = [s for s in statuses if classify_blocking(s)]
        if not blocking:
            return VerificationResult(
                allowed=True,
                reason="all_prs_merged",
                pr_statuses=statuses,
            )

        lines = ["Cannot mark Done — referenced PRs are not merged:"]
        for status in blocking:
            repo = status.ref.repo or "?"
            if status.error:
                lines.append(f"  - {repo}#{status.ref.number}: {status.error}")
            else:
                lines.append(
                    f"  - {repo}#{status.ref.number}: state={status.state} "
                    f"mergeState={status.merge_state}"
                )
                # OMN-18749: "merge it" is not a remedy for something already
                # closed, and that is exactly what this message used to leave
                # the reader with. Say what can actually be done instead, and
                # say it with the citation already filled in.
                if status.state == "CLOSED" and status.ref.repo:
                    lines.append(
                        "      "
                        + _closed_unmerged_remedy(
                            status,
                            declarations.get((status.ref.repo, status.ref.number)),
                        )
                    )
        lines.append(
            "A `close-if-done` label/frontmatter does NOT waive an open cited "
            "PR (OMN-14641) — merge the linked PR, or cite the merged "
            "implementing PR. The exemption only applies when no product PR is "
            "cited."
        )
        return VerificationResult(
            allowed=False,
            reason="\n".join(lines),
            pr_statuses=statuses,
        )

    # No product PR cited — the exemption may legitimately apply (decision-only
    # tickets, epic ALL_CHILDREN_DONE roll-ups that carry the label).
    if is_exempt(description, labels):
        return VerificationResult(allowed=True, reason="exempt")

    # No PR references and no exemption — trust the human; nothing to verify.
    return VerificationResult(allowed=True, reason="no_pr_references")


# ---------------------------------------------------------------------------
# Deploy-readback path (OMN-14792) — scoped implementing-PR scan + marker parse
# ---------------------------------------------------------------------------


def line_is_scratch_annotated(line: str) -> bool:
    """Return True if a description line explicitly labels a scratch/test PR.

    Used only by :func:`parse_implementing_pr_refs` to drop a live-mint /
    throwaway PR reference (e.g. an intentionally-closed readback PR) from the
    DoD-implementing set. Pure function.
    """
    return bool(_SCRATCH_ANNOTATION_RE.search(line))


def _split_paragraphs(text: str) -> list[list[str]]:
    """Split ``text`` into blank-line-delimited paragraphs (lists of lines).

    A run of consecutive non-blank lines forms one paragraph; whitespace-only
    lines are delimiters and are dropped. Pure function.
    """
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append(current)
            current = []
    if current:
        paragraphs.append(current)
    return paragraphs


def parse_implementing_pr_refs(
    description: str,
    default_repo: str | None = None,
    prober: Callable[[int], bool] | None = None,
) -> list[PRRef]:
    """Extract only the *DoD-implementing* product PR references.

    This is the scoped counterpart to :func:`parse_pr_refs`, used exclusively by
    the deploy-readback path (OMN-14792). It answers "which PRs does this ticket
    cite as implementing the work?" — as opposed to every ``#N`` string that
    happens to appear in the body — by excluding:

    * lines explicitly annotated scratch/throwaway/live-mint/do-not-merge
      (:func:`line_is_scratch_annotated`) — a disposable readback PR is not
      implementing work;
    * bare ``#N`` references that cannot be resolved to a repo (no
      ``default_repo``) — an unrepo'd ``#N`` in a historical merge-chain
      narrative is context, not a verifiable DoD citation, and the
      unconditional path only ever surfaced it as an un-verifiable error; and
    * weak-signal ``onex_change_control`` evidence-companion PRs
      (:func:`is_weak_signal_ref`), as elsewhere.

    A fully-qualified ``https://github.com/owner/repo/pull/N`` URL in a
    non-scratch paragraph is always kept — that is a real, verifiable
    implementing citation. Scratch annotation is scoped to the blank-line-
    delimited paragraph the reference sits in, so a label line followed by the
    URL on the next line (the common Linear layout) is correctly excluded.
    Pure function when ``prober`` is left at its default (``None``) — passing
    a live prober (OMN-15782, see :func:`is_weak_signal_ref`) makes this
    impure (one ``gh`` call per unresolved bare weak-signal candidate).
    """
    refs: dict[tuple[str, int], PRRef] = {}

    for paragraph in _split_paragraphs(description):
        # A paragraph is scratch if ANY of its lines carries a scratch/throwaway
        # annotation — the label may precede or follow the reference line.
        if any(line_is_scratch_annotated(line) for line in paragraph):
            continue
        block = "\n".join(paragraph)

        for url_match in _PR_URL_RE.finditer(block):
            owner = url_match.group(1)
            repo_name = url_match.group(2)
            num = int(url_match.group(3))
            full_repo = f"{owner}/{repo_name}"
            refs[(full_repo, num)] = PRRef(number=num, repo=full_repo)

        # OMN-14882: Linear-rewritten `<pull-request>` tag / markdown-link
        # embed — see _PR_OWNER_REPO_HASH_RE.
        for owner_repo_match in _PR_OWNER_REPO_HASH_RE.finditer(block):
            full_repo = owner_repo_match.group(1)
            num = int(owner_repo_match.group(2))
            key = (full_repo, num)
            if key not in refs:
                refs[key] = PRRef(number=num, repo=full_repo)

        # A bare ``#N`` is only an implementing citation when it resolves to a
        # concrete repo. Without a default repo it is unverifiable narrative and
        # is dropped rather than surfaced as a false-blocking "cannot verify".
        if default_repo:
            for num_match in _PR_NUMBER_RE.finditer(block):
                num = int(num_match.group(1))
                key = (default_repo, num)
                if key not in refs:
                    refs[key] = PRRef(number=num, repo=default_repo, bare=True)

    return [ref for ref in refs.values() if not is_weak_signal_ref(ref, prober=prober)]


def verify_implementing(
    description: str,
    labels: list[str] | None,
    default_repo: str | None = None,
    fetcher: Any = fetch_pr_status,
    prober: Callable[[int], bool] | None = None,
) -> VerificationResult:
    """Scoped merge check for the deploy-readback path (OMN-14792).

    Verifies only the DoD-*implementing* product PRs
    (:func:`parse_implementing_pr_refs`) — scratch/throwaway PRs and
    unresolvable narrative ``#N`` refs are ignored. Returns ``allowed=True``
    with reason ``no_implementing_pr`` when nothing implementing is cited (the
    common runtime-deploy shape: the DoD is a live readback, not a PR).

    This is invoked ONLY when a deploy-readback marker is present, and it exists
    so the marker can never waive an unmerged *real* implementing PR — the same
    integrity rule OMN-14641 applied to the ``close-if-done`` label. ``labels``
    is accepted for signature parity with :func:`verify` but is not consulted
    here (the marker, not a label, authorizes this path).
    """
    del labels  # signature parity with verify(); not consulted on this path.

    refs = parse_implementing_pr_refs(
        description, default_repo=default_repo, prober=prober
    )
    if not refs:
        return VerificationResult(allowed=True, reason="no_implementing_pr")

    statuses = [fetcher(ref) for ref in refs]
    blocking = [s for s in statuses if classify_blocking(s)]
    if not blocking:
        return VerificationResult(
            allowed=True,
            reason="all_implementing_prs_merged",
            pr_statuses=statuses,
        )

    lines = ["Cannot mark Done — a DoD-implementing PR is not merged:"]
    for status in blocking:
        repo = status.ref.repo or "?"
        if status.error:
            lines.append(f"  - {repo}#{status.ref.number}: {status.error}")
        else:
            lines.append(
                f"  - {repo}#{status.ref.number}: state={status.state} "
                f"mergeState={status.merge_state}"
            )
    lines.append(
        "A deploy-readback marker does NOT waive an open implementing PR "
        "(OMN-14792 / OMN-14641) — merge the implementing PR, or remove the "
        "citation if it is not part of this ticket's DoD."
    )
    return VerificationResult(
        allowed=False,
        reason="\n".join(lines),
        pr_statuses=statuses,
    )


def parse_deploy_readback_marker(description: str) -> str | None:
    """Return the evidence body of a ``deploy-readback-proven:`` marker, or None.

    Recognises a frontmatter/body line of the form::

        deploy-readback-proven: <probe + exit-0 receipt evidence>

    (leading list/heading punctuation is tolerated, key is case-insensitive,
    ``-`` and ``_`` spellings both accepted). Returns the stripped evidence
    value when present and NON-EMPTY, else ``None``.

    A content-free marker (``deploy-readback-proven:`` with no value) is
    deliberately NOT accepted: requiring the probe/receipt body prevents the
    marker from degrading into a blanket bypass token the way the bare
    ``close-if-done`` label once did (OMN-14641). Pure function.
    """
    for line in description.splitlines():
        stripped = line.strip().lstrip("-*# ").strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        if key.strip().lower() in DEPLOY_READBACK_MARKER_KEYS and value.strip():
            return value.strip()
    return None


def parse_live_state_marker(description: str, now: datetime) -> str | None:
    """Return the evidence of a valid ``live-state-proven:`` marker, or None.

    OMN-13856 (the OMN-13907 refusal). Recognises a body line of the form::

        live-state-proven: 2026-09-25 `ls $OMNI_HOME/omni_worktrees/X` -> absent

    and accepts it only when its value carries BOTH a readback date
    (``YYYY-MM-DD``) that is not in the future and no more than
    ``LIVE_STATE_MAX_AGE_DAYS`` old relative to ``now`` (UTC), AND the probe
    that produced the readback quoted in backticks. A marker with no date, no
    probe, a stale date or a future date is not evidence and returns None. The
    first date on the line is the readback date. Pure function: it checks the
    shape and freshness of the attestation, not its truth, the same limit the
    deploy-readback marker has.
    """
    today = now.astimezone(UTC).date()
    for line in description.splitlines():
        stripped = line.strip().lstrip("-*# ").strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        if key.strip().lower() not in LIVE_STATE_MARKER_KEYS:
            continue
        value = value.strip()
        date_match = _ISO_DATE_RE.search(value)
        if date_match is None or _BACKTICK_PROBE_RE.search(value) is None:
            continue
        try:
            readback = date(
                int(date_match.group(1)),
                int(date_match.group(2)),
                int(date_match.group(3)),
            )
        except ValueError:
            continue
        age_days = (today - readback).days
        if 0 <= age_days <= LIVE_STATE_MAX_AGE_DAYS:
            return value
    return None


def _load_stdin_tool_call() -> dict[str, Any]:
    try:
        parsed = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


_LINEAR_GRAPHQL_QUERY = """
query($id: String!) {
  issue(id: $id) {
    id
    title
    description
    state { name }
    labels { nodes { name } }
    attachments { nodes { url } }
  }
}
""".strip()

_LINEAR_API_URL = "https://api.linear.app/graphql"


def _fetch_linear_issue(ticket_id: str) -> dict[str, Any] | None:
    """Fetch a Linear issue via the GraphQL API.

    Returns None on network/auth failure so the caller can decide whether to
    fail-open or fail-closed.  Missing LINEAR_API_KEY → fail-open (returns {}
    so the hook does not block the user when credentials aren't configured).
    """
    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        sys.stderr.write(
            "[linear_done_verify] LINEAR_API_KEY not set — skipping Live fetch, "
            "failing open.\n"
        )
        return {}

    payload = json.dumps(
        {"query": _LINEAR_GRAPHQL_QUERY, "variables": {"id": ticket_id}}
    ).encode()
    req = urllib.request.Request(  # noqa: S310
        _LINEAR_API_URL,
        data=payload,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            body = resp.read()
    except (urllib.error.URLError, OSError):
        # HTTPError (non-2xx) is a subclass of URLError and caught here too.
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None

    issue = (data.get("data") or {}).get("issue")
    if not isinstance(issue, dict):
        return None

    label_nodes = (issue.get("labels") or {}).get("nodes") or []
    attachment_nodes = (issue.get("attachments") or {}).get("nodes") or []
    return {
        "id": issue.get("id"),
        "title": issue.get("title"),
        "description": issue.get("description") or "",
        "state": (issue.get("state") or {}).get("name") or "",
        "labels": [n.get("name") for n in label_nodes if n.get("name")],
        # Linear GitHub-integration links the PR as an attachment, NOT as a
        # `#N` mention in the description. Surface those URLs so the merge check
        # sees the *linked* PR even when it is not cited in the ticket body —
        # this is the OMN-14582 false-Done shape (label-driven close while the
        # linked PR was still OPEN). See OMN-14641.
        "attachment_urls": [n.get("url") for n in attachment_nodes if n.get("url")],
    }


def augment_description_with_attachments(
    description: str, attachment_urls: list[str] | None
) -> str:
    """Append linked-PR attachment URLs to the description for verification.

    The merge check parses PR references out of free text, so appending the
    Linear GitHub-integration attachment URLs (which carry the *linked* PR) lets
    a status-only Done flip be verified against the linked PR even when the
    ticket body does not cite it with a `#N` mention. Non-PR attachment URLs are
    harmlessly ignored by :func:`parse_pr_refs`. Pure function.
    """
    urls = [u for u in (attachment_urls or []) if u]
    if not urls:
        return description
    return description + "\n\n" + "\n".join(urls)


def main() -> int:
    call = _load_stdin_tool_call()
    tool_name = call.get("tool_name", "")
    if tool_name not in {
        "mcp__linear-server__save_issue",
        "mcp__linear-server__update_issue",
    }:
        return 0

    params: dict[str, Any] = call.get("tool_input") or {}
    state_value = str(params.get("state") or params.get("status") or "")
    # Cancel/Duplicate/Won't-do close the ticket without requiring a PR;
    # short-circuit before any verification logic. (OMN-10047)
    if is_cancel_state(state_value):
        return 0
    if not is_done_state(state_value):
        return 0

    ticket_id = str(params.get("id") or params.get("issueId") or "")
    description = str(params.get("description") or "")
    labels: list[str] = list(params.get("labels") or [])

    # If the description wasn't passed on this update (common: status-only
    # updates), fetch the live ticket to read DoD references.
    # Semantics of _fetch_linear_issue return values:
    #   None  → network/API failure → fail-closed (block transition)
    #   {}    → LINEAR_API_KEY missing → fail-open (skip PR check)
    #   {...} → real issue data → use description + labels from response
    if not description and ticket_id:
        issue = _fetch_linear_issue(ticket_id)
        if issue is None:
            decision = {
                "decision": "block",
                "reason": (
                    f"[OMN-8415 done-state PR verify] Could not fetch Linear "
                    f"ticket {ticket_id} to read DoD; refusing to mark Done "
                    "without verifying referenced PRs. Retry once Linear is "
                    "reachable or pass the description in the save_issue call."
                ),
            }
            sys.stderr.write(json.dumps(decision) + "\n")
            return 2
        description = str(issue.get("description") or "")
        labels = labels or list(issue.get("labels") or [])
        # Fold in the linked-PR attachment URLs so the merge check sees the PR
        # linked via the Linear GitHub integration, not only PRs cited in the
        # body (OMN-14641 — the OMN-14582 linked-but-uncited false-Done shape).
        description = augment_description_with_attachments(
            description, list(issue.get("attachment_urls") or [])
        )

    default_repo = os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None

    # OMN-15782: wire the live onex_change_control membership prober so a
    # bare `#N` reference to a genuine OCC PR classifies weak the same as
    # `owner/repo#N` — see is_weak_signal_ref()/probe_occ_membership().
    result = verify(
        description,
        labels,
        default_repo=default_repo,
        prober=probe_occ_membership,
        ticket_id=ticket_id or None,
    )
    if result.allowed:
        return 0

    decision = {
        "decision": "block",
        "reason": f"[OMN-8415 done-state PR verify] {result.reason}",
    }
    sys.stderr.write(json.dumps(decision) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
