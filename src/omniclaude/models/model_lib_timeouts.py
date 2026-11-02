# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Validated timeout policy for the lib and effect modules, declared by the lib timeouts contract."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from omnibase_core.utils.util_safe_yaml_loader import load_yaml_mapping_no_duplicates
from pydantic import BaseModel, ConfigDict, Field

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "contract_omniclaude_lib_timeouts.yaml"
)


class ModelLibTimeouts(BaseModel):
    """Required values from the ``lib`` section of the lib timeouts contract.

    Callers may inject an instance; ``from_contract`` reads the packaged contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    agent_router_route_timeout_ms: int = Field(gt=0, strict=True)
    demo_sleep_seconds: float = Field(gt=0)
    cache_ttl_seconds: int = Field(gt=0, strict=True)
    demo_ttl_seconds: int = Field(gt=0, strict=True)
    demo_ttl_short: int = Field(gt=0, strict=True)
    demo_wait_seconds: float = Field(gt=0)
    quirk_worker_stop_seconds: float = Field(gt=0)
    local_verifier_seconds: float = Field(gt=0)
    self_check_seconds: int = Field(gt=0, strict=True)
    standalone_inbox_ttl_seconds: int = Field(gt=0, strict=True)
    lane_evidence_scm_seconds: float = Field(gt=0)
    lane_evidence_git_seconds: float = Field(gt=0)

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelLibTimeouts:
        """Read the section from the contract; a missing or invalid value fails validation."""
        contract_path = path if path is not None else _CONTRACT_PATH
        contract = load_yaml_mapping_no_duplicates(
            contract_path.read_text(encoding="utf-8"), source=str(contract_path)
        )
        section = contract["lib"]
        if not isinstance(section, dict):
            raise ValueError("lib must be a mapping")
        return cls.model_validate(section)


@cache
def lib_timeouts() -> ModelLibTimeouts:
    """Return the packaged contract's values, read once per process."""
    return ModelLibTimeouts.from_contract()
