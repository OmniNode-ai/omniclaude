# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Refusal rendering and lane classification used by Git admission."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from omniclaude.nodes.node_git_effect.models.model_git_refusal_advice_request import (
    ModelGitRefusalAdviceRequest,
)
from omniclaude.nodes.node_git_effect.protocols.protocol_git_lane_policy import (
    ProtocolGitLanePolicy,
)


class ProtocolGitRefusalAdvice(Protocol):
    def handle(self, request: ModelGitRefusalAdviceRequest) -> str: ...

    def lane_name(
        self, policy: ProtocolGitLanePolicy, environ: Mapping[str, str]
    ) -> str: ...

    def is_lane_path(
        self,
        path: Path,
        policy: ProtocolGitLanePolicy,
        worktree_roots: tuple[Path, ...],
    ) -> bool: ...

    def caller_is_lane(
        self,
        policy: ProtocolGitLanePolicy,
        payload_cwd: Path,
        worktree_roots: tuple[Path, ...],
        environ: Mapping[str, str],
    ) -> bool: ...
