# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shared-clone refusal advice and lane classification for the Git node."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from omniclaude.nodes.node_git_effect.models.model_git_refusal_advice_request import (
    ModelGitRefusalAdviceRequest,
)
from omniclaude.nodes.node_git_effect.protocols.protocol_git_lane_policy import (
    ProtocolGitLanePolicy,
)


class HandlerGitRefusalAdvice:
    """Keep shared-clone advice consistent with the lane fetch arm (OMN-19998)."""

    @staticmethod
    def handle(request: ModelGitRefusalAdviceRequest) -> str:
        """Render advice matching the caller's lane fetch policy."""
        if request.lane:
            ungated = (
                "Reads are never gated, and neither is `git merge --ff-only`. "
                "From a lane, `git fetch` and `git pull` against GitHub are "
                f"refused ({request.fetch_ticket}): origin refs here are kept "
                "current by canonical-clone-sync, so use origin/<branch> as is, "
                f"or run `python3 {request.clone_sync_engine} refresh "
                "<owner>/<repo> --wait`."
            )
        else:
            ungated = (
                "Reads are never gated, and neither is "
                "`git fetch`, `git merge --ff-only` or `git pull --ff-only`."
            )
        return (
            f"BLOCKED: `git {request.subcommand}` in {request.git_root}, the shared "
            f"registry clone ({request.ticket}, {request.rule}). Many "
            "concurrent lanes work in this ONE tree, so a command that moves it "
            "takes their work with it: "
            f"{request.detail}. Use a sanctioned alternative instead -- "
            f"{request.safe_alternatives}. {ungated} To "
            f"disable this guard: onex hooks disable {request.gate_bit_name}"
        )

    @staticmethod
    def is_lane_path(
        path: Path, policy: ProtocolGitLanePolicy, worktree_roots: tuple[Path, ...]
    ) -> bool:
        texts = {str(path)}
        try:
            texts.add(str(path.resolve()))
        except OSError:
            pass
        for text in texts:
            probe = text.rstrip("/") + "/"
            if any(marker in probe for marker in policy.fetch_lane_path_markers):
                return True
            if any(
                probe.startswith(str(root).rstrip("/") + "/") for root in worktree_roots
            ):
                return True
        return False

    @staticmethod
    def lane_name(policy: ProtocolGitLanePolicy, environ: Mapping[str, str]) -> str:
        for name in policy.fetch_lane_envs:
            if environ.get(name):
                return environ[name]
        return ""

    @staticmethod
    def caller_is_lane(
        policy: ProtocolGitLanePolicy,
        payload_cwd: Path,
        worktree_roots: tuple[Path, ...],
        environ: Mapping[str, str],
    ) -> bool:
        """Whether the lane git-fetch arm would treat this caller as a lane."""
        if any(environ.get(k) == v for k, v in policy.fetch_allow_env):
            return False
        return bool(
            HandlerGitRefusalAdvice.lane_name(policy, environ)
        ) or HandlerGitRefusalAdvice.is_lane_path(payload_cwd, policy, worktree_roots)
