# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Linear GraphQL endpoint of NodeLinearEffect, declared by its contract (OMN-21791)."""

from __future__ import annotations

from pathlib import Path

from omnibase_core.utils.util_safe_yaml_loader import load_yaml_mapping_no_duplicates
from pydantic import BaseModel, ConfigDict, Field


class ModelLinearEndpoint(BaseModel):
    """Host, path and deadline of the Linear API; callers may inject an overlay value."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    host: str = Field(min_length=1)
    path: str = Field(pattern=r"^/")
    timeout_seconds: float = Field(gt=0)

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelLinearEndpoint:
        """Read the packaged contract's ``endpoint`` block; no code fallback duplicates it."""
        contract_path = (
            path if path is not None else Path(__file__).parents[1] / "contract.yaml"
        )
        contract = load_yaml_mapping_no_duplicates(
            contract_path.read_text(encoding="utf-8"), source=str(contract_path)
        )
        return cls.model_validate(contract["endpoint"])
