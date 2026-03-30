# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for task contract generator.

Verifies:
- Base mechanical checks always included
- Linear DoD items merged (mechanical vs human routing)
- Contract persistence and immutability
- YAML roundtrip
- Fingerprint stability
"""

from __future__ import annotations

import pytest

from omniclaude.contracts.task_contract_generator import (
    EnumCheckType,
    ModelTaskContract,
    generate_task_contract,
    persist_task_contract,
)


@pytest.mark.unit
def test_generate_from_task_description() -> None:
    """Generate contract from task description with base mechanical checks."""
    contract = generate_task_contract(
        task_id="task-1",
        description="Implement new Effect handler in omnibase_infra",
        parent_ticket="OMN-7001",
        repo="omnibase_infra",
    )
    assert contract.task_id == "task-1"
    assert contract.parent_ticket == "OMN-7001"
    assert contract.repo == "omnibase_infra"

    check_criteria = [c.criterion for c in contract.definition_of_done]
    assert "Unit tests pass" in check_criteria
    assert "Type checking passes" in check_criteria
    assert "Pre-commit hooks pass" in check_criteria


@pytest.mark.unit
def test_generate_with_linear_dod_mechanical() -> None:
    """When parent ticket has DoD with mechanical items, merge into checks."""
    contract = generate_task_contract(
        task_id="task-2",
        description="Add Kafka topic registration",
        parent_ticket="OMN-7002",
        repo="omnibase_infra",
        linear_dod=["No hardcoded topic strings", "Contract YAML exists"],
    )
    check_criteria = [c.criterion for c in contract.definition_of_done]
    assert "No hardcoded topic strings" in check_criteria
    assert "Contract YAML exists" in check_criteria
    # Base checks still present
    assert "Unit tests pass" in check_criteria


@pytest.mark.unit
def test_generate_with_linear_dod_human_checks() -> None:
    """Non-mechanical DoD items go to human_checks, not faked as commands."""
    contract = generate_task_contract(
        task_id="task-3",
        description="Refactor auth flow",
        linear_dod=[
            "Unit tests pass",  # mechanical
            "Architecture is clean and maintainable",  # non-mechanical
            "Documentation is clear for new developers",  # non-mechanical
        ],
    )
    check_criteria = [c.criterion for c in contract.definition_of_done]
    assert "Unit tests pass" in check_criteria

    assert "Architecture is clean and maintainable" in contract.human_checks
    assert "Documentation is clear for new developers" in contract.human_checks


@pytest.mark.unit
def test_contract_is_frozen() -> None:
    """Task contracts are immutable once created."""
    contract = generate_task_contract(
        task_id="task-frozen",
        description="Test immutability",
    )
    with pytest.raises(Exception):
        contract.task_id = "modified"  # type: ignore[misc]


@pytest.mark.unit
def test_contract_yaml_roundtrip() -> None:
    """Contract survives YAML serialization/deserialization."""
    contract = generate_task_contract(
        task_id="task-rt",
        description="Roundtrip test",
        parent_ticket="OMN-9999",
        repo="omniclaude",
        branch="jonah/test",
        linear_dod=["File exists for handler"],
    )
    yaml_str = contract.to_yaml()
    loaded = ModelTaskContract.from_yaml(yaml_str)

    assert loaded.task_id == contract.task_id
    assert loaded.parent_ticket == contract.parent_ticket
    assert loaded.repo == contract.repo
    assert loaded.branch == contract.branch
    assert len(loaded.definition_of_done) == len(contract.definition_of_done)
    assert loaded.fingerprint == contract.fingerprint


@pytest.mark.unit
def test_fingerprint_stability() -> None:
    """Same inputs produce same fingerprint."""
    c1 = generate_task_contract(
        task_id="task-fp1",
        description="Fingerprint test",
        linear_dod=["No hardcoded strings"],
    )
    c2 = generate_task_contract(
        task_id="task-fp2",
        description="Fingerprint test",
        linear_dod=["No hardcoded strings"],
    )
    assert c1.fingerprint == c2.fingerprint


@pytest.mark.unit
def test_persist_task_contract(tmp_path: object) -> None:
    """Contract is written to .onex_state/contracts/task-{id}.yaml."""
    from pathlib import Path

    base = Path(str(tmp_path))
    contract = generate_task_contract(
        task_id="persist-1",
        description="Persistence test",
    )
    path = persist_task_contract(contract, base_dir=base)

    assert path.exists()
    assert path.name == "task-persist-1.yaml"
    assert ".onex_state/contracts" in str(path)

    # Verify content is valid YAML that roundtrips
    loaded = ModelTaskContract.from_yaml(path.read_text())
    assert loaded.task_id == "persist-1"


@pytest.mark.unit
def test_persist_immutability_blocks_overwrite(tmp_path: object) -> None:
    """Second persist of same task_id raises FileExistsError."""
    from pathlib import Path

    base = Path(str(tmp_path))
    contract = generate_task_contract(
        task_id="immutable-1",
        description="Immutability test",
    )
    persist_task_contract(contract, base_dir=base)

    with pytest.raises(FileExistsError, match="immutable after work begins"):
        persist_task_contract(contract, base_dir=base)


@pytest.mark.unit
def test_check_types_are_enum_constrained() -> None:
    """All base checks use EnumCheckType values."""
    contract = generate_task_contract(
        task_id="task-enum",
        description="Enum test",
    )
    for check in contract.definition_of_done:
        assert isinstance(check.check_type, EnumCheckType)


@pytest.mark.unit
def test_verification_tier_default() -> None:
    """Default verification tier is 'full'."""
    contract = generate_task_contract(
        task_id="task-tier",
        description="Tier test",
    )
    assert contract.verification_tier == "full"


@pytest.mark.unit
def test_verification_tier_reduced() -> None:
    """Can set verification tier to 'reduced'."""
    contract = generate_task_contract(
        task_id="task-reduced",
        description="Reduced tier",
        verification_tier="reduced",
    )
    assert contract.verification_tier == "reduced"
