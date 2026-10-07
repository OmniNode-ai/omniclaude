# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Typed command and verdict for Git admission."""

from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ModelGitAdmissionRequest(BaseModel):
    raw_payload: str
    policy_path: Path | None = None
    clone_sync_engine: str = "canonical_clone_sync.py"
    correlation_id: UUID = Field(default_factory=uuid4)


class ModelGitAdmissionResult(BaseModel):
    blocked: bool
    reason: str = ""
    notes: tuple[str, ...] = ()
    correlation_id: UUID
