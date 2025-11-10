#!/usr/bin/env python3
"""
Test fixtures and configuration for Phase 2 Stream D testing.

Provides comprehensive fixtures for:
- Contract validation testing
- Pipeline execution testing
- Node generation testing
- Performance benchmarking
"""

import asyncio
from pathlib import Path
from typing import Dict
from uuid import uuid4

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file for distributed testing
# This ensures tests use the correct remote infrastructure configuration
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
    print(f"✅ Loaded .env configuration from {env_path}")
else:
    print(f"⚠️  No .env file found at {env_path}, using system environment variables")

# Import project modules
# Temporarily commented out - contract_validator depends on omnibase_core
# from agents.lib.generation.contract_validator import ContractValidator, ValidationResult


# -------------------------------------------------------------------------
# Sample Contract Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def sample_effect_contract_yaml() -> str:
    """Sample EFFECT contract YAML for testing."""
    return """
name: NodeDatabaseWriterEffect
version: "1.0.0"
description: "Writes data to PostgreSQL database"
node_type: EFFECT
input_model: ModelDatabaseInput
output_model: ModelDatabaseOutput
error_model: ModelOnexError
io_operations:
  - operation_type: database_write
    target: postgresql
    is_async: true
lifecycle:
  initialization: ["connect_to_database"]
  cleanup: ["close_connection"]
dependencies:
  - asyncpg
  - psycopg2-binary
performance:
  expected_duration_ms: 100
  timeout_ms: 5000
"""


@pytest.fixture
def sample_compute_contract_yaml() -> str:
    """Sample COMPUTE contract YAML for testing."""
    return """
name: NodeDataTransformerCompute
version: "1.0.0"
description: "Transforms data using pure computation"
node_type: COMPUTE
input_model: ModelDataInput
output_model: ModelDataOutput
error_model: ModelOnexError
computation_type: transformation
is_pure: true
dependencies:
  - numpy
performance:
  expected_duration_ms: 50
  timeout_ms: 2000
"""


@pytest.fixture
def sample_reducer_contract_yaml() -> str:
    """Sample REDUCER contract YAML for testing."""
    return """
name: NodeAggregationReducer
version: "1.0.0"
description: "Aggregates data and emits intents"
node_type: REDUCER
input_model: ModelAggregationInput
output_model: ModelAggregationOutput
error_model: ModelOnexError
aggregation_strategy: sum
state_management: true
intent_emissions:
  - intent_type: data_aggregated
    destination: event_bus
dependencies:
  - redis
performance:
  expected_duration_ms: 200
  timeout_ms: 10000
"""


@pytest.fixture
def sample_orchestrator_contract_yaml() -> str:
    """Sample ORCHESTRATOR contract YAML for testing."""
    return """
name: NodeWorkflowOrchestrator
version: "1.0.0"
description: "Orchestrates multi-step workflow"
node_type: ORCHESTRATOR
input_model: ModelWorkflowInput
output_model: ModelWorkflowOutput
error_model: ModelOnexError
workflow_steps:
  - step: validate_input
  - step: process_data
  - step: store_results
lease_management: true
dependencies:
  - redis
  - asyncio
performance:
  expected_duration_ms: 500
  timeout_ms: 30000
"""


@pytest.fixture
def invalid_contract_yaml() -> str:
    """Invalid contract YAML for testing validation errors."""
    return """
name: InvalidNode
# Missing required fields: version, description, node_type
input_model: ModelInput
"""


# -------------------------------------------------------------------------
# Contract Validator Fixtures
# -------------------------------------------------------------------------


# Temporarily commented out - contract_validator depends on omnibase_core
# @pytest.fixture
# def contract_validator() -> ContractValidator:
#     """Create contract validator instance."""
#     return ContractValidator()
#
#
# @pytest.fixture
# def contract_validator_with_search_paths(tmp_path: Path) -> ContractValidator:
#     """Create contract validator with model search paths."""
#     models_dir = tmp_path / "models"
#     models_dir.mkdir()
#     return ContractValidator(model_search_paths=[models_dir])


# -------------------------------------------------------------------------
# Temporary Directory Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Create temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def temp_models_dir(tmp_path: Path) -> Path:
    """Create temporary models directory."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    return models_dir


# -------------------------------------------------------------------------
# Sample Prompt Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def sample_effect_prompt() -> str:
    """Sample prompt for EFFECT node generation."""
    return "Create EFFECT node for PostgreSQL database write operations"


@pytest.fixture
def sample_compute_prompt() -> str:
    """Sample prompt for COMPUTE node generation."""
    return "Create COMPUTE node for data transformation using numpy"


@pytest.fixture
def sample_reducer_prompt() -> str:
    """Sample prompt for REDUCER node generation."""
    return "Create REDUCER node for data aggregation with intent emission"


@pytest.fixture
def sample_orchestrator_prompt() -> str:
    """Sample prompt for ORCHESTRATOR node generation."""
    return "Create ORCHESTRATOR node for multi-step workflow coordination"


# -------------------------------------------------------------------------
# Node Type Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(params=["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"])
def node_type(request) -> str:
    """Parametrized fixture for all node types."""
    return request.param


@pytest.fixture
def all_node_types() -> list[str]:
    """List of all supported node types."""
    return ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]


# -------------------------------------------------------------------------
# Mock Data Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def mock_parsed_data() -> Dict:
    """Mock parsed data from prompt parser."""
    return {
        "node_type": "EFFECT",
        "service_name": "test_service",
        "domain": "test_domain",
        "description": "Test node for testing purposes",
        "operations": ["write", "read"],
        "features": ["async", "caching"],
        "confidence": 0.85,
    }


@pytest.fixture
def correlation_id() -> str:
    """Generate correlation ID for testing."""
    return str(uuid4())


# -------------------------------------------------------------------------
# Validation Result Helpers
# -------------------------------------------------------------------------

# Temporarily commented out - ValidationResult depends on omnibase_core
# def create_valid_validation_result(
#     node_type: str = "EFFECT",
# ) -> ValidationResult:
#     """Helper to create valid validation result for testing."""
#     return ValidationResult(
#         valid=True,
#         node_type=node_type,
#         schema_compliance=True,
#         model_references_valid=True,
#     )
#
#
# def create_invalid_validation_result(
#     node_type: str = "EFFECT", errors: list = None
# ) -> ValidationResult:
#     """Helper to create invalid validation result for testing."""
#     return ValidationResult(
#         valid=False,
#         node_type=node_type,
#         schema_compliance=False,
#         errors=errors or [{"loc": ["test"], "msg": "Test error", "type": "test"}],
#     )


# -------------------------------------------------------------------------
# Performance Benchmark Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def benchmark_iterations() -> int:
    """Number of iterations for performance benchmarks."""
    return 10


@pytest.fixture
def performance_thresholds() -> Dict[str, float]:
    """Performance thresholds for different operations."""
    return {
        "contract_validation_ms": 200,
        "effect_generation_s": 45,
        "compute_generation_s": 40,
        "reducer_generation_s": 50,
        "orchestrator_generation_s": 55,
        "average_generation_s": 48,
    }


# -------------------------------------------------------------------------
# pytest configuration
# -------------------------------------------------------------------------


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (deselect with '-m \"not integration\"')",
    )
    config.addinivalue_line(
        "markers",
        "benchmark: marks tests as performance benchmarks (deselect with '-m \"not benchmark\"')",
    )


# -------------------------------------------------------------------------
# Kafka Producer Cleanup Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _cleanup_kafka_producers():
    """
    Automatically cleanup global Kafka producers after all tests complete.

    This fixture ensures that singleton Kafka producers in action_event_publisher
    and transformation_event_publisher are properly closed, preventing
    "Unclosed AIOKafkaProducer" resource warnings.

    Scope: session (runs once after all tests)
    Autouse: True (runs automatically without being requested)
    """
    # Yield to run all tests
    yield

    # Cleanup after all tests complete
    async def cleanup():
        try:
            # Import here to avoid issues if modules aren't used
            from agents.lib import (
                action_event_publisher,
                transformation_event_publisher,
            )

            # Close action event publisher
            if action_event_publisher._kafka_producer is not None:
                await action_event_publisher.close_producer()

            # Close transformation event publisher
            if transformation_event_publisher._kafka_producer is not None:
                await transformation_event_publisher.close_producer()

        except Exception as e:
            # Log but don't fail - cleanup is best-effort
            print(f"Warning: Error during Kafka producer cleanup: {e}")

    # Run cleanup in event loop
    try:
        # Try to get existing event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, get or create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Always use run_until_complete to ensure cleanup completes before fixture exits
        # This is safe in pytest fixtures which are not async contexts
        loop.run_until_complete(cleanup())
    except Exception as e:
        # Fallback to asyncio.run if event loop management fails
        print(f"Warning: Event loop error during cleanup, using asyncio.run: {e}")
        asyncio.run(cleanup())
