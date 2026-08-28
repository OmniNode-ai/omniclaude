#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""worktree_auto_prune.py — ticket-close-keyed worktree pruner [OMN-16901].

The fact-collecting half of the automated pruner. It walks every worktree under
the worktrees root, gathers observations from git / the tracker / the rolling
work ledger, hands them to the **pure** predicate in
``omniclaude.hooks.lib.worktree_prune_policy``, and then either reports or acts.

Why this exists
---------------
Pruning is keyed to the **ticket closing**, not to a PR merging. A ticket spans
multiple PRs and OCC companions and worktrees are keyed by ticket directory, so
a merged PR is an *input to the safety check* (it is what makes the tree-diff
against ``dev`` empty) while ticket completion is what *fires* eligibility. The
predecessor surfaces got this backwards: ``prune-worktrees.sh`` keys purely on
"PR merged or remote branch gone", which per OMN-15551 is anti-correlated with
liveness — a clean, pushed, merged worktree is exactly the state a live lane
occupies between push and post-merge verification.

This script does NOT reimplement ``prune-worktrees.sh``. That script stays the
merge-keyed GC used after a batch merge sweep; this one is the ticket-keyed
sweep, and the two disagree on purpose.

Safety posture
--------------
Dry-run is the default; ``--execute`` is required to remove anything. Removal
uses plain ``git worktree remove`` (no ``--force``) so git itself re-checks
cleanliness as a second, independent gate after the policy's. Everything that is
not prunable becomes a triage row — never a silent drop, never a deletion.

Usage
-----
    # dry run over the default root (report only, removes nothing)
    uv run python scripts/worktree_auto_prune.py

    # write the report where the daily runner expects it
    uv run python scripts/worktree_auto_prune.py \
        --report-md "$OMNI_HOME/docs/tracking/2026-08-29-worktree-prune.md" \
        --report-json "$OMNI_HOME/docs/tracking/2026-08-29-worktree-prune.json"

    # act
    uv run python scripts/worktree_auto_prune.py --execute

Ticket-state resolution reads ``LINEAR_API_KEY`` from the environment, falling
back to ``~/.omnibase/.env``. With ``--no-tracker`` (or no key available) every
ticket state is ``UNKNOWN`` and eligibility falls back to the ledger's
``TERMINAL`` rows, which fails closed when there is none.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # noqa: S404 — fixed git argv lists, never shell-interpolated
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omniclaude.hooks.lib.worktree_health import extract_ticket_id
from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumPruneBlockReason,
    EnumPruneDisposition,
    EnumTicketLifecycle,
    ModelWorktreePruneDecision,
    ModelWorktreePruneFacts,
    classify_worktree_prune,
)

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_BATCH_SIZE = 50
BASE_REF_CANDIDATES: tuple[str, ...] = ("origin/dev", "origin/main")
GIT_TIMEOUT_SECONDS = 60

_TICKET_RE = re.compile(r"OMN-\d+")
_CLAIM_MARKERS: tuple[str, ...] = ("| CLAIM |", "(CLAIM)", "**Status:** IN PROGRESS")
_TERMINAL_MARKERS: tuple[str, ...] = (
    "| TERMINAL |",
    "(TERMINAL)",
    "CLAIM+TERMINAL",
    "**Status:** TERMINAL",
)


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    """Run a git command, returning ``(returncode, stripped stdout)``."""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def discover_worktrees(root: Path) -> list[Path]:
    """Return every git worktree directory under ``root``.

    A linked worktree's ``.git`` is a *file* pointing back at the canonical
    clone, which is what distinguishes it from a full clone.
    """
    found = [p.parent for p in root.glob("*/.git") if p.is_file()]
    found += [p.parent for p in root.glob("*/*/.git") if p.is_file()]
    found += [p.parent for p in root.glob("*/*/*/.git") if p.is_file()]
    return sorted(set(found))


def canonical_root_of(worktree: Path) -> Path | None:
    """Resolve the canonical clone backing a linked worktree."""
    code, common_dir = _git(worktree, "rev-parse", "--git-common-dir")
    if code != 0 or not common_dir:
        return None
    common = Path(common_dir)
    if not common.is_absolute():
        common = (worktree / common).resolve()
    # <canonical>/.git  ->  <canonical>
    return common.parent if common.name == ".git" else None


def resolve_base_ref(canonical: Path) -> str | None:
    """Return the first of ``origin/dev`` / ``origin/main`` that exists."""
    for ref in BASE_REF_CANDIDATES:
        code, _ = _git(canonical, "rev-parse", "--verify", "--quiet", ref)
        if code == 0:
            return ref
    return None


def fetch_base(canonical: Path) -> None:
    """Refresh the base branches of a canonical clone, tolerating failure.

    Fetches the two candidate branches by name rather than running a bare
    ``git fetch origin``: a bare fetch aborts wholesale when any stale
    remote-tracking ref no longer exists upstream, which is routine here.
    """
    for branch in ("dev", "main"):
        _git(canonical, "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")


def stash_subjects(canonical: Path) -> list[str]:
    """Return the subject line of every stash entry in a canonical clone.

    Stashes live in the shared ``refs/stash`` of the common dir, so they are
    repo-wide; attribution to a worktree is by the branch named in the subject
    (``WIP on <branch>: ...`` / ``On <branch>: ...``).
    """
    code, out = _git(canonical, "stash", "list", "--format=%gs")
    if code != 0 or not out:
        return []
    return out.splitlines()


def count_attributed_stashes(subjects: Sequence[str], branch: str | None) -> int:
    """Count stash entries whose subject names ``branch``."""
    if branch is None:
        return 0
    needles = (f"WIP on {branch}:", f"On {branch}:")
    return sum(1 for s in subjects if any(s.startswith(n) for n in needles))


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


def parse_ledger_claims(ledger_path: Path) -> dict[str, tuple[bool, str | None]]:
    """Map each ticket to ``(has_terminal, open_claim_text_or_None)``.

    The ledger is append-only, so line order is chronological order: a CLAIM
    appearing at a later line than the newest TERMINAL for the same ticket means
    a lane resumed work and the worktree must not be touched. A line carrying
    both markers (``CLAIM+TERMINAL``) resolves to TERMINAL.

    Section bodies (``- **Status:** IN PROGRESS.``) carry no ticket id of their
    own, so they inherit the ticket from the nearest preceding ``#`` heading.
    """
    if not ledger_path.is_file():
        return {}

    last_claim: dict[str, tuple[int, str]] = {}
    last_terminal: dict[str, int] = {}
    section_ticket: str | None = None

    for lineno, raw in enumerate(
        ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
    ):
        line = raw.strip()
        if line.startswith("#"):
            heading_ticket = _TICKET_RE.search(line.upper())
            section_ticket = heading_ticket.group(0) if heading_ticket else None

        is_claim = any(m in line for m in _CLAIM_MARKERS)
        is_terminal = any(m in line for m in _TERMINAL_MARKERS)
        if not (is_claim or is_terminal):
            continue

        tickets = set(_TICKET_RE.findall(line.upper()))
        if not tickets and section_ticket:
            tickets = {section_ticket}
        if not tickets:
            continue

        for ticket in tickets:
            if is_terminal:
                last_terminal[ticket] = lineno
            if is_claim:
                last_claim[ticket] = (lineno, line[:240])

    result: dict[str, tuple[bool, str | None]] = {}
    for ticket in set(last_claim) | set(last_terminal):
        terminal_line = last_terminal.get(ticket)
        claim = last_claim.get(ticket)
        open_claim: str | None = None
        if claim is not None and (terminal_line is None or claim[0] > terminal_line):
            open_claim = claim[1]
        result[ticket] = (terminal_line is not None, open_claim)
    return result


# ---------------------------------------------------------------------------
# tracker (Linear)
# ---------------------------------------------------------------------------


def load_linear_api_key() -> str | None:
    """Read ``LINEAR_API_KEY`` from the environment, else ``~/.omnibase/.env``."""
    key = os.environ.get("LINEAR_API_KEY")
    if key:
        return key
    env_file = Path.home() / ".omnibase" / ".env"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("LINEAR_API_KEY="):
            return stripped.split("=", 1)[1].strip().strip("'\"") or None
    return None


def _state_type_to_lifecycle(state_type: str) -> EnumTicketLifecycle:
    if state_type == "completed":
        return EnumTicketLifecycle.DONE
    if state_type == "canceled":
        return EnumTicketLifecycle.CANCELED
    return EnumTicketLifecycle.OPEN


def resolve_ticket_states(
    tickets: Iterable[str], api_key: str
) -> dict[str, EnumTicketLifecycle]:
    """Batch-resolve ticket lifecycle states from Linear.

    Unresolvable tickets are simply absent from the result; the caller maps them
    to :data:`EnumTicketLifecycle.UNKNOWN`, which fails closed.
    """
    ordered = sorted(set(tickets))
    states: dict[str, EnumTicketLifecycle] = {}

    for start in range(0, len(ordered), LINEAR_BATCH_SIZE):
        batch = ordered[start : start + LINEAR_BATCH_SIZE]
        aliases = {f"t{i}": ident for i, ident in enumerate(batch)}
        selections = " ".join(
            f'{alias}: issue(id: "{ident}") {{ identifier state {{ type }} }}'
            for alias, ident in aliases.items()
        )
        payload = json.dumps({"query": f"query {{ {selections} }}"}).encode()
        request = urllib.request.Request(  # noqa: S310 — constant https endpoint
            LINEAR_API_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(
                f"  tracker: batch {start // LINEAR_BATCH_SIZE} failed ({exc}); "
                "those tickets stay UNKNOWN and fail closed",
                file=sys.stderr,
            )
            continue

        for alias, node in (body.get("data") or {}).items():
            if not node:
                continue
            identifier = node.get("identifier") or aliases.get(alias)
            state_type = ((node.get("state") or {}).get("type")) or ""
            if identifier:
                states[identifier.upper()] = _state_type_to_lifecycle(state_type)

    return states


# ---------------------------------------------------------------------------
# fact collection
# ---------------------------------------------------------------------------


def collect_facts(
    worktree: Path,
    root: Path,
    ticket_states: dict[str, EnumTicketLifecycle],
    ledger: dict[str, tuple[bool, str | None]],
    base_ref_cache: dict[Path, str | None],
    stash_cache: dict[Path, list[str]],
) -> ModelWorktreePruneFacts:
    """Observe one worktree. Pure observation — no judgement, no mutation."""
    rel = worktree.relative_to(root)
    ticket_dir = rel.parts[0]
    ticket = extract_ticket_id(ticket_dir)

    code, branch_out = _git(worktree, "branch", "--show-current")
    branch = branch_out if (code == 0 and branch_out) else None

    _, status_out = _git(worktree, "status", "--porcelain")
    dirty_files = tuple(
        line[3:].strip() for line in status_out.splitlines() if line.strip()
    )

    canonical = canonical_root_of(worktree)
    if canonical is None:
        base_ref = None
        stashes: list[str] = []
    else:
        if canonical not in base_ref_cache:
            base_ref_cache[canonical] = resolve_base_ref(canonical)
        base_ref = base_ref_cache[canonical]
        if canonical not in stash_cache:
            stash_cache[canonical] = stash_subjects(canonical)
        stashes = stash_cache[canonical]

    commits_ahead = 0
    unmerged: tuple[str, ...] = ()
    tree_diff_empty = False
    if base_ref is not None:
        code, count_out = _git(worktree, "rev-list", "--count", f"{base_ref}..HEAD")
        if code == 0 and count_out.isdigit():
            commits_ahead = int(count_out)
        if commits_ahead > 0:
            code, cherry_out = _git(worktree, "cherry", base_ref, "HEAD")
            if code == 0:
                unmerged = tuple(
                    line.split(" ", 1)[1].strip()
                    for line in cherry_out.splitlines()
                    if line.startswith("+ ")
                )
            else:
                # Unreadable cherry output must not read as "nothing unmerged".
                unmerged = tuple(f"<unreadable:{i}>" for i in range(commits_ahead))
            code, _ = _git(worktree, "diff", "--quiet", f"{base_ref}...HEAD")
            tree_diff_empty = code == 0

    has_terminal, open_claim = ledger.get(ticket or "", (False, None))

    return ModelWorktreePruneFacts(
        path=str(worktree),
        ticket=ticket,
        repo=worktree.name,
        branch=branch,
        ticket_state=(
            ticket_states.get(ticket, EnumTicketLifecycle.UNKNOWN)
            if ticket
            else EnumTicketLifecycle.UNKNOWN
        ),
        ledger_has_terminal=has_terminal,
        ledger_open_claim=open_claim,
        base_ref=base_ref,
        dirty_files=dirty_files,
        commits_ahead=commits_ahead,
        unmerged_ahead_commits=unmerged,
        tree_diff_vs_base_empty=tree_diff_empty,
        attributed_stash_count=count_attributed_stashes(stashes, branch),
    )


# ---------------------------------------------------------------------------
# action
# ---------------------------------------------------------------------------


def prune_worktree(decision: ModelWorktreePruneDecision) -> tuple[bool, str]:
    """Remove one proven-safe worktree and its local branch.

    Uses plain ``git worktree remove`` — never ``--force`` — so git re-checks
    cleanliness independently of the policy that just approved the removal.
    """
    worktree = Path(decision.path)
    canonical = canonical_root_of(worktree)
    if canonical is None:
        return False, "canonical clone not resolvable"

    code, out = _git(canonical, "worktree", "remove", str(worktree))
    if code != 0:
        return False, f"git worktree remove refused: {out or 'no output'}"

    if decision.branch:
        branch_code, branch_out = _git(canonical, "branch", "-D", decision.branch)
        if branch_code != 0:
            return True, f"worktree removed; branch delete failed: {branch_out}"

    return True, "worktree removed; local branch deleted"


def cleanup_empty_ticket_dirs(root: Path) -> list[str]:
    """Remove now-empty ``omni_worktrees/<ticket>/`` directories."""
    removed: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if any(child.rglob("*")):
            continue
        child.rmdir()
        removed.append(str(child))
    return removed


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def render_report(
    decisions: Sequence[ModelWorktreePruneDecision],
    *,
    root: Path,
    executed: bool,
    generated_at: str,
    removals: Sequence[tuple[str, bool, str]],
    tracker_resolved: int,
) -> str:
    """Render the markdown report. Every worktree appears exactly once."""
    prunable = [d for d in decisions if d.disposition is EnumPruneDisposition.PRUNE]
    triage = [d for d in decisions if d.disposition is EnumPruneDisposition.TRIAGE]

    by_reason: dict[EnumPruneBlockReason, int] = defaultdict(int)
    for decision in triage:
        for reason in decision.block_reasons:
            by_reason[reason] += 1

    mode = "EXECUTE" if executed else "DRY RUN — nothing was removed"
    lines: list[str] = [
        "# Worktree auto-prune report",
        "",
        f"- **Generated:** {generated_at}",
        f"- **Root:** `{root}`",
        f"- **Mode:** {mode}",
        f"- **Scanned:** {len(decisions)}",
        f"- **Prune-eligible and safe:** {len(prunable)}",
        f"- **Triage (never deleted):** {len(triage)}",
        f"- **Ticket states resolved from tracker:** {tracker_resolved}",
        "",
        "Pruning is keyed to the **ticket closing**, not to a PR merging. A merged",
        "PR is an input to the safety check; ticket completion is what fires",
        "eligibility. See `omniclaude/src/omniclaude/hooks/lib/worktree_prune_policy.py`.",
        "",
        "## Triage block reasons",
        "",
        "| Reason | Count |",
        "| --- | ---: |",
    ]
    for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{reason.value}` | {count} |")
    if not by_reason:
        lines.append("| _(none)_ | 0 |")

    lines += [
        "",
        f"## Prune candidates ({len(prunable)})",
        "",
        "| Path | Ticket | Branch | Eligibility | Safety |",
        "| --- | --- | --- | --- | --- |",
    ]
    for decision in prunable:
        lines.append(
            f"| `{decision.path}` | {decision.ticket} | `{decision.branch}` "
            f"| {decision.eligibility_evidence} | {decision.safety_evidence} |"
        )
    if not prunable:
        lines.append("| _(none)_ | | | | |")

    lines += [
        "",
        f"## Triage rows ({len(triage)})",
        "",
        "Never deleted. Each row carries what a human or the morning friction",
        "sweep needs to adjudicate it.",
        "",
        "| Path | Ticket | Branch | Ahead | Dirty files | Block reasons | Ledger claim |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for decision in triage:
        reasons = ", ".join(f"`{r.value}`" for r in decision.block_reasons)
        claim = (decision.ledger_open_claim or "").replace("|", "\\|")
        branch = f"`{decision.branch}`" if decision.branch else "_(detached)_"
        lines.append(
            f"| `{decision.path}` | {decision.ticket or '—'} | {branch} "
            f"| {decision.commits_ahead} | {decision.dirty_file_count} | {reasons} "
            f"| {claim} |"
        )
    if not triage:
        lines.append("| _(none)_ | | | | | | |")

    if removals:
        lines += [
            "",
            f"## Removals ({sum(1 for _, ok, _ in removals if ok)} succeeded)",
            "",
            "| Path | Result | Detail |",
            "| --- | --- | --- |",
        ]
        for path, ok, detail in removals:
            lines.append(f"| `{path}` | {'OK' if ok else 'FAILED'} | {detail} |")

    lines.append("")
    return "\n".join(lines)


def decision_to_json(decision: ModelWorktreePruneDecision) -> dict[str, Any]:
    payload = decision.model_dump(mode="json")
    payload["block_reasons"] = [r.value for r in decision.block_reasons]
    return payload


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ticket-close-keyed worktree pruner. Dry-run by default; --execute "
            "to remove. Eligibility fires on ticket closure, safety gates on "
            "local git state, everything else is reported for triage."
        )
    )
    parser.add_argument(
        "--worktrees-root",
        default=os.environ.get("ONEX_WORKTREES_ROOT")
        or (
            f"{os.environ['OMNI_HOME'].rstrip('/')}/omni_worktrees"
            if os.environ.get("OMNI_HOME")
            else None
        ),
        help="Worktrees root (default: $ONEX_WORKTREES_ROOT, else $OMNI_HOME/omni_worktrees)",
    )
    parser.add_argument(
        "--ledger",
        default=(
            f"{os.environ['OMNI_HOME'].rstrip('/')}/docs/tracking/ROLLING_WORK_LEDGER.md"
            if os.environ.get("OMNI_HOME")
            else None
        ),
        help="Rolling work ledger path (default: $OMNI_HOME/docs/tracking/ROLLING_WORK_LEDGER.md)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually remove prune-eligible worktrees (default: dry run)",
    )
    parser.add_argument(
        "--no-tracker",
        action="store_true",
        help="Skip Linear resolution; every ticket state is UNKNOWN (fails closed)",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip refreshing origin/dev in each canonical clone before classifying",
    )
    parser.add_argument("--report-md", help="Write the markdown report to this path")
    parser.add_argument("--report-json", help="Write the JSON report to this path")
    parser.add_argument(
        "--limit", type=int, default=0, help="Scan at most N worktrees (0 = all)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.worktrees_root:
        print(
            "ERROR: worktrees root unresolved. Set ONEX_WORKTREES_ROOT or OMNI_HOME, "
            "or pass --worktrees-root.",
            file=sys.stderr,
        )
        return 2
    root = Path(args.worktrees_root).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: worktrees root is not a directory: {root}", file=sys.stderr)
        return 2

    ledger_path = Path(args.ledger).expanduser() if args.ledger else None
    if ledger_path is None or not ledger_path.is_file():
        # Fail closed: with no ledger there is no claim-awareness, and a prune
        # without claim-awareness is exactly the OMN-15551 hazard.
        print(
            f"ERROR: ledger not readable ({ledger_path}); refusing to classify "
            "without claim-awareness (OMN-15551).",
            file=sys.stderr,
        )
        return 2

    worktrees = discover_worktrees(root)
    if args.limit > 0:
        worktrees = worktrees[: args.limit]
    print(f"Scanning {len(worktrees)} worktree(s) under {root}", flush=True)

    ledger = parse_ledger_claims(ledger_path)
    print(f"Ledger: {len(ledger)} ticket(s) carry CLAIM/TERMINAL rows", flush=True)

    base_ref_cache: dict[Path, str | None] = {}
    stash_cache: dict[Path, list[str]] = {}

    if not args.no_fetch:
        canonicals = {
            c for c in (canonical_root_of(w) for w in worktrees) if c is not None
        }
        print(
            f"Refreshing base branches in {len(canonicals)} canonical clone(s)",
            flush=True,
        )
        for canonical in sorted(canonicals):
            fetch_base(canonical)

    tickets = {
        t
        for t in (extract_ticket_id(w.relative_to(root).parts[0]) for w in worktrees)
        if t
    }
    ticket_states: dict[str, EnumTicketLifecycle] = {}
    if not args.no_tracker:
        api_key = load_linear_api_key()
        if api_key:
            print(f"Resolving {len(tickets)} ticket state(s) from Linear", flush=True)
            ticket_states = resolve_ticket_states(tickets, api_key)
        else:
            print(
                "WARNING: no LINEAR_API_KEY; every ticket state is UNKNOWN and "
                "eligibility falls back to ledger TERMINAL rows",
                file=sys.stderr,
            )

    # A full root is ~1000 worktrees and several git calls each, so the scan runs
    # for minutes. Report progress as it goes: a silent multi-minute run is
    # indistinguishable from a hung one.
    decisions: list[ModelWorktreePruneDecision] = []
    for index, worktree in enumerate(worktrees, start=1):
        decisions.append(
            classify_worktree_prune(
                collect_facts(
                    worktree, root, ticket_states, ledger, base_ref_cache, stash_cache
                )
            )
        )
        if index % 100 == 0 or index == len(worktrees):
            print(f"  classified {index}/{len(worktrees)}", flush=True)

    prunable = [d for d in decisions if d.disposition is EnumPruneDisposition.PRUNE]
    triage = [d for d in decisions if d.disposition is EnumPruneDisposition.TRIAGE]

    removals: list[tuple[str, bool, str]] = []
    if args.execute:
        for decision in prunable:
            ok, detail = prune_worktree(decision)
            removals.append((decision.path, ok, detail))
            print(f"  {'REMOVED' if ok else 'FAILED '} {decision.path} — {detail}")
        for empty_dir in cleanup_empty_ticket_dirs(root):
            print(f"  RMDIR   {empty_dir}")

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = render_report(
        decisions,
        root=root,
        executed=args.execute,
        generated_at=generated_at,
        removals=removals,
        tracker_resolved=len(ticket_states),
    )

    if args.report_md:
        md_path = Path(args.report_md).expanduser()
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(report, encoding="utf-8")
        print(f"Wrote markdown report: {md_path}")
    if args.report_json:
        json_path = Path(args.report_json).expanduser()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "root": str(root),
                    "executed": args.execute,
                    "scanned": len(decisions),
                    "prune_count": len(prunable),
                    "triage_count": len(triage),
                    "decisions": [decision_to_json(d) for d in decisions],
                    "removals": [
                        {"path": p, "ok": ok, "detail": d} for p, ok, d in removals
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Wrote JSON report: {json_path}")

    print(
        f"\nscanned={len(decisions)} safe={len(prunable)} triage={len(triage)} "
        f"removed={sum(1 for _, ok, _ in removals if ok)}"
    )
    if not args.execute and prunable:
        print("Dry run — re-run with --execute to remove the prune candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
