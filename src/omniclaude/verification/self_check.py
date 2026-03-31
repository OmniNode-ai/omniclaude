# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Self-check (A): agent verifies own work against task contract.

Executes all mechanical checks in a ModelTaskContract and returns structured
SelfCheckResult with per-check PASS/FAIL, evidence metadata, and YAML
serialization for downstream verifier consumption.

Shell execution doctrine: Phase 1 uses shell execution for speed. High-value
check types should migrate toward structured execution over time.
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from datetime import UTC, datetime
from enum import StrEnum

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Contract types — local definitions until omnibase_core.models.task lands.
# TODO(OMN-7028): Replace with `from omnibase_core.models.task import ...`
#   once omnibase_core Task 1 is merged.
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
        return yaml.dump(
            self.model_dump(mode="json"), default_flow_style=False, sort_keys=False
        )

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ModelTaskContract:
        data = yaml.safe_load(yaml_str)
        return cls(**data)

    @property
    def fingerprint(self) -> str:
        content = str(self.requirements) + str(
            [c.model_dump(mode="json") for c in self.definition_of_done]
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Self-check result models
# ---------------------------------------------------------------------------

_CHECK_TIMEOUT_SECONDS = 120


class EnumCheckStatus(StrEnum):
    """Allowed statuses for a mechanical check result."""

    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"


class ModelCheckResult(BaseModel):
    """Result of a single mechanical check execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: str
    status: EnumCheckStatus = Field(description="PASS or FAIL")
    exit_code: int | None = Field(
        default=None, description="Process exit code, None on exception"
    )
    stdout: str = Field(default="")
    stderr: str = Field(default="")
    duration_seconds: float = Field(default=0.0)


class ModelSelfCheckResult(BaseModel):
    """Structured result from self-check (A) verification pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    passed: bool
    timestamp: str = Field(description="ISO-8601 UTC timestamp of check execution")
    contract_fingerprint: str = Field(description="SHA-256 prefix of contract content")
    working_directory: str = Field(default="")
    total_duration_seconds: float = Field(default=0.0)
    checks: list[ModelCheckResult] = Field(default_factory=list)

    def to_yaml(self) -> str:
        return yaml.dump(
            self.model_dump(mode="json"), default_flow_style=False, sort_keys=False
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_self_check(
    contract: ModelTaskContract,
    working_dir: str | None = None,
    timeout: int = _CHECK_TIMEOUT_SECONDS,
) -> ModelSelfCheckResult:
    """Run all mechanical checks in the contract and return structured results.

    Args:
        contract: The task contract containing definition_of_done checks.
        working_dir: Working directory for shell command execution.
        timeout: Per-check timeout in seconds (default 120).

    Returns:
        ModelSelfCheckResult with per-check PASS/FAIL and evidence metadata.
    """
    results: list[ModelCheckResult] = []
    all_passed = True
    start_total = time.monotonic()

    for check in contract.definition_of_done:
        start = time.monotonic()
        try:
            proc = subprocess.run(  # nosec B602 — shell=True is intentional (contract-driven check execution)
                check.check,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
                check=False,
            )
            elapsed = time.monotonic() - start
            status = (
                EnumCheckStatus.PASS if proc.returncode == 0 else EnumCheckStatus.FAIL
            )
            results.append(
                ModelCheckResult(
                    criterion=check.criterion,
                    status=status,
                    exit_code=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    duration_seconds=round(elapsed, 3),
                )
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            status = EnumCheckStatus.FAIL
            results.append(
                ModelCheckResult(
                    criterion=check.criterion,
                    status=status,
                    exit_code=None,
                    stdout="",
                    stderr=f"Timeout after {timeout}s",
                    duration_seconds=round(elapsed, 3),
                )
            )
        except OSError as e:
            elapsed = time.monotonic() - start
            status = EnumCheckStatus.FAIL
            results.append(
                ModelCheckResult(
                    criterion=check.criterion,
                    status=status,
                    exit_code=None,
                    stdout="",
                    stderr=str(e),
                    duration_seconds=round(elapsed, 3),
                )
            )

        if status == EnumCheckStatus.FAIL:
            all_passed = False

    total_duration = time.monotonic() - start_total

    return ModelSelfCheckResult(
        task_id=contract.task_id,
        passed=all_passed,
        timestamp=datetime.now(UTC).isoformat(),
        contract_fingerprint=contract.fingerprint,
        working_directory=working_dir or "",
        total_duration_seconds=round(total_duration, 3),
        checks=results,
    )
