# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Facts for the runner-placement snapshot policy (OMN-19998).

Standard-library models keep the exported hook usable with only PyYAML installed.
Environment values and snapshot contents never enter this policy request.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRunnerPlacementSnapshotRequest:
    """Whether a snapshot is supplied and where the placement gate is running."""

    snapshot_supplied: bool
    github_actions: bool
    lane_markers: tuple[str, ...]
