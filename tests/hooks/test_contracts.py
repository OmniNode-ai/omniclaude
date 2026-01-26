# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for ONEX contract YAML synchronization with code.

These tests ensure that contract YAML definitions remain synchronized with
the actual Pydantic model implementations. This prevents drift between
documentation (contracts) and runtime behavior (code).

Key validations:
- Contract YAML files are syntactically valid
- Models referenced in contracts exist in code
- Critical parameters (like preview_max_length) match
- Required fields in contracts match model required fields
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from omniclaude.hooks.contracts import (
    CONTRACT_PROMPT_SUBMITTED,
    CONTRACT_SESSION_ENDED,
    CONTRACT_SESSION_STARTED,
    CONTRACT_TOOL_EXECUTED,
    CONTRACTS_DIR,
)
from omniclaude.hooks.models import ModelEventPublishResult
from omniclaude.hooks.schemas import (
    PROMPT_PREVIEW_MAX_LENGTH,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# =============================================================================
# Contract Loading Helpers
# =============================================================================


def load_contract(path: Path) -> dict[str, Any]:
    """Load and parse a contract YAML file.

    Args:
        path: Path to the contract YAML file.

    Returns:
        Parsed contract as a dictionary.

    Raises:
        FileNotFoundError: If the contract file does not exist.
        yaml.YAMLError: If the YAML is invalid.
    """
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# Contract File Existence Tests
# =============================================================================


class TestContractFilesExist:
    """Tests that all expected contract files exist."""

    def test_contracts_directory_exists(self) -> None:
        """Contracts directory exists."""
        assert CONTRACTS_DIR.exists()
        assert CONTRACTS_DIR.is_dir()

    def test_session_started_contract_exists(self) -> None:
        """Session started contract file exists."""
        assert CONTRACT_SESSION_STARTED.exists()

    def test_session_ended_contract_exists(self) -> None:
        """Session ended contract file exists."""
        assert CONTRACT_SESSION_ENDED.exists()

    def test_prompt_submitted_contract_exists(self) -> None:
        """Prompt submitted contract file exists."""
        assert CONTRACT_PROMPT_SUBMITTED.exists()

    def test_tool_executed_contract_exists(self) -> None:
        """Tool executed contract file exists."""
        assert CONTRACT_TOOL_EXECUTED.exists()


# =============================================================================
# Contract YAML Validity Tests
# =============================================================================


class TestContractYamlValidity:
    """Tests that contract YAML files are syntactically valid."""

    @pytest.mark.parametrize(
        "contract_path",
        [
            CONTRACT_SESSION_STARTED,
            CONTRACT_SESSION_ENDED,
            CONTRACT_PROMPT_SUBMITTED,
            CONTRACT_TOOL_EXECUTED,
        ],
    )
    def test_contract_is_valid_yaml(self, contract_path: Path) -> None:
        """Contract file contains valid YAML."""
        contract = load_contract(contract_path)
        assert isinstance(contract, dict)

    @pytest.mark.parametrize(
        "contract_path",
        [
            CONTRACT_SESSION_STARTED,
            CONTRACT_SESSION_ENDED,
            CONTRACT_PROMPT_SUBMITTED,
            CONTRACT_TOOL_EXECUTED,
        ],
    )
    def test_contract_has_required_sections(self, contract_path: Path) -> None:
        """Contract file contains required ONEX sections."""
        contract = load_contract(contract_path)

        # Core identifiers
        assert "name" in contract
        assert "version" in contract
        assert "node_type" in contract

        # I/O models
        assert "input_model" in contract
        assert "output_model" in contract

        # Event bus configuration
        assert "event_bus" in contract

        # Definitions
        assert "definitions" in contract


# =============================================================================
# Contract-Code Synchronization Tests
# =============================================================================


class TestContractCodeSync:
    """Tests that contracts stay synchronized with code."""

    def test_prompt_preview_max_length_synchronized(self) -> None:
        """privacy.preview_max_length in contract matches PROMPT_PREVIEW_MAX_LENGTH constant.

        This is a critical synchronization point. The contract documents the
        privacy constraint (100 chars max for prompt preview), and the code
        enforces it. They must match.
        """
        contract = load_contract(CONTRACT_PROMPT_SUBMITTED)

        # Contract defines privacy.preview_max_length
        privacy_config = contract.get("privacy", {})
        contract_max_length = privacy_config.get("preview_max_length")

        assert contract_max_length is not None, (
            "Contract missing privacy.preview_max_length"
        )
        assert contract_max_length == PROMPT_PREVIEW_MAX_LENGTH, (
            f"Contract preview_max_length ({contract_max_length}) does not match "
            f"code PROMPT_PREVIEW_MAX_LENGTH ({PROMPT_PREVIEW_MAX_LENGTH}). "
            "Update one to match the other."
        )

    def test_prompt_preview_max_length_in_definition(self) -> None:
        """Contract definition maxLength for prompt_preview matches code constant."""
        contract = load_contract(CONTRACT_PROMPT_SUBMITTED)

        # Get the model definition
        definitions = contract.get("definitions", {})
        payload_def = definitions.get("ModelHookPromptSubmittedPayload", {})
        properties = payload_def.get("properties", {})
        prompt_preview = properties.get("prompt_preview", {})

        definition_max_length = prompt_preview.get("maxLength")

        assert definition_max_length is not None, (
            "Contract definition missing maxLength for prompt_preview"
        )
        assert definition_max_length == PROMPT_PREVIEW_MAX_LENGTH, (
            f"Contract definition maxLength ({definition_max_length}) does not match "
            f"code PROMPT_PREVIEW_MAX_LENGTH ({PROMPT_PREVIEW_MAX_LENGTH}). "
            "Update one to match the other."
        )


# =============================================================================
# Model Reference Tests
# =============================================================================


class TestContractModelReferences:
    """Tests that models referenced in contracts exist in code."""

    def test_session_started_input_model_exists(self) -> None:
        """ModelHookSessionStartedPayload referenced in contract exists."""
        contract = load_contract(CONTRACT_SESSION_STARTED)
        input_model = contract["input_model"]

        assert input_model["name"] == "ModelHookSessionStartedPayload"
        assert input_model["module"] == "omniclaude.hooks.schemas"

        # Verify model exists
        assert ModelHookSessionStartedPayload is not None

    def test_session_ended_input_model_exists(self) -> None:
        """ModelHookSessionEndedPayload referenced in contract exists."""
        contract = load_contract(CONTRACT_SESSION_ENDED)
        input_model = contract["input_model"]

        assert input_model["name"] == "ModelHookSessionEndedPayload"
        assert input_model["module"] == "omniclaude.hooks.schemas"

        # Verify model exists
        assert ModelHookSessionEndedPayload is not None

    def test_prompt_submitted_input_model_exists(self) -> None:
        """ModelHookPromptSubmittedPayload referenced in contract exists."""
        contract = load_contract(CONTRACT_PROMPT_SUBMITTED)
        input_model = contract["input_model"]

        assert input_model["name"] == "ModelHookPromptSubmittedPayload"
        assert input_model["module"] == "omniclaude.hooks.schemas"

        # Verify model exists
        assert ModelHookPromptSubmittedPayload is not None

    def test_tool_executed_input_model_exists(self) -> None:
        """ModelHookToolExecutedPayload referenced in contract exists."""
        contract = load_contract(CONTRACT_TOOL_EXECUTED)
        input_model = contract["input_model"]

        assert input_model["name"] == "ModelHookToolExecutedPayload"
        assert input_model["module"] == "omniclaude.hooks.schemas"

        # Verify model exists
        assert ModelHookToolExecutedPayload is not None

    @pytest.mark.parametrize(
        "contract_path",
        [
            CONTRACT_SESSION_STARTED,
            CONTRACT_SESSION_ENDED,
            CONTRACT_PROMPT_SUBMITTED,
            CONTRACT_TOOL_EXECUTED,
        ],
    )
    def test_output_model_exists(self, contract_path: Path) -> None:
        """ModelEventPublishResult referenced in all contracts exists."""
        contract = load_contract(contract_path)
        output_model = contract["output_model"]

        assert output_model["name"] == "ModelEventPublishResult"
        assert output_model["module"] == "omniclaude.hooks.models"

        # Verify model exists
        assert ModelEventPublishResult is not None


# =============================================================================
# Required Fields Synchronization Tests
# =============================================================================


class TestRequiredFieldsSync:
    """Tests that required fields in contracts match model definitions."""

    def test_session_started_required_fields(self) -> None:
        """Required fields in contract match model required fields."""
        contract = load_contract(CONTRACT_SESSION_STARTED)
        definitions = contract.get("definitions", {})
        payload_def = definitions.get("ModelHookSessionStartedPayload", {})
        contract_required = set(payload_def.get("required", []))

        # Get model required fields (fields without defaults)
        model_fields = ModelHookSessionStartedPayload.model_fields
        model_required = {
            name for name, field in model_fields.items() if field.is_required()
        }

        assert contract_required == model_required, (
            f"Required fields mismatch for ModelHookSessionStartedPayload.\n"
            f"Contract: {sorted(contract_required)}\n"
            f"Model: {sorted(model_required)}"
        )

    def test_session_ended_required_fields(self) -> None:
        """Required fields in contract match model required fields."""
        contract = load_contract(CONTRACT_SESSION_ENDED)
        definitions = contract.get("definitions", {})
        payload_def = definitions.get("ModelHookSessionEndedPayload", {})
        contract_required = set(payload_def.get("required", []))

        model_fields = ModelHookSessionEndedPayload.model_fields
        model_required = {
            name for name, field in model_fields.items() if field.is_required()
        }

        assert contract_required == model_required, (
            f"Required fields mismatch for ModelHookSessionEndedPayload.\n"
            f"Contract: {sorted(contract_required)}\n"
            f"Model: {sorted(model_required)}"
        )

    def test_prompt_submitted_required_fields(self) -> None:
        """Required fields in contract match model required fields."""
        contract = load_contract(CONTRACT_PROMPT_SUBMITTED)
        definitions = contract.get("definitions", {})
        payload_def = definitions.get("ModelHookPromptSubmittedPayload", {})
        contract_required = set(payload_def.get("required", []))

        model_fields = ModelHookPromptSubmittedPayload.model_fields
        model_required = {
            name for name, field in model_fields.items() if field.is_required()
        }

        assert contract_required == model_required, (
            f"Required fields mismatch for ModelHookPromptSubmittedPayload.\n"
            f"Contract: {sorted(contract_required)}\n"
            f"Model: {sorted(model_required)}"
        )

    def test_tool_executed_required_fields(self) -> None:
        """Required fields in contract match model required fields."""
        contract = load_contract(CONTRACT_TOOL_EXECUTED)
        definitions = contract.get("definitions", {})
        payload_def = definitions.get("ModelHookToolExecutedPayload", {})
        contract_required = set(payload_def.get("required", []))

        model_fields = ModelHookToolExecutedPayload.model_fields
        model_required = {
            name for name, field in model_fields.items() if field.is_required()
        }

        assert contract_required == model_required, (
            f"Required fields mismatch for ModelHookToolExecutedPayload.\n"
            f"Contract: {sorted(contract_required)}\n"
            f"Model: {sorted(model_required)}"
        )


# =============================================================================
# Event Bus Configuration Tests
# =============================================================================


class TestEventBusConfiguration:
    """Tests that event bus configuration is consistent."""

    @pytest.mark.parametrize(
        ("contract_path", "expected_topic"),
        [
            (CONTRACT_SESSION_STARTED, "onex.evt.omniclaude.session-started.v1"),
            (CONTRACT_SESSION_ENDED, "onex.evt.omniclaude.session-ended.v1"),
            (CONTRACT_PROMPT_SUBMITTED, "onex.evt.omniclaude.prompt-submitted.v1"),
            (CONTRACT_TOOL_EXECUTED, "onex.evt.omniclaude.tool-executed.v1"),
        ],
    )
    def test_topic_base_matches_topics_module(
        self, contract_path: Path, expected_topic: str
    ) -> None:
        """Event bus topic_base in contract matches topics.py definitions."""
        contract = load_contract(contract_path)
        event_bus = contract.get("event_bus", {})
        topic_base = event_bus.get("topic_base")

        assert topic_base == expected_topic, (
            f"Contract topic_base ({topic_base}) does not match expected topic ({expected_topic})"
        )

    @pytest.mark.parametrize(
        "contract_path",
        [
            CONTRACT_SESSION_STARTED,
            CONTRACT_SESSION_ENDED,
            CONTRACT_PROMPT_SUBMITTED,
            CONTRACT_TOOL_EXECUTED,
        ],
    )
    def test_partition_key_is_entity_id(self, contract_path: Path) -> None:
        """All contracts use entity_id as partition key for ordering."""
        contract = load_contract(contract_path)
        event_bus = contract.get("event_bus", {})
        partition_key = event_bus.get("partition_key_field")

        assert partition_key == "entity_id", (
            f"Contract {contract_path.name} uses partition_key_field "
            f"'{partition_key}' instead of 'entity_id'"
        )
