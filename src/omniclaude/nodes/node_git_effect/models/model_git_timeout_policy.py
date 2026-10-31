# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Validated subprocess deadlines for the git effect node, declared by its contract.

The contract's ``error_handling.timeouts`` block is the single source of every
deadline the subprocess backend applies (OMN-21737). The operator overlay
``OMNICLAUDE_GIT_TIMEOUT_<OPERATION>`` replaces one operation's deadline; no
deadline is spelled in code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from omnibase_core.utils.util_safe_yaml_loader import load_yaml_mapping_no_duplicates
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .model_git_request import GitOperation

_OVERLAY_ENV_PREFIX = "OMNICLAUDE_GIT_TIMEOUT_"


class ModelGitTimeoutPolicy(BaseModel):
    """Required deadlines; the composition root may inject an overlay-resolved one."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    binary_probe_timeout_seconds: float = Field(gt=0)
    operation_timeout_seconds: dict[GitOperation, float]

    @model_validator(mode="after")
    def _every_operation_bounded(self) -> ModelGitTimeoutPolicy:
        missing = sorted(
            op.value for op in GitOperation if op not in self.operation_timeout_seconds
        )
        if missing:
            raise ValueError(f"operation_timeout_seconds lacks {missing}")
        bad = sorted(
            op.value
            for op, seconds in self.operation_timeout_seconds.items()
            if seconds <= 0
        )
        if bad:
            raise ValueError(f"operation_timeout_seconds must be positive: {bad}")
        return self

    def timeout_for(self, operation: GitOperation) -> float:
        """Deadline in seconds for one operation."""
        return self.operation_timeout_seconds[operation]

    @staticmethod
    def overlay_env_name(operation: GitOperation) -> str:
        """Name of the operator overlay variable for one operation."""
        return f"{_OVERLAY_ENV_PREFIX}{operation.name}"

    @classmethod
    def from_contract(
        cls,
        path: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ModelGitTimeoutPolicy:
        """Read the packaged contract, then apply the operator overlay.

        A missing or invalid contract value, or a malformed overlay value,
        fails validation; no code fallback duplicates the contract.
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
        timeouts = error_handling["timeouts"]
        if not isinstance(timeouts, dict):
            raise ValueError("error_handling.timeouts must be a mapping")
        per_operation = timeouts["operation_timeout_seconds"]
        if not isinstance(per_operation, dict):
            raise ValueError("operation_timeout_seconds must be a mapping")
        resolved: dict[str, object] = dict(per_operation)
        overlay = env if env is not None else {}
        for operation in GitOperation:
            raw = overlay.get(cls.overlay_env_name(operation))
            if raw is not None and raw.strip():
                resolved[operation.value] = float(raw)
        return cls.model_validate(
            {
                "binary_probe_timeout_seconds": timeouts[
                    "binary_probe_timeout_seconds"
                ],
                "operation_timeout_seconds": resolved,
            }
        )
