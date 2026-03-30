# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for quorum gate with tiebreaker and circuit breaker."""

from __future__ import annotations

import pytest
import yaml

from omniclaude.verification.quorum_gate import (
    evaluate_quorum,
    write_escalation_artifact,
)


@pytest.mark.unit
def test_both_pass_completes_task() -> None:
    result = evaluate_quorum(self_check_passed=True, verifier_passed=True)
    assert result.verdict == "PASS"
    assert result.tiebreaker_needed is False


@pytest.mark.unit
def test_both_fail_stays_in_progress() -> None:
    result = evaluate_quorum(self_check_passed=False, verifier_passed=False)
    assert result.verdict == "FAIL"
    assert result.tiebreaker_needed is False


@pytest.mark.unit
def test_disagreement_triggers_tiebreaker() -> None:
    result = evaluate_quorum(self_check_passed=True, verifier_passed=False)
    assert result.verdict == "TIEBREAKER_NEEDED"
    assert result.tiebreaker_needed is True

    # Also test reverse disagreement
    result2 = evaluate_quorum(self_check_passed=False, verifier_passed=True)
    assert result2.verdict == "TIEBREAKER_NEEDED"
    assert result2.tiebreaker_needed is True


@pytest.mark.unit
def test_tiebreaker_resolves_with_majority() -> None:
    # Self-check PASS + verifier FAIL + tiebreaker PASS → majority PASS
    result = evaluate_quorum(
        self_check_passed=True,
        verifier_passed=False,
        tiebreaker_passed=True,
    )
    assert result.verdict == "PASS"
    assert result.tiebreaker_needed is False

    # Self-check PASS + verifier FAIL + tiebreaker FAIL → majority FAIL
    result2 = evaluate_quorum(
        self_check_passed=True,
        verifier_passed=False,
        tiebreaker_passed=False,
    )
    assert result2.verdict == "FAIL"
    assert result2.tiebreaker_needed is False


@pytest.mark.unit
def test_circuit_breaker_max_one_tiebreak() -> None:
    result = evaluate_quorum(
        self_check_passed=True,
        verifier_passed=False,
        tiebreaker_passed=None,
        tiebreak_count=1,
    )
    assert result.verdict == "ESCALATE"
    assert result.tiebreaker_needed is False
    assert "Circuit breaker" in result.reasoning


@pytest.mark.unit
def test_model_quorum_result_is_frozen() -> None:
    result = evaluate_quorum(self_check_passed=True, verifier_passed=True)
    with pytest.raises(Exception):
        result.verdict = "FAIL"  # type: ignore[misc]


@pytest.mark.unit
def test_write_escalation_artifact(tmp_path: object) -> None:
    from pathlib import Path

    base = Path(str(tmp_path))
    path = write_escalation_artifact(
        task_id="42",
        contract_path=".onex_state/contracts/task-42.yaml",
        self_check_summary="PASS: all 3 checks green",
        verifier_summary="FAIL: test_integration_wiring failed",
        disagreement_details="Verifier found broken import in handler.py:12",
        recommended_action="Re-run verifier after fixing import",
        base_dir=base,
    )
    assert path.exists()
    assert path.name == "escalation.yaml"
    data = yaml.safe_load(path.read_text())
    assert data["task_id"] == "42"
    assert data["contract_path"] == ".onex_state/contracts/task-42.yaml"
    assert "disagreement_summary" in data
