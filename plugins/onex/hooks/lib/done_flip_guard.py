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

* ``pre_tool_use_dod_completion_guard.sh`` receipt semantics (a fresh
  ``ModelDodReceipt`` with ``status == PASS``), and
* ``linear_done_verify.py`` merged-PR semantics (every PR cited in the ticket
  description is ``MERGED``).

Neither guard ALONE closes the incident: the DoD guard fails OPEN when
``ONEX_EVIDENCE_ROOT`` is unset, and the PR guard ALLOWS when the ticket cites
no PR at all (``no_pr_references``) — exactly the incident shape. A single guard
is required because the pass condition is a *disjunction* ("a merged-PR citation
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
4. Durable evidence path B — mechanized ``dod_verify``: run the DETERMINISTIC
   LOCAL ``node_dod_verify`` path (``python -m omnimarket.nodes.node_dod_verify``
   — NO Kafka; the documented ``onex run-node`` dispatch hard-requires an
   unreachable broker, OMN-13857) and require a fresh ``status == PASS``
   ``ModelDodReceipt`` → ALLOW.
5. Otherwise → BLOCK. A Done-flip with no merged-PR citation and no PASS receipt
   is refused; if ``dod_verify`` cannot be made to run at all, the guard STILL
   BLOCKS (never fail-open on a fake-Done — design requirement 4).

Deterministic contract-root resolution (OMN-13857):
    ``node_dod_verify``'s evidence-check templates embed a ``$CONTRACT_REPO_DIR``
    token that, when unexported, false-negatives every check (real evidence →
    reported "failed"). This guard does NOT rely on an ambient ``CONTRACT_REPO_DIR``
    — it resolves the contract root deterministically from ``OMNI_HOME``
    (``$OMNI_HOME/onex_change_control``) and exports it for the child process.
    The node-side fix (deriving the root inside the node for all callers) is
    tracked in OMN-13857; this guard is self-sufficient regardless.

Exit codes (via :func:`main`):
    0 — allow the tool call
    2 — block the tool call (JSON decision on stderr)
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - deterministic local node invocation, fixed argv
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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

# A receipt older than this is not trusted as proof of a *current* Done. Matches
# the freshness window enforced by pre_tool_use_dod_completion_guard.sh.
_RECEIPT_MAX_AGE_SECONDS = 30 * 60

_LINEAR_TOOLS = frozenset(
    {"mcp__linear-server__save_issue", "mcp__linear-server__update_issue"}
)

# How long the mechanized dod_verify child process is allowed to run before the
# guard treats it as "could not verify" and fails closed.
_DOD_VERIFY_TIMEOUT_SECONDS = 120


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
    default OMNI_HOME. When it is unresolvable, path B (dod_verify) cannot run,
    and the caller falls through to the fail-closed BLOCK.
    """
    raw = os.environ.get("OMNI_HOME", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def contract_repo_dir(omni_home: Path) -> Path:
    """Return the deterministic onex_change_control repo root under OMNI_HOME.

    This is the value the guard exports as ``CONTRACT_REPO_DIR`` for the
    dod_verify child — resolved from a known repo-relative anchor, never read
    from the ambient environment (OMN-13857). Pure function.
    """
    return omni_home / "onex_change_control"


# ---------------------------------------------------------------------------
# Receipt classification (ModelDodReceipt — status=PASS, fresh, well-shaped)
# ---------------------------------------------------------------------------


def verified_check_counts(receipt: dict[str, Any]) -> tuple[int, int, int] | None:
    """Return ``(verified, failed, skipped)`` from a receipt, or ``None``.

    node_dod_verify records the per-check tally as a JSON blob in the receipt's
    ``probe_stdout`` field: ``{"total", "verified", "failed", "skipped", ...}``.
    This is the ONLY field that distinguishes a real durable PASS (>=1 check
    actually verified) from a vacuous PASS where the node found no contract and
    SKIPPED everything (``verified == 0``) — the latter is reported ``PASS`` by
    the node but is NOT evidence. Returns ``None`` when the tally cannot be
    parsed, which the caller treats as fail-closed. Pure function.
    """
    blob = receipt.get("probe_stdout")
    if not isinstance(blob, str) or not blob.strip():
        return None
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    verified = parsed.get("verified")
    failed = parsed.get("failed")
    skipped = parsed.get("skipped")
    if (
        not isinstance(verified, int)
        or not isinstance(failed, int)
        or not isinstance(skipped, int)
    ):
        return None
    return verified, failed, skipped


def classify_receipt(
    receipt: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> str:
    """Classify a dod_verify receipt dict. Returns ``"pass"`` or a failure token.

    Fail-closed: ``"pass"`` requires ALL of — a fresh, well-shaped
    ``ModelDodReceipt``; ``status == PASS``; and a per-check tally proving at
    least one check was actually VERIFIED with zero failures. The last clause is
    decisive: node_dod_verify reports ``status == PASS`` for a ticket with NO
    contract (every check SKIPPED, ``verified == 0``) — a vacuous PASS that is
    NOT durable evidence and is exactly the ``wf_1628d9a5`` incident shape. Any
    other outcome (missing receipt, missing/blank/non-ISO ``run_timestamp``,
    stale, non-PASS status, unparseable or zero-verified tally) returns a
    descriptive non-``"pass"`` token. Mirrors and hardens the validation in
    pre_tool_use_dod_completion_guard.sh.
    """
    if receipt is None:
        return "missing"

    run_ts = receipt.get("run_timestamp")
    if not isinstance(run_ts, str) or not run_ts.strip():
        return "missing_run_timestamp"
    try:
        receipt_time = datetime.fromisoformat(run_ts)
    except ValueError:
        return "parse_error:run_timestamp is not ISO-8601"
    if receipt_time.tzinfo is None:
        return "parse_error:run_timestamp must be timezone-aware"

    reference = now or datetime.now(tz=UTC)
    age = (reference - receipt_time).total_seconds()
    if age > _RECEIPT_MAX_AGE_SECONDS:
        return "stale"

    status = receipt.get("status")
    if not isinstance(status, str) or not status.strip():
        return "missing_status"
    status_norm = status.strip().upper()
    if status_norm != "PASS":
        return f"status_not_pass:{status_norm}"

    # Decisive check: a PASS is durable evidence only if it verified >=1 real
    # check with zero failures. A no-contract PASS (verified == 0) is refused.
    counts = verified_check_counts(receipt)
    if counts is None:
        return "no_verified_checks"
    verified, failed, _skipped = counts
    if failed > 0:
        return f"status_not_pass:PASS_WITH_{failed}_FAILURES"
    if verified < 1:
        return "no_verified_checks"
    return "pass"


# ---------------------------------------------------------------------------
# Mechanized dod_verify runner (deterministic local path — NO Kafka)
# ---------------------------------------------------------------------------


def run_dod_verify_local(
    ticket_id: str,
    *,
    omni_home: Path,
    timeout: int = _DOD_VERIFY_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """Run node_dod_verify via the deterministic local module path.

    Invokes ``uv run --project <OMNI_HOME>/omnimarket python -m
    omnimarket.nodes.node_dod_verify --ticket-id <id> --output-path <tmp>`` with
    ``CONTRACT_REPO_DIR`` exported deterministically. This is the NON-Kafka path
    (OMN-13857 finding 1: the documented ``onex run-node`` dispatch hard-requires
    an unreachable broker; ``onex`` CLI extensions also currently fail to load in
    this env — the ``python -m`` module entry bypasses both).

    Returns the parsed receipt dict, or ``None`` on any failure (missing repo,
    non-zero exit with no receipt, timeout, unparseable output). ``None`` maps to
    a fail-closed BLOCK in the caller.
    """
    market_repo = omni_home / "omnimarket"
    if not market_repo.is_dir():
        return None

    child_env = dict(os.environ)
    # Deterministic contract-root resolution — the crux of OMN-13857. Do NOT
    # inherit an ambient (possibly-unset) CONTRACT_REPO_DIR.
    child_env["CONTRACT_REPO_DIR"] = str(contract_repo_dir(omni_home))

    with tempfile.TemporaryDirectory() as tmpdir:
        receipt_path = Path(tmpdir) / "dod_report.json"
        cmd = [
            "uv",
            "run",
            "--project",
            str(market_repo),
            "python",
            "-m",
            "omnimarket.nodes.node_dod_verify",
            "--ticket-id",
            ticket_id,
            "--output-path",
            str(receipt_path),
        ]
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell, deterministic
                cmd,
                cwd=str(market_repo),
                env=child_env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

        if not receipt_path.exists():
            return None
        try:
            parsed = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return parsed if isinstance(parsed, dict) else None


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
    dod_verify_runner: Callable[[str], dict[str, Any] | None] | None = None,
    pr_fetcher: Callable[[Any], Any] = fetch_pr_status,
    linear_fetcher: Callable[[str], dict[str, Any] | None] = _default_linear_fetcher,
    now: datetime | None = None,
) -> Decision:
    """Return the guard decision for a PreToolUse tool call.

    All I/O boundaries are injectable so unit tests stay hermetic:
      * ``dod_verify_runner(ticket_id) -> receipt|None`` — mechanized dod_verify;
        defaults to the local module runner bound to the resolved OMNI_HOME.
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
    # unreachable: do NOT allow on that basis — fall through to dod_verify,
    # which reads OCC governance, not Linear.
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
    # the mechanized dod_verify receipt path; do NOT allow here.

    if not ticket_id:
        return Decision(
            False,
            "no_ticket_id: cannot verify durable evidence for a Done-flip without "
            "an issue id. Pass 'id' in the save_issue call.",
        )

    # (4) durable evidence path B — mechanized, deterministic-local dod_verify.
    runner = dod_verify_runner
    if runner is None:
        omni_home = resolve_omni_home()
        if omni_home is None:
            return Decision(
                False,
                "no_durable_evidence: OMNI_HOME is unset/invalid, so the local "
                "dod_verify path cannot run and no merged-PR citation was found. "
                "Failing closed (design requirement 4 — never fail-open on a "
                "fake-Done). Set OMNI_HOME, or cite the merged implementing PR in "
                "the ticket description.",
            )
        runner = lambda tid: run_dod_verify_local(tid, omni_home=omni_home)  # noqa: E731

    receipt = runner(ticket_id)
    verdict = classify_receipt(receipt, now=now)
    if verdict == "pass":
        return Decision(True, "durable_evidence:dod_receipt_pass")

    return Decision(False, _block_reason_for_verdict(verdict, ticket_id))


def _block_reason_for_verdict(verdict: str, ticket_id: str) -> str:
    """Render a fail-closed block reason for a non-pass receipt verdict."""
    base = (
        f"no_durable_evidence for {ticket_id}: no merged-PR citation in the "
        "description, and the mechanized dod_verify path did not return a fresh "
        "PASS receipt "
    )
    if verdict == "missing":
        detail = (
            "(dod_verify produced no receipt — no OCC contract for this ticket, or "
            "the local node invocation failed). "
        )
    elif verdict == "no_verified_checks":
        detail = (
            "(dod_verify returned PASS but verified ZERO real checks — no contract "
            "found, so there is nothing proving this ticket is Done). "
        )
    elif verdict == "stale":
        detail = "(the receipt is older than 30 minutes — re-run dod_verify). "
    elif verdict.startswith("status_not_pass:"):
        detail = f"(receipt status is {verdict.split(':', 1)[1]!r}, not PASS). "
    elif verdict.startswith("parse_error:"):
        detail = f"(receipt malformed: {verdict.split(':', 1)[1]}). "
    else:
        detail = f"({verdict}). "
    return (
        base
        + detail
        + "Fail-closed (no fake Done). Cite the merged implementing PR in the "
        "ticket description, add durable OCC evidence, or apply an explicit "
        "close-if-done exemption for a legitimate no-PR close."
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
