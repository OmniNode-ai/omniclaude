# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for publish_handler_contracts() function.

Tests verify that handler contracts are correctly published to Kafka
via the event bus publisher. These tests use mocked publishers to
avoid requiring real Kafka infrastructure.

Ticket: OMN-1605 - Implement contract-driven handler registration loader
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

# Mark all tests in this module as integration tests (they read real contract files)
pytestmark = pytest.mark.integration


# =============================================================================
# Mock omnibase_core Dependencies
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
        event_id: UUID,
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


# Topic suffix constant
MOCK_TOPIC_SUFFIX = "onex.evt.omninode.contract-registered.v1"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_publisher() -> AsyncMock:
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
def mock_container(mock_publisher: AsyncMock) -> MagicMock:
    """Create a mock ONEX container that returns the mock publisher.

    The container's get_service_async() method returns the mock publisher
    when called with "ProtocolEventBusPublisher".
    """
    container = MagicMock()
    container.get_service_async = AsyncMock(return_value=mock_publisher)
    return container


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
    """Fixture to mock omnibase_core imports required by wiring.py.

    This patches the imports that happen inside publish_handler_contracts().
    """
    # Create mock modules
    mock_contract_registration = MagicMock()
    mock_contract_registration.TOPIC_SUFFIX_CONTRACT_REGISTERED = MOCK_TOPIC_SUFFIX
    mock_contract_registration.ModelContractRegisteredEvent = (
        MockModelContractRegisteredEvent
    )

    mock_primitives = MagicMock()
    mock_primitives.ModelSemVer = MockModelSemVer

    # Patch the import system
    with patch.dict(
        sys.modules,
        {
            "omnibase_core.models.events.contract_registration": mock_contract_registration,
            "omnibase_core.models.primitives.model_semver": mock_primitives,
        },
    ):
        yield


# =============================================================================
# Tests for publish_handler_contracts
# =============================================================================


class TestPublishHandlerContracts:
    """Tests for the publish_handler_contracts() function."""

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_emits_events(
        self,
        mock_container: MagicMock,
        mock_publisher: AsyncMock,
        contracts_root: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that publish_handler_contracts emits events to Kafka.

        This test confirms that:
        1. The function calls publisher.publish()
        2. The handler ID 'effect.learned_pattern.storage.postgres' is returned
        3. The topic includes the environment prefix
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Act
        result = await publish_handler_contracts(
            container=mock_container,
            contracts_root=contracts_root,
            environment="test",
        )

        # Assert: publisher.publish was called
        assert mock_publisher.publish.called, (
            "Expected publisher.publish() to be called"
        )

        # Assert: handler ID is in the returned list
        assert "effect.learned_pattern.storage.postgres" in result.published, (
            "Expected 'effect.learned_pattern.storage.postgres' in result.published"
        )

        # Assert: at least one publish call was made
        assert mock_publisher.publish.call_count >= 1, (
            "Expected at least one publish call"
        )

        # Assert: the topic includes environment prefix
        call_args = mock_publisher.publish.call_args
        assert call_args is not None
        topic = call_args.kwargs.get("topic") or call_args.args[0]
        assert topic.startswith("test."), (
            f"Expected topic to start with 'test.', got: {topic}"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_handles_missing_directory(
        self,
        mock_container: MagicMock,
        mock_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that missing contracts directory returns empty list without raising.

        When the contracts_root directory does not exist, the function should:
        1. Return an empty list
        2. Not raise an exception
        3. Not call publisher.publish()
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Arrange: use a non-existent directory
        non_existent_path = tmp_path / "does_not_exist" / "contracts"

        # Act
        result = await publish_handler_contracts(
            container=mock_container,
            contracts_root=non_existent_path,
            environment="test",
        )

        # Assert: returns empty published and failed lists
        assert result.published == [], (
            f"Expected empty published list for missing directory, got: {result.published}"
        )
        assert result.failed == [], (
            f"Expected empty failed list for missing directory, got: {result.failed}"
        )

        # Assert: publisher.publish was NOT called
        assert not mock_publisher.publish.called, (
            "Expected publisher.publish() NOT to be called for missing directory"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_handles_empty_directory(
        self,
        mock_container: MagicMock,
        mock_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that empty contracts directory returns empty list.

        When the contracts_root exists but has no contract.yaml files,
        the function should return an empty list.
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Arrange: create empty directory
        empty_dir = tmp_path / "empty_contracts"
        empty_dir.mkdir(parents=True)

        # Act
        result = await publish_handler_contracts(
            container=mock_container,
            contracts_root=empty_dir,
            environment="test",
        )

        # Assert: returns empty published list
        assert result.published == [], (
            f"Expected empty published list for empty directory, got: {result.published}"
        )

        # Assert: publisher.publish was NOT called
        assert not mock_publisher.publish.called, (
            "Expected publisher.publish() NOT to be called for empty directory"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_uses_correct_key(
        self,
        mock_container: MagicMock,
        mock_publisher: AsyncMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that the publish call uses handler_id as the key.

        The key should be the handler_id encoded as UTF-8 bytes.
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Act
        result = await publish_handler_contracts(
            container=mock_container,
            contracts_root=temp_contracts_dir,
            environment="test",
        )

        # Assert: handler was published
        assert "test.handler.mock" in result.published

        # Assert: key was the handler_id as bytes
        call_args = mock_publisher.publish.call_args
        assert call_args is not None
        key = call_args.kwargs.get("key") or call_args.args[1]
        assert key == b"test.handler.mock", (
            f"Expected key to be b'test.handler.mock', got: {key}"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_uses_default_environment(
        self,
        mock_container: MagicMock,
        mock_publisher: AsyncMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that environment defaults to ONEX_ENV or 'dev'.

        When environment is not specified, it should use the ONEX_ENV
        environment variable or fall back to 'dev'.
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Act: call without environment parameter
        with patch.dict("os.environ", {"ONEX_ENV": "staging"}):
            result = await publish_handler_contracts(
                container=mock_container,
                contracts_root=temp_contracts_dir,
            )

        # Assert: handler was published
        assert len(result.published) >= 1

        # Assert: topic uses staging environment
        call_args = mock_publisher.publish.call_args
        assert call_args is not None
        topic = call_args.kwargs.get("topic") or call_args.args[0]
        assert topic.startswith("staging."), (
            f"Expected topic to start with 'staging.', got: {topic}"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_gets_publisher_from_container(
        self,
        mock_container: MagicMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that the function retrieves publisher from container.

        The function should call container.get_service_async() with
        "ProtocolEventBusPublisher" to obtain the publisher.
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Act
        await publish_handler_contracts(
            container=mock_container,
            contracts_root=temp_contracts_dir,
            environment="test",
        )

        # Assert: get_service_async was called with correct argument
        mock_container.get_service_async.assert_called_once_with(
            "ProtocolEventBusPublisher"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_handles_invalid_yaml(
        self,
        mock_container: MagicMock,
        mock_publisher: AsyncMock,
        tmp_path: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that invalid YAML contracts are skipped gracefully.

        When a contract.yaml contains invalid content (not a dict),
        it should be skipped and other contracts should still be published.
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Arrange: create directory with invalid contract
        invalid_dir = tmp_path / "contracts" / "handlers" / "invalid"
        invalid_dir.mkdir(parents=True)
        (invalid_dir / "contract.yaml").write_text("not a dict - just a string")

        # Also create a valid contract
        valid_dir = tmp_path / "contracts" / "handlers" / "valid"
        valid_dir.mkdir(parents=True)
        valid_yaml = """
handler_id: valid.handler
name: Valid Handler
contract_version:
  major: 1
  minor: 0
  patch: 0
"""
        (valid_dir / "contract.yaml").write_text(valid_yaml)

        contracts_root = tmp_path / "contracts" / "handlers"

        # Act: should not raise
        result = await publish_handler_contracts(
            container=mock_container,
            contracts_root=contracts_root,
            environment="test",
        )

        # Assert: valid handler was published, invalid was tracked as failed
        assert "valid.handler" in result.published, (
            f"Expected 'valid.handler' in result.published, got: {result.published}"
        )
        # Invalid contract should be tracked in failed list (not crash the function)
        assert len(result.failed) >= 1, (
            f"Expected at least one failed contract, got: {result.failed}"
        )

    @pytest.mark.asyncio
    async def test_publish_handler_contracts_raises_on_missing_publisher(
        self,
        temp_contracts_dir: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify that missing publisher raises an exception.

        When the container cannot provide the event bus publisher,
        the function should raise an exception.
        """
        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Arrange: container that fails to get publisher
        mock_container = MagicMock()
        mock_container.get_service_async = AsyncMock(
            side_effect=Exception("Publisher not available")
        )

        # Act & Assert: should raise
        with pytest.raises(Exception, match="Publisher not available"):
            await publish_handler_contracts(
                container=mock_container,
                contracts_root=temp_contracts_dir,
                environment="test",
            )

    @pytest.mark.asyncio
    async def test_published_event_structure_is_deserializable(
        self,
        mock_container: MagicMock,
        mock_publisher: AsyncMock,
        temp_contracts_dir: Path,
        mock_omnibase_imports: None,
    ) -> None:
        """Verify published event structure matches KafkaContractSource expectations.

        This test ensures the serialized event can be deserialized and contains
        all fields required by KafkaContractSource for handler discovery.

        KafkaContractSource expects:
        - node_name: Handler identifier for routing
        - contract_hash: SHA-256 hash for change detection
        - contract_yaml: Raw YAML for contract parsing
        - node_version: SemVer for version tracking
        """
        import json

        # Import after mocks are in place
        from omniclaude.runtime.wiring import publish_handler_contracts

        # Act
        result = await publish_handler_contracts(
            container=mock_container,
            contracts_root=temp_contracts_dir,
            environment="test",
        )

        # Assert: handler was published
        assert "test.handler.mock" in result.published

        # Get the published value (JSON bytes)
        call_args = mock_publisher.publish.call_args
        assert call_args is not None
        value_bytes = call_args.kwargs.get("value") or call_args.args[2]

        # Verify it's valid JSON
        event_json = value_bytes.decode("utf-8")
        event_data = json.loads(event_json)

        # Verify required fields for KafkaContractSource
        assert "node_name" in event_data, (
            "Published event must contain 'node_name' for KafkaContractSource routing"
        )
        assert event_data["node_name"] == "test.handler.mock", (
            f"node_name should be handler_id, got: {event_data['node_name']}"
        )

        assert "contract_hash" in event_data, (
            "Published event must contain 'contract_hash' for change detection"
        )
        # SHA-256 hex digest is 64 characters
        assert len(event_data["contract_hash"]) == 64, (
            f"contract_hash should be 64-char SHA-256 hex, got length: {len(event_data['contract_hash'])}"
        )

        assert "contract_yaml" in event_data, (
            "Published event must contain 'contract_yaml' for contract parsing"
        )
