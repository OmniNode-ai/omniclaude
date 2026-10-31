# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Validated timeout policy for the CI relay service, declared by the timeouts contract."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from omnibase_core.utils.util_safe_yaml_loader import load_yaml_mapping_no_duplicates
from pydantic import BaseModel, ConfigDict, Field

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "contract_omniclaude_timeouts.yaml"
)


class ModelCiRelayTimeouts(BaseModel):
    """Required values from the ``ci_relay`` section of the timeouts contract.

    Callers may inject an instance; ``from_contract`` reads the packaged contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    gh_api_seconds: float = Field(gt=0)
    pr_cache_ttl: float = Field(gt=0)
    kafka_request_ms: int = Field(gt=0, strict=True)
    dedupe_ttl_seconds: int = Field(gt=0, strict=True)

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelCiRelayTimeouts:
        """Read the section from the contract; a missing or invalid value fails validation."""
        contract_path = path if path is not None else _CONTRACT_PATH
        contract = load_yaml_mapping_no_duplicates(
            contract_path.read_text(encoding="utf-8"), source=str(contract_path)
        )
        section = contract["ci_relay"]
        if not isinstance(section, dict):
            raise ValueError("ci_relay must be a mapping")
        return cls.model_validate(section)


@cache
def relay_timeouts() -> ModelCiRelayTimeouts:
    """Return the packaged contract's values, read once per process."""
    return ModelCiRelayTimeouts.from_contract()
