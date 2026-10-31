# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Validated timeout policy for the hook libraries, declared by the timeouts contract."""

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


class ModelHookTimeouts(BaseModel):
    """Required values from the ``hooks`` section of the timeouts contract.

    Callers may inject an instance; ``from_contract`` reads the packaged contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    alert_timeout_seconds: float = Field(gt=0)
    alert_ttl_seconds: int = Field(gt=0, strict=True)
    notify_seconds: float = Field(gt=0)
    cli_emit_seconds: float = Field(gt=0)
    kafka_hook_timeout_seconds: int = Field(gt=0, strict=True)
    kafka_circuit_breaker_reset_seconds: float = Field(gt=0)
    fabric_load_seconds: float = Field(gt=0)
    resume_load_seconds: float = Field(gt=0)
    fabric_http: float = Field(gt=0)
    resume_http: float = Field(gt=0)
    resolve_secs: float = Field(gt=0)
    poll_ms: int = Field(gt=0, strict=True)
    backoff_seconds: float = Field(gt=0)
    db_secs: int = Field(gt=0, strict=True)
    offload_direct_seconds: float = Field(gt=0)
    offload_agent_seconds: float = Field(gt=0)

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelHookTimeouts:
        """Read the section from the contract; a missing or invalid value fails validation."""
        contract_path = path if path is not None else _CONTRACT_PATH
        contract = load_yaml_mapping_no_duplicates(
            contract_path.read_text(encoding="utf-8"), source=str(contract_path)
        )
        section = contract["hooks"]
        if not isinstance(section, dict):
            raise ValueError("hooks must be a mapping")
        return cls.model_validate(section)


@cache
def hook_timeouts() -> ModelHookTimeouts:
    """Return the packaged contract's values, read once per process."""
    return ModelHookTimeouts.from_contract()
