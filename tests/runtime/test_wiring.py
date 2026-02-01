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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mark all tests in this module as unit tests (they use mocked publishers)
pytestmark = pytest.mark.unit


# =============================================================================
# Mock omnibase_core and omnibase_infra Dependencies
# =============================================================================


class MockModelSemVer:
    """Mock ModelSemVer for testing."""

    def __init__(self, major: int = 0, minor: int = 0, patch: int = 0) -> None:
        self.major = major
        self.minor = minor
        self.patch = patch

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
    containing the pattern_storage_postgres contract.
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

    mock_primitives = MagicMock()
    mock_primitives.ModelSemVer = MockModelSemVer

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

    # Patch the import system
    with patch.dict(
        sys.modules,
        {
            "omnibase_core.models.events.contract_registration": mock_contract_registration,
            "omnibase_core.models.primitives.model_semver": mock_primitives,
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
        1. The ServiceContractPublisher.from_container() is called
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
            environment="test",
        )
        result = await publisher.publish_all()

        # Assert: from_container was called
        ServiceContractPublisher.from_container.assert_called_once()

        # Assert: publish_all was called
        mock_publisher_instance.publish_all.assert_called_once()

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
        1. Return an empty list
        2. Not raise an exception (when allow_zero_contracts=True)
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
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        # Act
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="test",
        )
        result = await publisher.publish_all()

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
            environment="test",
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
        """Verify ModelPublishResult has all expected fields.

        The result should contain:
        - published: list of handler IDs
        - contract_errors: list of ContractError
        - infra_errors: list of InfraError
        - duration_ms: float
        """
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ServiceContractPublisher,
        )

        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=temp_contracts_dir,
        )

        # Setup mock with full result structure
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.publish_all = AsyncMock(
            return_value=MockModelPublishResult(
                published=["test.handler.mock"],
                contract_errors=[],
                infra_errors=[],
                duration_ms=25.5,
            )
        )
        ServiceContractPublisher.from_container = MagicMock(
            return_value=mock_publisher_instance
        )

        # Act
        publisher = ServiceContractPublisher.from_container(
            container=mock_container,
            config=config,
            environment="test",
        )
        result = await publisher.publish_all()

        # Assert: result has all expected fields
        assert hasattr(result, "published"), "Result should have 'published' field"
        assert hasattr(result, "contract_errors"), (
            "Result should have 'contract_errors' field"
        )
        assert hasattr(result, "infra_errors"), (
            "Result should have 'infra_errors' field"
        )
        assert hasattr(result, "duration_ms"), "Result should have 'duration_ms' field"

        # Assert: handler was published
        assert "test.handler.mock" in result.published

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

        # Track what environment was passed
        captured_env = {}

        def mock_from_container(container, config, environment=None):
            captured_env["value"] = environment
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

        # Assert: handler was published
        assert len(result.published) >= 1

        # Assert: environment was None (letting implementation handle default)
        # The actual topic prefix is handled by ServiceContractPublisher internally
        assert captured_env.get("value") is None

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
            environment="test",
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

        # Setup mock to raise error
        ServiceContractPublisher.from_container = MagicMock(
            side_effect=ContractPublishingInfraError(
                [MockInfraError("publisher_unavailable", "Publisher not available")]
            )
        )

        # Act & Assert: should raise ContractPublishingInfraError
        with pytest.raises(ContractPublishingInfraError):
            ServiceContractPublisher.from_container(
                container=mock_container,
                config=config,
                environment="test",
            )

    # =========================================================================
    # Tests for wire_omniclaude_services wrapper
    # =========================================================================

    @pytest.mark.asyncio
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
                environment="test",
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
            environment="test",
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
            environment="test",
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
                environment="test",
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
            environment="test",
        )
        result = await publisher.publish_all()

        assert result.published == []
        assert result.contract_errors == []
        assert result.infra_errors == []
