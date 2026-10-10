# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tells the gh user shim from the real gh binary by the shim's own marker (OMN-20916)."""

from __future__ import annotations

#: The marker the shim carries in its first 512 bytes (scripts/user-bin/gh).
GH_SHIM_MARKER = b"ONEX_GH_USER_SHIM"


class FileGhShimProbe:
    """Reads a file's first 512 bytes for the shim's marker, as the shim itself does."""

    def is_gh_shim(self, path: str) -> bool:
        try:
            with open(path, "rb") as handle:
                return GH_SHIM_MARKER in handle.read(512)
        except OSError:
            return False


__all__ = ["GH_SHIM_MARKER", "FileGhShimProbe"]
