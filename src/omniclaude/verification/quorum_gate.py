# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Quorum gate: A+B must agree, C breaks ties. Circuit breaker after 1 tiebreak.

Dual verification (self-check A + independent verifier B) gates task completion.
On disagreement, tiebreaker C casts the deciding vote. If tiebreaker is
inconclusive and the circuit breaker limit is reached, verdict escalates to
the user with a compact artifact.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ModelQuorumResult(BaseModel):
    """Frozen result of a quorum evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    verdict: str = Field(
        description="PASS | FAIL | TIEBREAKER_NEEDED | ESCALATE",
    )
    tiebreaker_needed: bool
    reasoning: str


def evaluate_quorum(
    self_check_passed: bool,
    verifier_passed: bool,
    tiebreaker_passed: bool | None = None,
    tiebreak_count: int = 0,
) -> ModelQuorumResult:
    """Evaluate verification quorum. 2-of-3 majority decides."""
    # Both agree
    if self_check_passed and verifier_passed:
        return ModelQuorumResult(
            verdict="PASS",
            tiebreaker_needed=False,
            reasoning="A and B both PASS",
        )
    if not self_check_passed and not verifier_passed:
        return ModelQuorumResult(
            verdict="FAIL",
            tiebreaker_needed=False,
            reasoning="A and B both FAIL",
        )

    # Disagreement — need tiebreaker
    if tiebreaker_passed is None:
        if tiebreak_count >= 1:
            return ModelQuorumResult(
                verdict="ESCALATE",
                tiebreaker_needed=False,
                reasoning="Circuit breaker: max 1 tiebreak reached, escalating to user",
            )
        return ModelQuorumResult(
            verdict="TIEBREAKER_NEEDED",
            tiebreaker_needed=True,
            reasoning="A and B disagree, tiebreaker (C) required",
        )

    # Tiebreaker provided — 2-of-3 majority
    votes = [self_check_passed, verifier_passed, tiebreaker_passed]
    passes = sum(votes)
    if passes >= 2:
        return ModelQuorumResult(
            verdict="PASS",
            tiebreaker_needed=False,
            reasoning=f"Majority PASS ({passes}/3)",
        )
    return ModelQuorumResult(
        verdict="FAIL",
        tiebreaker_needed=False,
        reasoning=f"Majority FAIL ({3 - passes}/3)",
    )


def write_escalation_artifact(
    task_id: str,
    contract_path: str,
    self_check_summary: str,
    verifier_summary: str,
    disagreement_details: str,
    recommended_action: str,
    base_dir: Path | None = None,
) -> Path:
    """Write a compact escalation artifact for user review.

    Returns the path to the written YAML file.
    """
    if base_dir is None:
        base_dir = Path(".onex_state")

    evidence_dir = base_dir / "evidence" / f"task-{task_id}"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    artifact = {
        "task_id": task_id,
        "contract_path": contract_path,
        "self_check_result": self_check_summary,
        "verifier_result": verifier_summary,
        "disagreement_summary": disagreement_details,
        "recommended_action": recommended_action,
    }

    path = evidence_dir / "escalation.yaml"
    path.write_text(yaml.dump(artifact, default_flow_style=False, sort_keys=False))
    return path
