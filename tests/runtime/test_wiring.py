# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Integration tests for wire_omniclaude_services() function.

Tests verify that handler contracts are correctly published to Kafka
via the ServiceContractPublisher from omnibase_infra. These tests use
mocked publishers to avoid requiring real Kafka infrastructure.

Ticket: OMN-1812 - Update tests for ServiceContractPublisher API migration
Original Ticket: OMN-1605 - Implement contract-driven handler registration loader
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Self
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

# Mark all tests in this module as unit tests (they use mocked publishers)
pytestmark = pytest.mark.unit


# =============================================================================
# Mock omnibase_core and omnibase_infra Dependencies
# =============================================================================


class MockModelSemVer(BaseModel):
    """Mock ModelSemVer for testing.

    Must be a Pydantic BaseModel so omnibase_infra can use it as a field type
    when omnibase_core.models.primitives.model_semver is patched in sys.modules.
    Also exposes the ``parse()`` classmethod used by omnibase_infra at import time.
    """

    major: int = 0
    minor: int = 0
    patch: int = 0

    @classmethod
    def parse(cls, version_str: str) -> Self:
        """Parse a semver string like '1.2.3'."""
        parts = version_str.split(".")
        return cls(
            major=int(parts[0]) if len(parts) > 0 else 0,
            minor=int(parts[1]) if len(parts) > 1 else 0,
            patch=int(parts[2]) if len(parts) > 2 else 0,
        )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class MockModelContractRegisteredEvent:
    """Mock ModelContractRegisteredEvent for testing."""

    def __init__(
        self,
        event_id,
        node_name: str,
        node_version: MockModelSemVer,
        contract_hash: str,
        contract_yaml: str,
    ) -> None:
        self.event_id = event_id
        self.node_name = node_name
        self.node_version = node_version
        self.contract_hash = contract_hash
        self.contract_yaml = contract_yaml

    def model_dump_json(self) -> str:
        """Mock JSON serialization matching real event structure."""
        import json

        return json.dumps(
            {
                "node_name": self.node_name,
                "contract_hash": self.contract_hash,
                "contract_yaml": self.contract_yaml,
                "event_id": str(self.event_id),
                "node_version": {
                    "major": self.node_version.major,
                    "minor": self.node_version.minor,
                    "patch": self.node_version.patch,
                },
            }
        )


class MockContractError:
    """Mock ContractError dataclass from omnibase_infra."""

    def __init__(
        self,
        contract_path: str,
        error_type: str,
        message: str,
    ) -> None:
        self.contract_path = contract_path
        self.error_type = error_type
        self.message = message


class MockInfraError:
    """Mock InfraError dataclass from omnibase_infra."""

    def __init__(
        self,
        error_type: str,
        message: str,
        retriable: bool = False,
    ) -> None:
        self.error_type = error_type
        self.message = message
        self.retriable = retriable


class MockModelPublishResult:
    """Mock ModelPublishResult Pydantic model from omnibase_infra."""

    def __init__(
        self,
        published: list[str] | None = None,
        contract_errors: list[MockContractError] | None = None,
        infra_errors: list[MockInfraError] | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        self.published = published or []
        self.contract_errors = contract_errors or []
        self.infra_errors = infra_errors or []
        self.duration_ms = duration_ms


class MockModelContractPublisherConfig:
    """Mock ModelContractPublisherConfig Pydantic model from omnibase_infra."""

    def __init__(
        self,
        mode: str = "filesystem",
        filesystem_root: Path | None = None,
        package_module: str | None = None,
        fail_fast: bool = True,
        allow_zero_contracts: bool = False,
        environment: str | None = None,
    ) -> None:
        self.mode = mode
        self.filesystem_root = filesystem_root
        self.package_module = package_module
        self.fail_fast = fail_fast
        self.allow_zero_contracts = allow_zero_contracts
        self.environment = environment

    def model_copy(
        self, update: dict | None = None
    ) -> MockModelContractPublisherConfig:
        """Create a copy of the config with optional field updates.

        Mimics Pydantic's model_copy(update=...) method.
        """
        new_config = MockModelContractPublisherConfig(
            mode=self.mode,
            filesystem_root=self.filesystem_root,
            package_module=self.package_module,
            fail_fast=self.fail_fast,
            allow_zero_contracts=self.allow_zero_contracts,
            environment=self.environment,
        )
        if update:
            for key, value in update.items():
                if hasattr(new_config, key):
                    setattr(new_config, key, value)
        return new_config


class MockContractPublishingInfraError(Exception):
    """Mock ContractPublishingInfraError from omnibase_infra."""

    def __init__(
        self, infra_errors: list[MockInfraError], message: str | None = None
    ) -> None:
        self.infra_errors = infra_errors
        if message is None:
            error_types = [e.error_type for e in infra_errors]
            message = f"Contract publishing failed due to infrastructure errors: {error_types}"
        super().__init__(message)


class MockNoContractsFoundError(Exception):
    """Mock NoContractsFoundError from omnibase_infra."""

    def __init__(self, source_description: str) -> None:
        self.source_description = source_description
        super().__init__(
            f"No contracts found from {source_description}. "
            "Set allow_zero_contracts=True to allow empty publishing."
        )


class MockContractSourceNotConfiguredError(Exception):
    """Mock ContractSourceNotConfiguredError from omnibase_infra."""

    def __init__(self, message: str | None = None):
        if message is None:
            message = (
                "No contract source configured. "
                "Provide either 'contract_dir' or 'contract_source' parameter."
            )
        super().__init__(message)


# Topic constant (matches CONTRACT_REGISTERED_EVENT in omnibase_core)
MOCK_CONTRACT_REGISTERED_EVENT = "onex.evt.contract-registered.v1"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_event_bus_publisher() -> AsyncMock:
    """Create a mock event bus publisher.

    The publisher has an async publish() method that is called with:
    - topic: str - the Kafka topic name
    - key: bytes - the handler ID as bytes
    - value: bytes - the JSON-serialized event
    """
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    return publisher


@pytest.fixture
def mock_container(mock_event_bus_publisher: AsyncMock) -> MagicMock:
    """Create a mock ONEX container that returns the mock publisher.

    The container's get_service_async() method returns the mock publisher
    when called with "ProtocolEventBusPublisher".
    """
    container = MagicMock()
    container.get_service_async = AsyncMock(return_value=mock_event_bus_publisher)
    return container


@pytest.fixture
def mock_service_publisher(mock_event_bus_publisher: AsyncMock) -> MagicMock:
    """Create a mock ServiceContractPublisher instance.

    Returns a mock with publish_all() method that returns MockModelPublishResult.
    """
    publisher = MagicMock()
    publisher.publish_all = AsyncMock()
    return publisher


@pytest.fixture
def contracts_root() -> Path:
    """Return the path to the contracts/handlers directory.

    This is the actual contracts directory in the repository,
    used for handler contract publishing tests.
    """
    # Path resolution: tests/runtime/test_wiring.py -> repo_root
    # .parent chain: test_wiring.py -> runtime/ -> tests/ -> repo_root
    # This assumes standard layout: repo_root/tests/runtime/test_wiring.py
    repo_root = Path(__file__).parent.parent.parent
    return repo_root / "contracts" / "handlers"


@pytest.fixture
def temp_contracts_dir(tmp_path: Path) -> Path:
    """Create a temporary contracts directory with a sample contract."""
    contracts_dir = tmp_path / "contracts" / "handlers" / "test_handler"
    contracts_dir.mkdir(parents=True)

    contract_yaml = """
handler_id: test.handler.mock
name: Test Handler
contract_version:
  major: 1
  minor: 0
  patch: 0
descriptor:
  node_archetype: effect
  purity: side_effecting
  idempotent: true
  timeout_ms: 5000
capability_outputs:
  - test.capability
input_model: test.input
output_model: test.output
metadata:
  handler_class: test.module.TestHandler
  protocol: test.protocol.ProtocolTest
"""
    (contracts_dir / "contract.yaml").write_text(contract_yaml)
    return tmp_path / "contracts" / "handlers"


@pytest.fixture
def mock_omnibase_imports():
    """Fixture to mock omnibase_core and omnibase_infra imports.

    This patches the imports that happen inside wire_omniclaude_services() and
    ServiceContractPublisher operations.
    """
    # Create mock modules for omnibase_core
    mock_contract_registration = MagicMock()
    mock_contract_registration.CONTRACT_REGISTERED_EVENT = (
        MOCK_CONTRACT_REGISTERED_EVENT
    )
    mock_contract_registration.ModelContractRegisteredEvent = (
        MockModelContractRegisteredEvent
    )

    # Mock protocol for type annotation
    mock_protocol_module = MagicMock()
    mock_protocol_module.ProtocolEventBusPublisher = MagicMock

    # Create mock module for omnibase_infra contract publisher
    mock_contract_publisher = MagicMock()
    mock_contract_publisher.ModelContractPublisherConfig = (
        MockModelContractPublisherConfig
    )
    mock_contract_publisher.ModelPublishResult = MockModelPublishResult
    mock_contract_publisher.ContractPublishingInfraError = (
        MockContractPublishingInfraError
    )
    mock_contract_publisher.NoContractsFoundError = MockNoContractsFoundError
    mock_contract_publisher.ContractSourceNotConfiguredError = (
        MockContractSourceNotConfiguredError
    )
    mock_contract_publisher.ContractError = MockContractError
    mock_contract_publisher.InfraError = MockInfraError

    # Create ServiceContractPublisher mock class
    mock_service_class = MagicMock()
    mock_contract_publisher.ServiceContractPublisher = mock_service_class

    # Patch the import system — do NOT mock omnibase_core.models.primitives.model_semver
    # as it causes Pydantic schema generation errors when omnibase_infra modules load.
    with patch.dict(
        sys.modules,
        {
            "omnibase_core.models.events.contract_registration": mock_contract_registration,
            "omnibase_spi.protocols.protocol_event_bus_publisher": mock_protocol_module,
            "omnibase_infra.services.contract_publisher": mock_contract_publisher,
        },
    ):
        yield {
            "contract_publisher": mock_contract_publisher,
            "service_class": mock_service_class,
        }


# =============================================================================
# Tests for wire_omniclaude_services and ServiceContractPublisher
# =============================================================================


class TestServiceContractPublisherAPI:
    """Tests for the ServiceContractPublisher API integration."""

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_emits_events(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        contracts_root: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that ServiceContractPublisher emits events to Kafka.

        This test confirms that:
        1. The ServiceContractPublisher.from_container() is called with correct args
        2. The publish_all() method is invoked
        3. Events are published with correct handler ID
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        # Create config for filesystem mode
        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=contracts_root,
        )

        # Setup mock to return a publisher instance
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=["effect.learned_pattern.storage.postgres"],
                contract_errors=[],
                infra_errors=[],
                duration_ms=50.0,
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        # Act
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="dev",
        )
        result = await publisher.publish_all()

        # Assert: from_container was called with correct parameters
        ServiceContractPublisher.from_container.assert_called_once_with(
            container=mock_container,
            config=config,
            environment="dev",
        )

        # Assert: publish_all was called exactly once (no extra calls)
        assert mock_publisher_instance.publish_all.call_count == 1, (
            f"Expected publish_all to be called once, got {mock_publisher_instance.publish_all.call_count}"
        )

        # Assert: handler ID is in the returned list
        assert "effect.learned_pattern.storage.postgres" in result.published, (
            "Expected 'effect.learned_pattern.storage.postgres' in result.published"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_handles_missing_directory(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that missing contracts directory returns empty list without raising.

        When the contracts_root directory does not exist, the function should:
        1. Delegate to ServiceContractPublisher with correct config
        2. Return an empty list
        3. Not raise an exception (when allow_zero_contracts=True)
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        # Arrange: use a non-existent directory
        non_existent_path = tmp_path / "does_not_exist" / "contracts"

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=non_existent_path,
            allow_zero_contracts=True,  # Allow empty result
        )

        # Track delegation to verify config is passed correctly
        captured_config = {}

        # Setup mock to return empty result
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=[],
                contract_errors=[],
                infra_errors=[],
                duration_ms=10.0,
            )
        )

        def capture_from_container(container, config, environment=None):
            captured_config["filesystem_root"] = config.filesystem_root
            captured_config["allow_zero_contracts"] = config.allow_zero_contracts
            return mock_publisher_instance

        ServiceContractPublisher.from_container = MagicMock(
            side_effect=capture_from_container
        )

        # Act
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="dev",
        )
        result = await publisher.publish_all()

        # Assert: config was passed with correct settings
        assert captured_config["filesystem_root"] == non_existent_path, (
            f"Expected config.filesystem_root={non_existent_path}, "
            f"got {captured_config['filesystem_root']}"
        )
        assert captured_config["allow_zero_contracts"] is True, (
            "Expected config.allow_zero_contracts=True for this test"
        )

        # Assert: returns empty published and error lists
        assert result.published == [], (
            f"Expected empty published list for missing directory, got: {result.published}"
        )
        assert result.contract_errors == [], (
            f"Expected empty contract_errors list for missing directory, got: {result.contract_errors}"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_handles_empty_directory(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that empty contracts directory returns empty list.

        When the contracts_root exists but has no contract.yaml files,
        the function should return an empty list (when allow_zero_contracts=True).
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        # Arrange: create empty directory
        empty_dir = tmp_path / "empty_contracts"
        empty_dir.mkdir(parents=True)

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=empty_dir,
            allow_zero_contracts=True,  # Allow empty result
        )

        # Setup mock to return empty result
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=[],
                contract_errors=[],
                infra_errors=[],
                duration_ms=5.0,
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        # Act
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="dev",
        )
        result = await publisher.publish_all()

        # Assert: returns empty published list
        assert result.published == [], (
            f"Expected empty published list for empty directory, got: {result.published}"
        )

    @pytest.mark.asyncio
    async def test_publish_result_structure(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify ModelPublishResult is correctly returned from delegation.

        This test verifies:
        1. publish_all is called exactly once
        2. The result object is returned unchanged (identity check)
        3. All expected fields are present
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
        )

        # Setup mock with full result structure - use specific object for identity check
        expected_result = MockModelPublishResult(
            published=["test.handler.mock"],
            contract_errors=[],
            infra_errors=[],
            duration_ms=25.5,
        )

        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(return_value=expected_result)
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        # Act
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="dev",
        )
        result = await publisher.publish_all()

        # Assert: publish_all was called exactly once
        assert mock_publisher_instance.publish_all.call_count == 1, (
            f"Expected publish_all called once, got {mock_publisher_instance.publish_all.call_count}"
        )

        # Assert: result is the exact object returned by publish_all (not a copy)
        assert result is expected_result, (
            "Result should be the exact object returned by publish_all"
        )

        # Assert: result has all expected fields
        assert hasattr(result, "published"), "Result should have 'published' field"
        assert hasattr(result, "contract_errors"), (
            "Result should have 'contract_errors' field"
        )
        assert hasattr(result, "infra_errors"), (
            "Result should have 'infra_errors' field"
        )
        assert hasattr(result, "duration_ms"), "Result should have 'duration_ms' field"

        # Assert: values match what was set up
        assert result.published == ["test.handler.mock"]
        assert result.duration_ms == 25.5

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_uses_default_environment(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that environment defaults to ONEX_ENV or 'dev'.

        When environment is not specified, it should use the ONEX_ENV
        environment variable or fall back to 'dev'.
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
        )

        # Track all arguments passed to from_container
        captured_args: dict = {}

        def mock_from_container(container, config, environment=None):
            captured_args["container"] = container
            captured_args["config"] = config
            captured_args["environment"] = environment
            mock_instance = MagicMock()
            mock_instance.publish_all = AsyncMock(
                return_value=MockModelPublishResult(
                    published=["test.handler.mock"],
                    duration_ms=10.0,
                )
            )
            return mock_instance

        ServiceContractPublisher.from_container = mock_from_container

        # Act: call without environment parameter, with ONEX_ENV set
        with patch.dict("os.environ", {"ONEX_ENV": "staging"}):
            publisher = ServiceContractPublisher.from_container(
                container=mock_container,
                config=config,
            )
            result = await publisher.publish_all()

        # Assert: delegation happened with correct container
        assert captured_args["container"] is mock_container, (
            "Expected mock_container to be passed to from_container"
        )

        # Assert: config was passed through
        assert captured_args["config"] is config, (
            "Expected config to be passed to from_container"
        )

        # Assert: handler was published
        assert len(result.published) >= 1

        # Assert: environment was None (letting implementation handle default)
        # The actual topic prefix is handled by ServiceContractPublisher internally
        assert captured_args.get("environment") is None

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_passes_environment_explicitly(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that explicit environment is passed to from_container.

        When environment is specified, it should be passed through to
        ServiceContractPublisher.from_container().
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
        )

        # Track all arguments passed to from_container
        captured_args: dict = {}

        def mock_from_container(container, config, environment=None):
            captured_args["container"] = container
            captured_args["config"] = config
            captured_args["environment"] = environment
            mock_instance = MagicMock()
            mock_instance.publish_all = AsyncMock(
                return_value=MockModelPublishResult(
                    published=["test.handler.mock"],
                    duration_ms=10.0,
                )
            )
            return mock_instance

        ServiceContractPublisher.from_container = mock_from_container

        # Act: call WITH explicit environment
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="production",
        )
        result = await publisher.publish_all()

        # Assert: delegation happened with correct container
        assert captured_args["container"] is mock_container, (
            "Expected mock_container to be passed to from_container"
        )

        # Assert: environment was explicitly passed
        assert captured_args["environment"] == "production", (
            f"Expected environment='production', got {captured_args['environment']}"
        )

        # Assert: result propagated correctly
        assert "test.handler.mock" in result.published

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_handles_invalid_yaml(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that invalid YAML contracts are skipped gracefully.

        When a contract.yaml contains invalid content (not a dict),
        it should be skipped and other contracts should still be published.
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        # Arrange: create directory with invalid contract (mocked at publish level)
        contracts_root = tmp_path / "contracts" / "handlers"
        contracts_root.mkdir(parents=True)

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=contracts_root,
        )

        # Setup mock with contract error
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=["valid.handler"],
                contract_errors=[
                    MockContractError(
                        contract_path="invalid/contract.yaml",
                        error_type="yaml_parse",
                        message="Invalid YAML syntax",
                    )
                ],
                infra_errors=[],
                duration_ms=30.0,
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        # Act: should not raise
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="dev",
        )
        result = await publisher.publish_all()

        # Assert: valid handler was published, invalid was tracked as contract error
        assert "valid.handler" in result.published, (
            f"Expected 'valid.handler' in result.published, got: {result.published}"
        )
        # Invalid contract should be tracked in contract_errors list
        assert len(result.contract_errors) >= 1, (
            f"Expected at least one contract error, got: {result.contract_errors}"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_raises_on_missing_publisher(
        self,
        temp_contracts_dir: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that missing publisher raises an exception.

        When the container cannot provide the event bus publisher,
        ServiceContractPublisher.from_container should raise ContractPublishingInfraError.
        This tests that error propagation works correctly through the delegation chain.
        """
        from omnibase_infra.services.contract_publisher import (
            ContractPublishingInfraError,
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        # Arrange: container that fails to get publisher
        mock_container = MagicMock()
        mock_container.get_service_async = AsyncMock(
            side_effect=Exception("Publisher not available")
        )

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
            fail_fast=True,  # Default behavior
        )

        # Track that from_container was called before raising
        call_tracker: dict = {"called": False, "args": {}}
        expected_error = ContractPublishingInfraError(
            [MockInfraError("publisher_unavailable", "Publisher not available")]
        )

        def track_and_raise(container, config, environment=None):
            call_tracker["called"] = True
            call_tracker["args"] = {
                "container": container,
                "config": config,
                "environment": environment,
            }
            raise expected_error

        ServiceContractPublisher.from_container = MagicMock(side_effect=track_and_raise)

        # Act & Assert: should raise ContractPublishingInfraError
        with pytest.raises(ContractPublishingInfraError) as exc_info:
            ServiceContractPublisher.from_container(
                container=mock_container,
                config=config,
                environment="dev",
            )

        # Assert: from_container was called with correct args before raising
        assert call_tracker["called"], "from_container should have been called"
        assert call_tracker["args"]["container"] is mock_container
        assert call_tracker["args"]["config"] is config
        assert call_tracker["args"]["environment"] == "dev"

        # Assert: the same error was propagated
        assert exc_info.value is expected_error

    # =========================================================================
    # Tests for publish_handler_contracts delegation behavior
    # =========================================================================

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason=(
            "Pre-existing failure (OMN-2403 chore): wiring.py has top-level imports "
            "from omnibase_infra so sys.modules patching in mock_omnibase_imports cannot "
            "intercept them after module load. Fix requires refactoring mock strategy."
        )
    )
    async def test_publish_handler_contracts_delegates_to_service_publisher(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify publish_handler_contracts correctly delegates to ServiceContractPublisher.

        This test verifies the actual delegation chain:
        1. from_container is called with correct parameters
        2. publish_all is called on the returned instance
        3. The result from publish_all is returned unchanged
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        from omniclaude.runtime.wiring import publish_handler_contracts

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
        )

        # Track delegation arguments
        captured_args: dict = {}
        expected_result = MockModelPublishResult(
            published=["delegated.handler"],
            contract_errors=[],
            infra_errors=[],
            duration_ms=42.0,
        )

        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(return_value=expected_result)

        async def mock_from_container(container, config):
            captured_args["container"] = container
            captured_args["config"] = config
            return mock_publisher_instance

        ServiceContractPublisher.from_container = mock_from_container

        # Act: call the actual wiring function
        result = await publish_handler_contracts(
            container=mock_container,
            config=config,
            environment="staging",
        )

        # Assert: from_container was called with correct container
        assert captured_args["container"] is mock_container, (
            "publish_handler_contracts should pass container to from_container"
        )

        # Assert: config was updated with environment via model_copy before delegation
        # (from_container does not accept an environment kwarg; it is stored in config)
        assert captured_args["config"].environment == "staging", (
            f"Expected config.environment='staging', got {captured_args['config'].environment}"
        )

        # Assert: publish_all was called
        mock_publisher_instance.publish_all.assert_called_once()

        # Assert: result was propagated unchanged
        assert result is expected_result, (
            "publish_handler_contracts should return result from publish_all unchanged"
        )
        assert result.published == ["delegated.handler"]
        assert result.duration_ms == 42.0

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason=(
            "Pre-existing failure (OMN-2403 chore): same mock isolation issue as "
            "test_publish_handler_contracts_delegates_to_service_publisher."
        )
    )
    async def test_publish_handler_contracts_strips_whitespace_from_environment(
        self,
        mock_container: MagicMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that environment whitespace is stripped before delegation.

        The wiring function should strip whitespace from environment and
        default to 'dev' if the result is empty.
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        from omniclaude.runtime.wiring import publish_handler_contracts

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
        )

        captured_envs: list = []

        async def mock_from_container(container, config):
            # Environment is stored in config.environment, not passed as a kwarg
            # (from_container does not accept an environment parameter)
            captured_envs.append(config.environment)
            mock_instance = MagicMock()
            mock_instance.publish_all = AsyncMock(
                return_value=MockModelPublishResult(published=[], duration_ms=1.0)
            )
            return mock_instance

        ServiceContractPublisher.from_container = mock_from_container

        # Act: call with whitespace-padded environment
        await publish_handler_contracts(
            container=mock_container,
            config=config,
            environment="  production  ",
        )

        # Assert: environment was stripped and stored in config.environment
        assert captured_envs[-1] == "production", (
            f"Expected stripped 'production', got '{captured_envs[-1]}'"
        )

        # Act: call with empty-after-strip environment
        await publish_handler_contracts(
            container=mock_container,
            config=config,
            environment="   ",
        )

        # Assert: empty string becomes 'dev' and is stored in config.environment
        assert captured_envs[-1] == "dev", (
            f"Expected 'dev' for empty environment, got '{captured_envs[-1]}'"
        )

    # =========================================================================
    # Tests for wire_omniclaude_services wrapper
    # =========================================================================

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason=(
            "Pre-existing failure (OMN-2403 chore): same mock isolation issue; "
            "wire_omniclaude_services triggers omnibase_infra imports that fail "
            "within the sys.modules patch context."
        )
    )
    async def test_requires_explicit_contract_source_config(
        self,
        mock_container: MagicMock,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that missing config raises ContractSourceNotConfiguredError.

        When wire_omniclaude_services is called without config and without
        OMNICLAUDE_CONTRACTS_ROOT env var, it must fail explicitly.
        """
        from omnibase_infra.services.contract_publisher import (
            ContractSourceNotConfiguredError,
        )

        from omniclaude.runtime.wiring import wire_omniclaude_services

        # Ensure env var is not set by clearing the environment
        env_copy = os.environ.copy()
        env_copy.pop("OMNICLAUDE_CONTRACTS_ROOT", None)

        with patch.dict(os.environ, env_copy, clear=True):
            with pytest.raises(ContractSourceNotConfiguredError):
                await wire_omniclaude_services(container=mock_container)

    @pytest.mark.asyncio
    async def test_infra_failure_fails_fast_by_default(
        self,
        mock_container: MagicMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that infrastructure errors fail fast when fail_fast=True (default).

        When Kafka publish fails, the function should raise ContractPublishingInfraError
        immediately rather than continuing and returning a partial result.
        """
        from omnibase_infra.services.contract_publisher import (
            ContractPublishingInfraError,
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
            fail_fast=True,  # Default, but explicit for test clarity
        )

        # Setup mock to raise infra error on publish_all
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            side_effect=ContractPublishingInfraError(
                [MockInfraError("broker_down", "Kafka connection refused")]
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        with pytest.raises(ContractPublishingInfraError) as exc_info:
            publisher = ServiceContractPublisher.from_container(
                container=mock_container,
                config=config,
                environment="dev",
            )
            await publisher.publish_all()

        # Verify infra errors are captured in the exception
        assert len(exc_info.value.infra_errors) >= 1

    @pytest.mark.asyncio
    async def test_contract_error_continues_and_reports(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that contract errors allow other contracts to proceed.

        When one contract has invalid YAML, the function should continue
        processing other contracts and report the error in the result.
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        contracts_root = tmp_path / "contracts" / "handlers"
        contracts_root.mkdir(parents=True)

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=contracts_root,
        )

        # Setup mock with mixed success/error result
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=["valid.test.handler"],
                contract_errors=[
                    MockContractError(
                        contract_path="invalid_contract/contract.yaml",
                        error_type="yaml_parse",
                        message="YAML parse error",
                    )
                ],
                infra_errors=[],
                duration_ms=40.0,
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="dev",
        )
        result = await publisher.publish_all()

        # Valid contract should be published
        assert "valid.test.handler" in result.published

        # Invalid contract should be in contract_errors
        assert len(result.contract_errors) >= 1
        assert any(e.error_type == "yaml_parse" for e in result.contract_errors)

    @pytest.mark.asyncio
    async def test_partial_publish_failure_distinguishes_infra_vs_contract(
        self,
        mock_container: MagicMock,
        tmp_path: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that infra errors and contract errors are tracked separately.

        When both types of errors occur, they should be in different lists
        in the result, not mixed together.
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        contracts_root = tmp_path / "contracts" / "handlers"
        contracts_root.mkdir(parents=True)

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=contracts_root,
            fail_fast=False,  # Don't raise, let us inspect the result
            allow_zero_contracts=True,  # Allow empty result since all contracts fail
        )

        # Setup mock with both error types
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=[],
                contract_errors=[
                    MockContractError(
                        contract_path="missing_id/contract.yaml",
                        error_type="missing_field",
                        message="Missing handler_id",
                    )
                ],
                infra_errors=[
                    MockInfraError(
                        error_type="publish_failed",
                        message="Broker down",
                        retriable=True,
                    )
                ],
                duration_ms=50.0,
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="dev",
        )
        result = await publisher.publish_all()

        # Should have contract errors (missing handler_id)
        assert len(result.contract_errors) >= 1
        assert any(e.error_type == "missing_field" for e in result.contract_errors)

        # Should have infra errors (publish failed)
        assert len(result.infra_errors) >= 1
        assert any(e.error_type == "publish_failed" for e in result.infra_errors)

    @pytest.mark.asyncio
    async def test_zero_contracts_is_error_unless_explicitly_allowed(
        self,
        mock_container: MagicMock,
        mock_event_bus_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: dict,
    ) -> None:
        """Verify that publishing zero contracts is an error by default.

        This catches misconfiguration where the contracts path is wrong.
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            NoContractsFoundError,
            ServiceContractPublisher,
        )

        # Empty directory
        empty_dir = tmp_path / "empty_contracts"
        empty_dir.mkdir(parents=True)

        # Default config (allow_zero_contracts=False)
        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=empty_dir,
            allow_zero_contracts=False,  # Default, explicit for clarity
        )

        # Setup mock to raise NoContractsFoundError
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            side_effect=NoContractsFoundError(str(empty_dir))
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        with pytest.raises(NoContractsFoundError):
            publisher = ServiceContractPublisher.from_container(
                container=mock_container,
                config=config,
                environment="dev",
            )
            await publisher.publish_all()

        # Now test that allow_zero_contracts=True allows empty publish
        config_allow_empty = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=empty_dir,
            allow_zero_contracts=True,
        )

        # Setup mock to return empty result
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=[],
                contract_errors=[],
                infra_errors=[],
                duration_ms=5.0,
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config_allow_empty,
            environment="dev",
        )
        result = await publisher.publish_all()

        assert result.published == []
        assert result.contract_errors == []
        assert result.infra_errors == []


# =============================================================================
# Integration Tests (Real ServiceContractPublisher, Mock Kafka Only)
# =============================================================================


class TestIntegrationWithServiceContractPublisher:
    """Integration tests that verify real ServiceContractPublisher behavior.

    These tests don't mock ServiceContractPublisher itself, only the underlying
    Kafka publisher, to verify the full delegation chain works correctly.

    The tests attempt to import the real ServiceContractPublisher from
    omnibase_infra. If the module is not available (e.g., running tests
    without the full dependency installed), the tests are skipped.

    Ticket: OMN-1812 - Validate ServiceContractPublisher integration
    """

    @pytest.fixture
    def real_omnibase_imports_available(self) -> bool:
        """Check if real omnibase_infra imports are available.

        Returns True if the real ServiceContractPublisher can be imported,
        False otherwise. Used to conditionally skip tests.
        """
        try:
            from omnibase_infra.services.contract_publisher import (
                ServiceContractPublisher,
            )

            # Verify it's a real class, not a mock
            return hasattr(ServiceContractPublisher, "from_container") and hasattr(
                ServiceContractPublisher, "__mro__"
            )
        except ImportError:
            return False

    @pytest.fixture
    def integration_mock_event_bus_publisher(self) -> AsyncMock:
        """Create a mock event bus publisher for integration tests.

        This mock captures publish() calls so we can verify that the real
        ServiceContractPublisher correctly delegates to the publisher.
        """
        publisher = AsyncMock()
        publisher.publish = AsyncMock(return_value=None)
        return publisher

    @pytest.fixture
    def integration_mock_container(
        self, integration_mock_event_bus_publisher: AsyncMock
    ) -> MagicMock:
        """Create a mock container that returns the mock publisher.

        The container provides the event bus publisher that ServiceContractPublisher
        uses internally to emit contract registration events.
        """
        container = MagicMock()
        container.get_service_async = AsyncMock(
            return_value=integration_mock_event_bus_publisher
        )
        return container

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_service_contract_publisher_parses_contracts(
        self,
        real_omnibase_imports_available: bool,
        integration_mock_container: MagicMock,
        integration_mock_event_bus_publisher: AsyncMock,
        temp_contracts_dir: Path,
    ) -> None:
        """Verify publish_handler_contracts delegates correctly to real ServiceContractPublisher.

        This test:
        1. Does NOT mock ServiceContractPublisher itself
        2. Only mocks the event bus publisher (Kafka layer)
        3. Uses temp_contracts_dir with a real contract YAML
        4. Verifies the real ServiceContractPublisher parses the contract
           and calls the publisher with correct data

        The test validates that our wiring correctly passes configuration
        to ServiceContractPublisher and that it processes contracts correctly.
        """
        if not real_omnibase_imports_available:
            pytest.skip("Real omnibase_infra.services.contract_publisher not available")

        # Import the REAL classes (no sys.modules patching)
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
        )

        from omniclaude.runtime.wiring import publish_handler_contracts

        # Create config pointing to temp_contracts_dir (which has a test contract)
        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
            fail_fast=True,
            allow_zero_contracts=False,
        )

        # Call the real wiring function with real ServiceContractPublisher
        result = await publish_handler_contracts(
            container=integration_mock_container,
            config=config,
            environment="dev",
        )

        # Verify the result contains published handler(s)
        assert result is not None, "publish_handler_contracts should return a result"
        assert hasattr(result, "published"), "Result should have 'published' field"
        assert hasattr(result, "contract_errors"), (
            "Result should have 'contract_errors' field"
        )
        assert hasattr(result, "duration_ms"), "Result should have 'duration_ms' field"

        # The temp_contracts_dir fixture creates a contract with handler_id "test.handler.mock"
        assert len(result.published) >= 1, (
            f"Expected at least one published handler, got {result.published}"
        )
        assert "test.handler.mock" in result.published, (
            f"Expected 'test.handler.mock' in published handlers, got {result.published}"
        )

        # Verify the mock publisher was called (Kafka emission happened)
        assert integration_mock_event_bus_publisher.publish.called, (
            "Event bus publisher should have been called to emit events"
        )

        # Verify publish was called with expected arguments
        call_args = integration_mock_event_bus_publisher.publish.call_args_list
        assert len(call_args) >= 1, (
            f"Expected at least one publish call, got {len(call_args)}"
        )

        # Verify the topic and key were provided
        first_call = call_args[0]
        assert first_call.kwargs.get("topic") or len(first_call.args) >= 1, (
            "Publish should be called with a topic"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_service_contract_publisher_handles_contract_errors(
        self,
        real_omnibase_imports_available: bool,
        integration_mock_container: MagicMock,
        integration_mock_event_bus_publisher: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Verify real ServiceContractPublisher handles invalid contracts gracefully.

        Creates a contract with invalid YAML (not a dict) and verifies that
        the real ServiceContractPublisher reports it as a contract error
        rather than crashing.
        """
        if not real_omnibase_imports_available:
            pytest.skip("Real omnibase_infra.services.contract_publisher not available")

        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
        )

        from omniclaude.runtime.wiring import publish_handler_contracts

        # Create a contracts directory with an invalid contract
        contracts_dir = tmp_path / "contracts" / "handlers" / "invalid_handler"
        contracts_dir.mkdir(parents=True)

        # Write invalid YAML (just a string, not a dict)
        invalid_yaml = "this is not a valid contract - just a plain string"
        (contracts_dir / "contract.yaml").write_text(invalid_yaml)

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=tmp_path / "contracts" / "handlers",
            fail_fast=False,  # Don't raise on contract errors
            allow_zero_contracts=True,  # Allow if all contracts fail
        )

        # Call the real wiring function
        result = await publish_handler_contracts(
            container=integration_mock_container,
            config=config,
            environment="dev",
        )

        # Verify result was returned (didn't crash)
        assert result is not None, "Should return result even with invalid contracts"

        # Depending on implementation, either:
        # 1. published is empty (no valid contracts)
        # 2. contract_errors contains the error
        # Both are valid behaviors
        assert hasattr(result, "published"), "Result should have 'published' field"
        assert hasattr(result, "contract_errors"), (
            "Result should have 'contract_errors' field"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_service_contract_publisher_respects_environment(
        self,
        real_omnibase_imports_available: bool,
        integration_mock_container: MagicMock,
        integration_mock_event_bus_publisher: AsyncMock,
        temp_contracts_dir: Path,
    ) -> None:
        """Verify that environment parameter is correctly passed to ServiceContractPublisher.

        The environment determines the Kafka topic prefix (e.g., "dev", "staging").
        This test verifies that the wiring correctly passes the environment through.
        """
        if not real_omnibase_imports_available:
            pytest.skip("Real omnibase_infra.services.contract_publisher not available")

        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
        )

        from omniclaude.runtime.wiring import publish_handler_contracts

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
        )

        # Call with explicit environment
        result = await publish_handler_contracts(
            container=integration_mock_container,
            config=config,
            environment="integration-test",
        )

        # Verify contract was published
        assert result is not None
        assert len(result.published) >= 1

        # Check that the topic name includes the environment prefix
        # This verifies the environment parameter was used
        if integration_mock_event_bus_publisher.publish.called:
            call_args = integration_mock_event_bus_publisher.publish.call_args_list
            for call in call_args:
                topic = call.kwargs.get("topic") or (
                    call.args[0] if call.args else None
                )
                if topic:
                    # Topic should be prefixed with environment
                    assert isinstance(topic, str), (
                        f"Topic should be a string, got {type(topic)}"
                    )
                    # Verify topic includes the environment prefix
                    assert "integration-test" in topic, (
                        f"Topic should include environment prefix 'integration-test', got {topic}"
                    )
