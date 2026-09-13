#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed ticket-creation admission gate (OMN-17942).

Why this exists
---------------
Measured over Linear between 2026-08-22 and 2026-09-04: **1553 tickets created
in fourteen days** -- about 111 a day -- against roughly 35 a day closed. 1537
of the 1553 were created under the single API identity every dispatched lane
writes as, so the creation side is lanes minting tickets, not a person filing
them. 398 have never been touched since filing. 779 have never left ``Backlog``.
343 are unclassifiable by title. Net ``+571`` landed in the *next* sprint's
project and ``+269`` in no project at all.

The operator's words: *"we have been averaging 4 closures a day but generating
8 tickets a day, that's a problem."*

The control that was supposed to stop this was prose -- ``omni_home``'s
``CLAUDE.md`` and every dispatch brief tell a lane not to file follow-up tickets
for residuals, and the standing three-closure-chain WIP limit tells it not to
open new chains. That is a memory-class control over a tool seam, which is
exactly the shape OMN-17499 measured failing 41 times in a single session. Here
it failed on the order of 1500 times in a fortnight.

So this module is the decision core of a ``PreToolUse`` hook that REFUSES the
call, the same primitive as ``pre_tool_use_worktree_guard.sh`` refusing a
``git worktree add`` outside the canonical root, and the same construction as
``workflow_model_guard.py``: standard library only, config-driven vocabulary,
one refusal naming every failing rule.

What it refuses, and what it deliberately does not
--------------------------------------------------
It fires on a **CREATE** -- ``mcp__linear-server__save_issue`` with no ``id``.
An **UPDATE** is never gated: ``save_issue`` with an ``id`` edits a row that
already exists, and gating it would block every state flip, description repair
and parent re-link the board-truth work (OMN-16729) depends on.

A create is admitted only when all six hold:

1. ``parentId`` is present, **or** the description declares the issue an epic
   on a line of its own.
2. A project is named -- ``project`` on the MCP surface, ``projectId`` in the
   REST spelling; either satisfies it.
3. The description carries a binding line, on a line of its own::

       Gate: C9
       Gate: INV-103
       Gate: OMN-16729 AC-5
       Gate: live-gate defect: kb-doc-gate

   ``C<n>`` and ``INV-<nnn>`` are read from the beta PRD -- section 6's
   release-criteria table and the front matter's ``invariant-coverage``
   block respectively -- at the revision the admission policy pins. See that
   policy's ``$comment`` for why the coverage block and not every ``INV-``
   token in the document.

4. The title does not read as a residual, follow-up or nit -- unless (3) is a
   live-gate defect.
5. If the create declares an IN-PROGRESS-class state, the description carries
   an executable probe line, on a line of its own::

       Probe: uv run pytest tests/unit/test_x.py -q => exits 0

   Rule 5 exists because of what the evidence closer can and cannot see. The
   scheduled closer (OMN-16106) re-runs ``onex skill dod_verify`` against the
   checks a ticket's OCC contract declares. A ticket whose definition of done
   is prose -- "write the PRD", "document the doctrine" -- declares no check
   the closer can run, so it is structurally unreachable by every closing
   mechanism and can only ever be closed by a person reading it. Four tickets
   in the 2026-08-31 sprint are in exactly that state. The probe line is the
   one thing that has to exist at the START for a ticket to be mechanically
   closeable at the end.

6. The parent it names does not already carry more than N children in an
   UNSTARTED state, N being ``unstarted_children_cap`` in the admission policy.

   Rules 1-5 bound a ticket's SHAPE and say nothing about VOLUME, so a parent
   can accumulate an unbounded queue of correctly-bound tickets nobody will
   ever start and every one of them passes. That is not hypothetical: the
   friction trend report of 2026-09-13 measured created against Done at
   **3.1 : 1** over fifteen days -- a net **+815** -- with 31 of 58 new friction
   tickets never started, across a window lying ENTIRELY AFTER this guard
   shipped. A live read the same day found **59 parents** already over a cap of
   ten, the deepest carrying 62, some children filed in March and never touched.

   The refusal names the parent, the count, the cap and the oldest unstarted
   child, and it names three routes out: start a child, cancel a child, or
   record an operator RULING row in the rolling work ledger and cite it on the
   create as ``Admission-Override: <ledger>:<line>``. That citation is resolved
   exactly the way OMN-17957's credential guard resolves a rotation consent --
   canonical path, the line exists, the row's second field is ``RULING``, and
   the row names this parent -- because authorisation has to outlive the session
   that granted it. There is no environment variable and no policy flag that
   turns rule 6 off; the disable is the mask bit, and a disabled run is logged.

What rule 5 enforces, and what it cannot
----------------------------------------
It enforces the SHAPE of a probe -- a command, then ``=>``, then the
observation that settles it -- on a line of its own. It does not, and cannot,
prove the command runs: this module has the payload and nothing else, and a
guard that shelled out to try the probe would be a PreToolUse hook executing
attacker-controlled text. Shape is what a gate at this seam can hold; whether
the command is the RIGHT one is what the OCC contract and dod_verify settle
later.

The transition surface is deliberately NOT covered
--------------------------------------------------
Rule 5 binds a create that names its state. A ticket created in ``Backlog`` and
moved to In Progress later moves by an UPDATE, and updates are never gated here
(see below) -- so the common path into In Progress is not gated by this module,
and saying otherwise would be a control that reports green while enforcing
nothing. Closing that path needs a rule scoped to a state-field transition on
an update, which is a different admission question from *is this ticket bound
to a commitment?* and is not answered here.

Rule 4's exemption is narrow on purpose. A residual belongs as a comment on its
parent. A *live gate that is broken* is not a residual: it is a control
reporting green while enforcing nothing, and burying that in a comment thread
is how it stays unfixed.

Line anchoring, not substring matching
--------------------------------------
Every textual rule here matches a **whole line**, never a substring. That is
``omni_home`` CLAUDE.md rule 15, and it cuts both ways. A substring rule fires
on prose that merely mentions the trigger (the OCC#7213 shape: a gate failing on
documentation about the gate) and -- the direction that matters for an admission
gate -- it *passes* on prose that mentions the trigger while meaning the
opposite. "This row carries no ``Gate: OMN-1 AC-1`` binding yet" would satisfy a
substring rule by describing its own absence.

Fail-closed boundary, stated deliberately
-----------------------------------------
* A tool other than the Linear write surface is passed through untouched. A bug
  here can never brick unrelated traffic.
* A create this module cannot evaluate -- unparseable payload, a non-object
  ``tool_input``, a non-string title or description, an unreadable policy, a
  body filled in server-side from a ``template`` the guard never sees -- is
  REFUSED. An unverifiable create is refused, never assumed clean. The blast
  radius of that decision is exactly one tool name.

The one read outside the payload, and its fail direction
--------------------------------------------------------
Rules 1-5 answer *is this ticket bound to a commitment?* from the payload alone.
Rule 6 cannot: *how long is this parent's queue already?* is not a property of
the call in front of it. So it takes a ``children_lookup`` -- an argument, not
an import, so this module stays a pure function of what it is given and the
network lives in one bindable seam. ``main`` binds it to the tracker; a test
binds it to a fixture; nothing else calls it.

Its fail direction is stated rather than discovered:

* **The lookup fails, or the parent does not resolve** -- REFUSE. A create the
  tracker cannot resolve would not have succeeded anyway, so the refusal costs a
  round trip and nothing else.
* **The enumeration truncates below the cap** -- REFUSE. A lower bound is not a
  count, and a cap applied to a number that might be wrong fires at random.
* **No read credential is configured on this machine** -- ADMIT, and say so on
  stderr. This is the second bounded fail-OPEN in this module, beside rule 5's
  uuid, and it is bounded to rule 6. Refusing here would make rules 1-5 --
  payload-only and always enforceable -- collateral damage of a missing key, and
  a guard that refuses every create on a machine with no key is a guard that
  gets disabled wholesale rather than repaired.

Deliberately NOT built here
---------------------------
No duplicate detection, no per-lane quota, no rate limit. Those need state this
module does not have and would make a refusal depend on the history of who filed
what, rather than on the board the ticket is about to land on.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "OVERRIDE_CITATION_GRAMMAR",
    "ChildrenLookup",
    "Finding",
    "ParentCensus",
    "Policy",
    "PolicyError",
    "UnstartedChild",
    "build_census",
    "check_save_issue",
    "load_policy",
    "render_block_reason",
]

DEFAULT_POLICY_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "ticket_creation_policy.json"
)

#: The mask bit this guard is gated by. Named in every refusal so a lane that
#: believes the guard is wrong has a documented route that is not "work around
#: it". See the module docstring of the shell wrapper for why it is borrowed.
GATE_BIT_NAME: Final[str] = "LINEAR_DONE_VERIFY"

TICKET: Final[str] = "OMN-17942"

#: ``Gate: OMN-16729 AC-5`` -- a parent issue plus an acceptance-criterion
#: ordinal. Both halves are required: a bare parent is a link, not a binding.
_PARENT_AC: Final[re.Pattern[str]] = re.compile(r"^OMN-\d+\s+AC-\d+$", re.IGNORECASE)

#: ``Gate: live-gate defect: <check name>`` -- the check must actually be named.
_LIVE_GATE_DEFECT: Final[re.Pattern[str]] = re.compile(
    r"^live-gate\s+defect:\s*(?P<check>\S.*)$", re.IGNORECASE
)

#: ``C3`` -- shape only; membership is checked against the configured set.
_CRITERION: Final[re.Pattern[str]] = re.compile(r"^C\d+$", re.IGNORECASE)

#: ``INV-103`` -- shape only; membership is checked against the configured set.
#: Zero-padded to at least three digits because that is the invariant
#: registry's own spelling, so ``INV-12`` is a typo for ``INV-012`` and is
#: refused rather than guessed at.
_INVARIANT: Final[re.Pattern[str]] = re.compile(r"^INV-\d{3,}$", re.IGNORECASE)

#: A binding line, anchored to the start of a line. Leading whitespace is
#: tolerated (a lane indenting inside a block quote is not the failure mode this
#: guards against); a list bullet is NOT, because a bullet is how a line ends up
#: inside a checklist that nothing binds.
_GATE_LINE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*Gate:[ \t]*(?P<binding>.*?)[ \t]*$", re.MULTILINE
)

_GATE_LINE_GRAMMAR: Final[str] = (
    "Gate: <C-id | INV-id | OMN-<parent> AC-<n> | live-gate defect: <check name>>"
)


def _render_ids(ids: frozenset[str]) -> str:
    """Sort ids by their numeric tail so ``C9`` precedes ``C10``.

    Lexical order renders ``C1, C10, C11, ... C2``, which reads as a corrupted
    set and makes a refusal harder to act on than it needs to be.
    """

    def key(value: str) -> tuple[str, int]:
        digits = "".join(c for c in value if c.isdigit())
        return (value.rstrip("0123456789"), int(digits) if digits else 0)

    return ", ".join(sorted(ids, key=key)) or "(none configured)"


#: ``Probe: <command> => <observation>`` -- the executable close probe. Anchored
#: to a whole line for the same reason ``_GATE_LINE`` is (CLAUDE.md rule 15):
#: a substring rule passes on prose that mentions a probe in order to say the
#: ticket has none. A bullet is refused, because a bullet is how a line ends up
#: inside a checklist that nothing binds.
_PROBE_LINE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*Probe:[ \t]*(?P<probe>.*?)[ \t]*$", re.MULTILINE
)

#: The two halves of a probe. ``=>`` separates the command from the observation
#: that settles it. BOTH are required: a command with no expected observation
#: cannot be adjudicated by anything except a person reading the output, which
#: is the state rule 5 exists to prevent, and an observation with no command is
#: a wish.
_PROBE_SPLIT: Final[str] = "=>"

_PROBE_LINE_GRAMMAR: Final[str] = "Probe: <command> => <observation that settles it>"

#: ``Admission-Override: docs/tracking/ROLLING_WORK_LEDGER.md:<line>`` -- the ONE
#: route past rule 6 that is not "start a child" or "cancel a child". Same
#: construction as OMN-17957's ``ROTATION-CONSENT:`` citation, and for the same
#: reason: authorisation has to be a durable, citable row that outlives the
#: session that granted it, because a lane's own assertion that it was allowed
#: is not evidence of anything. There is deliberately no environment variable
#: and no policy flag -- a gate with an off switch is a gate that is off.
OVERRIDE_CITATION_GRAMMAR: Final[str] = (
    "Admission-Override: docs/tracking/ROLLING_WORK_LEDGER.md:<line>"
)

#: Anchored to a whole line, like every other textual rule here (CLAUDE.md rule
#: 15). A bullet is refused for the same reason a bulleted ``Gate:`` line is.
_OVERRIDE_LINE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*Admission-Override:[ \t]*(?P<path>[^\s:'\"]+):(?P<line>\d+)[ \t]*$",
    re.MULTILINE,
)

#: The ledger row kind that authorises. A CLAIM, NOTE, PROGRESS or TERMINAL row
#: records what a lane DID; only a RULING decides anything. The kind is read
#: from the row's SECOND field rather than from anywhere in the row, because a
#: CLAIM row whose free text mentions a ruling is not a ruling.
_REQUIRED_OVERRIDE_ROW_KIND: Final[str] = "RULING"

_LINEAR_API_URL: Final[str] = (
    "https://api.linear.app/graphql"  # url-authority-ok: the tracker's single documented GraphQL endpoint, read-only child-state lookups from a PreToolUse decision core that is standard-library-only by construction (it must resolve its own interpreter and refuse when it cannot, so it cannot import a routing authority or an integration catalog to resolve from); same endpoint and same reasoning as scripts/worktree_auto_prune.py
)

#: Per-request timeout and page bounds for the children census. Small on
#: purpose: this runs inside a PreToolUse hook, in front of a human waiting on a
#: tool call, and a slow census is indistinguishable from a hung session.
_CENSUS_TIMEOUT_S: Final[float] = 8.0
_CENSUS_PAGE_SIZE: Final[int] = 100
_CENSUS_MAX_PAGES: Final[int] = 12

_CENSUS_QUERY: Final[str] = """
query($id: String!, $after: String, $first: Int!) {
  issue(id: $id) {
    identifier
    children(first: $first, after: $after) {
      nodes { identifier title createdAt state { name type } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
""".strip()


class PolicyError(RuntimeError):
    """The admission policy could not be read.

    Raised rather than defaulting to a permissive policy: a policy that cannot
    be parsed is an unknown policy, and an unknown policy that admits
    everything is a gate reporting green while enforcing nothing.
    """


@dataclass(frozen=True, slots=True)
class Policy:
    """The admission vocabulary, read from config."""

    criterion_ids: frozenset[str]
    invariant_ids: frozenset[str]
    epic_markers: tuple[str, ...]
    residual_title_terms: tuple[str, ...]
    in_progress_state_names: frozenset[str]
    unstarted_children_cap: int
    unstarted_state_types: frozenset[str]
    override_ledger_paths: frozenset[str]
    override_ledger_path_prefixes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    """One failing admission rule.

    ``code`` is stable and machine-greppable; ``reason`` says what is wrong and
    ``fix`` says what to do about it. Both are rendered to the operator, because
    a refusal that names a problem without naming its remedy is a refusal a lane
    routes around.
    """

    code: str
    field: str
    reason: str
    fix: str


@dataclass(frozen=True, slots=True)
class UnstartedChild:
    """One child of a parent that nobody has started.

    ``created_at`` is Linear's own ISO-8601 UTC spelling
    (``2026-08-01T00:00:00.000Z``). It is compared as a string rather than
    parsed: that format sorts lexically in chronological order, and a guard on
    an enforcement path does not need a datetime parser to say which of two
    timestamps came first.
    """

    identifier: str
    title: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ParentCensus:
    """What a parent's queue looks like right now.

    ``complete`` is False when the enumeration was truncated -- then
    ``unstarted`` is a LOWER BOUND, not a count. Rule 6 refuses a create it
    cannot settle from a lower bound rather than guessing, because a cap
    applied to a number that might be wrong is a cap that fires at random.
    """

    parent: str
    unstarted: tuple[UnstartedChild, ...]
    complete: bool = True


#: Resolve a parent reference -- an identifier like ``OMN-18232`` or a uuid --
#: to its census, or ``None`` when it cannot be resolved at all. The seam is a
#: callable so the decision core stays a pure function of its arguments and the
#: network lives in exactly one place, which is what makes rule 6 testable
#: without a workspace.
ChildrenLookup = Callable[[str], "ParentCensus | None"]


def build_census(
    parent: str, nodes: list[dict[str, Any]], policy: Policy, complete: bool = True
) -> ParentCensus:
    """Classify raw Linear child nodes into a census.

    Classification is by state **type**, never by state name: a workspace that
    renames its Backlog column keeps the type, and Linear's own unstarted band
    is exactly the configured set. A node whose state cannot be read is counted
    as unstarted -- the conservative direction for a cap, and the one that
    cannot be gamed by a malformed state.
    """
    unstarted: list[UnstartedChild] = []
    for node in nodes:
        # Non-dict entries are dropped by the fetch, which is the only producer
        # of this list that does not construct it by hand.
        state = node.get("state")
        state_type = ""
        if isinstance(state, dict):
            state_type = str(state.get("type") or "").strip().lower()
        if state_type and state_type not in policy.unstarted_state_types:
            continue
        unstarted.append(
            UnstartedChild(
                identifier=str(node.get("identifier") or "(unnamed)"),
                title=str(node.get("title") or ""),
                created_at=str(node.get("createdAt") or ""),
            )
        )
    unstarted.sort(key=lambda child: (child.created_at, child.identifier))
    return ParentCensus(parent=parent, unstarted=tuple(unstarted), complete=complete)


def _string_list(raw: Any, key: str, source: Path) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise PolicyError(
            f"{source}: '{key}' must be a non-empty list of strings, got {raw!r}"
        )
    out: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise PolicyError(
                f"{source}: '{key}' contains a blank or non-string entry {entry!r}"
            )
        out.append(entry.strip())
    return tuple(out)


def _positive_int(raw: Any, key: str, source: Path) -> int:
    """Read a count, or raise.

    ``bool`` is rejected explicitly because it is an ``int`` subclass in Python
    and ``"unstarted_children_cap": true`` would otherwise configure a cap of
    one. Zero and negatives are rejected because a cap of zero refuses every
    create under every parent, which is a workspace-wide outage spelled as a
    config typo.
    """
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise PolicyError(
            f"{source}: '{key}' must be an integer of at least 1, got {raw!r}"
        )
    return int(raw)


def load_policy(path: Path | None = None) -> Policy:
    """Read the admission vocabulary, or raise.

    There is no default policy in code. A missing or malformed config is a
    refusal of every create until it is repaired, which is loud, rather than a
    silent widening of what the board admits, which is not.
    """
    source = path or DEFAULT_POLICY_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"admission policy not found at {source}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{source}: not valid JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"{source}: top level must be an object, got {type(raw)}")

    criterion_ids = _string_list(raw.get("criterion_ids"), "criterion_ids", source)
    for cid in criterion_ids:
        if not _CRITERION.match(cid):
            raise PolicyError(f"{source}: criterion id {cid!r} is not of the form C<n>")
    invariant_ids = _string_list(raw.get("invariant_ids"), "invariant_ids", source)
    for inv in invariant_ids:
        if not _INVARIANT.match(inv):
            raise PolicyError(
                f"{source}: invariant id {inv!r} is not of the form INV-<nnn>"
            )
    return Policy(
        criterion_ids=frozenset(c.upper() for c in criterion_ids),
        invariant_ids=frozenset(i.upper() for i in invariant_ids),
        epic_markers=tuple(
            m.lower()
            for m in _string_list(raw.get("epic_markers"), "epic_markers", source)
        ),
        residual_title_terms=_string_list(
            raw.get("residual_title_terms"), "residual_title_terms", source
        ),
        in_progress_state_names=frozenset(
            n.lower()
            for n in _string_list(
                raw.get("in_progress_state_names"), "in_progress_state_names", source
            )
        ),
        unstarted_children_cap=_positive_int(
            raw.get("unstarted_children_cap"), "unstarted_children_cap", source
        ),
        unstarted_state_types=frozenset(
            t.lower()
            for t in _string_list(
                raw.get("unstarted_state_types"), "unstarted_state_types", source
            )
        ),
        override_ledger_paths=frozenset(
            _string_list(
                raw.get("override_ledger_paths"), "override_ledger_paths", source
            )
        ),
        override_ledger_path_prefixes=_string_list(
            raw.get("override_ledger_path_prefixes"),
            "override_ledger_path_prefixes",
            source,
        ),
    )


def _is_present(value: Any) -> bool:
    """A field counts as present only when it carries a non-blank string.

    ``None`` is Linear's own spelling for *remove this*, and a whitespace string
    is a field a lane filled in to get past a check.
    """
    return isinstance(value, str) and bool(value.strip())


def _declares_epic(description: str, policy: Policy) -> bool:
    """True when a line of the description is exactly an epic marker.

    Exact-line, not prefix: a line reading ``Epic: OMN-16729`` *names a parent
    epic*, so under a prefix rule the ticket most tightly bound to a parent
    would be the one admitted as parentless.
    """
    markers = set(policy.epic_markers)
    return any(line.strip().lower() in markers for line in description.splitlines())


def _binding_kind(description: str, policy: Policy) -> str | None:
    """Classify the strongest binding line in ``description``.

    Returns ``"criterion"``, ``"invariant"``, ``"parent_ac"``,
    ``"live_gate_defect"``, or ``None`` when no line binds. A body may carry several ``Gate:`` lines (a
    quoted example above the real one, say); a live-gate-defect binding wins,
    because it is the one that carries an exemption and rule 4 must not depend
    on which line happened to come first.
    """
    kinds: set[str] = set()
    for match in _GATE_LINE.finditer(description):
        binding = match.group("binding").strip()
        if not binding:
            continue
        if _LIVE_GATE_DEFECT.match(binding):
            kinds.add("live_gate_defect")
        elif _PARENT_AC.match(binding):
            kinds.add("parent_ac")
        elif _CRITERION.match(binding) and binding.upper() in policy.criterion_ids:
            kinds.add("criterion")
        elif _INVARIANT.match(binding) and binding.upper() in policy.invariant_ids:
            kinds.add("invariant")
    for preferred in ("live_gate_defect", "parent_ac", "criterion", "invariant"):
        if preferred in kinds:
            return preferred
    return None


def _residual_terms_in(title: str, policy: Policy) -> list[str]:
    """Residual vocabulary found in ``title``, matched on word boundaries.

    Word-bounded so ``minor`` does not fire on ``minority`` and ``nit`` does not
    fire on ``monitor``. A gate that refuses correct work teaches lanes to route
    around it, which costs more than the tickets it stops.
    """
    hits: list[str] = []
    for term in policy.residual_title_terms:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", title, re.IGNORECASE):
            hits.append(term)
    return hits


def _declares_in_progress(tool_input: dict[str, Any], policy: Policy) -> bool:
    """True when this create names an IN-PROGRESS-class state.

    Reads both spellings the Linear write surface accepts: ``state`` (a state
    type, name or id) and ``stateId``. A raw uuid in either field is NOT
    matched -- the guard has no workspace lookup and will not guess what a uuid
    resolves to. That is the fail-OPEN direction for this one rule and it is
    deliberate: rule 5 must never refuse a create it cannot classify, because
    the classification depends on data this module cannot see, and refusing on
    a uuid would make every id-shaped create unfileable. The refusal it does
    make is on a create that says, in words, that it starts In Progress.
    """
    names = {
        str(tool_input.get(field, "")).strip().lower()
        for field in ("state", "stateId", "status", "statusType")
    }
    return bool(names & policy.in_progress_state_names)


def _probe_line_findings(description: str) -> list[Finding]:
    """Rule 5's verdict on the probe line, if any.

    Returns the findings for: no probe line at all, a probe line missing its
    ``=>`` separator, and a probe line with a blank half. A body may carry
    several ``Probe:`` lines (a quoted example above the real one); ONE
    well-formed line satisfies the rule, matching how ``_binding_kind`` treats
    several ``Gate:`` lines.
    """
    candidates = [
        match.group("probe").strip() for match in _PROBE_LINE.finditer(description)
    ]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return [
            Finding(
                code="missing_probe_line",
                field="description",
                reason=(
                    "this ticket starts In Progress but declares no executable "
                    "probe, so nothing that closes tickets mechanically can "
                    "ever reach it -- the scheduled evidence closer re-runs "
                    "dod_verify against declared checks and a prose definition "
                    "of done declares none"
                ),
                fix=(
                    f"add a line of its own, unbulleted, reading "
                    f"'{_PROBE_LINE_GRAMMAR}' -- e.g. "
                    "'Probe: uv run pytest tests/unit/test_x.py -q => exits 0', "
                    "or 'Probe: gh api repos/O/r/branches/main/protection "
                    "--jq .required_status_checks.contexts => contains "
                    "deploy-gate'. If the deliverable genuinely has no "
                    "executable probe, it is not ready to be In Progress: the "
                    "probe is what makes it closeable at the end"
                ),
            )
        ]
    for candidate in candidates:
        head, separator, tail = candidate.partition(_PROBE_SPLIT)
        if separator and head.strip() and tail.strip():
            return []
    return [
        Finding(
            code="malformed_probe_line",
            field="description",
            reason=(
                "a Probe: line is present but no line carries BOTH a command "
                f"and the observation that settles it, separated by "
                f"'{_PROBE_SPLIT}'. A command with no expected observation can "
                "only be adjudicated by a person reading its output, which is "
                "the state this rule exists to prevent"
            ),
            fix=(
                f"write it as '{_PROBE_LINE_GRAMMAR}' -- the observation is "
                "what a later dod_verify check asserts, so make it something a "
                "machine can compare, not a judgement"
            ),
        )
    ]


def _override_path_is_canonical(cited: str, policy: Policy) -> bool:
    """True when the citation names the append-only coordination surface.

    A lane that may cite any file it can write has not been authorised by
    anybody -- it has written itself a permission slip. Same check, and the same
    reasoning, as OMN-17957's ``_citation_path_is_canonical``.
    """
    normalised = cited.strip().lstrip("./")
    if ".." in Path(normalised).parts or Path(normalised).is_absolute():
        return False
    if normalised in policy.override_ledger_paths:
        return True
    return any(
        normalised.startswith(prefix) for prefix in policy.override_ledger_path_prefixes
    )


def _row_names(row: str, subject: str) -> bool:
    """True when ``row`` names ``subject``, matched on word boundaries."""
    if not subject:
        return False
    return (
        re.search(rf"(?<![\w.-]){re.escape(subject)}(?![\w.-])", row, re.IGNORECASE)
        is not None
    )


def _resolve_override(
    description: str,
    parents: tuple[str, ...],
    policy: Policy,
    ledger_root: Path | None,
) -> Finding | bool:
    """Resolve an ``Admission-Override:`` citation.

    Returns ``False`` when no citation is present, ``True`` when one resolves to
    a RULING row naming the parent, and a :class:`Finding` when a citation IS
    present and does not resolve. That last case is deliberately not "ignore it
    and fall through to the cap": a lane that cited a row and got refused for
    being over the cap would read the refusal as the citation being unnecessary,
    when in fact the citation was wrong. The reason has to name which half
    failed.
    """
    match = _OVERRIDE_LINE.search(description)
    if match is None:
        return False

    cited = match.group("path")
    if not _override_path_is_canonical(cited, policy):
        allowed = ", ".join(sorted(policy.override_ledger_paths))
        return Finding(
            code="override_path_not_canonical",
            field="description",
            reason=(
                f"the override citation names {cited!r}, which is not the "
                "append-only coordination surface a ruling lives in"
            ),
            fix=(
                f"cite a row in {allowed} (or a docs/tracking/archive/ roll), "
                "appended through scripts/ledger_lock.py"
            ),
        )

    if ledger_root is None:
        return Finding(
            code="override_ledger_unreadable",
            field="description",
            reason=(
                "the override cites a ledger row, but OMNI_HOME is not set in "
                "this environment, so the row cannot be read and the "
                "authorisation cannot be checked"
            ),
            fix=(
                "set OMNI_HOME to the registry clone whose ledger carries the "
                "ruling. An override nobody can resolve is not an override"
            ),
        )

    ledger = ledger_root / cited.strip().lstrip("./")
    try:
        rows = ledger.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return Finding(
            code="override_ledger_unreadable",
            field="description",
            reason=f"the cited ledger {ledger} could not be read ({exc})",
            fix=(
                "cite a line that exists in the rolling ledger of the clone "
                "OMNI_HOME names"
            ),
        )

    line_no = int(match.group("line"))
    if line_no < 1 or line_no > len(rows):
        return Finding(
            code="override_line_absent",
            field="description",
            reason=(
                f"the override cites line {line_no} of {cited}, which has "
                f"{len(rows)} lines"
            ),
            fix=(
                "cite the line number the RULING row actually occupies. The "
                "ledger is append-only, so a row's line number does not move"
            ),
        )

    row = rows[line_no - 1]
    fields = [field.strip() for field in row.split("|")]
    kind = fields[1] if len(fields) > 1 else ""
    if kind.upper() != _REQUIRED_OVERRIDE_ROW_KIND:
        return Finding(
            code="override_row_not_ruling",
            field="description",
            reason=(
                f"{cited}:{line_no} is a {kind or '(no kind)'} row, not a "
                f"{_REQUIRED_OVERRIDE_ROW_KIND} row"
            ),
            fix=(
                f"cite a row whose second field is exactly "
                f"{_REQUIRED_OVERRIDE_ROW_KIND}. A CLAIM, NOTE, PROGRESS or "
                "TERMINAL row records what a lane DID; only a RULING decides "
                "anything, and a row that merely mentions a ruling in its free "
                "text decides nothing"
            ),
        )

    if not any(_row_names(row, parent) for parent in parents if parent):
        named = " or ".join(p for p in parents if p)
        return Finding(
            code="override_row_does_not_name_parent",
            field="description",
            reason=(
                f"{cited}:{line_no} is a RULING row, but it does not name "
                f"{named} -- so it rules on some other subject"
            ),
            fix=(
                "a waiver has to name the parent whose queue it waives. A "
                "ruling about another subject is not a blanket permission, and "
                "a citation that resolves to one is how a single ruling ends up "
                "waiving the cap for every parent on the board"
            ),
        )

    return True


def _unstarted_cap_findings(
    tool_input: dict[str, Any],
    description: str,
    policy: Policy,
    children_lookup: ChildrenLookup | None,
    ledger_root: Path | None,
) -> list[Finding]:
    """Rule 6's verdict on the parent's queue."""
    parent_ref = tool_input.get("parentId")
    if not _is_present(parent_ref):
        # No parent named -- an epic declaring itself one under rule 1. It has
        # no queue to be over, and looking one up would be a network call on a
        # question nobody asked.
        return []
    assert isinstance(parent_ref, str)

    if children_lookup is None:
        # The one bounded fail-OPEN in this module outside rule 5, and it is
        # stated rather than discovered: no census source is configured on this
        # machine (no Linear read credential). Refusing here would make rules
        # 1-5 -- payload-only and always enforceable -- collateral damage of a
        # missing key, and a guard that refuses every create on a laptop with no
        # key is a guard that gets disabled wholesale rather than repaired.
        return []

    census = children_lookup(parent_ref.strip())
    if census is None:
        return [
            Finding(
                code="unstarted_cap_unresolved",
                field="parentId",
                reason=(
                    f"the queue of parent {parent_ref!r} could not be counted -- "
                    "the tracker did not answer, or it does not carry that "
                    "parent. The cap is unverified, so the create is refused "
                    "rather than assumed clean"
                ),
                fix=(
                    "check the parentId names a real issue, and that the "
                    "tracker is reachable. A create the tracker cannot resolve "
                    "would not have succeeded anyway, so this refusal costs "
                    "nothing but the round trip"
                ),
            )
        ]

    count = len(census.unstarted)
    cap = policy.unstarted_children_cap

    if count <= cap and not census.complete:
        return [
            Finding(
                code="unstarted_cap_unresolved",
                field="parentId",
                reason=(
                    f"the enumeration of {census.parent}'s children was "
                    f"truncated, so {count} is a lower bound and not a count. A "
                    "cap applied to a number that might be wrong fires at random"
                ),
                fix=(
                    "re-issue the create; if it keeps happening the parent "
                    "carries more children than the census will page through, "
                    "which is itself the condition this rule exists to refuse"
                ),
            )
        ]

    if count <= cap:
        return []

    override = _resolve_override(
        description, (census.parent, parent_ref.strip()), policy, ledger_root
    )
    if override is True:
        return []
    if isinstance(override, Finding):
        return [override]

    oldest = census.unstarted[0]
    filed = oldest.created_at[:10] or "(date unknown)"
    return [
        Finding(
            code="unstarted_children_cap",
            field="parentId",
            reason=(
                f"{census.parent} already carries {count} children in an "
                f"unstarted state, over the cap of {cap}. The oldest is "
                f"{oldest.identifier}, filed {filed}, and still nobody has "
                "started it. A queue this long is not a plan -- measured across "
                "the workspace on 2026-09-13, 59 parents were over this cap and "
                "the deepest carried 62, some filed in March"
            ),
            fix=(
                "do one of three things, in this order of preference. (1) START "
                "a child of this parent -- if this new ticket is the most "
                "important thing under it, that is an argument for starting it "
                "now, not for queueing it behind ten others. (2) CANCEL the "
                "children that are not going to be done; a ticket nobody will "
                "start is a decision already made and not recorded. (3) If the "
                "queue is deliberate, record an operator RULING row in the "
                "rolling ledger through scripts/ledger_lock.py, naming this "
                f"parent, and cite it on this create as "
                f"'{OVERRIDE_CITATION_GRAMMAR}'. There is no environment "
                "variable and no policy flag that turns this off"
            ),
        )
    ]


def check_save_issue(
    tool_input: Any,
    policy: Policy,
    children_lookup: ChildrenLookup | None = None,
    ledger_root: Path | None = None,
) -> list[Finding]:
    """Return every failing admission rule for one ``save_issue`` call.

    An empty list admits the call. Updates always return an empty list.

    ``children_lookup`` is rule 6's only window onto anything outside the
    payload, and it is an argument rather than an import so this function stays
    a pure function of what it is given. ``None`` means no census source is
    configured; see :func:`_unstarted_cap_findings` for why that admits rather
    than refuses. ``ledger_root`` is where an override citation is resolved from.
    """
    if not isinstance(tool_input, dict):
        return [
            Finding(
                code="unevaluable",
                field="tool_input",
                reason=(
                    "the save_issue call carries no tool_input object, so the "
                    "guard cannot tell a create from an update"
                ),
                fix="re-issue the call with a well-formed tool_input object",
            )
        ]

    if "id" in tool_input:
        if _is_present(tool_input["id"]):
            # An UPDATE. Never gated -- see the module docstring.
            return []
        return [
            Finding(
                code="unevaluable",
                field="id",
                reason=(
                    f"'id' is present but is {tool_input['id']!r}, which is "
                    "neither a usable issue identifier nor an absent field, so "
                    "the guard cannot tell whether this creates a ticket"
                ),
                fix=(
                    "omit 'id' entirely to create an issue, or pass the "
                    "identifier of the issue being updated"
                ),
            )
        ]

    findings: list[Finding] = []

    title = tool_input.get("title")
    if not _is_present(title):
        findings.append(
            Finding(
                code="unevaluable",
                field="title",
                reason=(
                    f"a create needs a title; got {title!r}, so the guard "
                    "cannot evaluate rule 4"
                ),
                fix="give the ticket a title that says what it commits to",
            )
        )
        title = ""
    assert isinstance(title, str)

    raw_description = tool_input.get("description")
    description_readable = raw_description is None or isinstance(raw_description, str)
    description = raw_description if isinstance(raw_description, str) else ""
    if not description_readable:
        findings.append(
            Finding(
                code="unevaluable",
                field="description",
                reason=(
                    f"'description' is {type(raw_description).__name__}, not a "
                    "string, so the binding line cannot be read"
                ),
                fix="pass the description as markdown text",
            )
        )

    # Rule 1 -- a parent, or an explicit epic declaration.
    if not _is_present(tool_input.get("parentId")) and not _declares_epic(
        description, policy
    ):
        markers = " | ".join(policy.epic_markers)
        findings.append(
            Finding(
                code="missing_parent",
                field="parentId",
                reason=(
                    "the issue names no parent, so nothing on the board says "
                    "which commitment it serves"
                ),
                fix=(
                    "pass parentId with the epic or parent issue this belongs "
                    f"to -- or, if this genuinely IS an epic, put a line reading "
                    f"exactly '{markers}' in the description"
                ),
            )
        )

    # Rule 2 -- a project.
    if not (
        _is_present(tool_input.get("project"))
        or _is_present(tool_input.get("projectId"))
    ):
        findings.append(
            Finding(
                code="missing_project",
                field="project",
                reason=(
                    "the issue names no project, so it lands in the 269-ticket "
                    "no-project pool that no sprint review ever reads"
                ),
                fix=(
                    "pass project with the sprint or project this belongs to; "
                    "if it belongs to no current commitment, it is not ready to "
                    "be a ticket"
                ),
            )
        )

    # Rule 3 -- a binding line.
    binding = _binding_kind(description, policy) if description_readable else None
    if binding is None:
        findings.append(
            Finding(
                code="missing_gate_line",
                field="description",
                reason=(
                    "the description carries no line binding this ticket to a "
                    "commitment"
                ),
                fix=(
                    f"add a line of its own, unbulleted, reading "
                    f"'{_GATE_LINE_GRAMMAR}'. The accepted release-criterion "
                    f"ids are {_render_ids(policy.criterion_ids)}. The accepted "
                    f"invariant ids are {_render_ids(policy.invariant_ids)}. "
                    "Both sets are read from the beta PRD at the revision the "
                    "admission policy pins, so an id the PRD does not carry is "
                    "refused on purpose. A parent AC reference names an "
                    "acceptance criterion on the parent issue, e.g. "
                    "'Gate: OMN-16729 AC-5'. A live-gate defect names the check "
                    "that is broken, e.g. 'Gate: live-gate defect: kb-doc-gate'"
                ),
            )
        )

    # Rule 4 -- residual-shaped titles, exempted only by a live-gate defect.
    if binding != "live_gate_defect":
        hits = _residual_terms_in(title, policy)
        if hits:
            findings.append(
                Finding(
                    code="residual_title",
                    field="title",
                    reason=(
                        f"the title reads as a residual ({', '.join(hits)}), and "
                        "the standing rule is that a residual is a comment on "
                        "its parent, not a new ticket"
                    ),
                    fix=(
                        "comment on the parent ticket instead. If this is a "
                        "LIVE GATE that is broken -- a check reporting green "
                        "while enforcing nothing -- it is not a residual: bind "
                        "it with 'Gate: live-gate defect: <check name>' and the "
                        "title stands"
                    ),
                )
            )

    # Rule 5 -- a create that STARTS In Progress needs an executable probe.
    # Scoped to a declared state rather than to every create on purpose: a
    # ticket parked in Backlog has not yet claimed to be work in flight, and a
    # probe demanded at filing time for work nobody has scoped yet is a field a
    # lane fills in with something plausible to get past the check.
    if description_readable and _declares_in_progress(tool_input, policy):
        findings.extend(_probe_line_findings(description))

    # Rule 6 -- a parent may not carry more than N children nobody has started.
    # The one rule here that reads state outside the payload, because the
    # question it answers -- how long is this parent's queue already? -- is not
    # answerable from the call in front of it. That is a real departure from
    # this module's original "from the payload alone" boundary, and it is
    # bounded to one lookup of one parent, behind a seam this function is given
    # rather than one it reaches for.
    findings.extend(
        _unstarted_cap_findings(
            tool_input, description, policy, children_lookup, ledger_root
        )
    )

    return findings


def render_block_reason(findings: list[Finding], policy: Policy) -> str:
    """Render one refusal naming every failing rule.

    Every rule at once, not the first: a guard that reports one missing field
    per attempt turns a single fix into four round trips, and each round trip is
    a chance for the lane to give up and file the ticket from a surface the gate
    does not see.
    """
    lines = [
        f"BLOCKED: this Linear issue CREATE is not bound to a commitment ({TICKET}).",
        "",
        (
            "Measured 2026-08-22..2026-09-04: 1553 tickets created in 14 days "
            "against ~35/day closed; 779 never left Backlog and 398 were never "
            "touched again. This guard refuses the creates that produce that."
        ),
        "",
    ]
    for finding in findings:
        lines.append(f"  * [{finding.code}] {finding.field}: {finding.reason}")
        lines.append(f"      fix: {finding.fix}")
    lines.extend(
        [
            "",
            "An UPDATE (save_issue with an id) is never gated -- only creates are.",
            (f"To disable this guard deliberately: onex hooks disable {GATE_BIT_NAME}"),
        ]
    )
    return "\n".join(lines)


def _resolve_api_key() -> str:
    """The tracker read credential, from the environment or the ONEX env file.

    The environment first. A PreToolUse hook inherits the session environment,
    which on a dispatched lane often does not carry it, so the same
    ``~/.omnibase/.env`` fallback ``scripts/worktree_auto_prune.py`` uses is read
    second. Returns ``""`` when neither carries one, which switches rule 6 off
    for this machine -- see :func:`_unstarted_cap_findings`.

    The value is never written anywhere: not to stdout, not to stderr, not to
    the refusal text.
    """
    key = os.environ.get("LINEAR_API_KEY", "").strip()
    if key:
        return key
    env_file = Path.home() / ".omnibase" / ".env"
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("LINEAR_API_KEY="):
            return stripped.partition("=")[2].strip().strip("'\"")
    return ""


def _fetch_children_nodes(
    parent_ref: str, api_key: str
) -> tuple[str, list[dict[str, Any]], bool] | None:
    """Enumerate a parent's children, or ``None`` when it cannot be resolved.

    Returns the parent's resolved identifier -- so a payload carrying a uuid
    still produces a refusal naming something a person can open -- its child
    nodes, and whether the enumeration ran to completion.

    Every failure mode collapses to ``None`` on purpose: a transport error, a
    non-200, a GraphQL error body, an unknown issue and an unparseable response
    are all "the tracker did not tell us", and the caller refuses on that
    uniformly rather than branching on which flavour of unknown it got.
    """
    identifier = parent_ref
    nodes: list[dict[str, Any]] = []
    after: str | None = None
    for _page in range(_CENSUS_MAX_PAGES):
        body = json.dumps(
            {
                "query": _CENSUS_QUERY,
                "variables": {
                    "id": parent_ref,
                    "after": after,
                    "first": _CENSUS_PAGE_SIZE,
                },
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310
            _LINEAR_API_URL,
            data=body,
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=_CENSUS_TIMEOUT_S
            ) as response:
                if response.status != 200:
                    return None
                raw = response.read()
        except (urllib.error.URLError, OSError):
            # HTTPError subclasses URLError, so a 400 on an unknown issue lands
            # here too.
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if payload.get("errors"):
            return None
        issue = (payload.get("data") or {}).get("issue")
        if not isinstance(issue, dict):
            return None
        identifier = str(issue.get("identifier") or parent_ref)
        children = issue.get("children") or {}
        page_nodes = children.get("nodes")
        if not isinstance(page_nodes, list):
            return None
        nodes.extend(node for node in page_nodes if isinstance(node, dict))
        page_info = children.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return identifier, nodes, True
        after = page_info.get("endCursor")
        if not isinstance(after, str) or not after:
            return None
    return identifier, nodes, False


def _network_lookup(api_key: str, policy: Policy) -> ChildrenLookup:
    """Bind the census seam to the live tracker."""

    def lookup(parent_ref: str) -> ParentCensus | None:
        fetched = _fetch_children_nodes(parent_ref, api_key)
        if fetched is None:
            return None
        identifier, nodes, complete = fetched
        return build_census(identifier, nodes, policy, complete=complete)

    return lookup


def _block(reason: str) -> int:
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.stdout.write("\n")
    return 3


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. Reads the PreToolUse JSON on stdin.

    Exit codes: ``0`` allow, ``3`` block (payload on stdout), ``1`` the guard
    itself could not decide. The shell wrapper treats ``1`` as a block too -- an
    undecidable create is refused, never assumed clean.
    """
    parser = argparse.ArgumentParser(description="ticket-creation admission gate")
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="override the shipped admission policy (tests only)",
    )
    args = parser.parse_args(argv)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"unparseable hook JSON on stdin: {exc}\n")
        return 1
    if not isinstance(payload, dict):
        sys.stderr.write("hook JSON on stdin is not an object\n")
        return 1

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or "save_issue" not in tool_name:
        return 0

    try:
        policy = load_policy(args.policy)
    except PolicyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    api_key = _resolve_api_key()
    lookup = _network_lookup(api_key, policy) if api_key else None
    ledger_root_raw = os.environ.get("OMNI_HOME", "").strip()
    ledger_root = Path(ledger_root_raw) if ledger_root_raw else None

    findings = check_save_issue(
        payload.get("tool_input"),
        policy,
        children_lookup=lookup,
        ledger_root=ledger_root,
    )
    if findings:
        # Nothing is written to stderr on this path. The shell wrapper captures
        # stdout and stderr TOGETHER and then reads `.reason` out of the result
        # with jq, so a diagnostic line here would not be a diagnostic -- it
        # would corrupt the refusal into the wrapper's generic fallback text and
        # throw away every finding this function just computed.
        return _block(render_block_reason(findings, policy))
    if lookup is None:
        sys.stderr.write(
            "[ticket_creation_guard] no LINEAR_API_KEY in the environment or "
            "~/.omnibase/.env, so rule 6 (the unstarted-children cap) was not "
            "evaluated for this create. Rules 1-5 ran normally.\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
