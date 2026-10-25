# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Budget publisher for the evidence sweep's injected Linear GraphQL reader.

No tracker write and no credentials are resolved here. The owning sweep supplies
its existing reader and calls ``publish_budget`` after a successful enumeration.
Both populations must reach hasNextPage=false before any file is replaced.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

from omniclaude.models.model_ticket_inflow_budget import (
    ModelTicketInflowBudget,
    timestamp,
)
from omniclaude.models.model_ticket_inflow_query import (
    ModelInflowFilter,
    ModelInflowIssue,
    ModelInflowResponse,
    ModelInflowTeamFilter,
    ModelInflowVariables,
)

Query = Callable[[str, ModelInflowVariables], ModelInflowResponse]
_QUERY = """query TicketInflow($filter: IssueFilter!, $after: String) {
  issues(filter: $filter, first: 100, after: $after) {
    nodes { id createdAt completedAt state { type } labels { nodes { name } } }
    pageInfo { hasNextPage endCursor }
  }
}"""


def _issues(query: Query, filters: ModelInflowFilter) -> Iterator[ModelInflowIssue]:
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        response = query(_QUERY, {"filter": filters, "after": cursor})
        if response.get("errors"):
            raise ValueError("Linear inflow enumeration returned GraphQL errors")
        connection = response["data"]["issues"]
        nodes, page = connection["nodes"], connection["pageInfo"]
        if not isinstance(nodes, list) or type(page["hasNextPage"]) is not bool:
            raise ValueError("Linear inflow enumeration has invalid pagination")
        for issue in nodes:
            if not isinstance(issue, dict) or not isinstance(issue.get("id"), str):
                raise ValueError("Linear inflow enumeration has invalid issue")
            yield issue
        if page["hasNextPage"] is False:
            return
        cursor = page["endCursor"]
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError("Linear inflow enumeration did not advance")
        seen.add(cursor)


def publish_budget(
    query: Query,
    path: Path,
    *,
    team_id: str,
    lane_label: str,
    window_days: int,
    now: datetime,
) -> ModelTicketInflowBudget:
    """Enumerate the team's trailing created and completed populations and publish.

    Completion filters on completedAt, never updatedAt. Canceled issues and old
    completions updated inside the window cannot fund admissions. IDs deduplicate
    rows across page boundaries. The half-open interval is shared by both reads.
    """
    if not team_id.strip() or not lane_label.strip():
        raise ValueError("inflow measurement requires a team and lane label")
    now = timestamp(now.isoformat())
    end = now.isoformat()
    start = (now - timedelta(days=window_days)).isoformat()
    team: ModelInflowTeamFilter = {"id": {"eq": team_id}}
    created: dict[str, ModelInflowIssue] = {}
    closed: set[str] = set()
    for issue in _issues(query, {"team": team, "createdAt": {"gte": start, "lt": end}}):
        if timestamp(start) <= timestamp(issue["createdAt"]) < now:
            created[issue["id"]] = issue
    for issue in _issues(
        query,
        {
            "team": team,
            "completedAt": {"gte": start, "lt": end},
            "state": {"type": {"eq": "completed"}},
        },
    ):
        completed = issue["completedAt"]
        if (
            issue["state"]["type"] == "completed"
            and completed is not None
            and timestamp(start) <= timestamp(completed) < now
        ):
            closed.add(issue["id"])
    lane_created = sum(
        any(label["name"] == lane_label for label in issue["labels"]["nodes"])
        for issue in created.values()
    )
    budget = ModelTicketInflowBudget.from_dict(
        {
            "created_count": len(created),
            "closed_count": len(closed),
            "lane_created_count": lane_created,
            "window": {"start": start, "end": end},
        }
    )
    budget.write(path)
    return budget
