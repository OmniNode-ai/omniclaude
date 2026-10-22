# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""epic_team's repo manifest uses the 13 active repositories (OMN-21284).

The removed repository's keywords included agent, routing, route, router and
dispatch. A ticket containing those keywords must now reach an active repository.
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

sys.path.insert(0, str(REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"))

from epic_decomposer import decompose_epic


def _manifest_names() -> set[str]:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return {repo["name"] for repo in data["repos"]}


def test_the_manifest_has_13_active_repositories() -> None:
    assert len(_manifest_names()) == 13


def test_the_manifest_still_names_the_live_repositories() -> None:
    # Positive control: the check above is not satisfied by an emptied manifest.
    assert _manifest_names() >= {"omnibase_core", "omniclaude"}


def test_agent_routing_dispatch_ticket_is_assigned_to_the_active_web_repository() -> (
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
    assert assigned == {"omniweb"}
    assert result.cross_repo == []
    assert result.unmatched == []
    assert len(result.assignments) == 13
