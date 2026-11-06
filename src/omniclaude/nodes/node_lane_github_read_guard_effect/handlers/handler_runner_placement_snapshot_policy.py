# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Select the placement gate's read source inside a lane (OMN-19998).

The exported hook calls the same typed handler as the node's payload routing.
This module uses only the standard library because the exported gate installs
PyYAML alone. It selects a source; the placement gate validates and judges it.
"""

from __future__ import annotations

import os
from pathlib import Path

from omniclaude.models.model_runner_placement_snapshot_decision import (
    ModelRunnerPlacementSnapshotDecision,
)
from omniclaude.models.model_runner_placement_snapshot_request import (
    ModelRunnerPlacementSnapshotRequest,
)

# Kept in step with the lane GitHub-read guard and the gh shim.
LANE_ENV_MARKERS: tuple[str, ...] = (
    "ONEX_LANE",
    "ONEX_LANE_ID",
    "ONEX_AGENT_NAME",
    "CLAUDE_AGENT_NAME",
    "CLAUDE_SUBAGENT_NAME",
    "CODEX_THREAD_ID",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_MANAGED_BY_NPM",
)
LANE_SKIPPED_LIVE = (
    "live read not attempted: this is a lane, whose GitHub reads are refused"
)
PUBLISHED_SNAPSHOT_RELPATH = Path(".omninode") / "prrp" / "variables-snapshot.json"


def handle(
    request: ModelRunnerPlacementSnapshotRequest,
) -> ModelRunnerPlacementSnapshotDecision:
    """Choose the snapshot only for a lane outside Actions with one supplied."""
    return ModelRunnerPlacementSnapshotDecision(
        snapshot_only=(
            request.snapshot_supplied
            and not request.github_actions
            and any(marker in LANE_ENV_MARKERS for marker in request.lane_markers)
        )
    )


def lane_reads_snapshot_only(snapshot: object | None) -> bool:
    """Adapt process facts to the node handler without carrying environment values."""
    return handle(
        ModelRunnerPlacementSnapshotRequest(
            snapshot_supplied=snapshot is not None,
            github_actions=os.environ.get("GITHUB_ACTIONS") == "true",
            lane_markers=tuple(
                name for name in LANE_ENV_MARKERS if os.environ.get(name)
            ),
        )
    ).snapshot_only


def published_snapshot_path() -> Path | None:
    """Find the publisher's host copy outside Actions, without validating its contents."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return None
    candidate = Path.home() / PUBLISHED_SNAPSHOT_RELPATH
    return candidate if candidate.is_file() else None
