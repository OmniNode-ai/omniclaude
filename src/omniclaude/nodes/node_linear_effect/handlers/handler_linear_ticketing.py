# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Linear API backend for ``ProtocolLinearTicketing`` (OMN-17427).

Lab lanes carry no Linear MCP, so a ticket whose definition of done was proven on
a lane sat open: nothing there could tick an acceptance box or flip Done. This is
the lane's write path. The key comes from the environment the secret store fills
(``LINEAR_API_KEY``), and every write that moves a ticket toward done goes
through the Done-flip guard's own decision first, with that decision's readers
swapped for ``LaneRepoEvidence`` because a lane cannot call ``gh``.

* ``ticket_tick_acceptance`` ticks the labelled boxes and, on request, sets Done in
  the same mutation. The guard judges the description and state the call WOULD
  leave behind; a refusal writes nothing. The guard's bar is whole-ticket (every
  labelled criterion bound by a contract with a green check), so a ticket with a
  criterion no check covers ticks nothing and the result names that criterion.
* ``ticket_update_status`` and ``ticket_add_comment`` take the same gates the MCP
  seam takes (Done evidence; the actor line).
* ``ticket_create`` is refused: a create goes through the ticket-creation gate.

A criterion's own line is never rewritten beyond ``[ ]`` to ``[x]``: its hash pins
a contract binding.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import re
from collections.abc import Callable
from functools import partial

from omniclaude.nodes.node_linear_effect.handlers.handler_lane_repo_evidence import (
    LaneRepoEvidence,
    hook_module,
)
from omniclaude.nodes.node_linear_effect.models import (
    LinearOperation,
    LinearResultStatus,
    ModelLinearEndpoint,
    ModelLinearRequest,
    ModelLinearResult,
)

_KEY_ENV = "LINEAR_API_KEY"
_DONE_STATE = "Done"
_UNCHECKED_LABELLED_BOX_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s*)\[ \](\s+)(.*)$")
_UNBOUND_LABEL_RE = re.compile(
    r"\b((?:AC|DOD)\d+): no dod_evidence item", re.IGNORECASE
)

_ISSUE_QUERY = """
query($id: String!) {
  issue(id: $id) {
    id identifier url description
    state { id name type }
    team { states { nodes { id name type } } }
  }
}
"""
_UPDATE_MUTATION = """
mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue { identifier description state { name } }
  }
}
"""
_COMMENT_MUTATION = """
mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) { success comment { id } }
}
"""


def _obj(value: object) -> dict[str, object]:
    """``value`` when it is a JSON object, else an empty one."""
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


#: ``(query, variables)`` -> the GraphQL ``data`` object. Raises ``LinearApiError``.
Transport = Callable[[str, "dict[str, object]"], "dict[str, object]"]
#: A guard call (``{"tool_name", "tool_input"}``) -> ``(allowed, reason)``.
GuardDecision = Callable[["dict[str, object]"], "tuple[bool, str]"]


class LinearApiError(RuntimeError):
    """The Linear API could not answer; the message never carries the key."""


def http_transport(
    endpoint: ModelLinearEndpoint,
) -> Transport:
    """A transport that POSTs GraphQL documents to ``endpoint`` with the env key."""
    return partial(_post_graphql, endpoint)


def _post_graphql(
    endpoint: ModelLinearEndpoint, query: str, variables: dict[str, object]
) -> dict[str, object]:
    """POST one GraphQL document with the key from the environment."""
    key = os.environ.get(_KEY_ENV, "")
    if not key:
        raise LinearApiError(f"no Linear credential: {_KEY_ENV} is not set")
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    connection = http.client.HTTPSConnection(
        endpoint.host, timeout=endpoint.timeout_seconds
    )
    try:
        connection.request(
            "POST",
            endpoint.path,
            body=payload,
            headers={"Content-Type": "application/json", "Authorization": key},
        )
        body = json.load(connection.getresponse())
    except (http.client.HTTPException, TimeoutError, ValueError, OSError) as error:
        raise LinearApiError(f"Linear call failed ({type(error).__name__})") from error
    finally:
        connection.close()
    if not isinstance(body, dict) or body.get("errors"):
        raise LinearApiError("Linear returned a GraphQL error")
    data = body.get("data")
    if not isinstance(data, dict):
        raise LinearApiError("Linear returned no data")
    return data


def tick_labelled_boxes(
    description: str,
    canonical_label: Callable[[str], str],
    leave_open: frozenset[str] = frozenset(),
) -> str:
    """``description`` with every unchecked box whose criterion carries an AC/DoD label ticked.

    A label in ``leave_open`` keeps its box unchecked.

    Only the ``[ ]`` token changes; the criterion text on the line is untouched.
    """
    lines = description.split("\n")
    for index, line in enumerate(lines):
        match = _UNCHECKED_LABELLED_BOX_RE.match(line)
        label = canonical_label(match.group(3)) if match else ""
        if match and label and label not in leave_open:
            lines[index] = f"{match.group(1)}[x]{match.group(2)}{match.group(3)}"
    return "\n".join(lines)


def unlabelled_unchecked_boxes(
    description: str, canonical_label: Callable[[str], str]
) -> list[str]:
    """Unchecked boxes with no AC/DoD label: nothing can bind them, so they stay open."""
    found: list[str] = []
    for line in description.split("\n"):
        match = _UNCHECKED_LABELLED_BOX_RE.match(line)
        if match and not canonical_label(match.group(3)):
            found.append(match.group(3).strip()[:120])
    return found


class HandlerLinearApi:
    """The ``linear_api`` backend. Async methods, blocking work off the loop."""

    handler_key = "linear_api"

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        endpoint: ModelLinearEndpoint | None = None,
        guard_decision: GuardDecision | None = None,
        evidence: LaneRepoEvidence | None = None,
    ) -> None:
        self._transport = (
            transport
            if transport is not None
            else http_transport(endpoint or ModelLinearEndpoint.from_contract())
        )
        self._guard_decision = guard_decision
        self._evidence = evidence
        self._evidence_lib = hook_module("no_pr_bound_evidence")

    # -- guard ------------------------------------------------------------

    def _decide(
        self, call: dict[str, object], live_description: str | None = None
    ) -> tuple[bool, str]:
        """The guard's decision on ``call``.

        ``live_description`` stands in for the ticket's stored text, so a dry run can
        judge Done against the description its tick WOULD have left behind.
        """
        if self._guard_decision is not None:
            return self._guard_decision(call)
        guard = hook_module("done_flip_guard")
        evidence = self._evidence or LaneRepoEvidence()
        probe = partial(
            self._evidence_lib.evaluate_repo_evidence,
            read_contract=evidence.read_contract,
            read_check_runs=evidence.read_check_runs,
        )
        decision = guard.decide(
            call,
            repo_evidence_probe=probe,
            pr_fetcher=evidence.fetch_pr_status,
            linear_fetcher=partial(self._fetch_for_guard, live_description),
        )
        return bool(decision.allowed), str(decision.reason)

    def _fetch_for_guard(
        self, live_description: str | None, ticket_id: str
    ) -> dict[str, object] | None:
        done = hook_module("linear_done_verify")
        fetched: dict[str, object] | None = done._fetch_linear_issue(ticket_id)
        if fetched and live_description is not None:
            fetched = {**fetched, "description": live_description}
        return fetched

    # -- reads and result shaping ------------------------------------------

    def _issue(self, ticket_id: str) -> dict[str, object]:
        issue = self._transport(_ISSUE_QUERY, {"id": ticket_id}).get("issue")
        if not isinstance(issue, dict) or issue.get("identifier") != ticket_id:
            raise LinearApiError(f"Linear holds no such ticket: {ticket_id}")
        return issue

    @staticmethod
    def _result(
        request: ModelLinearRequest,
        status: LinearResultStatus,
        *,
        ticket_url: str | None = None,
        ticket_state: str | None = None,
        output: str | None = None,
        error: str | None = None,
        ticked_labels: tuple[str, ...] = (),
        uncovered_labels: tuple[str, ...] = (),
    ) -> ModelLinearResult:
        return ModelLinearResult(
            operation=request.operation.value,
            status=status,
            ticket_id=request.ticket_id,
            ticket_url=ticket_url,
            ticket_state=ticket_state,
            output=output,
            error=error,
            ticked_labels=ticked_labels,
            uncovered_labels=uncovered_labels,
            correlation_id=request.correlation_id,
        )

    def _failed(self, request: ModelLinearRequest, error: str) -> ModelLinearResult:
        return self._result(request, LinearResultStatus.FAILED, error=error)

    @staticmethod
    def _state_id(issue: dict[str, object], name: str) -> str | None:
        nodes = _obj(_obj(issue.get("team")).get("states")).get("nodes")
        for state in nodes if isinstance(nodes, list) else []:
            if str(state.get("name", "")).casefold() == name.casefold():
                return str(state["id"])
        return None

    # -- ProtocolLinearTicketing -------------------------------------------

    async def ticket_get(self, request: ModelLinearRequest) -> ModelLinearResult:
        if not request.ticket_id:
            return self._failed(request, "ticket_id is required")
        try:
            issue = await asyncio.to_thread(self._issue, request.ticket_id)
        except LinearApiError as error:
            return self._failed(request, str(error))
        return self._result(
            request,
            LinearResultStatus.SUCCESS,
            ticket_url=_text(issue.get("url")),
            ticket_state=_text(_obj(issue.get("state")).get("name")),
            output=json.dumps(
                {
                    "identifier": issue.get("identifier"),
                    "state": _text(_obj(issue.get("state")).get("name")),
                    "description": issue.get("description") or "",
                }
            ),
        )

    async def ticket_update_status(
        self, request: ModelLinearRequest
    ) -> ModelLinearResult:
        if not request.ticket_id or not request.status:
            return self._failed(request, "ticket_id and status are required")
        return await asyncio.to_thread(self._update_status, request)

    def _update_status(self, request: ModelLinearRequest) -> ModelLinearResult:
        assert request.ticket_id and request.status
        allowed, reason = self._decide(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": request.ticket_id, "state": request.status},
            }
        )
        if not allowed:
            return self._failed(request, f"refused by the Done-flip guard: {reason}")
        try:
            issue = self._issue(request.ticket_id)
            state_id = self._state_id(issue, request.status)
            if state_id is None:
                return self._failed(
                    request, f"no workflow state named {request.status}"
                )
            self._transport(
                _UPDATE_MUTATION,
                {"id": request.ticket_id, "input": {"stateId": state_id}},
            )
        except LinearApiError as error:
            return self._failed(request, str(error))
        return self._result(
            request, LinearResultStatus.SUCCESS, ticket_state=request.status
        )

    async def ticket_add_comment(
        self, request: ModelLinearRequest
    ) -> ModelLinearResult:
        if not request.ticket_id or not request.comment_body:
            return self._failed(request, "ticket_id and comment_body are required")
        actor = hook_module("actor_line_guard")
        if not actor.has_actor_line(request.comment_body):
            return self._failed(
                request,
                "refused: the comment must open with `actor: <lane or agent> (<model>)`",
            )
        try:
            issue = await asyncio.to_thread(self._issue, request.ticket_id)
            await asyncio.to_thread(
                self._transport,
                _COMMENT_MUTATION,
                {"input": {"issueId": issue["id"], "body": request.comment_body}},
            )
        except LinearApiError as error:
            return self._failed(request, str(error))
        return self._result(request, LinearResultStatus.SUCCESS)

    async def ticket_create(self, request: ModelLinearRequest) -> ModelLinearResult:
        return self._failed(
            request,
            "refused: a ticket is created through the ticket-creation gate "
            "(omni:create-ticket), never by this backend",
        )

    async def ticket_tick_acceptance(
        self, request: ModelLinearRequest
    ) -> ModelLinearResult:
        if not request.ticket_id:
            return self._failed(request, "ticket_id is required")
        return await asyncio.to_thread(self._tick, request)

    def _tick(self, request: ModelLinearRequest) -> ModelLinearResult:
        assert request.ticket_id
        evidence = self._evidence_lib
        try:
            issue = self._issue(request.ticket_id)
        except LinearApiError as error:
            return self._failed(request, str(error))
        before = str(issue.get("description") or "")
        state_name = _text(_obj(issue.get("state")).get("name"))
        held = frozenset(
            evidence.canonical_ac_label(label) for label in request.leave_open
        )
        after = tick_labelled_boxes(before, evidence.canonical_ac_label, held)
        ticked = tuple(
            sorted(
                label
                for m in map(_UNCHECKED_LABELLED_BOX_RE.match, before.split("\n"))
                if m
                for label in (evidence.canonical_ac_label(m.group(3)),)
                if label and label not in held
            )
        )
        notes: list[str] = []
        if after != before:
            allowed, reason = self._decide(
                {
                    "tool_name": "mcp__linear-server__save_issue",
                    "tool_input": {"id": request.ticket_id, "description": after},
                }
            )
            if not allowed:
                return self._result(
                    request,
                    LinearResultStatus.FAILED,
                    error=f"refused by the Done-flip guard: {reason}",
                    uncovered_labels=tuple(
                        sorted(set(_UNBOUND_LABEL_RE.findall(reason)))
                    ),
                    ticket_state=state_name,
                )
            if request.apply:
                try:
                    self._transport(
                        _UPDATE_MUTATION,
                        {"id": request.ticket_id, "input": {"description": after}},
                    )
                except LinearApiError as error:
                    return self._failed(request, str(error))
                notes.append(f"ticked {', '.join(ticked)}")
            else:
                notes.append(f"dry run: the guard admits ticking {', '.join(ticked)}")
        else:
            notes.append("no unchecked labelled box to tick")
        if request.set_done:
            state_name = self._set_done(request, issue, after, notes, state_name)
        return self._result(
            request,
            LinearResultStatus.SUCCESS,
            output="; ".join(notes),
            ticked_labels=ticked,
            ticket_state=state_name,
        )

    def _set_done(
        self,
        request: ModelLinearRequest,
        issue: dict[str, object],
        description: str,
        notes: list[str],
        state_name: str | None,
    ) -> str | None:
        """Set Done as a second edit: the guard reads the live description for open boxes."""
        assert request.ticket_id
        if request.leave_open:
            notes.append(f"Done withheld: {', '.join(request.leave_open)} left open")
            return state_name
        left = unlabelled_unchecked_boxes(
            description, self._evidence_lib.canonical_ac_label
        )
        if left:
            notes.append(
                f"Done withheld: {len(left)} unchecked box(es) carry no AC label"
            )
            return state_name
        allowed, reason = self._decide(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": request.ticket_id, "state": _DONE_STATE},
            },
            live_description=None if request.apply else description,
        )
        if not allowed:
            notes.append(f"Done refused by the guard: {reason}")
            return state_name
        if not request.apply:
            notes.append("dry run: the guard admits Done")
            return state_name
        state_id = self._state_id(issue, _DONE_STATE)
        if state_id is None:
            notes.append("Done withheld: no workflow state named Done")
            return state_name
        try:
            self._transport(
                _UPDATE_MUTATION,
                {"id": request.ticket_id, "input": {"stateId": state_id}},
            )
        except LinearApiError as error:
            notes.append(f"Done not written: {error}")
            return state_name
        notes.append("set Done")
        return _DONE_STATE

    async def handle(self, request: ModelLinearRequest) -> ModelLinearResult:
        """Route a request to the operation it names."""
        routes = {
            LinearOperation.TICKET_GET: self.ticket_get,
            LinearOperation.TICKET_UPDATE_STATUS: self.ticket_update_status,
            LinearOperation.TICKET_ADD_COMMENT: self.ticket_add_comment,
            LinearOperation.TICKET_CREATE: self.ticket_create,
            LinearOperation.TICKET_TICK_ACCEPTANCE: self.ticket_tick_acceptance,
        }
        return await routes[request.operation](request)


__all__ = [
    "HandlerLinearApi",
    "LinearApiError",
    "Transport",
    "http_transport",
    "tick_labelled_boxes",
    "unlabelled_unchecked_boxes",
]
