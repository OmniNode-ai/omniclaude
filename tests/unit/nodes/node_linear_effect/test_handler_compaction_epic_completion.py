# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The epic completion evidence rejects partial and unreadable Linear reads."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_linear_effect.handlers import (
    handler_compaction_epic_completion as probe,
)

pytestmark = pytest.mark.unit


def _reply(state="Done", *, prefix="T0.", more=False):
    return {
        "data": {
            "issue": {
                "children": {
                    "nodes": [
                        {
                            "identifier": "OMN-21093",
                            "title": prefix + " Adapter",
                            "state": {"name": state},
                        }
                    ],
                    "pageInfo": {"hasNextPage": more},
                }
            }
        }
    }


def test_complete_track_passes_and_other_tracks_do_not_count():
    probe.validate_children(_reply(), "T0.")
    with pytest.raises(ValueError, match="no children"):
        probe.validate_children(_reply(prefix="TA."), "T0.")


@pytest.mark.parametrize("state", ["Backlog", "In Progress", "In Review", "Canceled"])
def test_incomplete_track_fails(state):
    with pytest.raises(ValueError, match="OMN-21093"):
        probe.validate_children(_reply(state), "T0.")


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"errors": [{"message": "unreadable"}]},
        _reply(more=True),
        {"data": {"issue": None}},
    ],
)
def test_incomplete_or_unreadable_response_never_passes(result):
    with pytest.raises((ValueError, KeyError, TypeError)):
        probe.validate_children(result, "T0.")


def test_missing_authorization_fails_without_opening_a_connection(monkeypatch, capsys):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    assert probe.main(["--epic", "OMN-21090", "--title-prefix", "T0."]) == 1
    assert "no Linear credential" in capsys.readouterr().err


@pytest.mark.parametrize(("state", "expected"), [("Done", 0), ("In Progress", 1)])
def test_cli_checks_the_returned_children(monkeypatch, capsys, state, expected):
    monkeypatch.setenv("LINEAR_API_KEY", "fixture-authorization")

    def opened(query, variables):
        assert variables == {"id": "OMN-21090"}
        assert "children(first: 100)" in query
        return _reply(state)["data"]

    assert (
        probe.main(["--epic", "OMN-21090", "--title-prefix", "T0."], transport=opened)
        == expected
    )
    output = capsys.readouterr()
    assert "fixture-authorization" not in output.out + output.err


def test_transport_failure_is_a_failed_check(capsys):
    def failed(query, variables):
        raise probe.LinearApiError("Linear returned a GraphQL error")

    assert (
        probe.main(["--epic", "OMN-21090", "--title-prefix", "T0."], transport=failed)
        == 1
    )
    assert "Linear returned a GraphQL error" in capsys.readouterr().err
