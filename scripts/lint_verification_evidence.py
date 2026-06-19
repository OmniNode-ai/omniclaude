#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lint gate: reject local-clone / ticket-text / statusCheckRollup citations as proof of state.

Retro enforcement R6 (OMN-13341), child of OMN-13325. Doctrine:
``docs/standards/VERIFICATION_DOCTRINE.md``.

A claim about system state is only true if verified against an authoritative,
live truth surface: ``origin/dev`` for existence, the live materialized
projection for runtime/data state, ``gh pr checks`` for PR verdicts. Local
canonical clones, ticket prose, and ``statusCheckRollup`` drift from live truth.
This session proved it three times (stale clone false NOT_FOUND; stale ticket
"escalation never fires"; statusCheckRollup FAILURE after passing reruns).

This gate scans worker-prompt / receipt / handoff / evidence documents and flags
text that cites a non-authoritative surface AS PROOF of state. It is a regression
guard against reverting to convenient-but-wrong evidence.

## What it flags

1. ``statusCheckRollup`` used as a PR pass/fail VERDICT — the field appearing on
   the same line as a verdict token (PASS/FAIL/FAILURE/SUCCESS/green/red/
   passed/failed/clean). The rollup caches stale terminal state; ``gh pr checks``
   is the live source. Merely fetching the field (``--json statusCheckRollup``),
   dropping cached state (``.pop(...)``), or explaining queue mechanics is NOT a
   verdict and does NOT trip the gate.
2. A "verified/proven/confirmed ... against/from/in the/a local clone" phrasing
   — asserting state from a local canonical clone instead of ``origin/dev``.
3. A "the ticket says/states ... so/therefore/proving ..." phrasing — asserting
   current state from ticket prose instead of the live projection/bus.

The patterns are deliberately phrase-anchored (verb / verdict token + non-
authoritative surface) so that *mentioning* a local clone, a ticket, or the
rollup field — e.g. documenting the failure mode (as this very file does), or
fetching the raw field in code — does not trip the gate. Only asserting state
FROM one as proof does.

## Scope

Scans these document classes (the surfaces where worker prompts and receipts
live), passed as args (pre-commit) or discovered under the repo (CI):

- ``plugins/onex/skills/**/*.md``       (skill prompts)
- ``docs/handoffs/**/*.md``             (handoffs)
- ``docs/receipts/**`` and ``**/*receipt*.md`` / ``**/*receipt*.txt``
- ``.onex_state/evidence/**``           (committed evidence text)

Source code, tests, and this doctrine doc are out of scope.

## Suppression

Append ``# verification-evidence-ok: <reason>`` to the offending line. The reason
must be a real justification, not a free-text bypass of the doctrine.

## Exit codes

- 0 — no violations
- 1 — one or more violations (or an unreadable in-scope file: fail closed)

## Usage

- Pre-commit: invoked with staged paths passed as arguments.
- CI: invoked with no arguments; discovers in-scope docs under the repo root.
- Self-test: ``--self-test`` runs synthetic cases and exits.

## Refs

- OMN-13341 (this gate) / OMN-13325 (epic)
- docs/standards/VERIFICATION_DOCTRINE.md
- omni_home/docs/audits/2026-06-19-ratchet-enforcement-audit.md
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

SUPPRESSION = "verification-evidence-ok:"

# This doctrine doc and this lint itself necessarily quote the forbidden phrasing
# to document it; exclude them from scanning so they do not self-trip.
SELF_EXCLUDE_SUFFIXES = (
    "docs/standards/VERIFICATION_DOCTRINE.md",
    "scripts/lint_verification_evidence.py",
    "tests/unit/scripts/test_lint_verification_evidence.py",
)

# Phrase-anchored patterns: a proof/verification verb adjacent to a
# non-authoritative surface used AS evidence of state. Phrase anchoring (not a
# bare keyword) is what keeps documentation of the failure mode from tripping.
_VERIFY_VERB = (
    r"(?:verif\w+|proven|prov(?:es|ed|ing)|confirm\w+|attest\w+|shows?\b|asserts?\b)"
)
_STATE_VERB = r"(?:says?|states?|claims?|reports?|shows?)"

# A PR pass/fail verdict token. statusCheckRollup is only a violation when it is
# being read AS a verdict (same line as one of these), not when the raw field is
# fetched (--json statusCheckRollup), dropped (.pop), or named in queue mechanics.
_VERDICT_WORD = (
    r"(?:PASS(?:ED|ING)?|FAIL(?:ED|URE|ING)?|SUCCESS|"
    r"\bgreen\b|\bred\b|\bclean\b|all\s+checks?\s+pass)"
)

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "statusCheckRollup read as a PR pass/fail verdict (use `gh pr checks` — "
        "rollup caches stale terminal state)",
        re.compile(
            rf"(?:statusCheckRollup[^.\n]*{_VERDICT_WORD}"
            rf"|{_VERDICT_WORD}[^.\n]*statusCheckRollup)",
            re.IGNORECASE,
        ),
    ),
    (
        "state asserted from a LOCAL CLONE (verify existence against "
        "`origin/dev`, not a local canonical clone)",
        re.compile(
            rf"{_VERIFY_VERB}[^.\n]*\b(?:against|from|in|via|using)\b[^.\n]*"
            r"\blocal\s+(?:canonical\s+)?clone\b",
            re.IGNORECASE,
        ),
    ),
    (
        "state asserted from TICKET TEXT (verify current state against the live "
        "projection/bus, not ticket prose)",
        re.compile(
            rf"\bticket\b[^.\n]*{_STATE_VERB}[^.\n]*"
            r"\b(?:so|therefore|thus|hence|proving|which\s+proves|confirming)\b",
            re.IGNORECASE,
        ),
    ),
)


def _in_scope(path: Path) -> bool:
    """True when ``path`` is a worker-prompt / receipt / handoff / evidence doc."""
    posix = path.as_posix()
    if any(posix.endswith(suffix) for suffix in SELF_EXCLUDE_SUFFIXES):
        return False
    if path.suffix not in (".md", ".txt"):
        return False
    parts = path.parts
    name = path.name.lower()
    if "skills" in parts and path.suffix == ".md" and "plugins" in parts:
        return True
    if "handoffs" in parts:
        return True
    if "receipt" in name or "receipts" in parts:
        return True
    if "evidence" in parts:
        return True
    return False


def _scan_text(text: str) -> tuple[list[tuple[int, str, str]], None]:
    """Return ``(hits, None)`` where each hit is ``(line_no, message, raw)``."""
    hits: list[tuple[int, str, str]] = []
    for idx, raw in enumerate(text.splitlines(), start=1):
        if SUPPRESSION in raw:
            continue
        for message, pattern in PATTERNS:
            if pattern.search(raw):
                hits.append((idx, message, raw.strip()))
    return hits, None


def _scan_file(path: Path) -> tuple[list[tuple[int, str, str]], str | None]:
    """Scan a file. Fail closed (treat as violation) if it is unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [], f"{path}: decode error: {exc}"
    except OSError as exc:
        return [], f"{path}: read error: {exc}"
    hits, _ = _scan_text(text)
    return hits, None


def _discover(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in (
        "plugins/onex/skills/**/*.md",
        "docs/handoffs/**/*.md",
        "docs/handoffs/**/*.txt",
        "docs/receipts/**/*.md",
        "docs/receipts/**/*.txt",
        ".onex_state/evidence/**/*.md",
        ".onex_state/evidence/**/*.txt",
    ):
        candidates.extend(root.glob(pattern))
    # Catch *receipt*.md anywhere under docs/.
    candidates.extend(root.glob("docs/**/*receipt*.md"))
    candidates.extend(root.glob("docs/**/*receipt*.txt"))
    return sorted({p for p in candidates if p.is_file() and _in_scope(p)})


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if args and args[0] == "--self-test":
        return _self_test()

    if args:
        targets = [Path(a) for a in args if _in_scope(Path(a))]
    else:
        targets = _discover(Path.cwd())

    total = 0
    violating: list[Path] = []
    for path in targets:
        if not path.exists():
            continue
        hits, read_error = _scan_file(path)
        if read_error is not None:
            sys.stderr.write(f"{read_error}\n")
            violating.append(path)
            total += 1
            continue
        if not hits:
            continue
        violating.append(path)
        for line_no, message, raw in hits:
            sys.stderr.write(f"{path}:{line_no}: {message}\n    | {raw}\n")
            total += 1

    if total == 0:
        return 0

    sys.stderr.write(
        "\n"
        f"BLOCKED: {total} non-authoritative evidence citation(s) in "
        f"{len(violating)} file(s).\n"
        "\n"
        "A claim about system state must be verified against a LIVE truth "
        "surface:\n"
        "  - existence       -> origin/dev (git show origin/dev:<path>), "
        "not a local clone\n"
        "  - runtime/data    -> the live materialized projection / bus, "
        "not ticket prose\n"
        "  - PR check verdict -> gh pr checks <num>, not statusCheckRollup\n"
        "\n"
        "See docs/standards/VERIFICATION_DOCTRINE.md.\n"
        f"Suppress a false positive with: # {SUPPRESSION} <reason>\n"
    )
    return 1


def _self_test() -> int:
    cases: list[tuple[str, str, bool]] = [
        # (name, line, should_flag)
        (
            "statusCheckRollup as verdict (PASS) flags",
            "CI verified via statusCheckRollup PASS",
            True,
        ),
        (
            "statusCheckRollup as verdict (green) flags",
            "PR is green per statusCheckRollup, merging.",
            True,
        ),
        (
            "statusCheckRollup --json field fetch passes",
            "gh pr view 1 --json headRefOid,state,statusCheckRollup",
            False,
        ),
        (
            "statusCheckRollup .pop drop passes",
            'live.pop("statusCheckRollup", None)',
            False,
        ),
        (
            "statusCheckRollup queue-mechanics mention passes",
            "Merge queues require ALL `statusCheckRollup` entries to complete.",
            False,
        ),
        (
            "verified against local clone flags",
            "Confirmed the node exists, verified against the local clone.",
            True,
        ),
        (
            "proven from local canonical clone flags",
            "Node absence proven from the local canonical clone (NOT_FOUND).",
            True,
        ),
        (
            "ticket-says-so-proves flags",
            "The ticket says escalation never fires, so the layer is broken.",
            True,
        ),
        (
            "gh pr checks verdict passes",
            "CI verified green via `gh pr checks 1781 --repo OmniNode-ai/omniclaude`.",
            False,
        ),
        (
            "origin/dev existence passes",
            "Confirmed the node exists on origin/dev via git show origin/dev:<path>.",
            False,
        ),
        (
            "projection runtime state passes",
            "Runtime state verified against projection_delegation_model_routing.",
            False,
        ),
        (
            "merely mentioning a local clone (no proof verb) passes",
            "Read the file from the local clone, then re-verify against origin/dev.",
            False,
        ),
        (
            "merely mentioning a ticket (no proof chain) passes",
            "The ticket describes the intended behavior; current state TBD.",
            False,
        ),
        (
            "suppression token passes",
            "verified against the local clone  # verification-evidence-ok: doc example",
            False,
        ),
    ]
    passed = 0
    failed = 0
    for name, line, should_flag in cases:
        hits, _ = _scan_text(line)
        flagged = bool(hits)
        if flagged == should_flag:
            print(f"  PASS: {name}")
            passed += 1
        else:
            print(f"  FAIL: {name} (expected flagged={should_flag}, got {flagged})")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
