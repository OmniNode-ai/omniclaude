#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Doctrine-claim gate — a sentence saying a mechanism is unenforced must be true.

OMN-18529 (W2-2). The companion to OMN-18528, which corrected four sentences in
the registry doctrine file that said a mechanism was unenforced, in flight or
never audited while the ticket each named was already Done. That was the
correction; this is the check that stops it recurring.

**What it refuses.** A doctrine sentence that asserts a mechanism is not built,
is being built, or is waiting on something, while the ticket it names is in a
state that claim cannot be true of. Three claim types, each binding a ticket to
a ROLE with its own expected state set:

* ``unbuilt`` binds the IMPLEMENTATION ticket and refuses ``completed`` or
  ``canceled``; anything else passes.
* ``in_flight`` binds the IMPLEMENTATION ticket and passes ``started`` ONLY.
  ``backlog``, ``unstarted``, ``completed`` and ``canceled`` all refuse.
* ``blocked`` binds the BLOCKER ticket and refuses ``completed`` or
  ``canceled``; anything else passes.

**Open-versus-closed is not a sufficient predicate, and that is the whole
point.** A check that only asks whether the named ticket is open passes a
sentence claiming work is *in flight* whose ticket sits in Backlog — and
Backlog is exactly where a reclassified in-flight item lands. Rule 18 of the
registry doctrine file spent three weeks reading as imminent for that reason,
its ticket never once started. So ``in_flight`` accepts ``started`` and
nothing else.

**It fails closed, everywhere.** An unreadable file, an unparseable sentence,
an unresolvable ticket id, an unreachable ticket-state source, and a scan that
matches zero claim sentences are each a refusal, never a pass. The
zero-sentence case is deliberate and is the shape this whole epic exists to
remove: a gate that audits nothing and reports green is worse than no gate,
because it manufactures confidence. If this checker is ever pointed at a file
with no claims in it, that is a wiring error and it says so loudly.

**The ticket-state source is named here, in the checker's own source, as AC3
requires.** It is the Linear GraphQL API at :data:`TICKET_STATE_ENDPOINT`,
authenticated with the token in :data:`TICKET_STATE_ENV`. There is no snapshot
file and no offline mode.

*This deliberately diverges from the nearest precedent in this repository.*
``.github/workflows/stale-todo-gate.yml`` reads the same secret and, when it is
absent, prints a warning and **skips** — a silent pass on a merge-gating path,
which is the class of defect this epic was opened to remove. A missing
credential here is a refusal: a gate that cannot read its input has not passed,
it has not run.

**Where it lives and why.** Here, in the repository that owns hooks and gates,
because the registry repository refuses functional code outside its
documentation and test trees. The registry repository consumes it as a pinned
reusable workflow plus an exported pre-commit hook — one implementation, one
verdict — which is the settled shape ``kb_doc_gate.py`` already uses across the
same two repositories.

Exit codes: ``0`` every claim holds, ``1`` findings, ``2`` the gate could not
run (which is also a failure, reported distinctly so a wiring fault is not read
as a doctrine defect).
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
TICKET_STATE_ENDPOINT: Final[str] = "https://api.linear.app/graphql"

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

#: Ordered. The FIRST matching pattern decides the claim type, so the more
#: specific phrasings come first. Each entry is (claim_type, pattern).
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

#: Phrasings that mark the ticket AFTER them as the blocker rather than the
#: implementation. AC7: a role is declared, never defaulted silently.
BLOCKER_ROLE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:blocked\s+on|wait(?:s|ing)?\s+on|gated\s+on|blocker(?:\s+is)?)\b[^.]{0,80}?"
    r"(OMN-\d{3,6})",
    re.I,
)

#: Phrasings that positively mark a ticket as the implementation. Without one
#: of these, a single-id sentence still binds to implementation (that is the
#: ordinary case and is not a guess); a MULTI-id sentence with no role markers
#: is a finding of its own kind, because defaulting there would resolve two
#: ids against one expected set.
_IMPL_MARKER: Final[str] = (
    r"tracked\s+(?:in|by)|tracks|implemented\s+(?:in|by)|built\s+(?:in|by)|"
    r"lands?\s+in|ticket\s+is"
)
# `covers` and `adds` are deliberately NOT markers. They describe what a
# ticket did, not that it OWNS the claim: rule 12 says the gate is unenforced
# and then cites OMN-15218 for "covering exactly one lane", a true sentence
# about a Done ticket. Treating a description verb as ownership turned that
# into a contradiction finding on correct prose.

#: Matched in BOTH directions, because doctrine writes it both ways: "tracked
#: in OMN-1234" and "OMN-16725 tracks adding the pattern". A marker-before-id
#: pattern alone missed rule 17, the single most important case in the corpus,
#: and silently downgraded a state contradiction to a weaker no-ticket finding.
IMPL_ROLE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:\b(?:{_IMPL_MARKER})[^.]{{0,80}}?(OMN-\d{{3,6}}))"
    rf"|(?:(OMN-\d{{3,6}})[^.]{{0,40}}?\b(?:{_IMPL_MARKER}))",
    re.I,
)

#: The states each claim type accepts, per role.
EXPECTED_STATES: Final[dict[str, frozenset[str]]] = {
    "unbuilt": KNOWN_STATE_TYPES - TERMINAL_STATE_TYPES,
    "blocked": KNOWN_STATE_TYPES - TERMINAL_STATE_TYPES,
    "in_flight": frozenset({"started"}),
}

#: Which role each claim type binds its ticket to.
CLAIM_ROLE: Final[dict[str, str]] = {
    "unbuilt": "implementation",
    "in_flight": "implementation",
    "blocked": "blocker",
}


class GateError(RuntimeError):
    """The gate could not run. Distinct from a doctrine finding (exit 2)."""


@dataclass(frozen=True)
class Claim:
    """One claim sentence, its type, and the tickets it binds."""

    path: str
    line: int
    sentence: str
    claim_type: str
    implementation: tuple[str, ...]
    blocker: tuple[str, ...]
    unroled: tuple[str, ...]


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
# Sentence extraction
# --------------------------------------------------------------------------

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*```")
_SENTENCE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`\[])")


def iter_blocks(text: str) -> list[tuple[int, str]]:
    """Yield ``(1-based first line, block text)`` for prose outside code fences.

    The unit is a BLOCK -- a run of non-blank lines -- not a sentence, and
    that is load-bearing rather than incidental. Doctrine routinely states the
    claim in one sentence and names its ticket in the next:

        This is currently doctrine only. OMN-16725 tracks adding the pattern
        to the existing PreToolUse Bash guard ...

    A sentence-scoped binder reads the first sentence as a claim naming no
    ticket and never resolves OMN-16725 at all, which converts the exact
    finding this gate exists to produce into a weaker, unfalsifiable one. The
    first draft of this module did precisely that, and the corpus caught it.

    Fenced blocks are skipped: a claim quoted inside a code sample is a
    quotation, not an assertion the document makes. Table rows are kept, since
    the registry doctrine file states several live claims inside tables.
    """
    out: list[tuple[int, str]] = []
    in_fence = False
    buf: list[str] = []
    start = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            if buf:
                out.append((start, " ".join(buf)))
                buf = []
            continue
        if in_fence:
            continue
        line = raw.strip()
        if not line:
            if buf:
                out.append((start, " ".join(buf)))
                buf = []
            continue
        if not buf:
            start = lineno
        buf.append(line)
    if buf:
        out.append((start, " ".join(buf)))
    return out


def binding_scope(block: str, pattern: re.Pattern[str]) -> str:
    """Return the text a claim's tickets are bound FROM.

    The claim sentence, plus the one that follows it when the claim sentence
    names no ticket of its own. Both halves are needed and neither is safe
    alone:

    * sentence-only misses the commonest doctrine shape, where the claim and
      its ticket are adjacent sentences ("This is currently doctrine only.
      OMN-16725 tracks adding the pattern ...");
    * whole-block sweeps in every id the paragraph happens to mention. The
      first draft did that and reported five findings against rule 21's
      "Related tickets:" list, which makes no claim about any of them. A gate
      that cries about a reference list is one people turn off, which is the
      failure this epic exists to remove -- so the scope stops at the
      elaboration.
    """
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(block) if p.strip()]
    for index, part in enumerate(parts):
        if not pattern.search(part):
            continue
        if TICKET_RE.search(part):
            return part
        nxt = parts[index + 1] if index + 1 < len(parts) else ""
        # The fallback reaches into the next sentence ONLY when that sentence
        # positively marks its ticket as the implementation ("OMN-16725 TRACKS
        # adding the pattern"). Without that gate it also binds a supporting
        # CITATION as the implementation: rule 12's gap paragraph says the gate
        # is unenforced and then cites OMN-15218 for covering one lane, which
        # is a true sentence about a Done ticket, and the ungated fallback
        # reported it as a contradiction. A false finding on a correct sentence
        # is how a gate loses its audience.
        if IMPL_ROLE_RE.search(nxt):
            return f"{part} {nxt}".strip()
        return part
    return block


def claim_sentence(block: str, pattern: re.Pattern[str]) -> str:
    """Return the sentence inside ``block`` that carries the claim, for the message."""
    for part in _SENTENCE_SPLIT_RE.split(block):
        if pattern.search(part):
            return part.strip()
    return block.strip()


def classify(sentence: str) -> str | None:
    """Return the claim type of ``sentence``, or None when it makes no claim."""
    for claim_type, pattern in CLAIM_PATTERNS:
        if pattern.search(sentence):
            return claim_type
    return None


def bind_roles(
    sentence: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Split the tickets a sentence names into (implementation, blocker, unroled).

    A single id with no marker binds to implementation: that is the ordinary
    shape and reading it any other way would refuse most of the corpus. Two or
    more ids with no marker distinguishing them is the ``unroled`` case, a
    finding of its own kind, because a default there would resolve both against
    one expected set — AC7's falsifier exactly.
    """
    ids = tuple(dict.fromkeys(TICKET_RE.findall(sentence)))
    if not ids:
        return (), (), ()
    blockers = tuple(
        dict.fromkeys(m.upper() for m in BLOCKER_ROLE_RE.findall(sentence))
    )
    impls = tuple(
        dict.fromkeys(
            g.upper()
            for match in IMPL_ROLE_RE.findall(sentence)
            for g in (match if isinstance(match, tuple) else (match,))
            if g
        )
    )
    marked = set(blockers) | set(impls)
    rest = tuple(i for i in ids if i not in marked)
    if len(ids) == 1 and not marked:
        return ids, (), ()
    if rest and len(ids) > 1:
        return impls, blockers, rest
    return impls or rest, blockers, ()


def collect_claims(path: Path) -> list[Claim]:
    """Parse one file into claims. Raises :class:`GateError` if unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"unreadable doctrine file {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise GateError(f"doctrine file {path} is not valid UTF-8: {exc}") from exc

    claims: list[Claim] = []
    for lineno, block in iter_blocks(text):
        hit = next((pat for _t, pat in CLAIM_PATTERNS if pat.search(block)), None)
        if hit is None:
            continue
        claim_type = classify(block)
        assert claim_type is not None  # noqa: S101 - same scan as `hit`
        impls, blockers, unroled = bind_roles(binding_scope(block, hit))
        claims.append(
            Claim(
                path=str(path),
                line=lineno,
                sentence=claim_sentence(block, hit),
                claim_type=claim_type,
                implementation=impls,
                blocker=blockers,
                unroled=unroled,
            )
        )
    return claims


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


def evaluate(claims: list[Claim], states: dict[str, str]) -> list[Finding]:
    """Turn claims plus resolved states into findings."""
    findings: list[Finding] = []
    for claim in claims:
        if not (claim.implementation or claim.blocker or claim.unroled):
            findings.append(
                Finding(
                    kind="CLAIM_NAMES_NO_TICKET",
                    path=claim.path,
                    line=claim.line,
                    ticket=None,
                    detail=(
                        f"a {claim.claim_type} claim names no ticket, so nothing can "
                        "ever falsify it and it will never be revisited"
                    ),
                    sentence=claim.sentence,
                )
            )
            continue
        if claim.unroled:
            findings.append(
                Finding(
                    kind="TICKET_HAS_NO_DECLARED_ROLE",
                    path=claim.path,
                    line=claim.line,
                    ticket=", ".join(claim.unroled),
                    detail=(
                        "the sentence names more than one ticket and does not say which "
                        "is the implementation and which is the blocker; resolving both "
                        "against one expected state set would be a guess"
                    ),
                    sentence=claim.sentence,
                )
            )
        expected = EXPECTED_STATES[claim.claim_type]
        role_of = dict.fromkeys(claim.implementation, "implementation")
        role_of.update(dict.fromkeys(claim.blocker, "blocker"))
        for ticket, role in sorted(role_of.items()):
            state = states.get(ticket)
            if state is None:  # pragma: no cover - resolve_states fails closed first
                raise GateError(f"{ticket} was never resolved")
            if state not in expected:
                findings.append(
                    Finding(
                        kind="CLAIM_CONTRADICTED_BY_TICKET_STATE",
                        path=claim.path,
                        line=claim.line,
                        ticket=ticket,
                        detail=(
                            f"the sentence claims {claim.claim_type!r} and binds {ticket} as the "
                            f"{role}, but {ticket} is {state!r}; a {claim.claim_type} claim accepts "
                            f"only {sorted(expected)}"
                        ),
                        sentence=claim.sentence,
                    )
                )
    return findings


def run(paths: list[Path], *, token: str | None = None) -> tuple[int, list[Finding]]:
    """Run the gate. Returns ``(exit_code, findings)``."""
    claims: list[Claim] = []
    for path in paths:
        claims.extend(collect_claims(path))
    if not claims:
        raise GateError(
            "the scan matched ZERO claim sentences across "
            f"{[str(p) for p in paths]}. A gate that audits nothing and reports green is "
            "the defect this gate exists to remove, so an empty scan is a refusal."
        )
    wanted = {t for c in claims for t in (*c.implementation, *c.blocker, *c.unroled)}
    states = resolve_states(wanted, token=token)
    findings = evaluate(claims, states)
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
