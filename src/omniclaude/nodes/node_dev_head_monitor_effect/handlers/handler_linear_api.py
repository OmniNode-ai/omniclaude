# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Linear GraphQL adapter of the dev-head monitor (OMN-18836)."""

from __future__ import annotations

import json

import httpx
import yaml

from omniclaude.nodes.node_dev_head_monitor_effect.models.model_dev_head_types import (
    DEFAULT_CONFIG_PATH,
    LINEAR_TIMEOUT_S,
)


class LinearApi:
    """:class:`LinearPort` over Linear's GraphQL API.

    :attr:`available` is False when no key is configured. That is a
    configuration fact, not an error, and the caller decides what it means —
    see the module docstring for why it is inert on a green head and red on a
    red one.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        try:
            contract = yaml.safe_load(
                (DEFAULT_CONFIG_PATH.parent / "contract.yaml").read_text()
            )
            endpoint = contract["metadata"]["integrations"]["linear"][
                "graphql_endpoint"
            ]
        except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
            raise RuntimeError("Linear integration contract is unreadable") from exc
        if not isinstance(endpoint, str) or not endpoint:
            raise RuntimeError("Linear integration contract carries no endpoint")
        self._endpoint = endpoint

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _query(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        if not self.available:
            raise RuntimeError("no LINEAR_API_KEY configured")
        try:
            response = httpx.post(
                self._endpoint,
                json={"query": query, "variables": variables},
                headers={"Authorization": self._api_key},
                timeout=LINEAR_TIMEOUT_S,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Linear request failed: {type(exc).__name__}") from None
        if not isinstance(payload, dict):
            raise RuntimeError("Linear returned a non-object response")
        if payload.get("errors"):
            raise RuntimeError(f"Linear returned errors: {payload['errors']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Linear response carries no data object")
        return data

    def find_issue(self, *, title: str) -> str | None:
        data = self._query(
            "\n            query($title: String!) {\n              issues(filter: { title: { eq: $title } }, first: 1, includeArchived: true) {\n                nodes { identifier }\n              }\n            }\n            ",
            {"title": title},
        )
        issues = data.get("issues")
        if not isinstance(issues, dict):
            raise RuntimeError("Linear search response carries no issues object")
        nodes = issues.get("nodes")
        if not isinstance(nodes, list):
            raise RuntimeError("Linear search response carries no nodes list")
        for node in nodes:
            if (
                not isinstance(node, dict)
                or not isinstance(node.get("identifier"), str)
                or not node["identifier"]
            ):
                raise RuntimeError("Linear search carries a malformed issue row")
            if isinstance(node, dict) and isinstance(node.get("identifier"), str):
                identifier = node["identifier"]
                assert isinstance(identifier, str)
                return identifier
        return None

    def create_issue(
        self, *, title: str, description: str, team_key: str, parent: str
    ) -> str:
        teams = self._query(
            "\n            query($key: String!) {\n              teams(filter: { key: { eq: $key } }, first: 1) { nodes { id } }\n            }\n            ",
            {"key": team_key},
        )
        team_id = _first_id(teams.get("teams"), what=f"team {team_key!r}")
        parent_data = self._query(
            "query($id: String!) { issue(id: $id) { id } }", {"id": parent}
        )
        issue = parent_data.get("issue")
        if not isinstance(issue, dict) or not isinstance(issue.get("id"), str):
            raise RuntimeError(f"Linear parent issue {parent!r} did not resolve")
        parent_id = issue["id"]
        created = self._query(
            "\n            mutation($input: IssueCreateInput!) {\n              issueCreate(input: $input) { success issue { identifier } }\n            }\n            ",
            {
                "input": {
                    "teamId": team_id,
                    "title": title,
                    "description": description,
                    "parentId": parent_id,
                }
            },
        )
        result = created.get("issueCreate")
        if not isinstance(result, dict) or not result.get("success"):
            raise RuntimeError(f"Linear issueCreate did not succeed: {result!r}")
        issue_node = result.get("issue")
        if not isinstance(issue_node, dict) or not isinstance(
            issue_node.get("identifier"), str
        ):
            raise RuntimeError("Linear issueCreate returned no identifier")
        identifier = issue_node["identifier"]
        assert isinstance(identifier, str)
        if not identifier:
            raise RuntimeError("Linear issueCreate returned an empty identifier")
        return identifier


def _first_id(container: object, *, what: str) -> str:
    if not isinstance(container, dict):
        raise RuntimeError(f"Linear response for {what} is not an object")
    nodes = container.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise RuntimeError(f"Linear returned no {what}")
    node = nodes[0]
    if not isinstance(node, dict) or not isinstance(node.get("id"), str):
        raise RuntimeError(f"Linear returned no id for {what}")
    identifier = node["id"]
    assert isinstance(identifier, str)
    if not identifier:
        raise RuntimeError(f"Linear returned an empty id for {what}")
    return identifier
