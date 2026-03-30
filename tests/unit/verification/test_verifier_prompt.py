# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the independent verifier prompt builder."""

from __future__ import annotations

import pytest

from omniclaude.verification.verifier_prompt import build_verifier_prompt


@pytest.mark.unit
def test_verifier_prompt_contains_contract() -> None:
    """Verifier prompt includes full contract and evidence path."""
    prompt = build_verifier_prompt(
        task_id="task-1",
        contract_path="/path/to/contract.yaml",
        self_check_path="/path/to/self-check.yaml",
        repo="omnibase_infra",
        branch="jonah/omn-7001-feature",
    )
    assert "task-1" in prompt
    assert "/path/to/contract.yaml" in prompt
    assert "omnibase_infra" in prompt
    assert "PASS or FAIL" in prompt
    # Must NOT reference conversation history
    assert "conversation" not in prompt.lower()


@pytest.mark.unit
def test_verifier_prompt_instructs_independence() -> None:
    """Verifier prompt instructs re-running checks independently."""
    prompt = build_verifier_prompt(
        task_id="task-2",
        contract_path="/contracts/task-2.yaml",
        self_check_path="/evidence/self-check.yaml",
        repo="omniclaude",
        branch="jonah/omn-7002-test",
    )
    assert "independently" in prompt.lower()


@pytest.mark.unit
def test_verifier_prompt_declares_self_check_non_authoritative() -> None:
    """Verifier prompt declares self-check as non-authoritative."""
    prompt = build_verifier_prompt(
        task_id="task-3",
        contract_path="/contracts/task-3.yaml",
        self_check_path="/evidence/self-check.yaml",
        repo="omnibase_core",
        branch="jonah/omn-7003-fix",
    )
    assert "non-authoritative" in prompt.lower()


@pytest.mark.unit
def test_verifier_prompt_specifies_evidence_output_path() -> None:
    """Verifier prompt specifies .onex_state/evidence/ output path."""
    prompt = build_verifier_prompt(
        task_id="task-4",
        contract_path="/contracts/task-4.yaml",
        self_check_path="/evidence/self-check.yaml",
        repo="omniintelligence",
        branch="jonah/omn-7004-hook",
    )
    assert ".onex_state/evidence/" in prompt


@pytest.mark.unit
def test_verifier_prompt_references_repo_authority() -> None:
    """Verifier prompt establishes repository as authoritative source."""
    prompt = build_verifier_prompt(
        task_id="task-5",
        contract_path="/contracts/task-5.yaml",
        self_check_path="/evidence/self-check.yaml",
        repo="omnidash",
        branch="jonah/omn-7005-page",
    )
    assert "repository" in prompt.lower()


@pytest.mark.unit
def test_verifier_prompt_no_conversation_reference() -> None:
    """Verifier prompt must never reference conversation history."""
    prompt = build_verifier_prompt(
        task_id="task-6",
        contract_path="/contracts/task-6.yaml",
        self_check_path="/evidence/self-check.yaml",
        repo="omnibase_spi",
        branch="jonah/omn-7006-protocol",
    )
    # Exhaustive check: no reference to conversation, chat, or history
    lower = prompt.lower()
    assert "conversation" not in lower
    assert "chat history" not in lower
    assert "previous messages" not in lower
