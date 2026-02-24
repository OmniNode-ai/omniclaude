#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""RRH Skill Adapter -- orchestrates A1 -> A2 -> A3 pipeline.

This module is the HOW of RRH: it runs the three-stage pipeline
(collect, validate, store) against a pluggable node client.  It is
pure -- no hook environment, no implicit I/O -- so it can be tested
and invoked from any context.

When the real ONEX runtime nodes (omnibase_infra >= 0.7.0) are not
available, a FallbackNodeClient returns QUARANTINE so that callers
degrade gracefully.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from omnibase_spi.contracts.pipeline.contract_rrh_result import ContractRRHResult
from omnibase_spi.contracts.shared.contract_check_result import ContractCheckResult
from omnibase_spi.contracts.shared.contract_verdict import ContractVerdict

# ---------------------------------------------------------------------------
# SPI: Node client protocol
# ---------------------------------------------------------------------------


class ProtocolRRHNodeClient(Protocol):
    """Interface for RRH node invocation.

    Implementations may use the ONEX runtime or the built-in fallback.
    """

    def collect_environment(self, repo_path: Path) -> dict[str, Any]:
        """A1: Collect git state, runtime target, toolchain versions."""
        ...

    def validate(
        self,
        environment_data: dict[str, Any],
        profile_name: str,
        governance: RRHGovernance,
    ) -> ContractRRHResult:
        """A2: Pure validation against profile rules."""
        ...

    def store_result(self, result: ContractRRHResult, output_dir: Path) -> Path:
        """A3: Write JSON artifact + symlinks.  Returns artifact path."""
        ...


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RRHGovernance:
    """Governance constraints derived from ModelTicketContract."""

    ticket_id: str
    evidence_requirements: tuple[str, ...] = ()
    interfaces_touched: tuple[str, ...] = ()
    deployment_targets: tuple[str, ...] = ()
    is_seam_ticket: bool = False
    expected_branch_pattern: str = ""


@dataclass(frozen=True)
class RRHRunConfig:
    """Full configuration for a single RRH pipeline run."""

    repo_path: Path
    profile_name: str  # default | ticket-pipeline | ci-repair | seam-ticket
    governance: RRHGovernance
    output_dir: Path


# ---------------------------------------------------------------------------
# Fallback node client (used when omnibase_infra is not installed)
# ---------------------------------------------------------------------------


class FallbackNodeClient:
    """Returns QUARANTINE when real RRH nodes are not installed."""

    def collect_environment(self, repo_path: Path) -> dict[str, Any]:
        return {"_fallback": True, "repo_path": str(repo_path)}

    def validate(
        self,
        environment_data: dict[str, Any],
        profile_name: str,
        governance: RRHGovernance,
    ) -> ContractRRHResult:
        return ContractRRHResult(
            run_id=f"fallback-{uuid.uuid4().hex[:12]}",
            checks=[
                ContractCheckResult(
                    check_id="RRH-0000",
                    domain="rrh",
                    status="skip",
                    severity="critical",
                    message=(
                        "RRH nodes not available (omnibase_infra >= 0.7.0 required)"
                    ),
                ),
            ],
            verdict=ContractVerdict(
                status="QUARANTINE",
                score=0,
                block_reasons=["RRH node implementations not installed"],
                human_summary="RRH validation skipped -- nodes not available.",
            ),
        )

    def store_result(self, result: ContractRRHResult, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / "rrh_fallback.json"
        artifact_path.write_text(result.model_dump_json(indent=2))
        return artifact_path


# ---------------------------------------------------------------------------
# Node client resolution
# ---------------------------------------------------------------------------


def _resolve_node_client() -> ProtocolRRHNodeClient:
    """Lazy import: use ONEX runtime nodes if available, else fallback."""
    try:
        # Presence check -- if these imports succeed the nodes are installed.
        # fmt: off
        from omnibase_infra.nodes.node_rrh_emit_effect import (
            NodeRRHEmitEffect,  # noqa: F401
        )
        from omnibase_infra.nodes.node_rrh_storage_effect import (
            NodeRRHStorageEffect,  # noqa: F401
        )
        from omnibase_infra.nodes.node_rrh_validate_compute import (
            NodeRRHValidateCompute,  # noqa: F401
        )
        # fmt: on

        # Nodes exist but full runtime wiring is not ready yet.
        # TODO(OMN-2138): When runtime wiring is complete, return an
        # ONEXRuntimeNodeClient here instead of the fallback.
        return FallbackNodeClient()
    except ImportError:
        return FallbackNodeClient()


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class RRHAdapter:
    """Orchestrates A1 -> A2 -> A3 RRH pipeline."""

    def __init__(self, node_client: ProtocolRRHNodeClient | None = None) -> None:
        self._client = node_client or _resolve_node_client()

    def run(self, config: RRHRunConfig) -> ContractRRHResult:
        """Execute full RRH pipeline.  Returns ContractRRHResult with timing."""
        start = time.monotonic()

        # A1: Collect environment
        env_data = self._client.collect_environment(config.repo_path)

        # A2: Validate against profile + governance
        result = self._client.validate(env_data, config.profile_name, config.governance)

        # A3: Store result artifact
        self._client.store_result(result, config.output_dir)

        elapsed_ms = (time.monotonic() - start) * 1000

        # Patch duration onto result if not already set.
        # ContractRRHResult is frozen, so we use model_copy.
        if result.duration_ms is None:
            result = result.model_copy(update={"duration_ms": elapsed_ms})

        return result
