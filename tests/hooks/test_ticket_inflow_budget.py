# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Measurement validation and exhaustive publication for OMN-18487."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from omniclaude.handlers.handler_ticket_inflow_sweep import publish_budget
from omniclaude.models.model_ticket_inflow_budget import ModelTicketInflowBudget
from omniclaude.models.model_ticket_inflow_query import (
    ModelInflowIssue,
    ModelInflowResponse,
    ModelInflowVariables,
)

pytestmark = pytest.mark.unit
_NOW = datetime(2026, 10, 25, 17, tzinfo=UTC)
_START = _NOW - timedelta(days=28)


def _record() -> dict[str, object]:
    return {
        "created_count": 10,
        "closed_count": 8,
        "lane_created_count": 4,
        "window": {"start": _START.isoformat(), "end": _NOW.isoformat()},
    }


def test_model_constructor_without_window_raises() -> None:
    raw = _record()
    del raw["window"]
    with pytest.raises(TypeError, match="window"):
        ModelTicketInflowBudget(**raw)


@pytest.mark.parametrize("key", list(_record()))
def test_model_refuses_any_absent_field(key: str) -> None:
    raw = _record()
    del raw[key]
    with pytest.raises(KeyError):
        ModelTicketInflowBudget.from_dict(raw)


@pytest.mark.parametrize("value", [-1, True, 1.5, "10", None])
def test_model_refuses_invalid_counts(value: object) -> None:
    raw = _record()
    raw["closed_count"] = value
    with pytest.raises(ValueError):
        ModelTicketInflowBudget.from_dict(raw)


@pytest.mark.parametrize(
    "window",
    [
        None,
        {},
        {"start": _START.isoformat()},
        {"start": _NOW.isoformat(), "end": _START.isoformat()},
        {"start": "2026-09-27", "end": "2026-10-25"},
    ],
)
def test_model_refuses_invalid_window(window: object) -> None:
    raw = {**_record(), "window": window}
    with pytest.raises((ValueError, TypeError)):
        ModelTicketInflowBudget.from_dict(raw)


def _issue(
    identifier: str,
    *,
    at: datetime = _NOW - timedelta(days=1),
    lane: bool = False,
    state: str = "completed",
) -> ModelInflowIssue:
    return {
        "id": identifier,
        "createdAt": at.isoformat(),
        "completedAt": at.isoformat(),
        "state": {"type": state},
        "labels": {"nodes": [{"name": "lane-created"}] if lane else []},
    }


def _page(
    nodes: list[ModelInflowIssue], more: bool = False, cursor: str | None = None
) -> ModelInflowResponse:
    return {
        "data": {
            "issues": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": more, "endCursor": cursor},
            }
        }
    }


def test_sweep_writes_budget_only_after_both_populations_exhaust_pages(
    tmp_path: Path,
) -> None:
    calls: list[ModelInflowVariables] = []
    pages = iter(
        [
            _page([_issue("a", lane=True)], True, "created-next"),
            _page([_issue("b"), _issue("a", lane=True)]),  # boundary duplicate
            _page([_issue("c")], True, "closed-next"),
            _page(
                [
                    _issue("d"),
                    _issue("c"),
                    _issue("old", at=_START - timedelta(days=1)),
                    _issue("canceled", state="canceled"),
                    _issue("future", at=_NOW),
                ]
            ),
        ]
    )
    path = tmp_path / "budget.json"

    def query(document: str, variables: ModelInflowVariables) -> ModelInflowResponse:
        assert not path.exists(), "no partial population may publish a budget"
        assert "pageInfo { hasNextPage endCursor }" in document
        calls.append(variables)
        return next(pages)

    budget = publish_budget(
        query, path, team_id="team", lane_label="lane-created", window_days=28, now=_NOW
    )
    assert json.loads(path.read_text()) == budget._asdict()
    assert (budget.created_count, budget.closed_count, budget.lane_created_count) == (
        2,
        2,
        1,
    )
    assert [call["after"] for call in calls] == [
        None,
        "created-next",
        None,
        "closed-next",
    ]
    assert calls[0]["filter"]["team"] == {"id": {"eq": "team"}}
    assert "completedAt" in calls[2]["filter"]
    assert "updatedAt" not in calls[2]["filter"]
    budget.validate_window(_NOW, 28, 21600)


@pytest.mark.parametrize(
    "failure", ["graphql", "repeated_cursor", "missing_page", "transport"]
)
def test_failed_enumeration_preserves_previous_measurement(
    failure: str, tmp_path: Path
) -> None:
    path = tmp_path / "budget.json"
    path.write_text("previous complete measurement")
    pages = iter([_page([_issue("a")]), _page([_issue("b")], True, "c")])

    def query(document: str, variables: ModelInflowVariables) -> ModelInflowResponse:
        try:
            return next(pages)
        except StopIteration:
            if failure == "transport":
                raise OSError("transport failure") from None
            if failure == "graphql":
                return {"errors": [{"message": "failed"}]}
            if failure == "missing_page":
                return cast("ModelInflowResponse", {"data": {"issues": {"nodes": []}}})
            return _page([], True, "c")

    with pytest.raises((ValueError, KeyError, OSError)):
        publish_budget(
            query,
            path,
            team_id="team",
            lane_label="lane-created",
            window_days=28,
            now=_NOW,
        )
    assert path.read_text() == "previous complete measurement"


@pytest.mark.parametrize(
    ("now", "days"),
    [(_NOW + timedelta(days=1), 28), (_NOW - timedelta(seconds=1), 28), (_NOW, 7)],
)
def test_budget_refuses_stale_future_or_wrong_window(now: datetime, days: int) -> None:
    with pytest.raises(ValueError):
        ModelTicketInflowBudget.from_dict(_record()).validate_window(now, days, 21600)
