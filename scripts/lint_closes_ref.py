#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Closes-reference gate: require a STRONG close signal on product PRs [OMN-14641].

## Why

A merged PR should close *its own* Linear ticket. Per doctrine
(``reference_linear_pr_ticket_close_reconciliation``) the only STRONG,
safe-to-close signals are:

* a ``Closes|Fixes|Resolves OMN-####`` magic-word reference in the PR body, or
* a **branch-primary** head branch — the first ``OMN-####`` token in the branch
  name (``jonah/omn-14641-...``), which Linear/GitHub treat as the owning ticket.

A **bare** ``OMN-####`` mention (link-only token) is a WEAK signal and does NOT
close a ticket. The 2026-07-15 false-Done incident (OMN-14582) was manufactured
by a ``close-if-done`` label sweep that closed tickets on bare cross-references
with the linked PR still OPEN. This gate makes the strong-signal requirement
mechanical (CLAUDE.md Rule #5 — enforcement, not detection) so that ticket
closure is driven by a real merge of a strongly-bound PR, never a label.

## Verdict

PASS when any of:

* title is an automated/release PR (deps bump / release) — nothing to close;
* head branch is an evidence / OCC companion (``evidence/*``, ``occ/*``) — a WEAK
  signal that must never by itself close a product ticket (deliverable 3);
* body carries an explicit ``[closes-ref-exempt: <reason>]`` escape (ticketless
  chore/docs/hotfix);
* the PR carries a STRONG close signal (Closes-word OR branch-primary).

FAIL otherwise, with guidance.

## Exit codes

- 0 — PASS
- 1 — FAIL (no strong close signal on a product PR)

## Usage

CI passes the PR fields via environment:

    PR_TITLE=... PR_BODY=... PR_HEAD_REF=... python3 scripts/lint_closes_ref.py

## Refs

- OMN-14641 (this gate), OMN-14582 (the confirmed false-Done),
  memory ``reference_linear_pr_ticket_close_reconciliation``.
"""

from __future__ import annotations

import os
import re
import sys

# Closing magic words Linear/GitHub honor, followed by an OMN ticket.
_CLOSES_WORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[\s:]+OMN-\d+",
    re.IGNORECASE,
)

# Branch-primary: the FIRST OMN token in the branch is the owning ticket.
# Matches `jonah/omn-14641-...`, `omn-14641-...`, `OMN-14641/...`.
_BRANCH_OMN_RE = re.compile(r"OMN-\d+", re.IGNORECASE)

# Explicit escape for genuinely ticketless PRs. Deliberately NOT a `[skip-*]`
# token (that form is globally banned by the Rule #10 skip-token gate) — this
# marker requires a non-empty reason.
_SKIP_RE = re.compile(r"\[closes-ref-exempt:\s*\S.*?\]", re.IGNORECASE)

# Automated / release PRs: nothing to close. Mirrors pr-title-check exemptions.
_RELEASE_TITLE_RE = re.compile(
    r"^\s*(?:chore\(deps|build\(deps|Bump\b|chore:\s*release|chore\(release\)|release:)",
    re.IGNORECASE,
)

# Evidence / OCC companion branches — WEAK close signals (deliverable 3).
_WEAK_BRANCH_RE = re.compile(
    r"(?:^|/)(?:evidence|occ|occ-companion)[-/]", re.IGNORECASE
)


def has_closes_word(body: str) -> bool:
    """Return True if the PR body carries a ``Closes/Fixes/Resolves OMN-####``."""
    return bool(_CLOSES_WORD_RE.search(body or ""))


def is_branch_primary(head_ref: str) -> bool:
    """Return True if the head branch names an owning OMN ticket (branch-primary)."""
    if not head_ref or _WEAK_BRANCH_RE.search(head_ref):
        return False
    return bool(_BRANCH_OMN_RE.search(head_ref))


def is_weak_companion_branch(head_ref: str) -> bool:
    """Return True for evidence/OCC-companion branches (weak close signal)."""
    return bool(head_ref and _WEAK_BRANCH_RE.search(head_ref))


def is_release_title(title: str) -> bool:
    """Return True for automated dependency-bump / release PR titles."""
    return bool(_RELEASE_TITLE_RE.match(title or ""))


def has_skip_escape(body: str) -> bool:
    """Return True if the body carries a ``[closes-ref-exempt: <reason>]`` escape."""
    return bool(_SKIP_RE.search(body or ""))


def evaluate(title: str, body: str, head_ref: str) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a PR's close-signal posture.

    Pure function — all inputs are plain strings, no I/O.
    """
    if is_release_title(title):
        return True, "release/deps PR — no ticket to close"
    if is_weak_companion_branch(head_ref):
        return True, "evidence/OCC companion branch — weak signal, not gated"
    if has_skip_escape(body):
        return True, "explicit [closes-ref-exempt] escape present"
    if has_closes_word(body):
        return True, "strong signal: Closes/Fixes/Resolves OMN-#### in body"
    if is_branch_primary(head_ref):
        return True, f"strong signal: branch-primary head branch '{head_ref}'"
    return (
        False,
        "no STRONG close signal found. Add a `Closes OMN-####` (or "
        "`Fixes`/`Resolves`) line to the PR body, or use a branch-primary head "
        "branch named `omn-####-...`. A bare `OMN-####` mention is a WEAK signal "
        "and does NOT close a ticket (OMN-14641). For a genuinely ticketless PR, "
        "add `[closes-ref-exempt: <reason>]` to the body.",
    )


def main() -> int:
    title = os.environ.get("PR_TITLE", "")
    body = os.environ.get("PR_BODY", "")
    head_ref = os.environ.get("PR_HEAD_REF", "")

    ok, reason = evaluate(title, body, head_ref)
    if ok:
        print(f"closes-ref-gate: PASS — {reason}")
        return 0

    print(f"closes-ref-gate: FAIL — {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
