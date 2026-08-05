#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Done-flip durable-evidence guard [OMN-13856].

L1 of the layered Done-flip durable-evidence gate
(``docs/plans/2026-07-02-done-flip-durable-evidence-gate-design.md``). This is
the single client-side chokepoint that every ``save_issue`` / ``update_issue``
caller passes through — foreground MCP writes included, which is the path the
``wf_1628d9a5`` incident used (bulk Backlog→Done, ``startedAt=null``, zero
durable evidence). No merged node-side gate covers that path.

It MERGES the two previously-separate guards into ONE fail-closed decision:

* ``pre_tool_use_dod_completion_guard.sh`` receipt semantics (a ``status == PASS``
  ``node_dod_verify`` receipt bound to the ticket), and
* ``linear_done_verify.py`` merged-PR semantics (every PR cited in the ticket
  description is ``MERGED``).

Neither guard ALONE closes the incident: the DoD guard fails OPEN when its
evidence root is unset, and the PR guard ALLOWS when the ticket cites no PR at
all (``no_pr_references``) — exactly the incident shape. A single guard is
required because the pass condition is a *disjunction* ("a merged-PR citation
OR a receipt-PASS"), and a hook can only block or pass through — two independent
hooks each pass on their own criterion and the fabricated Done slips through.

Decision (fail-closed — the default outcome for a real Done-flip is BLOCK):

1. Not a ``save_issue``/``update_issue`` call, or not a Done-class target state
   → ALLOW (nothing to verify).
2. cancel-class target state (``canceled/duplicate/won't do``) → ALLOW.
2b. Unchecked acceptance-criteria checkbox gate (OMN-15030): if the ticket's
    current description contains any unchecked GFM task-list box (``- [ ]``)
    → BLOCK, unconditionally — no later evidence path (merged PR, OCC receipt,
    exempt label) waives this. Every later path proves *some* evidence exists;
    none of them prove the ticket's own stated acceptance criteria were met.
    OMN-13991 is the concrete incident this closes: a genuinely merged, cited,
    implementing PR still under-delivered against the ticket's own DoD text,
    and passed every existing presence-check because "merged" was treated as
    sufficient. See :func:`find_unchecked_acceptance_boxes`.
2a. Durable evidence path C — deploy-readback marker (OMN-14792): a
    runtime-deploy ticket whose DoD is a live readback, not a merged product PR
    (``node_dod_verify`` structurally skips such tickets —
    ``reference_dod_verify_cannot_close_deploy_tickets`` — and they close via an
    operator deliberate-Done). When a ``deploy-readback-proven: <probe + exit-0
    receipt>`` marker with real evidence is present, the merge check is SCOPED to
    DoD-*implementing* PRs (``verify_implementing``): full-URL / resolvable bare
    ``#N`` citations, EXCLUDING scratch/throwaway/live-mint-annotated PRs and
    unresolvable merge-chain-narrative ``#N`` refs. No unmerged implementing PR
    → ALLOW; an unmerged implementing PR still BLOCKS (the marker is not a
    blanket bypass — the OMN-14641 lesson). This closes the OMN-14437 false block
    where the guard treated a closed scratch live-mint PR and bare narrative
    numbers as blocking DoD evidence.
3. Durable evidence path A — merged PR: if the ticket cites (or links via a
   Linear attachment) any *product* PR and every one is ``MERGED`` → ALLOW. If
   any is open / unmerged → BLOCK. (A "superseded-by-merged-sibling" close is a
   merged-PR citation and is accepted here.) ``onex_change_control`` evidence /
   OCC-receipt PRs are WEAK signals and are filtered out — they never gate a
   product Done in either direction (OMN-14641, deliverable 3).
3a. Exemption carve-out — an explicit ``close-if-done`` label / frontmatter
    (covers decision-only tickets and epic ALL_CHILDREN_DONE roll-ups) → ALLOW,
    but ONLY when no product PR is cited/linked. OMN-14641: the label was
    previously a blanket merge-check bypass, so a ticket carrying it flipped Done
    with its linked product PR still OPEN (the OMN-14582 false-Done). The label
    can no longer waive an open cited/linked PR — that path BLOCKS at step 3.
4. Durable evidence path B — OCC receipt on ``origin/dev``: a schema-valid
   ``status == PASS`` ``node_dod_verify`` receipt bound to the ticket under
   ``drift/dod_receipts/<TICKET>/`` on ``origin/dev`` of the local
   onex_change_control clone → ALLOW.
5. Otherwise → BLOCK. A Done-flip with no merged-PR citation and no PASS receipt
   is refused; if the evidence cannot be resolved at all, the guard STILL BLOCKS
   (never fail-open on a fake-Done — design requirement 4).

Why ``origin/dev`` git-backed (freshness + determinism) — OMN-13857 findings:
    Two paths that LOOK authoritative are broken for a Done-flip gate:
    (a) the remote ``node_dod_verify`` Kafka consumer answers from a STALE
        onex_change_control mirror (it returned "no contract" for a same-day
        ticket that genuinely had one) — gating on it would FALSE-BLOCK
        legitimate recent Done-flips;
    (b) running ``node_dod_verify`` locally reads the clone's WORKING TREE — if
        that tree is behind ``origin/dev`` a just-merged receipt is invisible,
        the same false-block failure mode, just local; it also depends on an
        ambient ``$CONTRACT_REPO_DIR`` that false-negatives when unset.
    This guard sidesteps BOTH: it resolves the OCC clone deterministically from
    ``OMNI_HOME`` (``$OMNI_HOME/onex_change_control``), does a targeted
    ``git fetch origin dev`` to refresh, and reads the receipt directly off the
    ``origin/dev`` ref (``git ls-tree`` / ``git show``) — fresh, git-backed, no
    remote-consumer dependency and no ambient-env dependency. This mirrors the
    OMN-13853 ``OccReceiptSubprocessProbe`` approach. The remote-consumer and
    ``$CONTRACT_REPO_DIR`` node-side defects are tracked in OMN-13857.

Exit codes (via :func:`main`):
    0 — allow the tool call
    2 — block the tool call (JSON decision on stderr)
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404 - fixed-argv git invocations, no shell
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Sibling module (same lib/ dir). The shell wrapper runs this file directly, so
# its directory is on sys.path[0] and the import resolves without packaging.
from linear_done_verify import (
    PRStatus,
    augment_description_with_attachments,
    classify_blocking,
    fetch_pr_status,
    is_cancel_state,
    is_done_state,
    is_exempt,
    parse_deploy_readback_marker,
    verify,
    verify_implementing,
)

_LINEAR_TOOLS = frozenset(
    {"mcp__linear-server__save_issue", "mcp__linear-server__update_issue"}
)

# OMN-15030: unchecked markdown acceptance-criteria checkbox gate.
#
# Every evidence path above this check (merged-PR citation, OCC receipt,
# exempt label) proves *something shipped* — none of them prove the shipped
# thing satisfies what the ticket's own author wrote down as the acceptance
# bar. OMN-13991 is the concrete incident: a genuinely MERGED, genuinely
# CITED, genuinely implementing PR (omnimarket#1838) still under-delivered
# against the ticket's own DoD text ("Staged: shadow -> measured ->
# enforcing"), and every existing presence-check (this guard's merged-PR
# path, node_linear_triage's close_evidence_gate, DurableEvidenceGate's
# CONTRACT_CITES_MERGE_COMMIT) passes on a merged-but-incomplete PR by
# design — "merged" is not "matches the ticket's stated DoD."
#
# A mechanical presence-check can never fully verify DoD-prose-vs-PR-content
# match (that is a judgment call). What IS mechanically checkable, and today
# checked nowhere, is whether the ticket's OWN description still carries
# unchecked GFM task-list boxes (`- [ ]`) at the moment of the Done flip —
# per feedback_specify_acceptance_tests_in_the_ticket, acceptance criteria
# belong in the ticket as checkboxes, and an unchecked box at Done-flip time
# is a plain, first-party admission that the ticket's own author does not
# consider the work complete. This is additive to every other path below —
# it can BLOCK even when a merged PR is cited (unlike the exempt-label and
# deploy-readback carve-outs, which are about *what kind* of evidence is
# owed, not whether that evidence's own text is self-consistent).
_UNCHECKED_BOX_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[ \][ \t]+\S.*$", re.MULTILINE
)
_MAX_UNCHECKED_BOX_SNIPPET_CHARS = 240


def find_unchecked_acceptance_boxes(description: str) -> list[str]:
    """Return every unchecked GFM task-list line (`- [ ]  ...`) in ``description``.

    Matches ``-``/``*``/``+`` bullets and ``1.``/``1)`` numbered items whose
    checkbox is unchecked (``[ ]``) and followed by non-blank text — a bare
    ``[ ]`` token elsewhere in prose (not a list-item checkbox) does not
    match. Checked boxes (``[x]``/``[X]``) never match. Pure function — no
    I/O, no network, no subprocess.
    """
    return [
        line.strip()[:_MAX_UNCHECKED_BOX_SNIPPET_CHARS]
        for line in _UNCHECKED_BOX_RE.findall(description or "")
    ]


# The OCC governance ref to read durable receipts from. OCC governance is
# dev-targeted — receipts land on ``dev`` first (OMN-12593), so ``origin/dev``
# is the authoritative fresh surface for a Done-flip gate.
_OCC_REF = "origin/dev"

# Receipt directory prefix under the OCC repo root (matches the platform layout
# node_pr_lifecycle_fix_effect writes: drift/dod_receipts/<TICKET>/<ITEM>/command.yaml).
_RECEIPT_DIR_PREFIX = "drift/dod_receipts"

# Git subprocess budgets. A PreToolUse hook must stay responsive; a Done-flip is
# infrequent so a short fetch is acceptable, but everything is bounded and any
# failure/timeout falls through to the fail-closed BLOCK.
_GIT_FETCH_TIMEOUT_SECONDS = 20
_GIT_READ_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class Decision:
    """Result of the guard: allow (exit 0) or block (exit 2)."""

    allowed: bool
    reason: str


# ---------------------------------------------------------------------------
# Environment / path resolution (deterministic — no ambient CONTRACT_REPO_DIR)
# ---------------------------------------------------------------------------


def resolve_omni_home() -> Path | None:
    """Return ``$OMNI_HOME`` as a Path, or ``None`` when unset/nonexistent.

    Fail-fast philosophy (CLAUDE.md rule 8): the guard never silently invents a
    default OMNI_HOME. When it is unresolvable, path B (the OCC receipt read)
    cannot run and the caller falls through to the fail-closed BLOCK.
    """
    raw = os.environ.get("OMNI_HOME", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def occ_repo_path(omni_home: Path) -> Path:
    """Return the deterministic onex_change_control clone root under OMNI_HOME.

    Resolved from a known repo-relative anchor, never read from the ambient
    environment (OMN-13857 — the ``$CONTRACT_REPO_DIR`` dependency is exactly
    what false-negatives when unset). Pure function.
    """
    return omni_home / "onex_change_control"


# ---------------------------------------------------------------------------
# Git-backed OCC receipt probe (reads origin/dev — fresh, deterministic)
# ---------------------------------------------------------------------------


def _run_git(
    args: list[str], *, cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str] | None:
    """Run ``git -C <cwd> <args>``; return the completed process or ``None``.

    ``None`` on timeout / OSError so every caller can fail closed. Fixed argv,
    no shell.
    """
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def parse_receipt_fields(text: str) -> dict[str, str]:
    """Extract top-level scalar ``key: value`` fields from a receipt YAML.

    Dependency-free (no PyYAML at hook time). node_dod_verify's committed
    receipts are flat ``ModelDodReceipt`` YAML with a couple of block scalars
    (``probe_stdout: |``); block-scalar bodies are indented and therefore never
    match the top-level ``key:`` pattern, so they are safely ignored. Only the
    first occurrence of each key is kept. Pure function.
    """
    fields: dict[str, str] = {}
    key_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
    for line in text.splitlines():
        match = key_re.match(line)
        if match is None:
            continue
        key, raw_val = match.group(1), match.group(2).strip()
        if key in fields:
            continue
        # Skip block-scalar indicators — the value is on following indented lines.
        if raw_val in ("|", ">", "|-", ">-", "|+", ">+", ""):
            fields[key] = ""
            continue
        fields[key] = raw_val.strip().strip('"').strip("'")
    return fields


def _receipt_is_pass_bound(fields: dict[str, str], ticket_id: str) -> bool:
    """Return True if a parsed receipt is a real PASS bound to ``ticket_id``.

    Requires ``status == PASS``, a matching ``ticket_id``, and a real check
    binding (``evidence_item_id`` + ``check_type`` present). The check-binding
    requirement is the git-backed equivalent of the "at least one real verified
    check" rule — it refuses a vacuous/empty receipt as durable evidence.
    """
    return (
        fields.get("status", "").strip().upper() == "PASS"
        and fields.get("ticket_id", "").strip() == ticket_id
        and bool(fields.get("evidence_item_id", "").strip())
        and bool(fields.get("check_type", "").strip())
    )


def occ_receipt_pass_on_dev(
    occ_repo: Path,
    ticket_id: str,
    *,
    ref: str = _OCC_REF,
    fetch: bool = True,
) -> bool:
    """Return True iff a PASS receipt bound to ``ticket_id`` exists on ``ref``.

    Reads the durable receipt directly off the ``origin/dev`` ref of the local
    onex_change_control clone (``git ls-tree`` + ``git show``), after a targeted
    ``git fetch origin dev`` so a just-merged receipt is visible even when the
    clone's working tree is stale. Fail-closed: returns ``False`` on missing
    clone, unreadable ref, no receipt, malformed receipt, non-PASS, or a receipt
    not bound to the ticket + a real check.

    The fetch is best-effort — if it fails (offline / transient), the last-known
    ``origin/dev`` ref is still read rather than hard-failing; the guard never
    fails OPEN, only reads a possibly-older ref.
    """
    if not occ_repo.is_dir():
        return False

    if fetch:
        # Best-effort refresh of the dev ref. Ignore the result — a failed fetch
        # falls through to reading the existing origin/dev ref.
        _run_git(
            ["fetch", "--quiet", "origin", "dev"],
            cwd=occ_repo,
            timeout=_GIT_FETCH_TIMEOUT_SECONDS,
        )

    receipt_dir = f"{_RECEIPT_DIR_PREFIX}/{ticket_id}"
    listing = _run_git(
        ["ls-tree", "-r", "--name-only", ref, "--", receipt_dir],
        cwd=occ_repo,
        timeout=_GIT_READ_TIMEOUT_SECONDS,
    )
    if listing is None or listing.returncode != 0 or not listing.stdout.strip():
        return False

    for rel_path in listing.stdout.splitlines():
        rel_path = rel_path.strip()
        if not rel_path.endswith(".yaml"):
            continue
        shown = _run_git(
            ["show", f"{ref}:{rel_path}"],
            cwd=occ_repo,
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
        if shown is None or shown.returncode != 0:
            continue
        if _receipt_is_pass_bound(parse_receipt_fields(shown.stdout), ticket_id):
            return True
    return False


# ---------------------------------------------------------------------------
# Attachment/citation supersession awareness (OMN-15712).
#
# The merge-check (path A) treats every product PR referenced in the
# description *or* folded in from a Linear GitHub-integration attachment
# (``augment_description_with_attachments``) as load-bearing: if it isn't
# MERGED, the Done-flip BLOCKS. That has no concept of supersession — a
# ticket that legitimately replaced a stale, closed-unmerged PR with a later
# merged one (recorded durably as a PASS ``dod-...-pr-<N>-superseded`` OCC
# receipt, per the OMN-14623 append-only supersede convention) or that simply
# carries a leftover attachment its DoD contract never cited, still gets
# hard-blocked on that stale PR's live state.
#
# This reads the SAME git-backed ``origin/dev`` OCC receipt surface used by
# path B (``occ_receipt_pass_on_dev``) — no new I/O boundary — and answers,
# per blocking PR number, whether the ticket's own receipt set ever cited it
# and, if so, whether every citation was later marked superseded. It is
# deliberately scoped to tickets that HAVE at least one OCC receipt: with
# zero receipts there is no contract data to reason about "cited" from, and
# treating an uncited PR as non-blocking in that case would gut the merge
# check for the common (non-OCC) ticket shape entirely.
# ---------------------------------------------------------------------------


def list_ticket_receipt_fields(
    occ_repo: Path,
    ticket_id: str,
    *,
    ref: str = _OCC_REF,
    fetch: bool = True,
) -> list[dict[str, str]]:
    """Return parsed top-level fields for every receipt YAML under
    ``drift/dod_receipts/<ticket_id>/`` on ``ref``.

    Fail-closed EMPTY list on any git failure (missing clone, unreadable ref,
    no receipts) — callers must treat an empty result as "no OCC contract data
    available for this ticket", never as "every citation is superseded".
    """
    if not occ_repo.is_dir():
        return []

    if fetch:
        _run_git(
            ["fetch", "--quiet", "origin", "dev"],
            cwd=occ_repo,
            timeout=_GIT_FETCH_TIMEOUT_SECONDS,
        )

    receipt_dir = f"{_RECEIPT_DIR_PREFIX}/{ticket_id}"
    listing = _run_git(
        ["ls-tree", "-r", "--name-only", ref, "--", receipt_dir],
        cwd=occ_repo,
        timeout=_GIT_READ_TIMEOUT_SECONDS,
    )
    if listing is None or listing.returncode != 0 or not listing.stdout.strip():
        return []

    fields_list: list[dict[str, str]] = []
    for rel_path in listing.stdout.splitlines():
        rel_path = rel_path.strip()
        if not rel_path.endswith(".yaml"):
            continue
        shown = _run_git(
            ["show", f"{ref}:{rel_path}"],
            cwd=occ_repo,
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
        if shown is None or shown.returncode != 0:
            continue
        fields_list.append(parse_receipt_fields(shown.stdout))
    return fields_list


def _receipt_pr_number(fields: dict[str, str]) -> int | None:
    """Return the receipt's top-level ``pr_number`` field as an int, or None."""
    raw = fields.get("pr_number", "").strip()
    if not raw or not raw.lstrip("-").isdigit():
        return None
    return int(raw)


def pr_citation_state(receipts: list[dict[str, str]], pr_number: int) -> str:
    """Classify ``pr_number``'s citation state within a ticket's OCC receipts.

    Returns one of:
      * ``"no_contract"`` — the ticket has ZERO receipts at all. Callers MUST
        NOT filter on this — behave exactly as if this feature didn't exist.
      * ``"uncited"`` — the ticket HAS receipts, but none reference this PR
        number. The DoD contract never cited it — not load-bearing.
      * ``"superseded"`` — at least one PASS receipt whose
        ``evidence_item_id`` ends in ``-superseded`` cites this PR number — a
        later append-only receipt explicitly retired the citation (the
        OMN-14623 / OMN-15422 convention). Not load-bearing.
      * ``"active"`` — the ticket's receipts cite this PR number and it is
        not (fully) superseded. Still load-bearing — normal blocking rules
        apply.

    Pure function — no I/O.
    """
    if not receipts:
        return "no_contract"
    matches = [r for r in receipts if _receipt_pr_number(r) == pr_number]
    if not matches:
        return "uncited"
    if any(
        r.get("evidence_item_id", "").strip().endswith("-superseded")
        and r.get("status", "").strip().upper() == "PASS"
        for r in matches
    ):
        return "superseded"
    return "active"


def _format_blocking_lines(blocking: list[PRStatus]) -> str:
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
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live Linear read (for status-only updates that omit the description)
# ---------------------------------------------------------------------------


def _default_linear_fetcher(ticket_id: str) -> dict[str, Any] | None:
    """Fetch a Linear issue's description/labels via the shared implementation.

    Delegates to ``linear_done_verify._fetch_linear_issue`` (GraphQL). Returns
    ``None`` on network/API failure, ``{}`` when ``LINEAR_API_KEY`` is unset, or
    the issue dict otherwise.
    """
    from linear_done_verify import _fetch_linear_issue

    result = _fetch_linear_issue(ticket_id)
    return result if isinstance(result, dict) or result is None else None


# ---------------------------------------------------------------------------
# Core decision
# ---------------------------------------------------------------------------


def decide(
    call: dict[str, Any],
    *,
    occ_probe: Callable[[str], bool] | None = None,
    pr_fetcher: Callable[[Any], Any] = fetch_pr_status,
    linear_fetcher: Callable[[str], dict[str, Any] | None] = _default_linear_fetcher,
    receipt_lister: Callable[[str], list[dict[str, str]]] | None = None,
) -> Decision:
    """Return the guard decision for a PreToolUse tool call.

    All I/O boundaries are injectable so unit tests stay hermetic:
      * ``occ_probe(ticket_id) -> bool`` — is a PASS OCC receipt on ``origin/dev``?
        defaults to :func:`occ_receipt_pass_on_dev` bound to the resolved OCC clone.
      * ``pr_fetcher(PRRef) -> PRStatus`` — GitHub PR state (default: ``gh``).
      * ``linear_fetcher(ticket_id) -> issue|{}|None`` — live Linear read.
      * ``receipt_lister(ticket_id) -> list[fields]`` — every OCC receipt's
        parsed fields for the ticket (OMN-15712 supersession/citation check);
        defaults to :func:`list_ticket_receipt_fields` bound to the resolved
        OCC clone.
    """
    tool_name = call.get("tool_name", "")
    if tool_name not in _LINEAR_TOOLS:
        return Decision(True, "not_linear_tool")

    params = call.get("tool_input") or {}
    if not isinstance(params, dict):
        return Decision(True, "no_tool_input")

    state_value = str(params.get("state") or params.get("status") or "")

    # (2) cancel-class carve-out: closing without shipping — no PR/receipt owed.
    if is_cancel_state(state_value):
        return Decision(True, "carve_out:cancel_state")

    # (1) not a Done-class transition — nothing to verify.
    if not is_done_state(state_value):
        return Decision(True, "not_done_state")

    ticket_id = str(params.get("id") or params.get("issueId") or "")
    description = str(params.get("description") or "")
    labels: list[str] = [str(x) for x in (params.get("labels") or [])]

    # Status-only updates commonly omit the description; read it live so PR
    # citations and exemption labels can be evaluated. None => Linear
    # unreachable: do NOT allow on that basis — fall through to the OCC receipt
    # path, which reads git-backed governance, not Linear.
    if not description and ticket_id:
        issue = linear_fetcher(ticket_id)
        if isinstance(issue, dict) and issue:
            description = str(issue.get("description") or "")
            if not labels:
                labels = [str(x) for x in (issue.get("labels") or [])]
            # Fold in the linked-PR attachment URLs (Linear GitHub integration
            # links the PR as an attachment, not a `#N` body mention) so the
            # merge check sees the *linked* PR even when it is uncited. This is
            # the OMN-14582 false-Done shape — a label-driven close while the
            # linked product PR was still OPEN (OMN-14641).
            description = augment_description_with_attachments(
                description, [str(x) for x in (issue.get("attachment_urls") or [])]
            )

    # (2b) unchecked acceptance-criteria checkbox gate (OMN-15030). Runs BEFORE
    # every evidence path below and is not waivable by any of them — a merged
    # PR, a PASS OCC receipt, or an exempt label all prove *some* evidence
    # exists, none of them prove the ticket's own stated acceptance criteria
    # were met. An unchecked `- [ ]` box in the ticket's current description
    # is the ticket author's own admission of incompleteness; refusing here is
    # the mechanical, judgment-free proxy for "does the shipped PR satisfy
    # this ticket's DoD" that no presence-check below can express.
    unchecked_boxes = find_unchecked_acceptance_boxes(description)
    if unchecked_boxes:
        preview = "; ".join(unchecked_boxes[:5])
        more = (
            f" (+{len(unchecked_boxes) - 5} more)" if len(unchecked_boxes) > 5 else ""
        )
        return Decision(
            False,
            f"unchecked_acceptance_criteria: {len(unchecked_boxes)} unchecked "
            f"box(es) remain in the ticket description: {preview}{more}. Check "
            "every acceptance-criteria box (or remove/rewrite the ones that no "
            "longer apply) before flipping Done — a merged PR or OCC receipt "
            "does not waive this (OMN-15030 / OMN-13991).",
        )

    default_repo = os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None

    # (3-pre) durable evidence path C — deploy-readback marker (OMN-14792). A
    # runtime-deploy ticket's DoD is a live readback (effects image rebuilt to
    # dev-tip + a clean probe read off the deployed bytes), NOT a merged product
    # PR: node_dod_verify structurally skips such tickets
    # (reference_dod_verify_cannot_close_deploy_tickets) and they close via an
    # operator deliberate-Done. Before this carve-out the guard false-blocked
    # them (the OMN-14437 shape) because it treated every PR string in the body
    # — a scratch/throwaway live-mint readback PR, and bare merge-chain-narrative
    # numbers — as blocking DoD evidence.
    #
    # When a `deploy-readback-proven:` marker with real evidence is present, the
    # merge check is SCOPED to DoD-*implementing* PRs only (verify_implementing:
    # full-URL / resolvable bare #N, excluding scratch-annotated and
    # unresolvable-narrative refs). If any implementing PR is unmerged the flip
    # still BLOCKS — the marker is not a blanket bypass (the OMN-14641 lesson).
    # Otherwise the live-readback attestation stands in for a merged PR.
    if parse_deploy_readback_marker(description) is not None:
        impl_result = verify_implementing(
            description, labels, default_repo=default_repo, fetcher=pr_fetcher
        )
        if not impl_result.allowed:
            return Decision(False, f"pr_not_merged\n{impl_result.reason}")
        return Decision(True, "durable_evidence:deploy_readback_proven")

    # (3) durable evidence path A — merged product-PR citation. This runs BEFORE
    # the close-if-done exemption carve-out (OMN-14641): the label was a blanket
    # merge-check bypass, so a ticket carrying it could flip Done with its linked
    # product PR still OPEN. verify() now blocks on any open cited product PR
    # regardless of the label; the exemption is honored only below, when NO
    # product PR is cited.
    pr_result = verify(
        description, labels, default_repo=default_repo, fetcher=pr_fetcher
    )
    if not pr_result.allowed:
        # A cited PR is open / unmerged / unresolvable — the classic OMN-8375
        # "Done while PR still BLOCKED" shape (and the OMN-14582 label-bypass
        # shape). Block outright — the close-if-done label does not waive this.
        #
        # OMN-15712: before blocking, check whether the ticket's own OCC DoD
        # contract still considers each blocking PR load-bearing. A ticket
        # that HAS OCC receipts (a real dod_verify contract instance) may have
        # legitimately superseded a stale attachment (an explicit PASS
        # `-superseded` receipt) or never cited it at all (a leftover
        # attachment, e.g. an old release PR replaced by a later one) — in
        # either case the stale PR's live state is not this ticket's evidence
        # and must not block. A ticket with ZERO OCC receipts is unaffected —
        # there is no contract data to reason "cited" from, so every blocking
        # ref is treated exactly as before this feature existed.
        if ticket_id:
            lister = receipt_lister
            if lister is None:
                omni_home = resolve_omni_home()
                if omni_home is not None:
                    _repo = occ_repo_path(omni_home)
                    lister = lambda tid: list_ticket_receipt_fields(_repo, tid)  # noqa: E731
            if lister is not None:
                receipts = lister(ticket_id)
                if (
                    receipts
                ):  # ticket HAS an OCC contract — citation-aware filtering applies
                    blocking = [
                        s for s in pr_result.pr_statuses if classify_blocking(s)
                    ]
                    still_blocking = [
                        s
                        for s in blocking
                        if pr_citation_state(receipts, s.ref.number)
                        not in ("uncited", "superseded")
                    ]
                    if not still_blocking:
                        return Decision(
                            True,
                            "durable_evidence:blocking_refs_uncited_or_superseded_"
                            "by_occ_contract",
                        )
                    return Decision(
                        False,
                        f"pr_not_merged\n{_format_blocking_lines(still_blocking)}",
                    )
        return Decision(False, f"pr_not_merged\n{pr_result.reason}")
    if pr_result.reason == "all_prs_merged":
        return Decision(True, "durable_evidence:all_prs_merged")

    # (2) explicit exemption label / close-if-done frontmatter. Covers
    # decision-only tickets and epic ALL_CHILDREN_DONE roll-ups (which carry the
    # label). Encoded explicitly — never inferred from ticket shape. Valid ONLY
    # here, where no product PR is cited; an open cited PR already returned above
    # (OMN-14641 — the label can no longer bypass an unmerged linked PR).
    if is_exempt(description, labels):
        return Decision(True, "carve_out:exempt_label")

    # pr_result.allowed with reason "no_pr_references" is NOT durable evidence on
    # its own — this is the incident shape (Done, no PR cited). Fall through to
    # the git-backed OCC receipt path; do NOT allow here.

    if not ticket_id:
        return Decision(
            False,
            "no_ticket_id: cannot verify durable evidence for a Done-flip without "
            "an issue id. Pass 'id' in the save_issue call.",
        )

    # (4) durable evidence path B — PASS OCC receipt on origin/dev (git-backed).
    probe = occ_probe
    if probe is None:
        omni_home = resolve_omni_home()
        if omni_home is None:
            return Decision(
                False,
                "no_durable_evidence: OMNI_HOME is unset/invalid, so the local "
                "onex_change_control clone cannot be resolved and no merged-PR "
                "citation was found. Failing closed (design requirement 4 — never "
                "fail-open on a fake-Done). Set OMNI_HOME, or cite the merged "
                "implementing PR in the ticket description.",
            )
        repo = occ_repo_path(omni_home)
        probe = lambda tid: occ_receipt_pass_on_dev(repo, tid)  # noqa: E731

    if probe(ticket_id):
        return Decision(True, "durable_evidence:occ_receipt_on_dev")

    return Decision(
        False,
        f"no_durable_evidence for {ticket_id}: no merged-PR citation in the "
        f"description, and no PASS node_dod_verify receipt bound to the ticket is "
        f"tracked under {_RECEIPT_DIR_PREFIX}/{ticket_id}/ on {_OCC_REF} of the "
        "local onex_change_control clone. Fail-closed (no fake Done). Cite the "
        "merged implementing PR in the ticket description, land a durable OCC "
        "receipt, or apply an explicit close-if-done exemption for a legitimate "
        "no-PR close.",
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _load_stdin_call() -> dict[str, Any]:
    try:
        parsed = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> int:
    """Read a PreToolUse tool call on stdin; exit 0 (allow) or 2 (block)."""
    call = _load_stdin_call()
    decision = decide(call)
    if decision.allowed:
        return 0
    payload = {
        "decision": "block",
        "reason": f"[OMN-13856 done-flip durable-evidence gate] {decision.reason}",
    }
    sys.stderr.write(json.dumps(payload) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
