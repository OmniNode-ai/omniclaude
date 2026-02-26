# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for NodeSkillIntegrationGateOrchestrator (OMN-2819).

Test markers:
    @pytest.mark.unit -- all tests here

Coverage:
    1. Import test: node class can be imported
    2. Contract YAML parses successfully
    3. Contract has correct event_bus topics
    4. Contract has correct consumer_group
    5. Contract has correct node_type
    6. Contract has correct capabilities
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NODE_DIR = Path(__file__).resolve().parents[4] / (
    "src/omniclaude/nodes/node_skill_integration_gate_orchestrator"
)
_CONTRACT_PATH = _NODE_DIR / "contract.yaml"

_EXPECTED_SUBSCRIBE_TOPIC = "onex.cmd.omniclaude.integration-gate.v1"
_EXPECTED_SUCCESS_TOPIC = "onex.evt.omniclaude.integration-gate-completed.v1"
_EXPECTED_FAILURE_TOPIC = "onex.evt.omniclaude.integration-gate-failed.v1"
_EXPECTED_CONSUMER_GROUP = "omniclaude.skill.integration_gate"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_contract() -> dict[str, Any]:
    """Load and parse the contract YAML."""
    with open(_CONTRACT_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Import Tests
# ---------------------------------------------------------------------------


class TestNodeImport:
    """Test that the node class can be imported."""

    def test_import_node_class(self) -> None:
        """NodeSkillIntegrationGateOrchestrator can be imported from package."""
        from omniclaude.nodes.node_skill_integration_gate_orchestrator import (
            NodeSkillIntegrationGateOrchestrator,
        )

        assert NodeSkillIntegrationGateOrchestrator is not None

    def test_import_from_node_module(self) -> None:
        """NodeSkillIntegrationGateOrchestrator can be imported from node.py."""
        from omniclaude.nodes.node_skill_integration_gate_orchestrator.node import (
            NodeSkillIntegrationGateOrchestrator,
        )

        assert NodeSkillIntegrationGateOrchestrator is not None

    def test_class_name(self) -> None:
        """Class name follows ONEX naming convention."""
        from omniclaude.nodes.node_skill_integration_gate_orchestrator import (
            NodeSkillIntegrationGateOrchestrator,
        )

        assert (
            NodeSkillIntegrationGateOrchestrator.__name__
            == "NodeSkillIntegrationGateOrchestrator"
        )


# ---------------------------------------------------------------------------
# Contract YAML Tests
# ---------------------------------------------------------------------------


class TestContractYaml:
    """Test that the contract YAML is valid and correct."""

    def test_contract_file_exists(self) -> None:
        """Contract YAML file exists."""
        assert _CONTRACT_PATH.exists(), f"Contract not found at {_CONTRACT_PATH}"

    def test_contract_is_valid_yaml(self) -> None:
        """Contract file contains valid YAML."""
        contract = _load_contract()
        assert isinstance(contract, dict)

    def test_contract_name(self) -> None:
        """Contract has correct name."""
        contract = _load_contract()
        assert contract["name"] == "node_skill_integration_gate_orchestrator"

    def test_contract_node_type(self) -> None:
        """Contract declares ORCHESTRATOR_GENERIC node type."""
        contract = _load_contract()
        assert contract["node_type"] == "ORCHESTRATOR_GENERIC"


# ---------------------------------------------------------------------------
# Topic Routing Tests
# ---------------------------------------------------------------------------


class TestTopicRouting:
    """Test event bus topic configuration."""

    def test_subscribe_topic(self) -> None:
        """Contract subscribes to correct command topic."""
        contract = _load_contract()
        event_bus = contract["event_bus"]
        subscribe = event_bus["subscribe"]
        assert subscribe["topic"] == _EXPECTED_SUBSCRIBE_TOPIC, (
            f"Expected subscribe topic '{_EXPECTED_SUBSCRIBE_TOPIC}', "
            f"got '{subscribe['topic']}'"
        )

    def test_success_topic(self) -> None:
        """Contract publishes to correct success topic."""
        contract = _load_contract()
        event_bus = contract["event_bus"]
        publish = event_bus["publish"]
        assert publish["success_topic"] == _EXPECTED_SUCCESS_TOPIC, (
            f"Expected success topic '{_EXPECTED_SUCCESS_TOPIC}', "
            f"got '{publish['success_topic']}'"
        )

    def test_failure_topic(self) -> None:
        """Contract publishes to correct failure topic."""
        contract = _load_contract()
        event_bus = contract["event_bus"]
        publish = event_bus["publish"]
        assert publish["failure_topic"] == _EXPECTED_FAILURE_TOPIC, (
            f"Expected failure topic '{_EXPECTED_FAILURE_TOPIC}', "
            f"got '{publish['failure_topic']}'"
        )

    def test_consumer_group(self) -> None:
        """Contract has correct consumer group."""
        contract = _load_contract()
        event_bus = contract["event_bus"]
        subscribe = event_bus["subscribe"]
        assert subscribe["consumer_group"] == _EXPECTED_CONSUMER_GROUP, (
            f"Expected consumer group '{_EXPECTED_CONSUMER_GROUP}', "
            f"got '{subscribe['consumer_group']}'"
        )

    def test_topic_naming_convention(self) -> None:
        """Topics follow onex.{cmd|evt}.omniclaude.<skill>.v1 convention."""
        contract = _load_contract()
        event_bus = contract["event_bus"]

        subscribe_topic = event_bus["subscribe"]["topic"]
        assert subscribe_topic.startswith("onex.cmd.omniclaude.")
        assert subscribe_topic.endswith(".v1")

        success_topic = event_bus["publish"]["success_topic"]
        assert success_topic.startswith("onex.evt.omniclaude.")
        assert success_topic.endswith(".v1")

        failure_topic = event_bus["publish"]["failure_topic"]
        assert failure_topic.startswith("onex.evt.omniclaude.")
        assert failure_topic.endswith(".v1")


# ---------------------------------------------------------------------------
# Capabilities Tests
# ---------------------------------------------------------------------------


class TestCapabilities:
    """Test capability declarations."""

    def test_has_capabilities(self) -> None:
        """Contract declares capabilities."""
        contract = _load_contract()
        assert "capabilities" in contract
        assert len(contract["capabilities"]) > 0

    def test_skill_capability_name(self) -> None:
        """Capability name follows skill.<name> convention."""
        contract = _load_contract()
        cap = contract["capabilities"][0]
        assert cap["name"] == "skill.integration_gate"

    def test_capability_has_version(self) -> None:
        """Capability declares a version."""
        contract = _load_contract()
        cap = contract["capabilities"][0]
        assert "version" in cap
        assert cap["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# IO Operations Tests
# ---------------------------------------------------------------------------


class TestIOOperations:
    """Test IO operation declarations."""

    def test_has_io_operations(self) -> None:
        """Contract declares io_operations."""
        contract = _load_contract()
        assert "io_operations" in contract
        assert len(contract["io_operations"]) > 0

    def test_skill_requested_operation(self) -> None:
        """Contract declares skill_requested operation."""
        contract = _load_contract()
        ops = contract["io_operations"]
        skill_op = next(
            (op for op in ops if op["operation"] == "skill_requested"), None
        )
        assert skill_op is not None
        assert skill_op["handler_method"] == "handle_skill_requested"

    def test_io_operation_has_input_output_fields(self) -> None:
        """IO operation has both input and output fields."""
        contract = _load_contract()
        ops = contract["io_operations"]
        for op in ops:
            assert "input_fields" in op, f"Op '{op['operation']}' missing input_fields"
            assert "output_fields" in op, (
                f"Op '{op['operation']}' missing output_fields"
            )


# ---------------------------------------------------------------------------
# Dependencies Tests
# ---------------------------------------------------------------------------


class TestDependencies:
    """Test dependency declarations."""

    def test_has_dependencies(self) -> None:
        """Contract declares dependencies."""
        contract = _load_contract()
        assert "dependencies" in contract

    def test_depends_on_shared_handler(self) -> None:
        """Contract depends on shared handle_skill_requested handler."""
        contract = _load_contract()
        deps = contract["dependencies"]
        handler_dep = next(
            (d for d in deps if d["name"] == "handler_skill_requested"), None
        )
        assert handler_dep is not None
        assert handler_dep["type"] == "handler"
        assert handler_dep["function"] == "handle_skill_requested"
        assert handler_dep["module"] == "omniclaude.nodes.shared"


# ---------------------------------------------------------------------------
# Metadata Tests
# ---------------------------------------------------------------------------


class TestMetadata:
    """Test contract metadata."""

    def test_has_metadata(self) -> None:
        """Contract has metadata section."""
        contract = _load_contract()
        assert "metadata" in contract

    def test_generated_by(self) -> None:
        """Contract was generated by generate_skill_node.py."""
        contract = _load_contract()
        assert contract["metadata"]["generated_by"] == "generate_skill_node.py"

    def test_has_integration_gate_tag(self) -> None:
        """Contract metadata includes integration_gate tag."""
        contract = _load_contract()
        tags = contract["metadata"].get("tags", [])
        assert "integration_gate" in tags
        assert "orchestrator" in tags
        assert "skill" in tags
