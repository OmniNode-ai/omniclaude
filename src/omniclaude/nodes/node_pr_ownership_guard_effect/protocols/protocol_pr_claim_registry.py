# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The claim registry the ownership gate reads and writes (OMN-20685)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ProtocolPrClaimRegistry(Protocol):
    """What the gate needs of the registry that holds the lane claims.

    Today that is the plugin hook library's ``pr_claim_registry.ClaimRegistry``; the
    omnimarket claim-registry node replaces it when it is released.
    """

    @property
    def claims_dir(self) -> Path:
        """The directory holding one claim file per target."""
        ...

    def acquire(
        self,
        pr_key: str,
        run_id: str,
        action: str,
        lane_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Record a claim; False when a peer already holds an active one."""
        ...
