# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Source selection for a runner-placement read (OMN-19998)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRunnerPlacementSnapshotDecision:
    """Snapshot-only reads still require the gate's freshness and coverage checks."""

    snapshot_only: bool
