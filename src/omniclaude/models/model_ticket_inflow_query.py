# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Linear GraphQL records consumed by the measured-closure budget publisher."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class ModelInflowEquality(TypedDict):
    """An exact Linear field match."""

    eq: str


class ModelInflowTeamFilter(TypedDict):
    """The team owning the measured populations."""

    id: ModelInflowEquality


class ModelInflowStateFilter(TypedDict):
    """Only governed completions fund admissions."""

    type: ModelInflowEquality


class ModelInflowTimeFilter(TypedDict):
    """A shared half-open measurement interval."""

    gte: str
    lt: str


class ModelInflowFilter(TypedDict):
    """Created or completed issue population in one team."""

    team: ModelInflowTeamFilter
    createdAt: NotRequired[ModelInflowTimeFilter]
    completedAt: NotRequired[ModelInflowTimeFilter]
    state: NotRequired[ModelInflowStateFilter]


class ModelInflowVariables(TypedDict):
    """The population filter and cursor sent to the injected reader."""

    filter: ModelInflowFilter
    after: str | None


class ModelInflowIssueState(TypedDict):
    """Linear workflow state category."""

    type: str


class ModelInflowLabel(TypedDict):
    """A label used to identify lane-created issues."""

    name: str


class ModelInflowLabels(TypedDict):
    """Issue labels returned by Linear."""

    nodes: list[ModelInflowLabel]


class ModelInflowIssue(TypedDict):
    """The fields used to count and deduplicate a Linear issue."""

    id: str
    createdAt: str
    completedAt: str | None
    state: ModelInflowIssueState
    labels: ModelInflowLabels


class ModelInflowPageInfo(TypedDict):
    """Proof that an enumeration exhausted or advanced its cursor."""

    hasNextPage: bool
    endCursor: str | None


class ModelInflowConnection(TypedDict):
    """One page of the measured issue population."""

    nodes: list[ModelInflowIssue]
    pageInfo: ModelInflowPageInfo


class ModelInflowData(TypedDict):
    """GraphQL query data."""

    issues: ModelInflowConnection


class ModelInflowError(TypedDict):
    """A GraphQL error makes the measurement unusable."""

    message: str


class ModelInflowResponse(TypedDict):
    """The injected reader returns data or GraphQL errors."""

    data: NotRequired[ModelInflowData]
    errors: NotRequired[list[ModelInflowError]]
