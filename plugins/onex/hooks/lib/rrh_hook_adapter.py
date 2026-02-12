#!/usr/bin/env python3
"""RRH Hook Adapter -- the WHEN layer for RRH validation.

Maps pipeline phases to RRH profiles, builds governance from
ModelTicketContract, and evaluates the ContractRRHResult into
an actionable RRHDecision.

This module lives in hooks/lib/ so it can be imported by pipeline
orchestration code (e.g., ticket-pipeline).  It delegates the actual
A1->A2->A3 work to the skill adapter (rrh_adapter.py).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnibase_core.models.ticket.model_ticket_contract import ModelTicketContract
    from omnibase_spi.contracts.pipeline.contract_rrh_result import ContractRRHResult

# Import from sibling skill directory -- follows existing pattern in hooks/lib
# (see cross_repo_detector.py, pipeline_slack_notifier.py imports).
_skill_dir = str(Path(__file__).parent.parent.parent / "skills" / "rrh")
if _skill_dir not in sys.path:
    sys.path.insert(0, _skill_dir)

from rrh_adapter import RRHAdapter, RRHGovernance, RRHRunConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Pipeline phases
# ---------------------------------------------------------------------------


class PipelinePhase(Enum):
    """Pipeline phases where RRH preflight can be invoked."""

    BEFORE_FIRST_SIDE_EFFECT = "before_first_side_effect"
    BEFORE_PR_CREATION = "before_pr_creation"
    BEFORE_DEPLOY = "before_deploy"
    ON_SKIP_TO_RESUME = "on_skip_to_resume"


# ---------------------------------------------------------------------------
# Phase -> profile mapping
# ---------------------------------------------------------------------------

PHASE_PROFILE_MAP: dict[PipelinePhase, str] = {
    PipelinePhase.BEFORE_FIRST_SIDE_EFFECT: "ticket-pipeline",
    PipelinePhase.BEFORE_PR_CREATION: "ticket-pipeline",
    PipelinePhase.BEFORE_DEPLOY: "ticket-pipeline",
    PipelinePhase.ON_SKIP_TO_RESUME: "ticket-pipeline",
}


# ---------------------------------------------------------------------------
# Decision value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RRHDecision:
    """Actionable decision produced by the hook adapter."""

    verdict: str  # PASS | FAIL | QUARANTINE
    should_block: bool
    human_summary: str
    result: ContractRRHResult
    idempotency_key: str


# ---------------------------------------------------------------------------
# Hook adapter
# ---------------------------------------------------------------------------


class RRHHookAdapter:
    """Maps pipeline phases to RRH runs and evaluates results."""

    def __init__(self, adapter: RRHAdapter | None = None) -> None:
        self._adapter = adapter or RRHAdapter()

    def run_preflight(
        self,
        phase: PipelinePhase,
        contract: ModelTicketContract,
        repo_path: Path,
        output_dir: Path,
        head_sha: str = "",
        original_phase: PipelinePhase | None = None,
    ) -> RRHDecision:
        """Run RRH preflight for the given pipeline phase.

        Args:
            phase: Current pipeline phase.
            contract: The ticket contract driving this pipeline run.
            repo_path: Path to the repository root.
            output_dir: Where to write RRH artifacts.
            head_sha: Current HEAD commit SHA (for idempotency).
            original_phase: When phase is ON_SKIP_TO_RESUME, the phase
                that was originally being resumed from.

        Returns:
            RRHDecision with verdict, blocking flag, and idempotency key.
        """
        profile = self._select_profile(phase, contract, original_phase)
        governance = self._build_governance(contract)
        idem_key = self._idempotency_key(contract.ticket_id, phase, head_sha)

        config = RRHRunConfig(
            repo_path=repo_path,
            profile_name=profile,
            governance=governance,
            output_dir=output_dir,
        )

        result = self._adapter.run(config)
        return self._evaluate(result, idem_key)

    # -- internals ---------------------------------------------------------

    def _select_profile(
        self,
        phase: PipelinePhase,
        contract: ModelTicketContract,
        original_phase: PipelinePhase | None,
    ) -> str:
        """Select the RRH profile for the given phase and contract.

        - Seam tickets get ``seam-ticket`` profile at BEFORE_DEPLOY.
        - ON_SKIP_TO_RESUME delegates to the original phase's profile.
        - Everything else uses the phase -> profile map.
        """
        # Seam tickets get the strictest profile at deploy phase
        is_seam = contract.context.get("is_seam_ticket", False)
        if phase == PipelinePhase.BEFORE_DEPLOY and is_seam:
            return "seam-ticket"

        # Skip-to resume uses the original phase's profile
        if phase == PipelinePhase.ON_SKIP_TO_RESUME and original_phase is not None:
            return self._select_profile(original_phase, contract, None)

        return PHASE_PROFILE_MAP[phase]

    @staticmethod
    def _build_governance(contract: ModelTicketContract) -> RRHGovernance:
        """Derive RRHGovernance from the ticket contract."""
        # Collect interface names from both provided and consumed
        interfaces: list[str] = []
        for iface in contract.interfaces_provided:
            interfaces.append(iface.name)
        for iface in contract.interfaces_consumed:
            interfaces.append(iface.name)

        # Derive evidence requirements from verification step kinds
        evidence: list[str] = []
        for step in contract.verification_steps:
            kind_value = step.kind.value
            if kind_value in ("unit_tests", "integration"):
                evidence.append("tests")

        return RRHGovernance(
            ticket_id=contract.ticket_id,
            evidence_requirements=tuple(sorted(set(evidence))),
            interfaces_touched=tuple(sorted(set(interfaces))),
            deployment_targets=tuple(contract.context.get("deployment_targets", [])),
            is_seam_ticket=contract.context.get("is_seam_ticket", False),
            expected_branch_pattern=contract.context.get("expected_branch_pattern", ""),
        )

    @staticmethod
    def _evaluate(result: ContractRRHResult, idempotency_key: str) -> RRHDecision:
        """Convert a ContractRRHResult into an actionable RRHDecision."""
        verdict = result.verdict.status
        should_block = verdict == "FAIL"
        return RRHDecision(
            verdict=verdict,
            should_block=should_block,
            human_summary=result.verdict.human_summary,
            result=result,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _idempotency_key(ticket_id: str, phase: PipelinePhase, head_sha: str) -> str:
        """Deterministic 16-char hex key for deduplication."""
        raw = f"{ticket_id}:{phase.value}:{head_sha}"
        return sha256(raw.encode()).hexdigest()[:16]
