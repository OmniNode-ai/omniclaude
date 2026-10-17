#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Doctrine-claim gate — explicit claims must match live ticket state.

OMN-18529. Every claim that a mechanism is unbuilt, in flight or blocked carries
an HTML comment with whitespace-separated key=value tokens, exactly these keys:

    <!-- doctrine-claim: type=unbuilt ticket=OMN-1234 role=implementation -->

One marker names one ticket; a claim naming two tickets carries two markers.
A marker can appear anywhere in the same block (a run of non-blank lines).
Each Markdown table row is its own block. Code fences are ignored.

* ``unbuilt`` requires role ``implementation`` and accepts any non-terminal
  state (``triage``, ``backlog``, ``unstarted``, ``started``).
* ``in_flight`` requires role ``implementation`` and accepts ``started`` only.
* ``blocked`` allows role ``blocker`` or ``implementation`` and accepts any
  non-terminal state. ``completed`` and ``canceled`` refuse both unbuilt and
  blocked claims.

**Open-versus-closed is not a sufficient predicate, and that is the whole
point.** A check that only asks whether the named ticket is open passes a
claim of work *in flight* whose ticket sits in Backlog, and Backlog is exactly
where a reclassified in-flight item lands. Rule 18 of the registry doctrine
file spent three weeks reading as imminent for that reason, so ``in_flight``
accepts ``started`` and nothing else.

Claim-shaped prose is checked for every matching type after markers are
removed. Each type requires a marker, so rewording cannot hide a claim.
Malformed markers, missing tickets, and missing or disallowed roles refuse.
Only fully valid markers cause ticket-state lookups.

An unreadable file, an unresolvable ticket, an unreachable tracker, or missing
credentials refuses. A scan with ZERO claim sentences or markers also refuses:
a gate that audits nothing and reports green manufactures confidence.
Claim-shaped prose without markers returns findings rather than an empty scan.

**The ticket-state source is named here, in the checker's own source.** It is
the Linear GraphQL API at :data:`TICKET_STATE_ENDPOINT`, authenticated with
the token in :data:`TICKET_STATE_ENV`. There is no snapshot file and no offline
mode. A missing credential is a refusal rather than a skip: a gate that cannot
read its input has not passed, it has not run.

*This deliberately diverges from the nearest precedent in this repository.*
``.github/workflows/stale-todo-gate.yml`` reads the same secret and, when it is
absent, prints a warning and **skips** — a silent pass on a merge-gating path,
which is the class of defect this gate exists to remove.

The registry repository consumes this checker as a pinned reusable workflow
plus an exported pre-commit hook — one implementation, one verdict.

Exit codes: ``0`` every claim holds, ``1`` findings, ``2`` the gate could not
run (also a failure, distinguished from a doctrine defect).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------
# The ticket-state resolution source. AC3: named in the checker's own source,
# fails closed when unreadable.
# --------------------------------------------------------------------------

#: The live tracker. Chosen over a dated snapshot refreshed by a scheduled job
#: because a snapshot introduces a second staleness window of exactly the kind
#: this gate exists to catch: the snapshot would go stale, the gate would read
#: it confidently, and a Done ticket would pass as open until someone noticed.
TICKET_STATE_ENDPOINT: Final[str] = (
    "https://api.linear.app/graphql"  # url-authority-ok: the tracker's single documented GraphQL endpoint, read-only ticket-state lookups from a CI checker script that is not a runtime node and has no routing authority or integration catalog to resolve from; same endpoint and same reasoning as scripts/worktree_auto_prune.py
)

#: The credential. Absent means REFUSE, never skip. See the module docstring.
TICKET_STATE_ENV: Final[str] = "LINEAR_API_KEY"

_HTTP_TIMEOUT_SECONDS: Final[int] = 20

# --------------------------------------------------------------------------
# Ticket-state vocabulary
# --------------------------------------------------------------------------

#: Linear's own `state.type` values. Anything outside this set is unknown and
#: refuses rather than being bucketed by guesswork.
KNOWN_STATE_TYPES: Final[frozenset[str]] = frozenset(
    {"triage", "backlog", "unstarted", "started", "completed", "canceled"}
)

#: A claim of the form "this does not exist" / "this is blocked" cannot be true
#: of a ticket that is finished or abandoned.
TERMINAL_STATE_TYPES: Final[frozenset[str]] = frozenset({"completed", "canceled"})

TICKET_RE: Final[re.Pattern[str]] = re.compile(r"\bOMN-\d{3,6}\b")

# --------------------------------------------------------------------------
# The claim-sentence family. AC1: a family, not one phrasing.
# --------------------------------------------------------------------------

#: Every distinct matching type is claim-shaped. Each entry is (type, pattern).
CLAIM_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    # blocked — the sentence says what the work waits on
    ("blocked", re.compile(r"\bblocked\s+on\b", re.I)),
    ("blocked", re.compile(r"\bwait(?:s|ing)?\s+on\b", re.I)),
    ("blocked", re.compile(r"\bgated\s+on\b", re.I)),
    # in_flight — the sentence says the work is happening now
    ("in_flight", re.compile(r"\bin\s+flight\b", re.I)),
    ("in_flight", re.compile(r"\bpending\s+merge\b", re.I)),
    ("in_flight", re.compile(r"\bis\s+pending\b", re.I)),
    ("in_flight", re.compile(r"\bis\s+being\s+(?:built|rolled|migrated)\b", re.I)),
    ("in_flight", re.compile(r"\bcurrently\s+in\s+progress\b", re.I)),
    # unbuilt — the sentence says the mechanism does not exist
    ("unbuilt", re.compile(r"\bnot\s+mechanically\s+enforced\b", re.I)),
    ("unbuilt", re.compile(r"\bdoctrine\s+only\b", re.I)),
    ("unbuilt", re.compile(r"\bnothing\s+enforces\b", re.I)),
    ("unbuilt", re.compile(r"\bis\s+not\s+enforced\b", re.I)),
    ("unbuilt", re.compile(r"\bnever\s+audited\b", re.I)),
    ("unbuilt", re.compile(r"\bdoes\s+not\s+yet\b", re.I)),
    ("unbuilt", re.compile(r"\bis\s+not\s+built\b", re.I)),
    ("unbuilt", re.compile(r"\bnot\s+started\b", re.I)),
    ("unbuilt", re.compile(r"\bnever\s+been\s+started\b", re.I)),
)

#: The states each claim type accepts, keyed by type.
EXPECTED_STATES: Final[dict[str, frozenset[str]]] = {
    "unbuilt": KNOWN_STATE_TYPES - TERMINAL_STATE_TYPES,
    "blocked": KNOWN_STATE_TYPES - TERMINAL_STATE_TYPES,
    "in_flight": frozenset({"started"}),
}

#: Roles must be declared explicitly in each marker.
ALLOWED_ROLES: Final[dict[str, frozenset[str]]] = {
    "unbuilt": frozenset({"implementation"}),
    "in_flight": frozenset({"implementation"}),
    "blocked": frozenset({"blocker", "implementation"}),
}


class GateError(RuntimeError):
    """The gate could not run. Distinct from a doctrine finding (exit 2)."""


@dataclass(frozen=True)
class Marker:
    """One explicit marker and the prose block it annotates."""

    path: str
    line: int
    claim_type: str | None
    ticket: str | None
    role: str | None
    raw: str
    sentence: str
    closed: bool


@dataclass(frozen=True)
class ClaimShaped:
    """All claim types found in a block after stripping marker text."""

    path: str
    line: int
    sentence: str
    claim_types: tuple[str, ...]
    marker_types: frozenset[str]


@dataclass(frozen=True)
class Scan:
    """Markers and claim-shaped blocks extracted from doctrine files."""

    markers: tuple[Marker, ...]
    claims: tuple[ClaimShaped, ...]


@dataclass(frozen=True)
class Finding:
    """One refusal, naming the rule, the sentence and the ticket."""

    kind: str
    path: str
    line: int
    ticket: str | None
    detail: str
    sentence: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}"
        who = f" [{self.ticket}]" if self.ticket else ""
        return f"{self.kind}: {where}{who}\n    {self.detail}\n    > {self.sentence.strip()[:200]}"


# --------------------------------------------------------------------------
# Block and marker extraction
# --------------------------------------------------------------------------

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*```")
_MARKER_START_RE: Final[re.Pattern[str]] = re.compile(r"<!--\s*doctrine-claim\b")
# Stop at the next marker start as well as the closing delimiter, so an
# unclosed marker cannot swallow a later marker in the same block.
_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"<!--\s*doctrine-claim\b(?:(?!<!--\s*doctrine-claim\b|-->).)*"
    r"(?:-->|$|(?=<!--\s*doctrine-claim\b))",
    re.S,
)


def iter_blocks(text: str) -> list[tuple[int, str]]:
    """Return prose blocks with first-line numbers, ignoring code fences.

    A block is a run of non-blank lines, except that each table row is its own
    block. Newlines are preserved so marker locations retain their line numbers.
    """
    out: list[tuple[int, str]] = []
    in_fence = False
    buf: list[str] = []
    start = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            if buf:
                out.append((start, "\n".join(buf)))
                buf = []
            continue
        if in_fence:
            continue
        line = raw.strip()
        if not line or line.startswith("|"):
            if buf:
                out.append((start, "\n".join(buf)))
                buf = []
            if line:
                out.append((lineno, line))
            continue
        if not buf:
            start = lineno
        buf.append(line)
    if buf:
        out.append((start, "\n".join(buf)))
    return out


def _marker_tokens(raw: str) -> tuple[dict[str, str], list[str]]:
    """Recover declared values and report every grammar problem."""
    body = _MARKER_START_RE.sub("", raw, count=1)
    if body.endswith("-->"):
        body = body[:-3]
    body = body.strip()
    problems: list[str] = []
    if not body.startswith(":"):
        problems.append("marker requires a colon after doctrine-claim")
    else:
        body = body[1:]
    values: dict[str, str] = {}
    for token in body.split():
        if "=" not in token:
            problems.append(f"token {token!r} is not key=value")
            continue
        key, value = token.split("=", 1)
        if key not in {"type", "ticket", "role"}:
            problems.append(f"unknown key {key!r}; keys are exactly type, ticket, role")
        if key in values:
            problems.append(f"duplicate key {key!r}")
        else:
            values[key] = value
    return values, problems


def collect_claims(path: Path) -> Scan:
    """Parse one file into markers and claim-shaped prose; refuse unreadable input."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"unreadable doctrine file {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise GateError(f"doctrine file {path} is not valid UTF-8: {exc}") from exc

    markers: list[Marker] = []
    claims: list[ClaimShaped] = []
    for lineno, block in iter_blocks(text):
        matches = list(_MARKER_RE.finditer(block))
        sentence = " ".join(_MARKER_RE.sub("", block).split())
        block_markers: list[Marker] = []
        for match in matches:
            raw = match.group()
            values, _ = _marker_tokens(raw)
            block_markers.append(
                Marker(
                    path=str(path),
                    line=lineno + block[: match.start()].count("\n"),
                    claim_type=values.get("type"),
                    ticket=values.get("ticket"),
                    role=values.get("role"),
                    raw=raw,
                    sentence=sentence,
                    closed=raw.endswith("-->"),
                )
            )
        markers.extend(block_markers)
        claim_types = tuple(
            dict.fromkeys(
                claim_type
                for claim_type, pattern in CLAIM_PATTERNS
                if pattern.search(sentence)
            )
        )
        if claim_types:
            claims.append(
                ClaimShaped(
                    path=str(path),
                    line=lineno,
                    sentence=sentence,
                    claim_types=claim_types,
                    marker_types=frozenset(
                        m.claim_type for m in block_markers if m.claim_type is not None
                    ),
                )
            )
    return Scan(tuple(markers), tuple(claims))


# --------------------------------------------------------------------------
# Ticket-state resolution
# --------------------------------------------------------------------------


def resolve_states(tickets: set[str], *, token: str | None = None) -> dict[str, str]:
    """Resolve every ticket to its Linear ``state.type``.

    Fails closed: no credential, a transport error, a GraphQL error, an
    unresolvable id, or a state type outside :data:`KNOWN_STATE_TYPES` each
    raise :class:`GateError`.
    """
    if not tickets:
        return {}
    key = token if token is not None else os.environ.get(TICKET_STATE_ENV, "")
    if not key:
        raise GateError(
            f"{TICKET_STATE_ENV} is not set, so ticket states cannot be resolved. "
            "This gate REFUSES rather than skipping: a gate that cannot read its "
            "input has not passed, it has not run."
        )

    states: dict[str, str] = {}
    for ticket in sorted(tickets):
        query = {
            "query": "query($id:String!){ issue(id:$id){ identifier state { type } } }",
            "variables": {"id": ticket},
        }
        # B310 asks whether this can be pointed at `file:` or a custom scheme.
        # It cannot: the endpoint is a module constant and the scheme is
        # asserted here rather than assumed, so the suppression below rests on
        # a check rather than on a promise.
        if not TICKET_STATE_ENDPOINT.startswith("https://"):
            raise GateError(
                f"refusing to resolve ticket state over a non-https endpoint: "
                f"{TICKET_STATE_ENDPOINT!r}"
            )
        request = urllib.request.Request(  # noqa: S310 - https asserted above
            TICKET_STATE_ENDPOINT,
            data=json.dumps(query).encode("utf-8"),
            headers={"Authorization": key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            # https scheme asserted above, so B310's file:/custom-scheme
            # concern cannot apply.
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request, timeout=_HTTP_TIMEOUT_SECONDS
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GateError(
                f"ticket-state source unreachable for {ticket}: {exc}"
            ) from exc
        if body.get("errors"):
            raise GateError(
                f"ticket-state source returned an error for {ticket}: {body['errors']}"
            )
        issue = (body.get("data") or {}).get("issue")
        if not issue:
            raise GateError(
                f"unresolvable ticket id {ticket}: the tracker returned no issue"
            )
        state_type = ((issue.get("state") or {}).get("type") or "").lower()
        if state_type not in KNOWN_STATE_TYPES:
            raise GateError(
                f"{ticket} has unknown state type {state_type!r}; refusing rather than guessing"
            )
        states[ticket] = state_type
    return states


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def _marker_findings(marker: Marker) -> list[Finding]:
    """Validate a marker without reading the tracker."""
    _, problems = _marker_tokens(marker.raw)
    if not marker.closed:
        problems.append("unclosed doctrine-claim comment; requires -->")
    if marker.claim_type not in EXPECTED_STATES:
        problems.append(
            f"type {marker.claim_type!r} must be unbuilt, in_flight or blocked"
        )
    ticket_valid = (
        marker.ticket is not None and TICKET_RE.fullmatch(marker.ticket) is not None
    )
    issues = [("MARKER_MALFORMED", problem) for problem in problems]
    if not ticket_valid:
        issues.append(
            (
                "MARKER_NAMES_NO_TICKET",
                "marker requires one ticket matching OMN- followed by 3 to 6 digits",
            )
        )
    allowed_roles = ALLOWED_ROLES.get(marker.claim_type or "")
    if not marker.role or (
        allowed_roles is not None and marker.role not in allowed_roles
    ):
        issues.append(
            (
                "MARKER_HAS_NO_ROLE",
                f"role {marker.role!r} is missing or not allowed for type {marker.claim_type!r}",
            )
        )
    return [
        Finding(
            kind,
            marker.path,
            marker.line,
            marker.ticket if ticket_valid else None,
            detail,
            marker.sentence,
        )
        for kind, detail in issues
    ]


def evaluate(scan: Scan, states: dict[str, str]) -> list[Finding]:
    """Turn a scan plus resolved states into findings."""
    findings: list[Finding] = []
    for claim in scan.claims:
        for claim_type in claim.claim_types:
            if claim_type not in claim.marker_types:
                findings.append(
                    Finding(
                        kind="UNMARKED_CLAIM",
                        path=claim.path,
                        line=claim.line,
                        ticket=None,
                        detail=f"a {claim_type} claim requires a marker so rewording cannot hide a claim",
                        sentence=claim.sentence,
                    )
                )
    for marker in scan.markers:
        invalid = _marker_findings(marker)
        if invalid:
            findings.extend(invalid)
            continue
        assert marker.ticket is not None and marker.claim_type is not None  # noqa: S101 - validated above
        state = states.get(marker.ticket)
        if state is None:  # pragma: no cover - resolve_states fails closed first
            raise GateError(f"{marker.ticket} was never resolved")
        expected = EXPECTED_STATES[marker.claim_type]
        if state not in expected:
            findings.append(
                Finding(
                    kind="CLAIM_CONTRADICTED_BY_TICKET_STATE",
                    path=marker.path,
                    line=marker.line,
                    ticket=marker.ticket,
                    detail=(
                        f"the sentence claims {marker.claim_type!r} and binds {marker.ticket} as the "
                        f"{marker.role}, but {marker.ticket} is {state!r}; a {marker.claim_type} claim accepts "
                        f"only {sorted(expected)}"
                    ),
                    sentence=marker.sentence,
                )
            )
    return findings


def run(paths: list[Path], *, token: str | None = None) -> tuple[int, list[Finding]]:
    """Run the gate. Returns ``(exit_code, findings)``."""
    scans = [collect_claims(path) for path in paths]
    scan = Scan(
        tuple(marker for item in scans for marker in item.markers),
        tuple(claim for item in scans for claim in item.claims),
    )
    if not scan.markers and not scan.claims:
        raise GateError(
            "the scan matched ZERO claim sentences or markers across "
            f"{[str(p) for p in paths]}. A gate that audits nothing and reports green is "
            "the defect this gate exists to remove, so an empty scan is a refusal."
        )
    wanted = {
        marker.ticket
        for marker in scan.markers
        if marker.ticket is not None and not _marker_findings(marker)
    }
    states = resolve_states(wanted, token=token) if wanted else {}
    findings = evaluate(scan, states)
    return (1 if findings else 0), findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="doctrine files to check")
    args = parser.parse_args(argv)
    try:
        code, findings = run(list(args.paths))
    except GateError as exc:
        print(f"doctrine-claim gate COULD NOT RUN: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.render(), file=sys.stderr)
    if findings:
        print(f"\n{len(findings)} doctrine-claim finding(s).", file=sys.stderr)
    else:
        print("doctrine-claim gate: every claim holds against live ticket state.")
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
