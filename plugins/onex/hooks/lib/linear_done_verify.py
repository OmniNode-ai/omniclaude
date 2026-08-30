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


@dataclass
class PRStatus:
    ref: PRRef
    state: str  # OPEN, CLOSED, MERGED
    merge_state: str  # CLEAN, BLOCKED, DIRTY, BEHIND, UNKNOWN, etc.
    error: str | None = None

    @property
    def is_blocking(self) -> bool:
        if self.error:
            return True
        if self.state == "MERGED":
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


def parse_pr_refs(text: str, default_repo: str | None = None) -> list[PRRef]:
    """Extract PR references from a ticket description.

    Finds both `#123` shorthand and full `https://github.com/owner/repo/pull/N`
    URLs. Bare `#N` references use `default_repo` if provided.
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

    repo_key = default_repo or ""
    for num_match in _PR_NUMBER_RE.finditer(text):
        num = int(num_match.group(1))
        key = (repo_key, num)
        if key in refs:
            continue
        refs[key] = PRRef(number=num, repo=default_repo, bare=True)

    return list(refs.values())


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
    ``gh pr view`` call per unresolved bare ref; explicitly-qualified refs
    never reach this (repo already known, no probe needed). Any error (gh
    unavailable, timeout, PR not found) is treated as "not a member" —
    fail-closed toward "not weak" so this can never *waive* a genuine
    blocking product PR, only correctly filter a genuine OCC one.
    """
    occ_repo = next(iter(_WEAK_SIGNAL_REPOS))
    repo = f"{DEFAULT_OWNER}/{occ_repo}"
    cmd = ["gh", "pr", "view", str(number), "--repo", repo, "--json", "number"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return proc.returncode == 0


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


def fetch_pr_status(ref: PRRef, timeout: float = 15.0) -> PRStatus:
    """Query GitHub for PR state via `gh pr view`."""
    repo = ref.repo
    if not repo:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=(
                f"PR #{ref.number} has no associated repo; cannot verify. "
                "Include a full GitHub URL in the ticket DoD."
            ),
        )

    cmd = [
        "gh",
        "pr",
        "view",
        str(ref.number),
        "--repo",
        repo,
        "--json",
        "state,mergeStateStatus,url",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=f"Timeout querying {repo}#{ref.number}",
        )
    except FileNotFoundError:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error="gh CLI not available in PATH",
        )

    if proc.returncode != 0:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=f"gh pr view failed for {repo}#{ref.number}: {proc.stderr.strip()}",
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=f"Could not parse gh output: {exc}",
        )

    return PRStatus(
        ref=ref,
        state=str(data.get("state", "UNKNOWN")).upper(),
        merge_state=str(data.get("mergeStateStatus", "UNKNOWN")).upper(),
    )


def classify_blocking(status: PRStatus) -> bool:
    """Return True if this PR should block a Done transition."""
    if status.error:
        return True
    if status.state == "MERGED":
        return False
    if status.state == "OPEN":
        return True
    if status.state == "CLOSED":
        return True  # closed-without-merge
    if status.merge_state in BLOCKING_MERGE_STATES:
        return True
    return False


def verify(
    description: str,
    labels: list[str] | None,
    default_repo: str | None = None,
    fetcher: Any = fetch_pr_status,
    prober: Callable[[int], bool] | None = None,
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
    """
    # Product PR references only — weak-signal (onex_change_control) refs are
    # filtered out so an OCC evidence companion never gates a product Done.
    refs = [
        ref
        for ref in parse_pr_refs(description, default_repo=default_repo)
        if not is_weak_signal_ref(ref, prober=prober)
    ]

    if refs:
        statuses = [fetcher(ref) for ref in refs]
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
        description, labels, default_repo=default_repo, prober=probe_occ_membership
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
