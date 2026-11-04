# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Policy vocabulary needed to classify a Git caller's lane context."""

from typing import Protocol


class ProtocolGitLanePolicy(Protocol):
    @property
    def fetch_allow_env(self) -> tuple[tuple[str, str], ...]: ...

    @property
    def fetch_lane_envs(self) -> tuple[str, ...]: ...

    @property
    def fetch_lane_path_markers(self) -> tuple[str, ...]: ...
