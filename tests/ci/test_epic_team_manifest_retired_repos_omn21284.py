# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""epic_team's repo manifest names no retired repository (OMN-21284).

RULING 2026-10-18T05:25:04Z retired omniagent and omniarchon. While omniagent stayed in
``repo_manifest.yaml`` with the keywords agent, routing, route, router and dispatch, the
keyword scorer in ``epic_decomposer`` could assign an epic's ticket to it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    REPO_ROOT / "plugins" / "onex" / "skills" / "epic_team" / "repo_manifest.yaml"
)
RETIRED = frozenset({"omniagent", "omniarchon"})

sys.path.insert(0, str(REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"))

from epic_decomposer import decompose_epic


def _manifest_names() -> set[str]:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return {repo["name"] for repo in data["repos"]}


def test_the_manifest_names_no_retired_repository() -> None:
    assert _manifest_names().isdisjoint(RETIRED), sorted(_manifest_names() & RETIRED)


def test_the_manifest_still_names_the_live_repositories() -> None:
    # Positive control: the check above is not satisfied by an emptied manifest.
    assert _manifest_names() >= {"omnibase_core", "omniclaude"}


def test_agent_routing_dispatch_ticket_is_not_assigned_to_a_retired_repository() -> (
    None
):
    ticket = {
        "id": "T-1",
        "title": "Agent routing dispatch selector",
        "description": "agents route and router dispatch with a coordinator,"
        " orchestration and lifecycle, delegation and selection",
        "labels": [],
    }
    result = decompose_epic([ticket], str(MANIFEST))

    assigned = {repo for repo, ids in result.assignments.items() if "T-1" in ids}
    in_cross_repo = {repo for cr in result.cross_repo for repo in cr.repos}
    assert (assigned | in_cross_repo).isdisjoint(RETIRED)
    assert RETIRED.isdisjoint(result.assignments)
