# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""How the guard tells the gh shim from the real gh binary (OMN-20916)."""

from __future__ import annotations

from typing import Protocol


class ProtocolGhShimProbe(Protocol):
    """Answers whether a resolved path is a copy of the gh user shim."""

    def is_gh_shim(self, path: str) -> bool:
        """True when path is a readable copy of scripts/user-bin/gh."""
        ...
