# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Generate ModelTaskContract from task description and optional Linear DoD.

Produces a frozen contract with base mechanical checks (unit tests, mypy,
pre-commit) always included. Non-mechanical Linear DoD items are routed to
human_checks rather than faked as shell commands.

Contract persistence: contracts are written to .onex_state/contracts/task-{id}.yaml.
Once persisted, contracts are immutable — overwrite is blocked after work begins.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Inline model definitions — will be replaced by omnibase_core.models.task
# imports once PR #749 lands. Until then, these are the canonical shapes.
# ---------------------------------------------------------------------------


class EnumCheckType(StrEnum):
    """Allowed mechanical check types."""

    COMMAND_EXIT_0 = "command_exit_0"
    FILE_EXISTS = "file_exists"
    GREP_ABSENT = "grep_absent"
    GREP_PRESENT = "grep_present"


class ModelMechanicalCheck(BaseModel):
    """A single mechanical DoD check that can be executed independently."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    criterion: str = Field(
        ..., description="Human-readable description of what is checked"
    )
    check: str = Field(..., description="Shell command or probe to execute")
    check_type: EnumCheckType = Field(
        default=EnumCheckType.COMMAND_EXIT_0,
        description="Type of mechanical check (enum-constrained)",
    )


class ModelTaskContract(BaseModel):
    """Frozen contract for a single agent team task."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    schema_version: str = Field(default="1.0.0", description="Contract schema version")
    task_id: str = Field(..., description="Task identifier (e.g., task-1)")
    parent_ticket: str | None = Field(
        default=None, description="Parent Linear ticket ID"
    )
    repo: str | None = Field(default=None, description="Target repository")
    branch: str | None = Field(default=None, description="Target branch")
    generated_at: datetime = Field(..., description="When this contract was generated")
    generated_by: str = Field(
        default="task_contract_generator",
        description="Generator source/provenance",
    )
    fingerprint: str = Field(
        default="",
        description="SHA-256 of requirements + definition_of_done for identity",
    )
    requirements: list[str] = Field(
        default_factory=list, description="Task requirements"
    )
    definition_of_done: list[ModelMechanicalCheck] = Field(
        default_factory=list, description="Mechanical checks that define completion"
    )
    human_checks: list[str] = Field(
        default_factory=list,
        description="Non-mechanical checks requiring human or LLM judgment",
    )
    verification_tier: str = Field(
        default="full",
        description="Verification tier: full (A+B quorum) or reduced (A only)",
    )

    def to_yaml(self) -> str:
        """Serialize contract to YAML string."""
        data = self.model_dump(mode="json")
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ModelTaskContract:
        """Deserialize contract from YAML string."""
        data = yaml.safe_load(yaml_str)
        return cls(**data)


# ---------------------------------------------------------------------------
# Base mechanical checks — every task gets these
# ---------------------------------------------------------------------------

BASE_CHECKS: list[ModelMechanicalCheck] = [
    ModelMechanicalCheck(
        criterion="Unit tests pass",
        check="uv run pytest tests/unit/ -m unit -q",
        check_type=EnumCheckType.COMMAND_EXIT_0,
    ),
    ModelMechanicalCheck(
        criterion="Type checking passes",
        check="uv run mypy src/ --strict",
        check_type=EnumCheckType.COMMAND_EXIT_0,
    ),
    ModelMechanicalCheck(
        criterion="Pre-commit hooks pass",
        check="pre-commit run --all-files",
        check_type=EnumCheckType.COMMAND_EXIT_0,
    ),
]

# Keywords that indicate a DoD item can be mechanically checked
_MECHANICAL_KEYWORDS: set[str] = {
    "test",
    "pass",
    "exist",
    "no hardcoded",
    "contract yaml",
    "no import",
    "file exists",
    "grep",
}


def _is_mechanical(item: str) -> bool:
    """Heuristic: does this DoD item look mechanically verifiable?"""
    lower = item.lower()
    return any(kw in lower for kw in _MECHANICAL_KEYWORDS)


def _compute_fingerprint(
    requirements: list[str],
    checks: list[ModelMechanicalCheck],
) -> str:
    """SHA-256 fingerprint over requirements + check criteria for identity."""
    payload = json.dumps(
        {
            "requirements": requirements,
            "checks": [c.criterion for c in checks],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def generate_task_contract(
    task_id: str,
    description: str,
    parent_ticket: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
    linear_dod: list[str] | None = None,
    verification_tier: str = "full",
) -> ModelTaskContract:
    """Generate a task contract from description and optional Linear DoD.

    Base mechanical checks (unit tests, mypy, pre-commit) are always included.
    Linear DoD items that look mechanically verifiable are added as checks;
    non-mechanical items go to human_checks.
    """
    checks = list(BASE_CHECKS)
    human_checks: list[str] = []

    if linear_dod:
        for item in linear_dod:
            if _is_mechanical(item):
                checks.append(
                    ModelMechanicalCheck(
                        criterion=item,
                        check=f"# TODO: wire mechanical check for: {item}",
                        check_type=EnumCheckType.COMMAND_EXIT_0,
                    )
                )
            else:
                human_checks.append(item)

    requirements = [description]
    fingerprint = _compute_fingerprint(requirements, checks)

    return ModelTaskContract(
        task_id=task_id,
        parent_ticket=parent_ticket,
        repo=repo,
        branch=branch,
        generated_at=datetime.now(tz=UTC),
        requirements=requirements,
        definition_of_done=checks,
        human_checks=human_checks,
        verification_tier=verification_tier,
        fingerprint=fingerprint,
    )


def persist_task_contract(
    contract: ModelTaskContract,
    base_dir: Path | None = None,
) -> Path:
    """Write contract YAML to .onex_state/contracts/task-{id}.yaml.

    Once persisted, contracts are immutable. This function raises FileExistsError
    if the contract file already exists (overwrite blocked after work begins).
    """
    root = base_dir or Path.cwd()
    contracts_dir = root / ".onex_state" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    path = contracts_dir / f"task-{contract.task_id}.yaml"
    if path.exists():
        raise FileExistsError(
            f"Contract already persisted at {path} — immutable after work begins"
        )

    path.write_text(contract.to_yaml())
    return path
