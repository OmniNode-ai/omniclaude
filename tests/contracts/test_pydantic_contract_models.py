# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for Pydantic contract backing models.

These tests ensure that Pydantic backing models for YAML contracts:
1. Load and validate successfully from their YAML files
2. Provide correct type-safe access to all fields
3. Reject invalid data with appropriate errors

Related contracts:
- contract_experiment_cohort.yaml (OMN-1674)
- contract_hook_session_started.yaml (OMN-1399)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from omniclaude.hooks.contracts.contract_experiment_cohort import (
    ExperimentCohortContract,
    Version,
)
from omniclaude.hooks.contracts.contract_hook_prompt_submitted import (
    HookPromptSubmittedContract,
)
from omniclaude.hooks.contracts.contract_hook_session_started import (
    HookSessionStartedContract,
)

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Version Model Tests
# =============================================================================


class TestVersionModel:
    """Tests for the shared Version model."""

    def test_version_str_representation(self) -> None:
        """Version string representation is semver format."""
        version = Version(major=1, minor=2, patch=3)
        assert str(version) == "1.2.3"

    def test_version_rejects_negative_numbers(self) -> None:
        """Version rejects negative version numbers."""
        with pytest.raises(ValidationError):
            Version(major=-1, minor=0, patch=0)

    def test_version_is_immutable(self) -> None:
        """Version model is frozen/immutable."""
        version = Version(major=1, minor=0, patch=0)
        with pytest.raises(ValidationError):
            version.major = 2


# =============================================================================
# ExperimentCohortContract Tests
# =============================================================================


class TestExperimentCohortContract:
    """Tests for ExperimentCohortContract Pydantic model."""

    def test_load_validates_yaml(self) -> None:
        """ExperimentCohortContract.load() validates YAML successfully."""
        contract = ExperimentCohortContract.load()

        assert contract.name == "experiment_cohort"
        assert contract.experiment.name == "pattern_injection_v1"
        assert contract.experiment.randomization_unit == "session_id"
        assert contract.experiment.assignment_method == "hash_mod"

    def test_control_percentage_in_valid_range(self) -> None:
        """Contract control_percentage is between 0-100."""
        contract = ExperimentCohortContract.load()

        assert 0 <= contract.experiment.cohort.control_percentage <= 100

    def test_salt_is_non_empty(self) -> None:
        """Contract salt is non-empty."""
        contract = ExperimentCohortContract.load()

        assert len(contract.experiment.cohort.salt) > 0

    def test_has_invariants(self) -> None:
        """Contract has invariants list."""
        contract = ExperimentCohortContract.load()

        assert len(contract.invariants) > 0
        assert any(
            inv.name == "control_percentage_range" for inv in contract.invariants
        )
        assert any(inv.name == "salt_non_empty" for inv in contract.invariants)

    def test_has_auditability(self) -> None:
        """Contract has auditability requirements."""
        contract = ExperimentCohortContract.load()

        assert len(contract.auditability.stamp_into_record) > 0
        assert "effective_control_percentage" in contract.auditability.stamp_into_record

    def test_has_metadata(self) -> None:
        """Contract has metadata."""
        contract = ExperimentCohortContract.load()

        assert contract.metadata.author == "OmniNode Team"
        assert contract.metadata.license == "MIT"
        assert contract.metadata.ticket == "OMN-1674"


# =============================================================================
# HookSessionStartedContract Tests
# =============================================================================


class TestHookSessionStartedContract:
    """Tests for HookSessionStartedContract Pydantic model."""

    def test_load_validates_yaml(self) -> None:
        """HookSessionStartedContract.load() validates YAML successfully."""
        contract = HookSessionStartedContract.load()

        assert contract.name == "hook_session_started"
        assert contract.node_type == "EFFECT"
        assert contract.node_name == "hook_session_started"

    def test_version_is_valid(self) -> None:
        """Contract has valid version."""
        contract = HookSessionStartedContract.load()

        assert contract.version.major >= 0
        assert str(contract.version) == "1.0.0"

    def test_node_version_is_valid(self) -> None:
        """Contract has valid node_version."""
        contract = HookSessionStartedContract.load()

        assert contract.node_version.major >= 0
        assert str(contract.node_version) == "0.1.0"

    def test_input_model_reference(self) -> None:
        """Input model reference is correct."""
        contract = HookSessionStartedContract.load()

        assert contract.input_model.name == "ModelHookSessionStartedPayload"
        assert contract.input_model.module == "omniclaude.hooks.schemas"

    def test_output_model_reference(self) -> None:
        """Output model reference is correct."""
        contract = HookSessionStartedContract.load()

        assert contract.output_model.name == "ModelEventPublishResult"
        assert contract.output_model.module == "omniclaude.hooks.models"

    def test_event_bus_configuration(self) -> None:
        """Event bus configuration is correct."""
        contract = HookSessionStartedContract.load()

        assert contract.event_bus.topic_base == "onex.evt.omniclaude.session-started.v1"
        assert contract.event_bus.partition_key_field == "entity_id"
        assert contract.event_bus.partition_strategy == "hash"

    def test_runtime_configuration(self) -> None:
        """Runtime configuration is correct."""
        contract = HookSessionStartedContract.load()

        assert contract.runtime.supports_direct_call is True
        assert contract.runtime.supports_event_driven is True
        assert contract.runtime.side_effects is True
        assert contract.runtime.timeout_ms == 500
        assert contract.runtime.deterministic is True

    def test_timestamp_policy(self) -> None:
        """Timestamp policy is correct."""
        contract = HookSessionStartedContract.load()

        assert contract.timestamp_policy.explicit_injection is True
        assert contract.timestamp_policy.timezone_required is True
        assert len(contract.timestamp_policy.rationale) > 0

    def test_has_dependencies(self) -> None:
        """Contract has dependencies."""
        contract = HookSessionStartedContract.load()

        assert len(contract.dependencies) >= 3
        dep_names = {dep.name for dep in contract.dependencies}
        assert "kafka_producer" in dep_names
        assert "topic_builder" in dep_names

    def test_has_capabilities(self) -> None:
        """Contract has capabilities."""
        contract = HookSessionStartedContract.load()

        assert len(contract.capabilities) >= 4
        cap_names = {cap.name for cap in contract.capabilities}
        assert "session_event_emission" in cap_names
        assert "causation_tracking" in cap_names
        assert "correlation_tracking" in cap_names
        assert "git_context_capture" in cap_names

    def test_has_model_definitions(self) -> None:
        """Contract has JSON Schema model definitions."""
        contract = HookSessionStartedContract.load()

        assert "ModelHookSessionStartedPayload" in contract.definitions
        assert "ModelEventPublishResult" in contract.definitions

        # Verify payload definition has expected properties
        payload_def = contract.definitions["ModelHookSessionStartedPayload"]
        assert "entity_id" in payload_def.properties
        assert "session_id" in payload_def.properties
        assert "emitted_at" in payload_def.properties

    def test_has_metadata(self) -> None:
        """Contract has metadata."""
        contract = HookSessionStartedContract.load()

        assert contract.metadata.author == "OmniNode Team"
        assert contract.metadata.license == "MIT"
        assert contract.metadata.ticket == "OMN-1399"
        assert "hook" in contract.metadata.tags
        assert "session" in contract.metadata.tags
        assert "kafka" in contract.metadata.tags

    def test_load_with_custom_path(self) -> None:
        """load() accepts custom path parameter."""
        contracts_dir = (
            Path(__file__).parent.parent.parent / "src/omniclaude/hooks/contracts"
        )
        yaml_path = contracts_dir / "contract_hook_session_started.yaml"

        contract = HookSessionStartedContract.load(yaml_path)

        assert contract.name == "hook_session_started"

    def test_model_is_immutable(self) -> None:
        """Contract model is frozen/immutable."""
        contract = HookSessionStartedContract.load()

        with pytest.raises(ValidationError):
            contract.name = "different_name"


# =============================================================================
# HookPromptSubmittedContract Tests
# =============================================================================


class TestHookPromptSubmittedContract:
    """Tests for HookPromptSubmittedContract Pydantic model."""

    def test_load_validates_yaml(self) -> None:
        """HookPromptSubmittedContract.load() validates YAML successfully."""
        contract = HookPromptSubmittedContract.load()

        assert contract.name == "hook_prompt_submitted"
        assert contract.node_type == "EFFECT"
        assert contract.node_name == "hook_prompt_submitted"

    def test_version_is_valid(self) -> None:
        """Contract has valid version."""
        contract = HookPromptSubmittedContract.load()

        assert contract.version.major >= 0
        assert str(contract.version) == "1.0.0"

    def test_node_version_is_valid(self) -> None:
        """Contract has valid node_version."""
        contract = HookPromptSubmittedContract.load()

        assert contract.node_version.major >= 0
        assert str(contract.node_version) == "0.1.0"

    def test_privacy_configuration(self) -> None:
        """Privacy configuration is correct."""
        contract = HookPromptSubmittedContract.load()

        assert contract.privacy.data_minimization is True
        assert contract.privacy.preview_max_length == 100
        assert contract.privacy.pii_policy == "exclude"

    def test_input_model_reference(self) -> None:
        """Input model reference is correct."""
        contract = HookPromptSubmittedContract.load()

        assert contract.input_model.name == "ModelHookPromptSubmittedPayload"
        assert contract.input_model.module == "omniclaude.hooks.schemas"

    def test_output_model_reference(self) -> None:
        """Output model reference is correct."""
        contract = HookPromptSubmittedContract.load()

        assert contract.output_model.name == "ModelEventPublishResult"
        assert contract.output_model.module == "omniclaude.hooks.models"

    def test_event_bus_configuration(self) -> None:
        """Event bus configuration is correct."""
        contract = HookPromptSubmittedContract.load()

        assert (
            contract.event_bus.topic_base == "onex.evt.omniclaude.prompt-submitted.v1"
        )
        assert contract.event_bus.partition_key_field == "entity_id"
        assert contract.event_bus.partition_strategy == "hash"

    def test_runtime_configuration(self) -> None:
        """Runtime configuration is correct."""
        contract = HookPromptSubmittedContract.load()

        assert contract.runtime.supports_direct_call is True
        assert contract.runtime.supports_event_driven is True
        assert contract.runtime.side_effects is True
        assert contract.runtime.timeout_ms == 500
        assert contract.runtime.deterministic is True

    def test_timestamp_policy(self) -> None:
        """Timestamp policy is correct."""
        contract = HookPromptSubmittedContract.load()

        assert contract.timestamp_policy.explicit_injection is True
        assert contract.timestamp_policy.timezone_required is True
        assert len(contract.timestamp_policy.rationale) > 0

    def test_has_dependencies(self) -> None:
        """Contract has dependencies."""
        contract = HookPromptSubmittedContract.load()

        assert len(contract.dependencies) >= 3
        dep_names = {dep.name for dep in contract.dependencies}
        assert "kafka_producer" in dep_names
        assert "topic_builder" in dep_names

    def test_has_capabilities(self) -> None:
        """Contract has capabilities."""
        contract = HookPromptSubmittedContract.load()

        assert len(contract.capabilities) >= 4
        cap_names = {cap.name for cap in contract.capabilities}
        assert "prompt_event_emission" in cap_names
        assert "causation_tracking" in cap_names
        assert "correlation_tracking" in cap_names
        assert "privacy_preservation" in cap_names

    def test_has_model_definitions(self) -> None:
        """Contract has JSON Schema model definitions."""
        contract = HookPromptSubmittedContract.load()

        assert "ModelHookPromptSubmittedPayload" in contract.definitions
        assert "ModelEventPublishResult" in contract.definitions

        # Verify payload definition has expected properties
        payload_def = contract.definitions["ModelHookPromptSubmittedPayload"]
        assert "entity_id" in payload_def.properties
        assert "prompt_id" in payload_def.properties
        assert "prompt_preview" in payload_def.properties
        assert "prompt_length" in payload_def.properties

    def test_has_metadata(self) -> None:
        """Contract has metadata."""
        contract = HookPromptSubmittedContract.load()

        assert contract.metadata.author == "OmniNode Team"
        assert contract.metadata.license == "MIT"
        assert contract.metadata.ticket == "OMN-1399"
        assert "hook" in contract.metadata.tags
        assert "prompt" in contract.metadata.tags
        assert "privacy" in contract.metadata.tags

    def test_load_with_custom_path(self) -> None:
        """load() accepts custom path parameter."""
        contracts_dir = (
            Path(__file__).parent.parent.parent / "src/omniclaude/hooks/contracts"
        )
        yaml_path = contracts_dir / "contract_hook_prompt_submitted.yaml"

        contract = HookPromptSubmittedContract.load(yaml_path)

        assert contract.name == "hook_prompt_submitted"

    def test_model_is_immutable(self) -> None:
        """Contract model is frozen/immutable."""
        contract = HookPromptSubmittedContract.load()

        with pytest.raises(ValidationError):
            contract.name = "different_name"

    def test_no_redundant_contract_version(self) -> None:
        """YAML no longer has redundant contract_version field."""
        import yaml

        contracts_dir = (
            Path(__file__).parent.parent.parent / "src/omniclaude/hooks/contracts"
        )
        yaml_path = contracts_dir / "contract_hook_prompt_submitted.yaml"

        with open(yaml_path) as f:
            raw_data = yaml.safe_load(f)

        # contract_version should NOT be in the raw YAML
        assert "contract_version" not in raw_data
