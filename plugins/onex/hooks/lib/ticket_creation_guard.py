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

An **UPDATE** is gated on ONE thing and nothing else (rule 9, OMN-18404): it may
not rewrite an acceptance criterion's own line. Every other update -- a state
flip, a parent re-link, a rewritten problem statement, a ticked checkbox -- is
admitted untouched, because gating those would block the board-truth work
(OMN-16729) this guard exists to serve.

A create is admitted only when all seven hold:

1. ``parentId`` is present, **or** the description declares the issue an epic
   on a line of its own.
2. A project is named -- ``project`` on the MCP surface, ``projectId`` in the
   REST spelling; either satisfies it.
3. The description carries a binding line, on a line of its own. The shape of
   that line, the rewrites applied to what it carries, and every form the
   binding may take are declared ONCE, in ``config/gate_binding_grammar.json``,
   and this module compiles that declaration rather than carrying a copy
   (OMN-18414). Read the contract for the forms and for why each is or is not
   a proof pointer.

   That file is vendored from the repository that owns it, and a drift test
   pins the two byte-identical. It is data read twice rather than one imported
   module for one reason: this decision core imports only the standard
   library, its hook script may resolve a bare system interpreter and runs it
   with a cleared ``PYTHONPATH``, so importing a packaged declaration would
   turn a missing dependency into a refusal of every Linear write on the
   machine.

   Before that contract this guard and the evidence closer carried DISJOINT
   vocabularies -- four forms here, one there, none shared -- so every ticket
   this guard admitted was a typed hold at the closer, and the form the closer
   required would have been refused at creation. The grammar is now the union,
   and it is one file.

   Two things stay this module's own, because they are admission policy and
   not grammar: which ids are in the pinned vocabulary a criterion or invariant
   binding is checked against, and which single form exempts a residual-shaped
   title under rule 4. The id sets are read from the beta PRD -- section 6's
   release-criteria table and the front matter's ``invariant-coverage`` block
   respectively -- at the revision the admission policy pins. See that policy's
   ``$comment`` for why the coverage block and not every invariant token in the
   document. Widening the shape grammar does not widen those sets.

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

6. Every acceptance criterion the description lists carries a **named
   falsifier** -- the check that would settle it -- written as part of the
   criterion::

       * AC1 -- the guard refuses an unfalsified create. -- falsifier: a guard
         test feeding a create with one unfalsified criterion asserts refusal

   A create whose criterion list has an unfalsified criterion is refused,
   naming that criterion.

7. A criterion that is **behaviour-shaped** may not name a **merge-state read**
   as its falsifier. "The companion PR is merged to main" may; "the guard
   refuses an unfalsified create" may not, because a merged pull request is not
   evidence that the guard refuses anything.

Rules 6 and 7 are the primary mechanism of OMN-18331's plan, and the argument
for putting them HERE rather than anywhere later in the lifecycle is worth
stating, because it is the whole reason the rules exist. A binding between a
criterion and the check that settles it has to be declared **before the
evidence exists, by the party that knows the intent, and attributably**. At
pull-request time the outcome is already known, so a binding written then can
be shaped to the result. At companion-mint time a machine would be inferring,
which OMN-18238 forbids outright. Ticket-creation time is the only point that
satisfies all three: the author writes the criterion and its falsifier in one
act, before any code exists, attributed to the creator with the ticket's own
timestamp.

The falsifier is a check name or a command shape -- **never a result**. It is a
claim about what WOULD settle the criterion, made before anything is built.

Rule 9 -- an update may not rewrite an acceptance criterion
----------------------------------------------------------
`onex_change_control`'s Acceptance-Criterion Binding Gate (OMN-18236) pins a
criterion by the hash of its text, so a binding cannot be left standing under a
criterion that was rewritten beneath it. Orchestration lanes patch descriptions
as BOOKKEEPING -- writing a comment-id citation, or a ``MET`` verdict, into the
criterion's own line -- and every such write moves that hash.

Measured 2026-09-15 on `onex_change_control` ``origin/dev`` ``48d9a167``
against live ticket bodies: **27 of 144 live pins were stale**, across
OMN-18387, OMN-18388 and OMN-18390, all three annotated the same day. 25 were
healed exactly by removing a ``(#<hex>)`` citation; the remaining 2 by removing
a ``MET`` verdict.

**Two shapes in one day** is the whole argument for putting the rule at the
writer rather than teaching the hash to ignore an annotation. A normaliser
taught to ignore the first shape would still have been red on the second, and
each exception carved into that hash is a channel through which a criterion CAN
be rewritten invisibly -- including the commit shas and digests this fleet
writes into criteria normatively.

Scope is exactly the bytes that gate hashes: the criterion's own LINE. Ticking
its checkbox, appending an indented evidence paragraph beneath it, adding a
criterion and removing one are all admitted. See :func:`criterion_lines` for why
that is deliberately narrower than this module's own :func:`criterion_units`.

The honest limit, as everywhere else here: this refuses an ACCIDENT. It cannot
tell a lane that a criterion is wrong, and a lane that means to change one may
still do so -- and must then re-accept the binding in the same act.

What rules 6 and 7 enforce, and what they cannot
------------------------------------------------
Rule 6 enforces that a falsifier was NAMED. It cannot judge whether the named
check is a good one, and it cannot run it. An author who names something
trivially true defeats it. That residual is real, it is recorded in the plan
rather than papered over, and it is bounded by three things this gate does
supply: the falsifier is written before the outcome is known, it is attributable
to a named creator, and rule 7 refuses the single commonest weak shape.

Rule 7 is that one shape. It reuses the OMN-18135 proof-class vocabulary --
transcribed into the policy file with its source revision pinned, because this
module parses its own policy with the standard library alone and can import
nothing from another repository. It does NOT re-implement proof
classification, and must not grow toward doing so: the classifier that decides
what a check PROVED runs later, over a receipt, with the command's real exit
status in hand. This one reads a sentence.

**The tie-break is inverted relative to its source, deliberately.** The source
asks whether a readback may discharge a criterion and answers yes only on a
state marker with no behaviour marker, so an ambiguous criterion falls to
behaviour and HOLDS a flip. This asks whether a criterion must be refused a
merge-state falsifier and answers yes only on a behaviour marker with no state
marker, so an ambiguous criterion is ADMITTED. Same wordlist, opposite default,
because the cost of the error is opposite: there a misread costs a comment,
here it costs a refused create, and a gate that refuses correct work is one
lanes learn to route around.

**Rule 7's conjunction, and why it is not an exemption.** A merge-state-shaped
falsifier is refused only when it names no test runner. That is OMN-18135's own
measured finding: ``gh api repos/<owner>/<repo>/commits/<sha> --jq .sha &&
uv run pytest ...`` is the form that satisfies receipt hardening AND keeps its
behaviour class, and a rule refusing every falsifier that mentions ``gh`` would
refuse the one shape that clears both gates. A lane meeting that refusal would
be right that the gate was wrong.

**Rule 6's scope, stated as a fail-open direction rather than implied.** It
fires only on a description carrying a recognised acceptance-criteria heading.
The closer's own parser falls back to reading the WHOLE BODY when it finds no
heading, because there an over-count holds a flip and holding is safe. Here an
over-count REFUSES a create, so the fallback is dropped. A create with no
criteria section is therefore not gated by rule 6. That is not a hole opened
here: such a ticket declares no map, the autobinder transcribes nothing, and
the closer holds it on an unbound criterion -- which is today's behaviour for
the entire corpus, and the hold is a comment on the ticket, not a silence.

The hashing unit, because a later mechanism depends on it
---------------------------------------------------------
The plan's next step transcribes each criterion's declared falsifier into a
companion contract as an ACCEPTED binding, whose ``criterion_hash`` pins the
criterion text as it read when the binding was accepted -- so a criterion
silently rewritten afterwards no longer satisfies a binding accepted against
its older wording. That only works if each criterion is independently
hashable: editing one criterion must not disturb the hash of any other.

This module therefore EXPORTS the unit rather than leaving the downstream
mechanism to re-derive it from markdown. :func:`criterion_units` returns one
:class:`CriterionUnit` per criterion -- its label, its canonical text, its
falsifier, and the hash of that canonical text. The unit is **one criterion
item**: its own bullet or ``AC<n>`` line plus any continuation lines before the
next item, which is exactly the span rule 6 already reads a falsifier from. Two
parsers would be two places to disagree about where one criterion ends, and a
disagreement there binds a criterion to a check declared for its neighbour.
Independence is a pinned property, not an incidental one: a test edits one
criterion and asserts every other hash is byte-identical.

**The canonical form is whitespace normalisation and nothing else** -- Unicode
NFC, runs of whitespace collapsed to single spaces, ends stripped. It
deliberately does NOT lowercase, strip emphasis, or drop the label: the hash
exists to detect that a criterion was rewritten, so anything it normalises away
is a rewrite it can no longer detect. Re-wrapping is the one edit that changes
the bytes without changing what the criterion says, which is why it is the one
thing normalised.

**The falsifier is inside the hash, deliberately.** What an author accepts is
the PAIR -- this criterion, settled by this check -- so a falsifier swapped
afterwards is exactly as much a rewrite as a reworded criterion, and a hash
covering only the criterion half would let the check change silently under an
accepted binding.

Rule 6 also does not require a criterion LABEL. An unlabelled criterion is
unbindable downstream and holds there, which is a ticket-authoring problem the
closer already reports; adding a second refusal for it here would refuse
creates for a defect that is already visible where it bites.

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
Rules 1-7 answer *is this ticket bound to a commitment?* from the payload alone. Rule 9
cannot: the criterion text an update is rewriting lives on the ticket, not in the patch.
So it takes a ``body_lookup`` -- an argument, not an import, so this module stays a pure
function of what it is given and the network lives in one bindable seam. ``main`` binds it
to the tracker; a test binds it to a fixture; nothing else calls it. Its fail direction is
stated rather than discovered: a body the tracker will not report REFUSES the update, and
a machine with no read credential admits it and says so on stderr -- the second bounded
fail-OPEN in this module, beside rule 5's uuid, because a guard that refuses every write
on a machine with no key is a guard that gets disabled wholesale rather than repaired.

The unstarted-children cap that OMN-18323 added here as rule 8 was RESCINDED by the
operator on 2026-09-21 (rolling work ledger RULING row 2026-09-21T14:46:45Z, item (f),
"that's not something I made"), and is gone with its policy constants, its census
lookup and its Admission-Override citation route. Nothing caps a parent's queue here.

Deliberately NOT built here
---------------------------
No duplicate detection, no per-lane quota, no rate limit. Those need state this
module does not have and would make a refusal depend on the history of who filed
what, rather than on the board the ticket is about to land on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "BindingForm",
    "BodyLookup",
    "CriterionUnit",
    "Finding",
    "GateGrammar",
    "Policy",
    "PolicyError",
    "apply_description_patch",
    "canonical_criterion_text",
    "check_save_issue",
    "criterion_lines",
    "criterion_units",
    "load_gate_grammar",
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

#: Rule 9's own ticket. Named separately because a refusal that cited the
#: creation gate's ticket would send somebody to the wrong diagnosis.
CRITERION_TICKET: Final[str] = "OMN-18404"

#: The ONE declaration of the binding grammar, vendored beside this module
#: (OMN-18414). Resolved relative to this file, never from an environment
#: variable: a grammar whose location can be pointed elsewhere is a grammar
#: that can be widened without review.
DEFAULT_GATE_GRAMMAR_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "gate_binding_grammar.json"
)

#: The contract's id for the form that also exempts a residual-shaped title
#: (rule 4). An ID, not a pattern: the shape of that form lives in the
#: contract, and the exemption is keyed on this form and on nothing else. Its
#: presence in the contract is checked at load time, so a contract that drops
#: the form refuses rather than silently retiring the exemption.
_RESIDUAL_EXEMPTING_FORM: Final[str] = "live_gate_defect"

#: The two form ids whose VALUE is additionally checked for membership in a
#: pinned vocabulary. Widening the shape grammar must not widen the id
#: vocabulary, so these two stay checked against the admission policy's own
#: sets after the contract has read their shape.
_CRITERION_FORM: Final[str] = "release_criterion"
_INVARIANT_FORM: Final[str] = "invariant"


@dataclass(frozen=True, slots=True)
class BindingForm:
    """One declared binding form.

    ``probe`` is the contract's statement of what the form resolves to at the
    reading consumer. This guard does not probe anything -- it records the
    value so a diagnostic can say which forms are proof pointers and which are
    traceability bindings, without this module deciding that.
    """

    id: str
    pattern: re.Pattern[str]
    probe: str
    example: str


@dataclass(frozen=True, slots=True)
class GateGrammar:
    """The ``Gate:`` grammar, compiled from the declaration both consumers read.

    This guard is the AUTHORING side, so it compiles ``line_pattern_authoring``
    -- the strict one, which refuses a bulleted binding line. The reading side
    tolerates bullets, quotes and emphasis because it faces descriptions that
    are already written. That asymmetry is declared, pinned by the contract's
    own superset fixtures, and is NOT the drift OMN-18414 closes: what must not
    differ, and did, is ``forms`` -- the grammar of the binding VALUE.
    """

    contract_version: str
    line: re.Pattern[str]
    normalizations: tuple[tuple[re.Pattern[str], str], ...]
    forms: tuple[BindingForm, ...]
    source: Path

    def normalize(self, binding: str) -> str:
        """Apply the declared rewrites, in declared order.

        Order is load-bearing and belongs to the contract: an issue mention
        nested inside a code span is only reached because the span is stripped
        after the mention is unwrapped, and the whitespace collapse is last so
        every earlier rewrite's output is folded the same way.
        """
        value = binding
        for pattern, replacement in self.normalizations:
            value = pattern.sub(replacement, value)
        return value.strip()

    def classify(self, binding: str) -> BindingForm | None:
        """The first declared form this binding matches, or ``None``.

        First match wins, in declared order. There is deliberately no wildcard
        form and no escape value: a binding matching nothing is unreadable, and
        a sanctioned spelling for an unreadable binding is a sanctioned
        incident.
        """
        value = self.normalize(binding)
        if not value:
            return None
        for form in self.forms:
            if form.pattern.match(value):
                return form
        return None

    def form(self, form_id: str) -> BindingForm | None:
        for candidate in self.forms:
            if candidate.id == form_id:
                return candidate
        return None

    def spelling(self, form_id: str) -> str:
        """How a binding of this form is written, as the contract spells it."""
        found = self.form(form_id)
        return found.example if found is not None else form_id

    @property
    def summary(self) -> str:
        """The whole grammar on one line, for a refusal to quote.

        Rendered from the contract rather than written here, so a form added
        there is named in the refusal without a second edit -- the failure mode
        that made the guard and the closer diverge in the first place.
        """
        return "Gate: <" + " | ".join(form.example for form in self.forms) + ">"


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
#: to a whole line for the same reason the binding line is (CLAUDE.md rule 15):
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

_LINEAR_API_URL: Final[str] = (
    "https://api.linear.app/graphql"  # url-authority-ok: the tracker's single documented GraphQL endpoint, read-only child-state lookups from a PreToolUse decision core that is standard-library-only by construction (it must resolve its own interpreter and refuse when it cannot, so it cannot import a routing authority or an integration catalog to resolve from); same endpoint and same reasoning as scripts/worktree_auto_prune.py
)

#: Per-request timeout for a tracker read. Small on purpose: this runs inside a
#: PreToolUse hook, in front of a human waiting on a tool call, and a slow read is
#: indistinguishable from a hung session.
_LOOKUP_TIMEOUT_S: Final[float] = 8.0

#: A bullet or numbered list item, and an unbulleted ``AC1 ...`` line. Both
#: transcribed from the closer's own criteria parser so the two mechanisms read
#: the same tickets the same way: a criterion this gate demands a falsifier for
#: must be one the closer will later look for a binding on, or the gate is
#: enforcing against a population nothing downstream reads.
_LIST_ITEM: Final[re.Pattern[str]] = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(.*)$")
_AC_ITEM: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*([*_]*)[ \t]*(AC[-_ ]?\d+)(?!\d)[*_]*(.*?)[ \t]*$", re.IGNORECASE
)
_TRAILING_EMPHASIS: Final[re.Pattern[str]] = re.compile(r"[*_]+$")
_TASK_MARKER: Final[re.Pattern[str]] = re.compile(r"^\[[ \t xX]\][ \t]*")
_TRAILING_QUALIFIER: Final[re.Pattern[str]] = re.compile(r"\s*\([^)]*\)\s*$")
_HEADING_ENUM: Final[re.Pattern[str]] = re.compile(r"^\d+[.)]\s*")

#: How much of a criterion is quoted back in a refusal. A description whose
#: criteria are paragraphs must not turn one refusal into an unreadable wall,
#: and an unbounded splice is how a message hits a transport limit.
_MAX_CRITERION_QUOTED: Final[int] = 160

#: How many unfalsified criteria are named individually. Past this the refusal
#: says how many more there are: forty quoted criteria do not make the point
#: forty times better, and the remedy is the same edit either way.
_MAX_CRITERIA_NAMED: Final[int] = 8

#: The label a downstream binding entry can point AT. Matched against the item
#: text this module returns, which has already had its bullet and any task
#: marker stripped -- so ``**AC1** ...``, ``AC-2: ...``, ``DoD3 -- ...`` and
#: ``ac 4)`` all reach here with the label leading. A criterion with no label
#: is NOT a parse failure: it is an UNBINDABLE criterion, because a binding
#: needs something stable to point at and an ordinal derived from parse
#: position renumbers every binding below it the moment a bullet is inserted.
#: Rule 6 does not refuse it -- that is a ticket-authoring problem reported
#: downstream, where it actually bites.
#:
#: OMN-18356: the optional single-letter SUFFIX group is the fix. A round
#: split into ``AC2b``/``AC2c``/... sits a letter directly after the ordinal
#: digits, with no boundary between them (both are word characters), so a
#: bare ``(\d+)\b`` never matched past the digits and the whole label was
#: lost -- the criterion came back indistinguishable from one with no ordinal
#: at all, and downstream never bound it. The suffix
#: is captured, not discarded, and is read verbatim (case preserved) because
#: it is part of the stable label a binding points at: ``AC2b`` and ``AC2B``
#: are different labels, not the same criterion written twice. A plain
#: ``AC2`` is unaffected -- the suffix group matches zero characters and the
#: boundary check falls back to its original position.
_CRITERION_LABEL: Final[re.Pattern[str]] = re.compile(
    r"^[\s>*_+-]*(?:\*\*)?\s*(AC|DOD)[-_ .]?(\d+)([a-zA-Z]?)\b", re.IGNORECASE
)

_FALSIFIER_GRAMMAR: Final[str] = (
    "<criterion text> -- falsifier: <check name or command shape that would settle it>"
)

#: The whole shape rule 10 asks for, rendered in every refusal it produces.
#: A refusal that names a missing property without showing the form that
#: carries it is one an author satisfies by guessing, and a guessed shape is
#: how a criteria section ends up parseable but unbindable -- which is the
#: defect, not a near miss of it.
_LABELLED_CRITERION_GRAMMAR: Final[str] = (
    "- [ ] AC<n>: <criterion text> -- falsifier: <check name or command shape "
    "that would settle it>"
)

#: The two ordinal prefixes :data:`_CRITERION_LABEL` reads, rendered for an
#: author. Spelled here rather than derived from the pattern because a regex
#: source is not a remedy anybody can act on.
_CRITERION_LABEL_FORMS: Final[str] = "AC<n> or DOD<n>"


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
    falsifier_markers: tuple[str, ...]
    acceptance_criteria_headings: frozenset[str]
    state_criterion_markers: tuple[re.Pattern[str], ...]
    behaviour_criterion_markers: tuple[re.Pattern[str], ...]
    merge_state_falsifier_markers: tuple[re.Pattern[str], ...]
    behaviour_runner_words: tuple[str, ...]
    #: Rule 10 (OMN-18484). The fewest LABELLED criteria a create may carry.
    min_labelled_criteria: int
    #: The binding-form ids that exempt a create from rule 10, validated at
    #: load time against the declared grammar: an exemption naming a form
    #: nothing can produce is an exemption that never fires, and a gate whose
    #: exemption never fires reads as working.
    labelled_criterion_exempt_binding_forms: frozenset[str]
    #: The declared binding grammar (OMN-18414). Carried on the policy so the
    #: decision core stays a pure function of what it is handed, and so a
    #: malformed declaration refuses at load time -- with everything else --
    #: rather than at the first create that happens to carry a binding line.
    gate_grammar: GateGrammar


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


#: Resolve an issue reference to its CURRENT description, or ``None`` when the
#: tracker will not report one. Rule 9's only window outside the payload, and a
#: callable so the decision core stays a pure function of what it is handed,
#: and the network lives in one place.
BodyLookup = Callable[[str], "str | None"]


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


def _compiled_markers(raw: Any, key: str, source: Path) -> tuple[re.Pattern[str], ...]:
    """Compile a configured marker list, or raise.

    A marker that will not compile is refused here rather than at match time.
    A regex error raised from inside a rule would surface as an unhandled
    exception in a PreToolUse hook, and the wrapper treats that as a block --
    so every Linear create on the machine would fail with a traceback instead
    of with a policy error naming the offending pattern.
    """
    patterns: list[re.Pattern[str]] = []
    for entry in _string_list(raw, key, source):
        try:
            patterns.append(re.compile(entry, re.IGNORECASE))
        except re.error as exc:
            raise PolicyError(
                f"{source}: '{key}' entry {entry!r} is not a regex ({exc})"
            ) from exc
    return tuple(patterns)


def _positive_int(raw: Any, key: str, source: Path) -> int:
    """Read a count, or raise.

    ``bool`` is rejected explicitly because it is an ``int`` subclass in Python
    and ``"min_labelled_criteria": true`` would otherwise configure a threshold
    of one. Zero and negatives are rejected because a threshold below one is a
    rule that never fires, which is a gate reading green while enforcing
    nothing -- a workspace-wide outage spelled as a config typo.
    """
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise PolicyError(
            f"{source}: '{key}' must be an integer of at least 1, got {raw!r}"
        )
    return int(raw)


def _grammar_string(raw: Any, key: str, source: Path) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise PolicyError(f"{source}: '{key}' must be a non-empty string, got {raw!r}")
    return raw


def _grammar_pattern(raw: Any, key: str, source: Path) -> re.Pattern[str]:
    """Compile a declared pattern with NO flags argument.

    Case-insensitivity arrives as an inline ``(?i)`` inside the declared
    pattern, which is what the contract states and why: a consumer adding
    ``re.IGNORECASE | re.MULTILINE`` trips the union-usage ratchet in the
    repository that owns the contract, and raising a ratchet ceiling to get
    past a false positive is how ceilings stop meaning anything. The one flag
    this module adds is :data:`re.MULTILINE`, and only to the LINE pattern,
    because the guard scans a whole description for a line of its own.
    """
    try:
        return re.compile(_grammar_string(raw, key, source))
    except re.error as exc:
        raise PolicyError(f"{source}: '{key}' is not a regex ({exc})") from exc


def load_gate_grammar(path: Path | None = None) -> GateGrammar:
    """Read the declared ``Gate:`` grammar, or raise.

    There is no built-in grammar to fall back to, deliberately. A guard that
    silently reverts to a private copy of the forms when the declaration is
    missing is a guard that has gone dark: it would keep admitting creates
    while the contract it claims to enforce was unreadable, which is the exact
    shape of a gate reporting green while enforcing nothing. Every failure here
    raises, and every create on the machine is refused with the reason named
    until the declaration is repaired.
    """
    source = path or DEFAULT_GATE_GRAMMAR_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"gate binding grammar not found at {source}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{source}: not valid JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"{source}: top level must be an object, got {type(raw)}")

    line = _grammar_pattern(
        raw.get("line_pattern_authoring"), "line_pattern_authoring", source
    )
    if "binding" not in line.groupindex:
        raise PolicyError(
            f"{source}: 'line_pattern_authoring' declares no 'binding' group, "
            "so a matching line names nothing to classify"
        )
    line = re.compile(line.pattern, re.MULTILINE)

    raw_norms = raw.get("normalizations")
    if not isinstance(raw_norms, list):
        raise PolicyError(
            f"{source}: 'normalizations' must be a list, got {raw_norms!r}"
        )
    normalizations: list[tuple[re.Pattern[str], str]] = []
    for entry in raw_norms:
        if not isinstance(entry, dict):
            raise PolicyError(f"{source}: normalization {entry!r} is not an object")
        label = f"normalizations[{entry.get('id')!r}].pattern"
        replacement = entry.get("replacement")
        if not isinstance(replacement, str):
            raise PolicyError(
                f"{source}: normalization {entry.get('id')!r} declares no string "
                f"replacement, got {replacement!r}"
            )
        normalizations.append(
            (_grammar_pattern(entry.get("pattern"), label, source), replacement)
        )

    #: A spelling per form, taken from the contract's own accepted fixtures, so
    #: a refusal quotes the grammar the contract declares rather than an
    #: example written here that can drift from it. A contract shipping no
    #: fixtures still loads: the form id stands in, and the fixtures are the
    #: test surface, not a runtime requirement.
    examples: dict[str, str] = {}
    fixtures = raw.get("fixtures")
    accepted = fixtures.get("accepted") if isinstance(fixtures, dict) else None
    if isinstance(accepted, list):
        for entry in accepted:
            if not isinstance(entry, dict):
                continue
            form_id, binding = entry.get("form"), entry.get("binding")
            if isinstance(form_id, str) and isinstance(binding, str):
                examples.setdefault(form_id, binding)

    raw_forms = raw.get("forms")
    if not isinstance(raw_forms, list) or not raw_forms:
        raise PolicyError(
            f"{source}: 'forms' must be a non-empty list. A contract declaring "
            "no form refuses every binding line, which is a workspace-wide "
            "outage spelled as an empty list"
        )
    forms: list[BindingForm] = []
    for entry in raw_forms:
        if not isinstance(entry, dict):
            raise PolicyError(f"{source}: form {entry!r} is not an object")
        form_id = _grammar_string(entry.get("id"), "forms[].id", source)
        forms.append(
            BindingForm(
                id=form_id,
                pattern=_grammar_pattern(
                    entry.get("pattern"), f"forms[{form_id!r}].pattern", source
                ),
                probe=_grammar_string(
                    entry.get("probe"), f"forms[{form_id!r}].probe", source
                ),
                example=examples.get(form_id, form_id),
            )
        )
    if not any(form.id == _RESIDUAL_EXEMPTING_FORM for form in forms):
        raise PolicyError(
            f"{source}: no {_RESIDUAL_EXEMPTING_FORM!r} form is declared, so "
            "rule 4's residual-title exemption is keyed on a form that does "
            "not exist. Refused rather than retiring the exemption silently"
        )
    for required in (_CRITERION_FORM, _INVARIANT_FORM):
        if not any(form.id == required for form in forms):
            raise PolicyError(
                f"{source}: no {required!r} form is declared, so the pinned id "
                "vocabulary it is checked against binds nothing"
            )
    return GateGrammar(
        contract_version=_grammar_string(
            raw.get("contract_version"), "contract_version", source
        ),
        line=line,
        normalizations=tuple(normalizations),
        forms=tuple(forms),
        source=source,
    )


def load_policy(path: Path | None = None, grammar_path: Path | None = None) -> Policy:
    """Read the admission vocabulary and the binding grammar, or raise.

    There is no default policy in code and no default grammar in code. A
    missing or malformed config is a refusal of every create until it is
    repaired, which is loud, rather than a silent widening of what the board
    admits, which is not.
    """
    grammar = load_gate_grammar(grammar_path)
    source = path or DEFAULT_POLICY_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"admission policy not found at {source}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{source}: not valid JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"{source}: top level must be an object, got {type(raw)}")

    # The SHAPE of a pinned id is the contract's business, not this module's:
    # the same form regex that reads a binding line validates the vocabulary
    # that binding line is checked against, so the two can never disagree.
    for key, form_id in (
        ("criterion_ids", _CRITERION_FORM),
        ("invariant_ids", _INVARIANT_FORM),
    ):
        form = grammar.form(form_id)
        assert form is not None  # load_gate_grammar refuses a contract missing it
        for value in _string_list(raw.get(key), key, source):
            if not form.pattern.match(value):
                raise PolicyError(
                    f"{source}: {key} entry {value!r} does not match the "
                    f"{form_id!r} form declared by {grammar.source} "
                    f"({form.pattern.pattern}); a binding spelled that way "
                    f"would never be read, e.g. {form.example!r}"
                )
    criterion_ids = _string_list(raw.get("criterion_ids"), "criterion_ids", source)
    invariant_ids = _string_list(raw.get("invariant_ids"), "invariant_ids", source)

    # Rule 10's exemption names FORMS, and the forms are the contract's. An id
    # the grammar does not declare can never be the answer _binding_kind
    # returns, so the exemption would silently never fire -- a gate reporting
    # green while enforcing something other than what its config says.
    exempt_key = "labelled_criterion_exempt_binding_forms"
    exempt_forms = _string_list(raw.get(exempt_key), exempt_key, source)
    for form_id in exempt_forms:
        if grammar.form(form_id) is None:
            raise PolicyError(
                f"{source}: {exempt_key} entry {form_id!r} is not a form "
                f"declared by {grammar.source}; the declared forms are "
                f"{', '.join(f.id for f in grammar.forms)}"
            )
    return Policy(
        gate_grammar=grammar,
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
        falsifier_markers=tuple(
            m.lower()
            for m in _string_list(
                raw.get("falsifier_markers"), "falsifier_markers", source
            )
        ),
        acceptance_criteria_headings=frozenset(
            h.lower()
            for h in _string_list(
                raw.get("acceptance_criteria_headings"),
                "acceptance_criteria_headings",
                source,
            )
        ),
        state_criterion_markers=_compiled_markers(
            raw.get("state_criterion_markers"), "state_criterion_markers", source
        ),
        behaviour_criterion_markers=_compiled_markers(
            raw.get("behaviour_criterion_markers"),
            "behaviour_criterion_markers",
            source,
        ),
        merge_state_falsifier_markers=_compiled_markers(
            raw.get("merge_state_falsifier_markers"),
            "merge_state_falsifier_markers",
            source,
        ),
        behaviour_runner_words=tuple(
            w.lower()
            for w in _string_list(
                raw.get("behaviour_runner_words"), "behaviour_runner_words", source
            )
        ),
        min_labelled_criteria=_positive_int(
            raw.get("min_labelled_criteria"), "min_labelled_criteria", source
        ),
        labelled_criterion_exempt_binding_forms=frozenset(exempt_forms),
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

    Returns the declared form id of the strongest binding, or ``None`` when no
    line binds. Every form the contract declares is read -- including the
    workflow-run form, which is the one the evidence closer requires and which
    this guard refused until OMN-18414, so that every ticket it admitted was a
    typed hold downstream.

    Two things this module still owns, because they are admission policy and
    not grammar: a body may carry several ``Gate:`` lines (a quoted example
    above the real one, say) and the exempting form wins regardless of which
    came first, so rule 4 does not depend on line order; and a form whose id
    names a pinned vocabulary is additionally checked for MEMBERSHIP. Widening
    the shape grammar must not widen the id vocabulary.
    """
    grammar = policy.gate_grammar
    vocabularies = {
        _CRITERION_FORM: policy.criterion_ids,
        _INVARIANT_FORM: policy.invariant_ids,
    }
    kinds: set[str] = set()
    for match in grammar.line.finditer(description):
        binding = grammar.normalize(match.group("binding"))
        if not binding:
            continue
        form = grammar.classify(binding)
        if form is None:
            continue
        allowed = vocabularies.get(form.id)
        if allowed is not None and binding.upper() not in allowed:
            continue
        kinds.add(form.id)
    for preferred in (_RESIDUAL_EXEMPTING_FORM, *(f.id for f in grammar.forms)):
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


def _is_criteria_heading(line: str, policy: Policy) -> bool:
    """True when ``line`` opens an acceptance-criteria section.

    Tolerates ``## Acceptance Criteria``, ``**Acceptance criteria:**``,
    ``### 3. Acceptance criteria`` and a bare ``AC``, and strips a trailing
    parenthetical qualifier -- ``Acceptance criteria (falsifiable)`` names the
    section as surely as the bare spelling does. Membership is against the
    configured closed set, never a prefix: a heading reading "Acceptance
    criteria coverage report" is about the section, not the section itself.
    """
    trimmed = line.strip()
    if not trimmed:
        return False
    trimmed = trimmed.lstrip("#").strip()
    trimmed = trimmed.strip("*_").strip()
    trimmed = _HEADING_ENUM.sub("", trimmed).strip()
    trimmed = trimmed.rstrip(":").strip()
    folded = trimmed.lower()
    if folded in policy.acceptance_criteria_headings:
        return True
    return (
        _TRAILING_QUALIFIER.sub("", folded).strip()
        in policy.acceptance_criteria_headings
    )


def _acceptance_criteria_items(description: str, policy: Policy) -> list[str]:
    """The criterion items listed under an acceptance-criteria heading.

    The section runs from the heading to the next markdown heading, or to the
    end of the body. An item spans its own line plus any continuation lines
    that follow it before the next item -- so a criterion whose falsifier is
    written on a wrapped line still carries it, and a falsifier belonging to
    the criterion above never discharges the one below.

    Returns an EMPTY list when no recognised heading is present. That differs
    from the closer's parser, which reads the whole body in that case; the
    divergence and its reason are in this module's docstring and in the policy
    file's own comment. Diverging silently would be the defect.
    """
    if not any(_is_criteria_heading(line, policy) for line in description.splitlines()):
        return []

    items: list[list[str]] = []
    in_section = False
    open_item = False
    for line in description.splitlines():
        if _is_criteria_heading(line, policy):
            in_section = True
            open_item = False
            continue
        if not in_section:
            continue
        if line.lstrip().startswith("#"):
            break
        text: str | None = None
        list_match = _LIST_ITEM.match(line)
        if list_match:
            text = _TASK_MARKER.sub("", list_match.group(1)).strip()
        else:
            ac_match = _AC_ITEM.match(line)
            if ac_match:
                lead, token, rest = ac_match.groups()
                text = f"{token}{rest}".strip()
                if lead:
                    text = _TRAILING_EMPHASIS.sub("", text).strip()
        if text is not None:
            if text:
                items.append([text])
                open_item = True
            else:
                open_item = False
            continue
        if not line.strip():
            continue
        if open_item:
            items[-1].append(line.strip())
    return [" ".join(parts).strip() for parts in items if " ".join(parts).strip()]


def _falsifier_of(item: str, policy: Policy) -> str | None:
    """The text a criterion names as its falsifier, or ``None``.

    Matched inside the item rather than on a line of its own -- the one place
    this module departs from whole-line anchoring, for the reason the policy
    file records: the falsifier has to be part of the criterion, written in the
    same act, and the item boundary supplies the anchoring instead. The LAST
    marker wins, so a criterion whose prose happens to use the word before
    naming the real one is read the way its author meant it.
    """
    best: str | None = None
    folded = item.lower()
    for marker in policy.falsifier_markers:
        start = folded.rfind(marker)
        if start == -1:
            continue
        tail = item[start + len(marker) :].strip(" \t:-*_")
        if tail and (best is None or start > folded.rfind(best.lower())):
            best = tail
    return best


def _criterion_is_behaviour_shaped(item: str, policy: Policy) -> bool:
    """True only on POSITIVE behaviour language with no live-state language.

    The inverted tie-break, stated once more where it is applied: an ambiguous
    criterion is NOT behaviour-shaped, so rule 7 does not fire on it. The
    source classifier resolves ties the other way because there a tie holds a
    flip and here it refuses a create.
    """
    if any(marker.search(item) for marker in policy.state_criterion_markers):
        return False
    return any(marker.search(item) for marker in policy.behaviour_criterion_markers)


def _falsifier_is_merge_state_read(falsifier: str, policy: Policy) -> bool:
    """True when a falsifier reads merge state and names no test runner.

    The conjunction is load-bearing and is OMN-18135's measured finding, not a
    softening: ``gh api repos/<owner>/<repo>/commits/<sha> --jq .sha &&
    uv run pytest ...`` reads merge state AND proves behaviour, and refusing it
    would refuse the one shape that satisfies receipt hardening and the
    proof-class rule at the same time.
    """
    if not any(
        marker.search(falsifier) for marker in policy.merge_state_falsifier_markers
    ):
        return False
    folded = falsifier.lower()
    return not any(
        re.search(rf"(?<!\w){re.escape(word)}(?!\w)", folded)
        for word in policy.behaviour_runner_words
    )


def canonical_criterion_text(item: str) -> str:
    """The form a criterion is hashed in.

    Unicode NFC, whitespace runs collapsed to single spaces, ends stripped --
    and nothing else. See the module docstring for why the normalisation is
    this narrow.
    """
    return " ".join(unicodedata.normalize("NFC", item).split())


@dataclass(frozen=True, slots=True)
class CriterionUnit:
    """One acceptance criterion, as a self-contained hashable unit.

    ``label`` is ``None`` for a criterion carrying no ``AC<n>``/``DoD<n>``
    ordinal -- unbindable downstream, but not refused here.

    ``falsifier`` is ``None`` for a criterion naming no check, which is exactly
    the population rule 6 refuses, so a consumer never re-derives it.

    ``criterion_hash`` is the SHA-256 of ``text`` encoded UTF-8, hex.
    """

    label: str | None
    text: str
    falsifier: str | None
    criterion_hash: str


def criterion_units(description: str, policy: Policy) -> list[CriterionUnit]:
    """Every acceptance criterion in ``description``, one hashable unit each.

    Exported for the binding transcriber. Returns an empty list for a
    description with no recognised criteria heading -- the same scope rule 6
    has.
    """
    units: list[CriterionUnit] = []
    for item in _acceptance_criteria_items(description, policy):
        text = canonical_criterion_text(item)
        match = _CRITERION_LABEL.match(text)
        units.append(
            CriterionUnit(
                label=(
                    f"{match.group(1).upper()}{match.group(2)}{match.group(3)}"
                    if match
                    else None
                ),
                text=text,
                falsifier=_falsifier_of(item, policy),
                criterion_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return units


# -- rule 9: a criterion's own line is not bookkeeping surface (OMN-18404) ----


def _criterion_line_text(line: str) -> str:
    """The criterion text ONE line carries, or ``""``.

    The per-line half of :func:`_acceptance_criteria_items`, lifted out so rule
    9 can read a criterion exactly as the change-control gate does. The task
    marker is stripped, which is why ticking a checkbox is invisible here and
    therefore always admitted.
    """
    list_match = _LIST_ITEM.match(line)
    if list_match:
        return _TASK_MARKER.sub("", list_match.group(1)).strip()
    ac_match = _AC_ITEM.match(line)
    if not ac_match:
        return ""
    lead, token, rest = ac_match.groups()
    text = f"{token}{rest}".strip()
    if lead:
        text = _TRAILING_EMPHASIS.sub("", text).strip()
    return text


def criterion_lines(description: str) -> dict[str, str]:
    """``{label: that criterion's OWN LINE}``, canonicalised.

    DELIBERATELY NOT :func:`criterion_units`, and the difference is the whole
    point of the rule. That function joins a criterion's continuation lines into
    one item, because the falsifier rules need the criterion as its author wrote
    it. `onex_change_control`'s binding gate hashes the criterion's own LINE and
    nothing else (`validation/ac_criteria.py`, ``item_text``), so the bytes rule
    9 must protect are the line's, not the item's.

    Reading it any wider would refuse the habit that is actually harmless --
    appending an indented evidence paragraph beneath a criterion, which three
    live tickets do and which changes no hash -- and a guard that refuses
    harmless work is a guard somebody turns off.

    Scanned over the WHOLE body rather than the criteria section, matching that
    gate's own whole-body fallback: a criterion written under an unrecognised
    heading is still one whose rewrite breaks a binding.

    First occurrence of a label wins, the same tie-break that gate uses, so two
    lines labelled ``AC1`` cannot make the comparison depend on scan order.
    """
    resolved: dict[str, str] = {}
    for line in description.splitlines():
        text = _criterion_line_text(line)
        if not text:
            continue
        match = _CRITERION_LABEL.match(text)
        if not match:
            continue
        label = f"{match.group(1).upper()}{match.group(2)}{match.group(3)}"
        if label not in resolved:
            resolved[label] = canonical_criterion_text(text)
    return resolved


class PatchUnapplicable(ValueError):
    """A description patch this guard cannot resolve to one definite result."""


def apply_description_patch(previous: str, operations: Any) -> str:
    """The description ``operations`` produce when applied to ``previous``.

    ``save_issue`` can edit a description through ``patch`` instead of sending
    the whole field, and ticking a checkbox is exactly the shape somebody
    reaches for ``patch`` to do. A rule 9 that read only ``description`` would
    therefore miss the most likely route to the defect while looking like it
    covered it, so the ops are applied here and the RESULT is compared.

    Anchor semantics are the tool's own: every anchor must match exactly once,
    and the ops apply in order, atomically. Anything this cannot resolve to one
    definite result raises :class:`PatchUnapplicable` and the caller refuses --
    "I could not work out what this writes" must not resolve to "so it passes".
    """
    if not isinstance(operations, list) or not operations:
        raise PatchUnapplicable("patch is not a non-empty list of operations")
    body = previous
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise PatchUnapplicable(f"operation {index} is not an object")
        op = raw.get("op")
        if op == "prepend":
            text = raw.get("text")
            if not isinstance(text, str):
                raise PatchUnapplicable(f"operation {index} carries no text")
            body = text + body
        elif op == "append":
            text = raw.get("text")
            if not isinstance(text, str):
                raise PatchUnapplicable(f"operation {index} carries no text")
            body = body + text
        elif op in {"insert_before", "insert_after"}:
            anchor, text = raw.get("anchor"), raw.get("text")
            if not isinstance(anchor, str) or not isinstance(text, str):
                raise PatchUnapplicable(
                    f"operation {index} needs a string anchor and text"
                )
            if body.count(anchor) != 1:
                raise PatchUnapplicable(
                    f"operation {index} anchor matches {body.count(anchor)} times"
                )
            at = body.index(anchor)
            at = at if op == "insert_before" else at + len(anchor)
            body = body[:at] + text + body[at:]
        elif op == "replace":
            old, new = raw.get("old_string"), raw.get("new_string")
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise PatchUnapplicable(
                    f"operation {index} needs a non-empty old_string and a new_string"
                )
            if raw.get("replace_all") is True:
                if old not in body:
                    raise PatchUnapplicable(f"operation {index} matches nothing")
                body = body.replace(old, new)
            else:
                if body.count(old) != 1:
                    raise PatchUnapplicable(
                        f"operation {index} old_string matches {body.count(old)} times"
                    )
                body = body.replace(old, new, 1)
        elif op == "replace_range":
            start, end = raw.get("from"), raw.get("to")
            new = raw.get("new_string")
            if (
                not isinstance(start, str)
                or not start
                or not isinstance(end, str)
                or not end
                or not isinstance(new, str)
            ):
                raise PatchUnapplicable(f"operation {index} needs from, to, new_string")
            if body.count(start) != 1:
                raise PatchUnapplicable(
                    f"operation {index} 'from' matches {body.count(start)} times"
                )
            head = body.index(start)
            tail = body.find(end, head + len(start))
            if tail == -1 or body.count(end, head + len(start)) != 1:
                raise PatchUnapplicable(
                    f"operation {index} 'to' does not follow 'from' exactly once"
                )
            body = body[:head] + new + body[tail:]
        else:
            raise PatchUnapplicable(f"operation {index} has unknown op {op!r}")
    return body


def _criterion_text_findings(
    issue_ref: str,
    tool_input: dict[str, Any],
    body_lookup: BodyLookup | None,
) -> list[Finding]:
    """Rule 9 -- an existing criterion's own line may not be rewritten.

    Only the labels present BOTH before and after are compared. Adding a
    criterion and removing one are authoring, not rewriting, and neither can
    leave a binding standing over changed text: a binding to a label the ticket
    no longer has is already refused by that gate as an unknown criterion.

    **Where the unknowns fall, stated rather than left to be discovered.** No
    credential configured is a stable property of the machine, not of this call
    -- the rule does not run and :func:`main` says so on stderr, which is rule
    8's precedent and its reasoning. A credential that IS present and a body
    that still cannot be read is a transient, and it REFUSES: a retry clears it,
    and "I hold a credential and could not check" is the shape that must not
    resolve to a pass.
    """
    if body_lookup is None:
        return []
    previous = body_lookup(issue_ref)
    if previous is None:
        return [
            Finding(
                code="criterion_text_unreadable",
                field="description",
                reason=(
                    f"the current body of {issue_ref} could not be read, so the "
                    "guard cannot tell whether this update rewrites an "
                    "acceptance criterion"
                ),
                fix=(
                    "retry the update; if the tracker stays unreachable, make "
                    "the edit once the read works rather than blind"
                ),
            )
        ]

    if "patch" in tool_input:
        try:
            proposed = apply_description_patch(previous, tool_input["patch"])
        except PatchUnapplicable as exc:
            return [
                Finding(
                    code="criterion_text_unreadable",
                    field="patch",
                    reason=(
                        f"this patch does not resolve to one definite body "
                        f"({exc}), so the guard cannot tell whether it rewrites "
                        "an acceptance criterion"
                    ),
                    fix=(
                        "send the edit as a full description, or give each "
                        "operation an anchor that matches exactly once"
                    ),
                )
            ]
    else:
        proposed = str(tool_input.get("description") or "")

    before = criterion_lines(previous)
    after = criterion_lines(proposed)
    findings: list[Finding] = []
    for label in sorted(set(before) & set(after)):
        if before[label] == after[label]:
            continue
        findings.append(
            Finding(
                code="criterion_text_rewritten",
                field=label,
                reason=(
                    f"this update rewrites {label}'s own line. Was: "
                    f"{_quote(before[label])!r}. Now: {_quote(after[label])!r}"
                ),
                fix=(
                    f"leave {label}'s line exactly as it is and put the "
                    "annotation on its own line BELOW the acceptance-criteria "
                    "block. A contract's ac_bindings pins this line by hash, so "
                    "editing it reverts every binding on it to unproven and "
                    "turns the change-control gate red. If the criterion itself "
                    "is genuinely wrong, change it and re-accept the binding in "
                    "the same act"
                ),
            )
        )
    return findings


def _quote(item: str) -> str:
    """One criterion, trimmed to a readable length for a refusal message."""
    flat = " ".join(item.split())
    if len(flat) <= _MAX_CRITERION_QUOTED:
        return flat
    return flat[: _MAX_CRITERION_QUOTED - 1].rstrip() + "\u2026"


def _criterion_findings(description: str, policy: Policy) -> list[Finding]:
    """Rules 6 and 7, over every criterion the description lists."""
    items = criterion_units(description, policy)
    if not items:
        return []

    unfalsified: list[str] = []
    merge_state: list[tuple[str, str]] = []
    for unit in items:
        if unit.falsifier is None:
            unfalsified.append(unit.text)
            continue
        if _criterion_is_behaviour_shaped(
            unit.text, policy
        ) and _falsifier_is_merge_state_read(unit.falsifier, policy):
            merge_state.append((unit.text, unit.falsifier))

    findings: list[Finding] = []
    canonical = policy.falsifier_markers[0]
    if unfalsified:
        named = unfalsified[:_MAX_CRITERIA_NAMED]
        remainder = len(unfalsified) - len(named)
        quoted = "; ".join(f'"{_quote(item)}"' for item in named)
        if remainder:
            quoted += f"; and {remainder} more"
        findings.append(
            Finding(
                code="unfalsified_criterion",
                field="description",
                reason=(
                    f"{len(unfalsified)} of {len(items)} acceptance criteria name "
                    f"no check that would settle them: {quoted}. A criterion with "
                    "no named falsifier cannot be bound to an evidence item, so "
                    "nothing that closes tickets mechanically can ever discharge "
                    "it -- and a binding written later, once the outcome is "
                    "known, can be shaped to that outcome, which is the thing "
                    "declaring it now prevents"
                ),
                fix=(
                    f"write each criterion as '{_FALSIFIER_GRAMMAR}' -- e.g. "
                    "'AC1 -- the guard refuses an unfalsified create. -- "
                    f"{canonical} a guard test feeding a create with one "
                    "unfalsified criterion asserts a non-zero refusal'. The "
                    "falsifier is a check name or a command shape, never a "
                    "result: it says what WOULD settle the criterion, not what "
                    "did. If a criterion has no such check, it is not yet an "
                    "acceptance criterion"
                ),
            )
        )
    for item, falsifier in merge_state[:_MAX_CRITERIA_NAMED]:
        findings.append(
            Finding(
                code="merge_state_falsifier_on_behaviour_criterion",
                field="description",
                reason=(
                    f'the criterion "{_quote(item)}" asks what the code DOES, '
                    f'but its falsifier "{_quote(falsifier)}" reads merge state. '
                    "A merged pull request and a green check say a change landed; "
                    "neither says the behaviour the criterion claims actually "
                    "happens, so a criterion settled that way is settled by "
                    "nothing"
                ),
                fix=(
                    "name a check that EXERCISES the behaviour -- a test runner "
                    f"({', '.join(policy.behaviour_runner_words[:5])}, ...) or the "
                    "onex CLI running the node or skill. A merge-state read is a "
                    "legitimate falsifier for a criterion about merge state "
                    "('the companion is merged to main and read back'), which "
                    "this rule does not touch. A falsifier that carries BOTH -- "
                    "'gh api repos/<owner>/<repo>/commits/<sha> --jq .sha && "
                    "uv run pytest ...' -- is admitted: it satisfies receipt "
                    "hardening and still proves behaviour"
                ),
            )
        )
    return findings


def _labelled_criterion_findings(
    description: str, binding: str | None, policy: Policy
) -> list[Finding]:
    """Rule 10 -- the create carries a criterion the closer can bind evidence to.

    Rules 6 and 7 ask what a LISTED criterion must carry. This asks the prior
    question: is there a criterion at all, and does one of them carry a label?
    Both halves are the same defect seen from the closing side. A binding entry
    keys on a label (``ModelAcBinding``), so an unlabelled criterion cannot
    appear in a binding record at all; and a description that parses to zero
    criteria is refused outright by the evidence-autoclose sweep, which is why
    such a ticket can never close mechanically no matter how good its evidence.

    This is deliberately the rule that closes rule 6's stated fail-OPEN. That
    rule declines to fire on a description with no criteria section, because
    there an over-count would refuse a create; here the absence IS the finding,
    so there is nothing to over-count.

    Two exempt shapes, both declared in config rather than inferred:

    * an epic states its own commitment and its children carry the criteria;
    * a create bound by a form the policy names -- the parent-criterion form --
      points at a LABELLED criterion on its parent, so the bindable thing this
      rule demands already exists. A binding that names a check or a document
      id (a workflow run, a release criterion, an invariant, a live-gate
      defect) does not, and is not exempt.

    The threshold is at least one labelled criterion, not all of them. Rules 6
    and 7 already bound what every criterion carries; asking every one of them
    to be labelled as well would refuse the mixed sections the corpus is full
    of, and a gate that refuses correct work is one lanes route around.
    """
    if _declares_epic(description, policy):
        return []
    if (
        binding is not None
        and binding in policy.labelled_criterion_exempt_binding_forms
    ):
        return []

    units = criterion_units(description, policy)
    if not units:
        headings = ", ".join(sorted(policy.acceptance_criteria_headings))
        return [
            Finding(
                code="missing_acceptance_criteria",
                field="description",
                reason=(
                    "the description lists no acceptance criterion: no "
                    "recognised criteria heading opens a section here, so the "
                    "parser the evidence closer reads tickets with returns "
                    "nothing. A ticket with no parseable criterion is refused "
                    "outright by that closer, so this one could never close "
                    "mechanically however good its evidence turned out to be"
                ),
                fix=(
                    "open a section with one of these headings -- "
                    f"{headings} -- and write each criterion as "
                    f"'{_LABELLED_CRITERION_GRAMMAR}'. At least "
                    f"{policy.min_labelled_criteria} criterion must carry an "
                    f"ordinal label ({_CRITERION_LABEL_FORMS}), because that "
                    "label is "
                    "what a change-control binding entry points at. If the "
                    "work has no such criterion, it is not yet a ticket"
                ),
            )
        ]

    labelled = sum(1 for unit in units if unit.label is not None)
    if labelled >= policy.min_labelled_criteria:
        return []
    return [
        Finding(
            code="unlabelled_criteria",
            field="description",
            reason=(
                f"every one of the {len(units)} acceptance criteria listed "
                "here parses, and none carries an ordinal label "
                f"({_CRITERION_LABEL_FORMS}). A binding entry keys on "
                "that label, so an unlabelled criterion cannot appear in a "
                "binding record at all -- the criteria read fine to a human "
                "and are invisible to everything that closes tickets"
            ),
            fix=(
                f"prefix at least {policy.min_labelled_criteria} of them with "
                f"an ordinal -- {_CRITERION_LABEL_FORMS} -- giving "
                f"'{_LABELLED_CRITERION_GRAMMAR}'. The ordinal is the stable "
                "thing a binding points at, which is why a position in the "
                "list will not do: inserting a bullet would renumber every "
                "binding below it"
            ),
        )
    ]


def check_save_issue(
    tool_input: Any,
    policy: Policy,
    body_lookup: BodyLookup | None = None,
) -> list[Finding]:
    """Return every failing admission rule for one ``save_issue`` call.

    An empty list admits the call. A CREATE is judged by rules 1-7; an UPDATE is
    judged by rule 9 alone, and only when it touches the description.

    ``body_lookup`` is rule 9's only window onto anything outside the payload,
    and it is an argument rather than an import so this function stays a pure
    function of what it is given; see :func:`_criterion_text_findings`.
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
            # An UPDATE. Rules 1-8 bound a ticket's SHAPE at creation and have
            # nothing to say here. Rule 9 does: an update is the only way an
            # acceptance criterion's text can change after a contract has
            # pinned it (OMN-18404).
            touches_body = (
                "patch" in tool_input or tool_input.get("description") is not None
            )
            if not touches_body:
                return []
            raw_body = tool_input.get("description")
            if "patch" not in tool_input and not isinstance(raw_body, str):
                return [
                    Finding(
                        code="unevaluable",
                        field="description",
                        reason=(
                            f"'description' is {type(raw_body).__name__}, not a "
                            "string, so the guard cannot read what this update "
                            "writes into the acceptance criteria"
                        ),
                        fix="pass the description as markdown text",
                    )
                ]
            return _criterion_text_findings(
                str(tool_input["id"]), tool_input, body_lookup
            )
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
                    f"'{policy.gate_grammar.summary}'. Those spellings are the "
                    f"forms declared by {policy.gate_grammar.source.name}, the "
                    "single grammar this guard and the evidence closer both "
                    f"read. The accepted release-criterion ids are "
                    f"{_render_ids(policy.criterion_ids)}. The accepted "
                    f"invariant ids are {_render_ids(policy.invariant_ids)}. "
                    "Both sets are read from the beta PRD at the revision the "
                    "admission policy pins, so an id the PRD does not carry is "
                    "refused on purpose"
                ),
            )
        )

    # Rule 4 -- residual-shaped titles, exempted by ONE declared form and no
    # other: a defect in a live gate is not a residual of anything.
    if binding != _RESIDUAL_EXEMPTING_FORM:
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
                        "it with 'Gate: "
                        f"{policy.gate_grammar.spelling(_RESIDUAL_EXEMPTING_FORM)}'"
                        " (naming the check that is broken) and the title "
                        "stands"
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

    # Rules 6 and 7 -- every listed criterion names the check that would settle
    # it, and a behaviour-shaped criterion does not name a merge-state read.
    if description_readable:
        findings.extend(_criterion_findings(description, policy))

    # Rule 10 -- the create carries a criterion the closer can bind evidence
    # to. Read AFTER rules 6 and 7 because it closes their stated fail-open,
    # and given the binding rule 3 already classified so the two cannot
    # disagree about which form this create declares.
    if description_readable:
        findings.extend(_labelled_criterion_findings(description, binding, policy))

    return findings


def render_block_reason(
    findings: list[Finding], policy: Policy, update: bool = False
) -> str:
    """Render one refusal naming every failing rule.

    Every rule at once, not the first: a guard that reports one missing field
    per attempt turns a single fix into four round trips, and each round trip is
    a chance for the lane to give up and file the ticket from a surface the gate
    does not see.

    ``update`` selects rule 9's preamble. A create's refusal cites the backlog
    measurement that justifies rules 1-7 and would be simply untrue on an
    update, which is refused for an unrelated reason.
    """
    if update:
        lines = [
            f"BLOCKED: this Linear issue UPDATE rewrites an acceptance "
            f"criterion ({CRITERION_TICKET}).",
            "",
            (
                "Measured 2026-09-15: 27 of 144 live ac_binding pins were stale "
                "across three tickets, every one of them because a lane wrote "
                "bookkeeping -- a comment-id citation, a MET verdict -- into a "
                "criterion's own line. A contract pins that line by hash, so the "
                "annotation reverts every binding on it to unproven."
            ),
            "",
        ]
    else:
        lines = [
            f"BLOCKED: this Linear issue CREATE is not bound to a commitment "
            f"({TICKET}).",
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
            (
                "Only a criterion's OWN LINE is protected. Ticking its checkbox, "
                "appending an indented paragraph beneath it, adding a criterion "
                "and removing one are all admitted."
                if update
                else "An UPDATE is gated only on rewriting an acceptance "
                "criterion's own line -- nothing else about it is checked."
            ),
            (f"To disable this guard deliberately: onex hooks disable {GATE_BIT_NAME}"),
        ]
    )
    return "\n".join(lines)


def _resolve_api_key() -> str:
    """The tracker read credential, from the environment or the ONEX env file.

    The environment first. A PreToolUse hook inherits the session environment,
    which on a dispatched lane often does not carry it, so the same
    ``~/.omnibase/.env`` fallback ``scripts/worktree_auto_prune.py`` uses is read
    second. Returns ``""`` when neither carries one, which switches rule 9 off
    for this machine -- see :func:`_criterion_text_findings`.

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


_BODY_QUERY: Final[str] = "query($id:String!){issue(id:$id){description}}"


def _fetch_issue_body(issue_ref: str, api_key: str) -> str | None:
    """One issue's current description, or ``None`` when it cannot be read.

    Every failure collapses to ``None`` on purpose: a transport error, a
    non-200, a GraphQL error body, an unknown issue and an unparseable response
    are all "the tracker did not tell us", and the caller refuses on that
    uniformly. An issue
    that exists with a genuinely empty description returns ``""``, which is a
    body and not an unknown.
    """
    request = urllib.request.Request(  # noqa: S310
        _LINEAR_API_URL,
        data=json.dumps(
            {"query": _BODY_QUERY, "variables": {"id": issue_ref}}
        ).encode(),
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=_LOOKUP_TIMEOUT_S
        ) as response:
            if response.status != 200:
                return None
            raw = response.read()
    except (urllib.error.URLError, OSError):
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
    description = issue.get("description")
    if description is None:
        return ""
    return description if isinstance(description, str) else None


def _body_network_lookup(api_key: str) -> BodyLookup:
    """Bind rule 9's body seam to the live tracker."""

    def lookup(issue_ref: str) -> str | None:
        return _fetch_issue_body(issue_ref, api_key)

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
    body_lookup = _body_network_lookup(api_key) if api_key else None

    tool_input = payload.get("tool_input")
    is_update = isinstance(tool_input, dict) and _is_present(tool_input.get("id"))

    findings = check_save_issue(tool_input, policy, body_lookup=body_lookup)
    if findings:
        # Nothing is written to stderr on this path. The shell wrapper captures
        # stdout and stderr TOGETHER and then reads `.reason` out of the result
        # with jq, so a diagnostic line here would not be a diagnostic -- it
        # would corrupt the refusal into the wrapper's generic fallback text and
        # throw away every finding this function just computed.
        return _block(render_block_reason(findings, policy, update=is_update))
    if body_lookup is None:
        sys.stderr.write(
            "[ticket_creation_guard] no LINEAR_API_KEY in the environment or "
            "~/.omnibase/.env, so rule 9 (an update may not rewrite an "
            "acceptance criterion) was not evaluated for this call. Rules 1-7 "
            "ran normally.\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
