# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Validated runtime policy for the transition selector, declared by its contract."""

from __future__ import annotations

from pathlib import Path

from omnibase_core.utils.util_safe_yaml_loader import load_yaml_mapping_no_duplicates
from pydantic import BaseModel, ConfigDict, Field


class ModelSelectorPolicy(BaseModel):
    """Required policy values; callers may inject an overlay-resolved instance."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    selection_timeout_seconds: float = Field(gt=0)
    http_timeout_margin_seconds: float = Field(gt=0)
    probe_timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0, strict=True)
    initial_delay_ms: float = Field(ge=0)

    @property
    def http_timeout_seconds(self) -> float:
        """Let the selection deadline fire before the HTTP deadline."""
        return self.selection_timeout_seconds + self.http_timeout_margin_seconds

    @property
    def retry_delay_seconds(self) -> float:
        """Convert the contract's millisecond retry delay to asyncio seconds."""
        return self.initial_delay_ms / 1000

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelSelectorPolicy:
        """Read the packaged contract using core's duplicate-key rejecting loader.

        Missing or invalid policy fails validation; no code fallback duplicates it.
        """
        contract_path = (
            path if path is not None else Path(__file__).parents[1] / "contract.yaml"
        )
        contract = load_yaml_mapping_no_duplicates(
            contract_path.read_text(encoding="utf-8"), source=str(contract_path)
        )
        error_handling = contract["error_handling"]
        if not isinstance(error_handling, dict):
            raise ValueError("error_handling must be a mapping")
        retry = error_handling["retry_policy"]
        if not isinstance(retry, dict):
            raise ValueError("retry_policy must be a mapping")
        return cls.model_validate(
            {
                "selection_timeout_seconds": error_handling[
                    "selection_timeout_seconds"
                ],
                "http_timeout_margin_seconds": error_handling[
                    "http_timeout_margin_seconds"
                ],
                "probe_timeout_seconds": error_handling["probe_timeout_seconds"],
                "max_retries": retry["max_retries"],
                "initial_delay_ms": retry["initial_delay_ms"],
            }
        )
