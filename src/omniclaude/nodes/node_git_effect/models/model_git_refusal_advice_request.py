# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Inputs for the Git node's shared-clone refusal renderer."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ModelGitRefusalAdviceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    subcommand: str
    git_root: Path
    detail: str
    ticket: str
    rule: str
    safe_alternatives: str
    fetch_ticket: str
    clone_sync_engine: str
    gate_bit_name: str
    lane: bool = False
