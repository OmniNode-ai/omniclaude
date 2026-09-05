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

A create is admitted only when all four hold:

1. ``parentId`` is present, **or** the description declares the issue an epic
   on a line of its own.
2. A project is named -- ``project`` on the MCP surface, ``projectId`` in the
   REST spelling; either satisfies it.
3. The description carries a binding line, on a line of its own::

       Gate: C3
       Gate: OMN-16729 AC-5
       Gate: live-gate defect: kb-doc-gate

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

Deliberately NOT built here
---------------------------
No duplicate detection, no per-lane quota, no rate limit. Those need state this
module does not have and would make a refusal depend on history rather than on
the call in front of it. This gate answers one question -- *is this ticket bound
to a commitment?* -- and answers it from the payload alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "Finding",
    "Policy",
    "PolicyError",
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

#: A binding line, anchored to the start of a line. Leading whitespace is
#: tolerated (a lane indenting inside a block quote is not the failure mode this
#: guards against); a list bullet is NOT, because a bullet is how a line ends up
#: inside a checklist that nothing binds.
_GATE_LINE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*Gate:[ \t]*(?P<binding>.*?)[ \t]*$", re.MULTILINE
)

_GATE_LINE_GRAMMAR: Final[str] = (
    "Gate: <C-id | OMN-<parent> AC-<n> | live-gate defect: <check name>>"
)

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
    epic_markers: tuple[str, ...]
    residual_title_terms: tuple[str, ...]
    in_progress_state_names: frozenset[str]


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
    return Policy(
        criterion_ids=frozenset(c.upper() for c in criterion_ids),
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

    Returns ``"criterion"``, ``"parent_ac"``, ``"live_gate_defect"``, or
    ``None`` when no line binds. A body may carry several ``Gate:`` lines (a
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
    for preferred in ("live_gate_defect", "parent_ac", "criterion"):
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


def check_save_issue(tool_input: Any, policy: Policy) -> list[Finding]:
    """Return every failing admission rule for one ``save_issue`` call.

    An empty list admits the call. Updates always return an empty list.
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
        criteria = ", ".join(sorted(policy.criterion_ids)) or "(none configured)"
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
                    f"'{_GATE_LINE_GRAMMAR}'. The configured criterion ids are "
                    f"{criteria}. A parent AC reference names an acceptance "
                    "criterion on the parent issue, e.g. 'Gate: OMN-16729 AC-5'. "
                    "A live-gate defect names the check that is broken, e.g. "
                    "'Gate: live-gate defect: kb-doc-gate'"
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

    findings = check_save_issue(payload.get("tool_input"), policy)
    if findings:
        return _block(render_block_reason(findings, policy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
