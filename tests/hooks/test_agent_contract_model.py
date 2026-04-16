# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""TDD tests for ModelAgentContract — required-field enforcement (OMN-8914).

These tests must fail before the Pydantic model is introduced and pass after.

Coverage:
    test_agent_yaml_with_all_required_fields_validates
        A complete, valid agent dict passes validation without error.
    test_agent_yaml_missing_description_fails
        Missing `description` raises ValidationError.
    test_agent_yaml_missing_purpose_fails
        Missing `purpose` raises ValidationError.
    test_agent_yaml_invalid_model_fails
        `model` not in {opus, sonnet, haiku} raises ValidationError.
    test_agent_yaml_invalid_name_pattern_fails
        `name` that doesn't match agent-[a-z][a-z0-9-]+ raises ValidationError.
    test_agent_yaml_disallowed_tools_missing_fails
        `disallowedTools` field absent raises ValidationError.
    test_agent_yaml_disallowed_tools_empty_list_passes
        `disallowedTools: []` is valid per OMN-8842.
    test_agent_yaml_name_pattern_valid_variants
        Several valid name patterns all pass.
    test_agent_yaml_description_too_short_fails
        description under 20 chars raises ValidationError.
    test_agent_yaml_purpose_too_short_fails
        purpose under 20 chars raises ValidationError.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from agent_contract_model import ModelAgentContract  # noqa: E402
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_AGENT: dict = {
    "name": "agent-code-reviewer",
    "description": "Reviews code for quality and ONEX compliance issues",
    "model": "sonnet",
    "triggers": ["review code", "code review"],
    "disallowedTools": [],
    "domain": "code-quality",
    "purpose": "Ensure all merged code meets ONEX quality and compliance standards",
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_agent_yaml_with_all_required_fields_validates() -> None:
    contract = ModelAgentContract(**VALID_AGENT)
    assert contract.name == "agent-code-reviewer"
    assert contract.model == "sonnet"
    assert contract.disallowedTools == []


def test_agent_yaml_disallowed_tools_empty_list_passes() -> None:
    data = {**VALID_AGENT, "disallowedTools": []}
    contract = ModelAgentContract(**data)
    assert contract.disallowedTools == []


def test_agent_yaml_disallowed_tools_non_empty_passes() -> None:
    data = {**VALID_AGENT, "disallowedTools": ["CronCreate", "CronDelete"]}
    contract = ModelAgentContract(**data)
    assert "CronCreate" in contract.disallowedTools


def test_agent_yaml_name_pattern_valid_variants() -> None:
    for name in [
        "agent-ab",
        "agent-foo",
        "agent-foo-bar",
        "agent-foo123",
        "agent-code-reviewer",
    ]:
        data = {**VALID_AGENT, "name": name}
        contract = ModelAgentContract(**data)
        assert contract.name == name


def test_agent_yaml_orchestrator_empty_triggers_passes() -> None:
    """Orchestrator agents (is_orchestrator=True) may have empty triggers."""
    data = {**VALID_AGENT, "triggers": [], "is_orchestrator": True}
    contract = ModelAgentContract(**data)
    assert contract.triggers == []


# ---------------------------------------------------------------------------
# Required field failures
# ---------------------------------------------------------------------------


def test_agent_yaml_missing_description_fails() -> None:
    data = {k: v for k, v in VALID_AGENT.items() if k != "description"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "description" in str(exc_info.value)


def test_agent_yaml_missing_purpose_fails() -> None:
    data = {k: v for k, v in VALID_AGENT.items() if k != "purpose"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "purpose" in str(exc_info.value)


def test_agent_yaml_missing_model_fails() -> None:
    data = {k: v for k, v in VALID_AGENT.items() if k != "model"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "model" in str(exc_info.value)


def test_agent_yaml_missing_domain_fails() -> None:
    data = {k: v for k, v in VALID_AGENT.items() if k != "domain"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "domain" in str(exc_info.value)


def test_agent_yaml_disallowed_tools_missing_fails() -> None:
    data = {k: v for k, v in VALID_AGENT.items() if k != "disallowedTools"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "disallowedTools" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Constraint failures
# ---------------------------------------------------------------------------


def test_agent_yaml_invalid_model_fails() -> None:
    data = {**VALID_AGENT, "model": "gpt-4"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "model" in str(exc_info.value)


def test_agent_yaml_invalid_name_pattern_fails() -> None:
    for bad_name in [
        "code-reviewer",  # missing agent- prefix
        "agent-",  # empty suffix
        "agent-Code-Reviewer",  # uppercase not allowed
        "AGENT-foo",  # uppercase prefix
        "agent_foo",  # underscore not allowed
    ]:
        data = {**VALID_AGENT, "name": bad_name}
        with pytest.raises(ValidationError, match="name"):
            ModelAgentContract(**data)


def test_agent_yaml_description_too_short_fails() -> None:
    data = {**VALID_AGENT, "description": "Too short"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "description" in str(exc_info.value)


def test_agent_yaml_purpose_too_short_fails() -> None:
    data = {**VALID_AGENT, "purpose": "Short"}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "purpose" in str(exc_info.value)


def test_agent_yaml_non_orchestrator_empty_triggers_fails() -> None:
    """Non-orchestrator agents must have at least one trigger."""
    data = {**VALID_AGENT, "triggers": [], "is_orchestrator": False}
    with pytest.raises(ValidationError) as exc_info:
        ModelAgentContract(**data)
    assert "triggers" in str(exc_info.value)
