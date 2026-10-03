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

Decision (OMN-20368 — fail-closed; the ONE sufficient condition for Done is
the bound-receipt bar, and every other path is a further condition):

1. Not a ``save_issue``/``update_issue`` call → ALLOW. A state passed by id
   (not by name) is REFUSED: it cannot be classified without a network read.
2. Cancel-class target state (``canceled/duplicate/won't do``) → ALLOW.
3. Acceptance-box tick gate (OMN-20368), for every non-Done edit that writes a
   description (``description`` or ``patch``): a box checked in the result that
   was not checked before is a tick, and a tick needs the bound-receipt bar
   (steps 7-8). A create with a checked box is refused. When the current
   description cannot be read, every checked box counts as a tick.
4. Done: an unchecked GFM box in today's description or the written one →
   BLOCK (OMN-15030). Ticking it is not the remedy; the receipt is.
5. Done: every cited / linked product PR must be merged (OMN-8375/OMN-14641),
   scoped to implementing PRs under a deploy-readback marker (OMN-14792), with
   OMN-15712's closed-and-uncited/superseded attachments excused. A merged PR
   used to ALLOW here; since OMN-20368 it is necessary and never sufficient.
6. The close-if-done exemption label and the deploy-readback marker no longer
   ALLOW anything on their own (OMN-20368).
7. Repo evidence first (``no_pr_bound_evidence``): a merged product PR's
   ``contracts/<TICKET>.yaml`` binds every labelled criterion, and a green
   ``repo-evidence / dod-verify`` GitHub Actions check on its head verifies
   the same contract that merged. Once engaged, this verdict is final and
   OCC is not consulted. A contract without the check has not adopted it.
8. When repo evidence is not engaged, the bound-receipt bar
   (``no_pr_bound_evidence``), on ``origin/dev`` of the
   local onex_change_control clone: ``contracts/<TICKET>.yaml`` binds EVERY
   labelled acceptance criterion — of today's description and of the one the
   call writes — through ``binds_ac``, and each criterion has a binding item
   with a PASS receipt that names the subject, the environment and a read
   time, is attested by a verifier other than its runner, and was taken
   against the current contract entry (``contract_entry_sha256``, or the
   legacy whole-file ``contract_sha256``). A ticket with no merged PR also
   holds its receipts to the freshness window. Anything short → BLOCK, naming
   what is missing. dod_verify's NO_ACCEPTANCE_CHECKS is the shape "no item
   binds the criterion", and it is refused.
9. A guard that cannot decide refuses (``main``), and the shell wrapper runs in
   every cwd, in lite mode and under any hooks mask.

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

import inspect
import json
import os
import re
import subprocess  # noqa: S404 - fixed-argv git invocations, no shell
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
    parse_deploy_readback_marker,
    verify,
    verify_implementing,
)
from no_pr_bound_evidence import (
    MERGED_PR_ENVIRONMENT_FIELDS,
    NO_PR_RECEIPT_MAX_AGE,
    BoundEvidenceVerdict,
    RepoEvidenceOutcome,
    RepoEvidenceVerdict,
    bounded_fetch,
    evaluate_bound_evidence,
    evaluate_repo_evidence,
    load_ticket_occ_evidence,
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
# the path-B receipt directory — no new I/O boundary — and answers,
# per blocking PR number, whether the ticket's own receipt set ever cited it
# and, if so, whether every citation was later marked superseded. It is
# deliberately scoped to tickets that HAVE at least one OCC receipt: with
# zero receipts there is no contract data to reason about "cited" from, and
# treating an uncited PR as non-blocking in that case would gut the merge
# check for the common (non-OCC) ticket shape entirely.
#
# Regression fix (2026-08-05, verified live against OMN-15422 + omniclaude#1976
# as a synthetic OPEN-PR probe): the carve-out is a *stale-attachment*
# concept — it only makes sense for a PR that is CLOSED-unmerged, i.e. dead
# and replaced. An OPEN PR is potentially load-bearing in-flight work no
# matter what the OCC contract has or hasn't cited yet, so it is EXCLUDED
# from this carve-out entirely and always blocks — the citation-state check
# below only runs for CLOSED-unmerged refs (see the ``s.state == "OPEN"``
# guard at the call site). Applying "uncited" to an OPEN ref would make any
# ticket with >=1 OCC receipt non-blocking on any unmerged, unreceipted PR —
# re-opening the exact OMN-8375/OMN-14582/OMN-14641 shape.
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
        bounded_fetch(occ_repo)

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

# OMN-20368: a CHECKED task-list box. Every box counts, as for the unchecked
# gate above: a lane that ticks a box is asserting a criterion was met.
_CHECKED_BOX_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[[xX]\][ \t]+(\S.*)$", re.MULTILINE
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _normalise_box_text(text: str) -> str:
    """Box text compared across edits: Linear's backslash escapes and spacing removed."""
    return " ".join(text.replace("\\", "").split()).casefold()


def checked_acceptance_boxes(description: str) -> set[str]:
    """The normalised text of every checked (``[x]``) task-list item. Pure."""
    return {_normalise_box_text(m) for m in _CHECKED_BOX_RE.findall(description or "")}


def newly_ticked_boxes(before: str | None, after: str) -> list[str]:
    """Checked boxes in ``after`` that were not checked in ``before``.

    ``before`` is None when the current description could not be read; every
    checked box in ``after`` then counts as newly ticked (fail closed: an edit
    whose effect cannot be compared is treated as the edit that ticks).
    """
    previously = checked_acceptance_boxes(before) if before is not None else set()
    return sorted(checked_acceptance_boxes(after) - previously)


def _patch_texts(ops: list[Any]) -> str:
    parts: list[str] = []
    for op in ops:
        if isinstance(op, dict):
            for key in ("new_string", "text"):
                value = op.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return "\n".join(parts)


def apply_description_patch(current: str, ops: list[Any]) -> str | None:
    """Apply the Linear MCP ``patch`` operations to ``current``; None if any fails.

    Mirrors the MCP's documented semantics (every anchor must match exactly
    once, unless ``replace_all``). A None result is not an error to the caller:
    it means the guard cannot predict the edit, and it fails closed on it.
    """
    text = current
    for op in ops:
        if not isinstance(op, dict):
            return None
        kind = op.get("op")
        if kind == "replace":
            old, new = op.get("old_string"), op.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str) or not old:
                return None
            if op.get("replace_all"):
                if old not in text:
                    return None
                text = text.replace(old, new)
            else:
                if text.count(old) != 1:
                    return None
                text = text.replace(old, new, 1)
        elif kind in ("insert_before", "insert_after"):
            anchor, add = op.get("anchor"), op.get("text")
            if not isinstance(anchor, str) or not isinstance(add, str):
                return None
            if text.count(anchor) != 1:
                return None
            joined = add + anchor if kind == "insert_before" else anchor + add
            text = text.replace(anchor, joined, 1)
        elif kind == "prepend":
            add = op.get("text")
            if not isinstance(add, str):
                return None
            text = add + text
        elif kind == "append":
            add = op.get("text")
            if not isinstance(add, str):
                return None
            text = text + add
        elif kind == "replace_range":
            start, end, new = op.get("from"), op.get("to"), op.get("new_string")
            if not all(isinstance(x, str) for x in (start, end, new)):
                return None
            assert isinstance(start, str) and isinstance(end, str)
            assert isinstance(new, str)
            if text.count(start) != 1:
                return None
            i = text.index(start)
            j = text.find(end, i + len(start))
            if j < 0 or text.count(end, i + len(start)) != 1:
                return None
            text = text[:i] + new + text[j:]
        else:
            return None
    return text


def _occ_lister(repo: Path) -> Callable[[str], list[dict[str, str]]]:
    def lister(ticket_id: str) -> list[dict[str, str]]:
        return list_ticket_receipt_fields(repo, ticket_id)

    return lister


def _accepts_merged_pr(probe: Callable[..., Any]) -> bool:
    """Whether ``probe`` takes the ``merged_pr`` keyword (an injected test probe may not)."""
    try:
        params = inspect.signature(probe).parameters
    except (TypeError, ValueError):
        return False
    return "merged_pr" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )


def _refuse(reason: str) -> Decision:
    return Decision(False, reason)


def _bound_receipt_refusal(ticket_id: str, detail: str, *, why: str) -> Decision:
    return _refuse(
        f"no_bound_dod_receipt for {ticket_id}: {why}. The bar (OMN-20368) is "
        f"contracts/{ticket_id}.yaml on {_OCC_REF} of onex_change_control binding "
        "EVERY labelled acceptance criterion through `binds_ac`, each discharged "
        f"by a PASS receipt under {_RECEIPT_DIR_PREFIX}/{ticket_id}/ taken "
        "against the current contract entry. What is missing: "
        f"{detail}. Ticked boxes, a merged PR, an evidence comment or an "
        "exemption label do not substitute for it: run dod_verify, land the "
        "binding and the receipts through an evidence PR, then flip."
    )


def _repo_evidence_refusal(ticket_id: str, detail: str, *, why: str) -> Decision:
    return _refuse(
        f"no_bound_dod_receipt for {ticket_id}: {why}. The repo-evidence bar is "
        f"the product repository's contracts/{ticket_id}.yaml binding EVERY "
        "labelled acceptance criterion through `binds_ac`, plus a green "
        '"repo-evidence / dod-verify" GitHub Actions check run on the merged '
        "head verifying the same contract that merged. OCC is not consulted "
        "once the repo carries the evidence. What is missing: "
        f"{detail} Land the bindings and a passing check in the product repository."
    )


def decide(
    call: dict[str, Any],
    *,
    occ_probe: Callable[..., BoundEvidenceVerdict] | None = None,
    repo_evidence_probe: Callable[[str, list[str], list[PRStatus]], RepoEvidenceVerdict]
    | None = None,
    pr_fetcher: Callable[[Any], Any] = fetch_pr_status,
    linear_fetcher: Callable[[str], dict[str, Any] | None] = _default_linear_fetcher,
    receipt_lister: Callable[[str], list[dict[str, str]]] | None = None,
    now: datetime | None = None,
) -> Decision:
    """Return the guard decision for a PreToolUse tool call.

    A Done transition needs repo-owned evidence binding every criterion and
    passing the verified-head check; when the repo has not adopted that evidence,
    OMN-20368's OCC contract must bind every criterion to a PASS receipt taken
    against the current contract entry (``occ_probe``). Every evidence path that used
    to ALLOW on its own (all cited PRs merged, a deploy-readback marker, a
    close-if-done label, OMN-15712's superseded attachments) is now a further
    condition, never a substitute. The same bar is required for an edit that
    ticks an acceptance box.

    All I/O boundaries are injectable so unit tests stay hermetic:
      * ``repo_evidence_probe(ticket_id, descriptions, merged_statuses)`` ->
        repo verdict (default: :func:`no_pr_bound_evidence.evaluate_repo_evidence`
        with its GitHub readers). An engaged verdict is final, before OCC.
      * ``occ_probe(ticket_id, description, merged_pr=bool)`` -> verdict on the
        bound-receipt bar, read off ``origin/dev`` of the OCC clone. Defaults
        to :func:`no_pr_bound_evidence.evaluate_bound_evidence` over one load of
        :func:`no_pr_bound_evidence.load_ticket_occ_evidence`. A test probe may
        take only ``(ticket_id, description)``.
      * ``pr_fetcher(PRRef) -> PRStatus`` -- GitHub PR state (default: ``gh``).
      * ``linear_fetcher(ticket_id) -> issue|{}|None`` -- live Linear read.
      * ``receipt_lister(ticket_id) -> list[fields]`` -- OCC receipt fields for
        the OMN-15712 supersession check.
      * ``now`` -- the clock a no-PR receipt's read time is judged against.
    """
    tool_name = call.get("tool_name", "")
    if tool_name not in _LINEAR_TOOLS:
        return Decision(True, "not_linear_tool")

    params = call.get("tool_input") or {}
    if not isinstance(params, dict):
        return Decision(True, "no_tool_input")

    ticket_id = str(params.get("id") or params.get("issueId") or "")
    state_value = str(params.get("state") or params.get("status") or "").strip()

    # A state passed by id (the MCP accepts "type, name, or ID") cannot be
    # classified without a network read, and an unclassified Done would slip
    # past every check below. Refused: pass the state by name.
    if state_value and _UUID_RE.match(state_value):
        return _refuse(
            f"state_by_id: state {state_value} was passed by id, so the guard "
            "cannot tell whether this is a Done transition. Pass the state by "
            "name (Done, In Progress, ...)."
        )

    if is_cancel_state(state_value):
        return Decision(True, "carve_out:cancel_state")
    is_done = is_done_state(state_value)

    # ---- the live description, read once ---------------------------------
    issue: dict[str, Any] | None = None
    live_read = False

    def _live() -> dict[str, Any] | None:
        nonlocal issue, live_read
        if not live_read:
            live_read = True
            fetched = linear_fetcher(ticket_id) if ticket_id else None
            issue = fetched if isinstance(fetched, dict) and fetched else None
        return issue

    # ---- the bound-receipt bar, loaded once -------------------------------
    clock = now or datetime.now(UTC)
    probe = occ_probe
    probe_error = ""
    occ_loaded = probe is not None
    repo_bound = False

    def _load_occ_probe() -> None:
        nonlocal probe, probe_error, occ_loaded
        if occ_loaded:
            return
        occ_loaded = True
        workspace_root = resolve_omni_home()
        if workspace_root is None:
            probe_error = (
                "OMNI_HOME is unset/invalid, so the local onex_change_control "
                "clone cannot be resolved"
            )
        else:
            evidence = load_ticket_occ_evidence(
                occ_repo_path(workspace_root), ticket_id
            )

            def probe(tid: str, desc: str, merged_pr: bool = False) -> Any:
                return evaluate_bound_evidence(
                    tid,
                    desc,
                    evidence,
                    clock,
                    max_age=None if merged_pr else NO_PR_RECEIPT_MAX_AGE,
                    environment_fields=(
                        MERGED_PR_ENVIRONMENT_FIELDS
                        if merged_pr
                        else ("target_identity", "working_dir")
                    ),
                )

    def _repo_verdict(
        descriptions: list[str], statuses: list[PRStatus] | None
    ) -> RepoEvidenceVerdict | None:
        if not ticket_id:
            return None
        if statuses is None:
            live = _live()
            description = (
                new_description
                if new_description is not None
                else str(live.get("description") or "")
                if live
                else ""
            )
            labels = [str(x) for x in (params.get("labels") or [])]
            if live is not None and not labels:
                labels = [str(x) for x in (live.get("labels") or [])]
            attachment_urls = (
                [str(x) for x in (live.get("attachment_urls") or [])] if live else []
            )
            pr_description = augment_description_with_attachments(
                description, attachment_urls
            )
            statuses = verify(
                pr_description,
                labels,
                default_repo=os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None,
                fetcher=pr_fetcher,
                ticket_id=ticket_id or None,
            ).pr_statuses
        merged_statuses = [s for s in statuses if s.state == "MERGED"]
        return (repo_evidence_probe or evaluate_repo_evidence)(
            ticket_id, descriptions, merged_statuses
        )

    def _bar(
        descriptions: list[str],
        *,
        merged_pr: bool,
        why: str,
        statuses: list[PRStatus] | None = None,
    ) -> Decision | None:
        """None when every description's criteria are bound; else the refusal."""
        nonlocal repo_bound
        repo_verdict = _repo_verdict(descriptions, statuses)
        if repo_verdict is not None:
            if repo_verdict.outcome is RepoEvidenceOutcome.REFUSED:
                return _repo_evidence_refusal(ticket_id, repo_verdict.detail, why=why)
            if repo_verdict.outcome is RepoEvidenceOutcome.PASSED:
                repo_bound = True
                return None

        def occ_refusal(detail: str) -> Decision:
            refused = _bound_receipt_refusal(ticket_id, detail, why=why)
            if (
                repo_verdict is not None
                and repo_verdict.outcome is RepoEvidenceOutcome.NOT_ENGAGED
                and f"carries contracts/{ticket_id}.yaml but no " in repo_verdict.detail
            ):
                return Decision(False, f"{refused.reason} {repo_verdict.detail}")
            return refused

        if not ticket_id:
            return _refuse(
                "no_ticket_id: a Done transition or an acceptance-box tick needs "
                "the issue id so its bound receipts can be read. Pass 'id'."
            )
        _load_occ_probe()
        if probe is None:
            return occ_refusal(probe_error)
        seen: set[str] = set()
        for desc in descriptions:
            if desc in seen:
                continue
            seen.add(desc)
            if _accepts_merged_pr(probe):
                verdict = probe(ticket_id, desc, merged_pr=merged_pr)
            else:
                verdict = probe(ticket_id, desc)
            if not verdict.passed:
                return occ_refusal(verdict.detail)
        return None

    # ---- the description this call would leave behind ----------------------
    has_description = isinstance(params.get("description"), str)
    patch_ops = params.get("patch")
    new_description: str | None = None
    current_description: str | None = None
    if has_description or isinstance(patch_ops, list):
        live = _live() if ticket_id else None
        current_description = (
            str(live.get("description") or "") if live is not None else None
        )
        if not ticket_id:
            current_description = ""  # a create: nothing was checked before it
        if has_description:
            new_description = str(params["description"])
        elif isinstance(patch_ops, list):
            applied = (
                apply_description_patch(current_description, patch_ops)
                if current_description is not None
                else None
            )
            # An edit the guard cannot predict is judged by what it inserts.
            new_description = (
                applied if applied is not None else _patch_texts(patch_ops)
            )
            if applied is None:
                current_description = None

    # ---- (T) acceptance-box tick gate (OMN-20368) -------------------------
    # A Done call is held to the full bar below on the description it writes,
    # which is strictly stronger, so the tick gate serves every other edit.
    if new_description is not None and not is_done:
        ticked = newly_ticked_boxes(current_description, new_description)
        if ticked:
            if not ticket_id:
                return _refuse(
                    "ac_tick_without_receipt: a new ticket cannot be created with "
                    f"checked acceptance boxes ({'; '.join(ticked[:3])}). Create "
                    "it with every box unchecked; boxes are ticked only once a "
                    "bound PASS dod_verify receipt exists (OMN-20368)."
                )
            preview = "; ".join(t[:120] for t in ticked[:3])
            refused = _bar(
                [new_description],
                merged_pr=True,
                why=(
                    f"this edit ticks {len(ticked)} acceptance box(es) ({preview}) "
                    "and no bound PASS receipt covers the criteria"
                ),
            )
            if refused is not None:
                return Decision(
                    False,
                    refused.reason.replace(
                        "no_bound_dod_receipt", "ac_tick_without_receipt", 1
                    ),
                )

    if not is_done:
        return Decision(True, "not_done_state")

    # ---- Done transition -------------------------------------------------
    labels: list[str] = [str(x) for x in (params.get("labels") or [])]
    live = _live() if ticket_id else None
    live_description = str(live.get("description") or "") if live else ""
    if live is not None and not labels:
        labels = [str(x) for x in (live.get("labels") or [])]
    attachment_urls = (
        [str(x) for x in (live.get("attachment_urls") or [])] if live else []
    )
    # The criteria a Done must satisfy: today's, and whatever this call writes.
    # Evaluating only the proposed text would let a Done call drop a criterion.
    descriptions = [d for d in (live_description, new_description) if d]
    description = new_description if new_description is not None else live_description
    pr_description = augment_description_with_attachments(description, attachment_urls)

    # (U) an unchecked box is the ticket's own admission it is not done
    # (OMN-15030). Checked against every description in play.
    for desc in descriptions or [""]:
        unchecked_boxes = find_unchecked_acceptance_boxes(desc)
        if unchecked_boxes:
            preview = "; ".join(unchecked_boxes[:5])
            more = (
                f" (+{len(unchecked_boxes) - 5} more)"
                if len(unchecked_boxes) > 5
                else ""
            )
            return _refuse(
                f"unchecked_acceptance_criteria: {len(unchecked_boxes)} unchecked "
                f"box(es) remain in the ticket description: {preview}{more}. "
                "Ticking them is not the remedy: a box is ticked only once a "
                "bound PASS dod_verify receipt covers it (OMN-15030 / OMN-20368)."
            )

    default_repo = os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None

    # (P) every cited / linked product PR must be merged. A further condition,
    # never a sufficient one (OMN-20368).
    merged_pr = False
    merged_statuses: list[PRStatus] = []
    if parse_deploy_readback_marker(pr_description) is not None:
        impl_result = verify_implementing(
            pr_description, labels, default_repo=default_repo, fetcher=pr_fetcher
        )
        if not impl_result.allowed:
            return _refuse(f"pr_not_merged\n{impl_result.reason}")
    else:
        pr_result = verify(
            pr_description,
            labels,
            default_repo=default_repo,
            fetcher=pr_fetcher,
            ticket_id=ticket_id or None,
        )
        merged_statuses = [s for s in pr_result.pr_statuses if s.state == "MERGED"]
        if pr_result.allowed:
            merged_pr = pr_result.reason == "all_prs_merged"
        else:
            still_blocking = [s for s in pr_result.pr_statuses if classify_blocking(s)]
            receipts: list[dict[str, str]] = []
            if ticket_id:
                lister = receipt_lister
                if lister is None:
                    workspace_root = resolve_omni_home()
                    if workspace_root is not None:
                        lister = _occ_lister(occ_repo_path(workspace_root))
                if lister is not None:
                    receipts = lister(ticket_id)
            if receipts:
                # OMN-15712: a CLOSED-unmerged attachment the contract never cited,
                # or explicitly superseded, is not load-bearing. OPEN always blocks.
                still_blocking = [
                    s
                    for s in still_blocking
                    if s.error
                    or s.state == "OPEN"
                    or pr_citation_state(receipts, s.ref.number)
                    not in ("uncited", "superseded")
                ]
                if still_blocking:
                    return _refuse(
                        f"pr_not_merged\n{_format_blocking_lines(still_blocking)}"
                    )
                merged_pr = any(s.state == "MERGED" for s in pr_result.pr_statuses)
            else:
                return _refuse(f"pr_not_merged\n{pr_result.reason}")

    # (B) the bound-receipt bar. The one sufficient condition, on every path.
    refused = _bar(
        descriptions or [description],
        merged_pr=merged_pr,
        statuses=merged_statuses,
        why=(
            "a Done transition needs a passing definition-of-done check for "
            "every acceptance criterion"
        ),
    )
    if refused is not None:
        return refused
    return Decision(
        True,
        (
            "durable_evidence:repo_bound_checks"
            if repo_bound
            else "durable_evidence:occ_bound_receipts"
        )
        + (":all_prs_merged" if merged_pr else ""),
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
    """Read a PreToolUse tool call on stdin; exit 0 (allow) or 2 (block).

    OMN-20368: fail CLOSED. A guard that cannot decide refuses the Linear
    write and says why; before this a runtime error in the guard was an allow.
    """
    call = _load_stdin_call()
    try:
        decision = decide(call)
    except (
        ArithmeticError,
        AttributeError,
        ImportError,
        LookupError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        decision = Decision(
            False,
            f"guard_error: the done-flip guard could not decide "
            f"({type(exc).__name__}: {exc}). Refusing the Linear write rather "
            "than letting it through unchecked (OMN-20368).",
        )
    if decision.allowed:
        return 0
    payload = {
        "decision": "block",
        "reason": f"[OMN-20368 done-flip bound-receipt gate] {decision.reason}",
    }
    sys.stderr.write(json.dumps(payload) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
