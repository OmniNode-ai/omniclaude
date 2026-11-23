# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Ownership boundary for the package's native delegation installation."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModelNativeDelegationRequest(BaseModel):
    """Prepare plugin files or remove this profile's owned registrations."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: Literal[
        "prepare",
        "remove",
        "snapshot",
        "restore",
        "recover",
        "settings",
        "manifest",
        "classic-remove",
    ]
    install_root: Path
    claude_settings: Path
    python_bin: str
    # The one operand an installer run step needs: the run's snapshot folder
    # (restore, settings), "dry" (recover), the pre-install backup (manifest)
    # or "true" to keep the history helper (classic-remove).
    argument: str = ""


class ModelNativeDelegationResult(BaseModel):
    """Whether the installation uses the native delegation entry point."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    native: bool
    # What the installer reads back: a snapshot folder, a backup path or a
    # rollback message.
    output: str = ""
