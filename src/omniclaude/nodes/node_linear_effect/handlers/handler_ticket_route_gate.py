# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Route rows of the ticket-creation guard: raw creates and hand edits of a standard ticket (OMN-23769).

Two rows, both carried by the core ticket-creation contract
(``ticket_creation.validation.yaml``, OMN-23764) and mirrored from
``ticket_creation_policy.json``'s ``route_rows`` object:

* ``create_route`` -- with the route switch at ``refuse``, a create that did not
  come from the ticket node is refused, naming ``onex ticket create --draft``.
  The Mac hook is the raw route; the node passes ``--node``. The switch is read
  from the Mac's overlay (:func:`read_switch`); absent, the contract default
  (``allow``) applies, so agents can always create until it is flipped.
* ``contract_block_edit`` -- an update that changes a standard ticket's fenced
  contract block, or its title, is refused naming ``onex ticket sync``, whatever
  the switch says. A ticket is standard when its current description carries a
  contract block. The title row is the hook's own (``title_edit``): core compares
  blocks only, and a title is the one other field the ticket file also owns.

The vocabulary is policy data. ``tests/hooks/test_ticket_route_rows_match_core.py``
reads the core rows from the installed ``omnibase_core`` and compares them with the
policy's, so a changed row on one side turns the suite red.

The tracker reads this rule needs (the credential, one text field of one issue)
live here too, with the Linear API calls this node owns.

The ticket-creation guard (``plugins/onex/hooks/lib/ticket_creation_guard.py``, a
baselined file that only shrinks) loads this module by path and runs it under a
bare interpreter with no ``omniclaude`` package, so it imports the standard
library only. The decisions are pure functions of what they are handed; the
filesystem is touched only by :func:`read_switch` and :func:`resolve_api_key`.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol

#: Where a Mac overlay carries the create-route switch: one word, ``allow`` or ``refuse``.
SWITCH_ENV = "ONEX_TICKET_CREATE_ROUTE_SWITCH"
SWITCH_FILE = Path(".omnibase") / "ticket_create_route_switch"

ROUTE_TICKET = "OMN-23769"
#: The finding codes the route rows raise.
ROUTE_CODES = frozenset({"create_route", "contract_block_edit"})


class _Coded(Protocol):
    """A finding: only its code is read here."""

    code: str


BodyLookup = Callable[[str], "str | None"]
TitleLookup = Callable[[str], "str | None"]


class RouteRows(NamedTuple):
    """The ``route_rows`` object of the ticket-creation policy, validated."""

    create: Mapping[str, str]
    block: Mapping[str, str]
    title: Mapping[str, str]
    block_pattern: re.Pattern[str]


_CREATE_KEYS = (
    "node_route",
    "raw_route",
    "allow_value",
    "refuse_value",
    "switch_default",
    "node_command",
    "message",
    "fix",
)
_BLOCK_KEYS = ("block_pattern", "sync_command", "message", "fix")
_TITLE_KEYS = ("message", "fix")


def _row(
    raw: object, key: str, keys: tuple[str, ...], source: Path, error: type[Exception]
) -> Mapping[str, str]:
    row = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(row, dict):
        raise error(f"{source}: 'route_rows.{key}' must be an object, got {row!r}")
    for name in keys:
        value = row.get(name)
        if not isinstance(value, str) or not value:
            raise error(
                f"{source}: 'route_rows.{key}.{name}' must be a non-empty string, got {value!r}"
            )
    return row


def load_rows(raw: object, source: Path, error: type[Exception]) -> RouteRows:
    """Validate the ``route_rows`` object, or raise ``error``."""
    create = _row(raw, "create_route", _CREATE_KEYS, source, error)
    block = _row(raw, "contract_block_edit", _BLOCK_KEYS, source, error)
    title = _row(raw, "title_edit", _TITLE_KEYS, source, error)
    try:
        pattern = re.compile(block["block_pattern"])
    except re.error as exc:
        raise error(
            f"{source}: 'route_rows.contract_block_edit.block_pattern' is not a regex ({exc})"
        ) from exc
    return RouteRows(create, block, title, pattern)


def read_switch(env: Mapping[str, str], home: Path) -> str | None:
    """The overlay's switch word, from the environment first, then the Mac's overlay file; ``None`` when unset."""
    word = env.get(SWITCH_ENV, "").strip()
    if not word:
        try:
            word = (home / SWITCH_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return word.lower() or None


def _finding(code: str, field: str, reason: str, fix: str) -> dict[str, str]:
    return {"code": code, "field": field, "reason": reason, "fix": fix}


def _create_dicts(
    rows: RouteRows, route: str | None, switch: str | None
) -> list[dict[str, str]]:
    """``create_route``: a raw create is refused with the switch at ``refuse``; an unknown switch is refused too."""
    row = rows.create
    if switch is not None and switch not in {row["allow_value"], row["refuse_value"]}:
        return [
            _finding(
                "unevaluable",
                "route_switch",
                f"the route switch reads {switch!r}, which is neither '{row['allow_value']}' nor '{row['refuse_value']}'",
                f"set the switch to '{row['allow_value']}' or '{row['refuse_value']}'",
            )
        ]
    effective = switch if switch is not None else row["switch_default"]
    if route != row["raw_route"] or effective != row["refuse_value"]:
        return []
    return [
        _finding(
            "create_route",
            "route",
            row["message"].format(switch=effective),
            row["fix"].format(command=row["node_command"]),
        )
    ]


def _blocks(rows: RouteRows, text: str) -> tuple[str, ...]:
    return tuple(
        m.group("body") for m in rows.block_pattern.finditer(text.replace("\r\n", "\n"))
    )


def edit_findings(
    rows: RouteRows,
    tool_input: Mapping[str, object],
    issue_ref: str,
    route: str | None,
    body_lookup: BodyLookup | None,
    title_lookup: TitleLookup | None,
    proposed_body: str | None,
) -> list[dict[str, str]]:
    """``contract_block_edit`` for an update: the switch plays no part.

    ``proposed_body`` is the description the update would write (patch applied),
    ``None`` when it writes none or the patch cannot be resolved (rule 9 refuses
    that on its own). A caller that is the node is never refused. With no read of
    the current body (no tracker key) the rule does not run, as rule 9 does not.
    """
    if route == rows.create["node_route"] or body_lookup is None:
        return []
    new_title = tool_input.get("title")
    if proposed_body is None and not isinstance(new_title, str):
        return []
    current = body_lookup(issue_ref)
    if current is None and proposed_body is not None:
        return []  # rule 9 refuses an update whose current body cannot be read
    if current is None:
        return [
            _finding(
                "contract_block_edit",
                "description",
                f"the current body of {issue_ref} could not be read, so the guard cannot tell whether this update changes a standard ticket's contract block or title",
                "retry the update; if the tracker stays unreachable, make the edit once the read works rather than blind",
            )
        ]
    before = _blocks(rows, current)
    command = rows.block["sync_command"]
    out: list[dict[str, str]] = []
    if proposed_body is not None:
        after = _blocks(rows, proposed_body)
        if before != after:
            out.append(
                _finding(
                    "contract_block_edit",
                    "description",
                    rows.block["message"].format(before=len(before), after=len(after)),
                    rows.block["fix"].format(command=command),
                )
            )
    if isinstance(new_title, str) and before and title_lookup is not None:
        current_title = title_lookup(issue_ref)
        if current_title is None or new_title != current_title:
            out.append(
                _finding(
                    "contract_block_edit",
                    "title",
                    rows.title["message"]
                    if current_title is not None
                    else f"the current title of {issue_ref} could not be read, so the guard cannot tell whether this update changes a standard ticket's title",
                    rows.title["fix"].format(command=command),
                )
            )
    return out


def _update_dicts(
    rows: RouteRows,
    tool_input: Mapping[str, object],
    route: str | None,
    body_lookup: BodyLookup | None,
    title_lookup: TitleLookup | None,
    apply_patch: Callable[[str, object], str],
    error: type[ValueError],
) -> list[dict[str, str]]:
    """The description an update writes (patch applied), judged by :func:`edit_findings`."""
    ref = str(tool_input["id"])
    proposed = tool_input.get("description")
    if "patch" in tool_input:
        current = body_lookup(ref) if body_lookup else None
        try:
            proposed = (
                None if current is None else apply_patch(current, tool_input["patch"])
            )
        except error:
            proposed = None
    return edit_findings(
        rows,
        tool_input,
        ref,
        route,
        body_lookup,
        title_lookup,
        proposed if isinstance(proposed, str) else None,
    )


def create_findings(
    rows: RouteRows, route: str | None, switch: str | None, make: Callable[..., object]
) -> list[Any]:
    """:func:`_create_dicts` as ``make`` findings (the guard's own ``Finding``)."""
    return [make(**f) for f in _create_dicts(rows, route, switch)]


def route_update_findings(
    rows: RouteRows,
    tool_input: Mapping[str, object],
    route: str | None,
    body_lookup: BodyLookup | None,
    title_lookup: TitleLookup | None,
    make: Callable[..., object],
    apply_patch: Callable[[str, object], str],
    error: type[ValueError],
) -> list[Any]:
    """:func:`_update_dicts` as ``make`` findings."""
    found = _update_dicts(
        rows, tool_input, route, body_lookup, title_lookup, apply_patch, error
    )
    return [make(**f) for f in found]


def preamble(
    findings: Sequence[_Coded], update: bool, ticket: str, criterion_ticket: str
) -> list[str]:
    """The opening lines of one refusal: a route refusal, a criterion rewrite or an unbound create."""
    if findings and all(f.code in ROUTE_CODES for f in findings):
        return [
            f"BLOCKED: this Linear issue {'UPDATE' if update else 'CREATE'} "
            f"was built by hand ({ROUTE_TICKET}).",
            "",
            "Standard tickets are written by the ticket node, which keeps the "
            "ticket and its contract file together; a hand edit cannot.",
            "",
        ]
    if update:
        return [
            f"BLOCKED: this Linear issue UPDATE rewrites an acceptance "
            f"criterion ({criterion_ticket}).",
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
    return [
        f"BLOCKED: this Linear issue CREATE is not bound to a commitment ({ticket}).",
        "",
        (
            "Measured 2026-08-22..2026-09-04: 1553 tickets created in 14 days "
            "against ~35/day closed; 779 never left Backlog and 398 were never "
            "touched again. This guard refuses the creates that produce that."
        ),
        "",
    ]


def resolve_api_key(env: Mapping[str, str], home: Path) -> str:
    """The tracker read credential, from the environment or ``~/.omnibase/.env``; ``""`` when neither has one.

    The value is never written anywhere: not to stdout, not to stderr, not to the
    refusal text.
    """
    key = env.get("LINEAR_API_KEY", "").strip()
    if key:
        return key
    try:
        lines = (home / ".omnibase" / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("LINEAR_API_KEY="):
            return stripped.partition("=")[2].strip().strip("'\"")
    return ""


def fetch_issue_field(
    url: str, timeout: float, issue_ref: str, api_key: str, query: str, field: str
) -> str | None:
    """One text field of one issue, or ``None`` when it cannot be read.

    Every failure collapses to ``None`` on purpose: a transport error, a non-200,
    a GraphQL error body, an unknown issue and an unparseable response are all
    "the tracker did not tell us", and the caller refuses on that uniformly. An
    issue that exists with a genuinely empty field returns ``""``, which is a
    value and not an unknown.
    """
    target = urllib.parse.urlsplit(url)
    body = json.dumps({"query": query, "variables": {"id": issue_ref}})
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    try:
        connection = http.client.HTTPSConnection(target.netloc, timeout=timeout)
        try:
            connection.request("POST", target.path or "/", body, headers)
            response = connection.getresponse()
            if response.status != 200:
                return None
            raw = response.read()
        finally:
            connection.close()
    except (http.client.HTTPException, OSError):
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
    value = issue.get(field)
    if value is None:
        return ""
    return value if isinstance(value, str) else None
