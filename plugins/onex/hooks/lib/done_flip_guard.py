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
2. Carve-outs (encoded explicitly, never inferred — design §2):
   - cancel-class target state (``canceled/duplicate/won't do``) → ALLOW;
   - explicit exemption label / ``close-if-done`` frontmatter (covers
     decision-only tickets and epic ALL_CHILDREN_DONE roll-ups, which carry the
     label) → ALLOW.
3. Durable evidence path A — merged PR: if the ticket description cites PRs and
   every cited PR is ``MERGED`` → ALLOW. If any cited PR is open / unmerged →
   BLOCK. (A "superseded-by-merged-sibling" close is a merged-PR citation and is
   accepted here.)
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
    fetch_pr_status,
    is_cancel_state,
    is_done_state,
    is_exempt,
    verify,
)

_LINEAR_TOOLS = frozenset(
    {"mcp__linear-server__save_issue", "mcp__linear-server__update_issue"}
)

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
) -> Decision:
    """Return the guard decision for a PreToolUse tool call.

    All I/O boundaries are injectable so unit tests stay hermetic:
      * ``occ_probe(ticket_id) -> bool`` — is a PASS OCC receipt on ``origin/dev``?
        defaults to :func:`occ_receipt_pass_on_dev` bound to the resolved OCC clone.
      * ``pr_fetcher(PRRef) -> PRStatus`` — GitHub PR state (default: ``gh``).
      * ``linear_fetcher(ticket_id) -> issue|{}|None`` — live Linear read.
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

    # (2) explicit exemption label / close-if-done frontmatter. Covers
    # decision-only tickets and epic ALL_CHILDREN_DONE roll-ups (which carry the
    # label). Encoded explicitly — never inferred from ticket shape.
    if is_exempt(description, labels):
        return Decision(True, "carve_out:exempt_label")

    # (3) durable evidence path A — merged PR citation.
    default_repo = os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None
    pr_result = verify(
        description, labels, default_repo=default_repo, fetcher=pr_fetcher
    )
    if not pr_result.allowed:
        # A cited PR is open / unmerged / unresolvable — the classic OMN-8375
        # "Done while PR still BLOCKED" shape. Block outright.
        return Decision(False, f"pr_not_merged\n{pr_result.reason}")
    if pr_result.reason == "all_prs_merged":
        return Decision(True, "durable_evidence:all_prs_merged")

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
