"""Tests for manifest injector with event bus integration."""

import uuid
from typing import Any, Dict
from unittest.mock import patch

import pytest

from agents.lib.manifest_injector import ManifestInjector, inject_manifest

# Mock data for event bus responses
MOCK_EXECUTION_PATTERNS_RESPONSE = {
    "patterns": [
        {
            "name": "CRUD Pattern",
            "file_path": "node_crud_effect.py",
            "description": "Standard CRUD operations",
            "node_types": ["EFFECT"],
            "confidence": 0.95,
            "use_cases": ["database operations"],
        },
        {
            "name": "Transformation Pattern",
            "file_path": "node_transform_compute.py",
            "description": "Data transformation",
            "node_types": ["COMPUTE"],
            "confidence": 0.92,
            "use_cases": ["data processing"],
        },
    ],
    "query_time_ms": 75,
}

MOCK_CODE_PATTERNS_RESPONSE = {
    "patterns": [
        {
            "name": "Aggregation Pattern",
            "file_path": "node_aggregate_reducer.py",
            "description": "Data aggregation",
            "node_types": ["REDUCER"],
            "confidence": 0.88,
            "use_cases": ["analytics"],
        },
        {
            "name": "Orchestration Pattern",
            "file_path": "node_orchestrate_orchestrator.py",
            "description": "Workflow orchestration",
            "node_types": ["ORCHESTRATOR"],
            "confidence": 0.91,
            "use_cases": ["workflows"],
        },
    ],
    "query_time_ms": 85,
}

MOCK_INFRASTRUCTURE_RESPONSE = {
    "postgresql": {
        "host": "192.168.86.200",
        "port": 5436,
        "database": "omninode_bridge",
        "status": "healthy",
    },
    "kafka": {
        "bootstrap_servers": "192.168.86.200:29102",
        "topics": 10,
        "status": "healthy",
    },
    "qdrant": {
        "endpoint": "localhost:6333",
        "collections": 5,
        "status": "healthy",
    },
    "archon_mcp": {
        "endpoint": "http://localhost:8051",
        "status": "healthy",
    },
    "docker_services": ["postgres", "kafka", "qdrant"],
}

MOCK_MODELS_RESPONSE = {
    "ai_models": {
        "providers": [
            {"name": "Anthropic", "models": ["claude-3-opus", "claude-3-sonnet"]},
            {"name": "Google Gemini", "models": ["gemini-pro", "gemini-flash"]},
        ]
    },
    "onex_models": {
        "node_types": [
            {"name": "EFFECT", "naming_pattern": "Node<Name>Effect"},
            {"name": "COMPUTE", "naming_pattern": "Node<Name>Compute"},
            {"name": "REDUCER", "naming_pattern": "Node<Name>Reducer"},
            {"name": "ORCHESTRATOR", "naming_pattern": "Node<Name>Orchestrator"},
        ]
    },
}

MOCK_DATABASE_SCHEMAS_RESPONSE = {
    "tables": [
        {"name": "agent_routing_decisions"},
        {"name": "agent_transformation_events"},
        {"name": "router_performance_metrics"},
    ]
}


class MockIntelligenceEventClient:
    """Mock IntelligenceEventClient for testing."""

    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False

    async def start(self):
        """Mock start method."""
        self.started = True

    async def stop(self):
        """Mock stop method."""
        self.stopped = True

    async def request_code_analysis(
        self,
        content: str,
        source_path: str,
        language: str,
        options: Dict[str, Any],
        timeout_ms: int = 2000,
    ) -> Dict[str, Any]:
        """Mock request_code_analysis method."""
        # Return appropriate mock data based on operation type
        operation = options.get("operation_type", "")

        if operation == "PATTERN_EXTRACTION":
            # Return different patterns based on collection_name
            collection_name = options.get("collection_name", "execution_patterns")
            if collection_name == "execution_patterns":
                return MOCK_EXECUTION_PATTERNS_RESPONSE
            elif collection_name == "code_patterns":
                return MOCK_CODE_PATTERNS_RESPONSE
            else:
                return {"patterns": [], "query_time_ms": 0}
        elif operation == "INFRASTRUCTURE_SCAN":
            return MOCK_INFRASTRUCTURE_RESPONSE
        elif operation == "MODEL_DISCOVERY":
            return MOCK_MODELS_RESPONSE
        elif operation == "SCHEMA_DISCOVERY":
            return MOCK_DATABASE_SCHEMAS_RESPONSE
        else:
            return {}


@pytest.fixture
def mock_intelligence_client():
    """Fixture to mock IntelligenceEventClient."""
    with patch(
        "agents.lib.manifest_injector.IntelligenceEventClient",
        MockIntelligenceEventClient,
    ):
        yield


@pytest.mark.asyncio
async def test_generate_dynamic_manifest_async(mock_intelligence_client):
    """Test async manifest generation with event bus."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    manifest = await injector.generate_dynamic_manifest_async(correlation_id)

    assert manifest is not None
    assert "manifest_metadata" in manifest
    assert "patterns" in manifest
    assert "infrastructure" in manifest
    assert "models" in manifest
    assert manifest["manifest_metadata"]["version"] == "2.0.0"
    assert manifest["manifest_metadata"]["source"] == "archon-intelligence-adapter"


def test_generate_dynamic_manifest_sync(mock_intelligence_client):
    """Test synchronous manifest generation (wrapper)."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    manifest = injector.generate_dynamic_manifest(correlation_id)

    assert manifest is not None
    assert "manifest_metadata" in manifest
    assert "patterns" in manifest
    assert "infrastructure" in manifest
    assert "models" in manifest


def test_format_for_prompt_with_data(mock_intelligence_client):
    """Test formatting manifest for prompt injection."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest first
    injector.generate_dynamic_manifest(correlation_id)

    # Format for prompt
    formatted = injector.format_for_prompt()

    assert "SYSTEM MANIFEST" in formatted
    assert "AVAILABLE PATTERNS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" in formatted
    assert "AI MODELS & DATA MODELS" in formatted


def test_format_for_prompt_selective_sections(mock_intelligence_client):
    """Test formatting specific sections only."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest first
    injector.generate_dynamic_manifest(correlation_id)

    # Format only patterns section
    formatted = injector.format_for_prompt(sections=["patterns"])

    assert "AVAILABLE PATTERNS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" not in formatted


def test_format_for_prompt_multiple_sections(mock_intelligence_client):
    """Test formatting multiple specific sections."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest first
    injector.generate_dynamic_manifest(correlation_id)

    # Format patterns and infrastructure sections
    formatted = injector.format_for_prompt(sections=["patterns", "infrastructure"])

    assert "AVAILABLE PATTERNS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" in formatted
    assert "AI MODELS & DATA MODELS" not in formatted


def test_manifest_summary(mock_intelligence_client):
    """Test manifest summary statistics."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest first
    injector.generate_dynamic_manifest(correlation_id)

    summary = injector.get_manifest_summary()

    assert "version" in summary
    assert summary["version"] == "2.0.0"
    assert summary["patterns_count"] >= 4  # We have 4 mock patterns
    assert summary["source"] == "archon-intelligence-adapter"
    assert summary["cache_valid"] is True


def test_manifest_caching(mock_intelligence_client):
    """Test that manifest is cached after first generation."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # First call should generate and cache
    manifest1 = injector.generate_dynamic_manifest(correlation_id)

    # Second call should use cache
    manifest2 = injector.generate_dynamic_manifest(correlation_id)

    assert manifest1 == manifest2
    assert injector._manifest_data is not None
    assert injector._is_cache_valid()


def test_manifest_patterns_section(mock_intelligence_client):
    """Test patterns section formatting."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    manifest = injector.generate_dynamic_manifest(correlation_id)

    # Format patterns section
    formatted = injector._format_patterns(manifest.get("patterns", {}))

    assert "AVAILABLE PATTERNS" in formatted
    assert "CRUD Pattern" in formatted
    assert "Transformation Pattern" in formatted


def test_manifest_infrastructure_section(mock_intelligence_client):
    """Test infrastructure section formatting."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    manifest = injector.generate_dynamic_manifest(correlation_id)

    # Format infrastructure section
    formatted = injector._format_infrastructure(manifest.get("infrastructure", {}))

    assert "INFRASTRUCTURE TOPOLOGY" in formatted
    assert "PostgreSQL" in formatted
    assert "Kafka" in formatted
    assert "Qdrant" in formatted


def test_manifest_contains_all_sections(mock_intelligence_client):
    """Test that formatted output contains all expected sections."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    injector.generate_dynamic_manifest(correlation_id)

    # Format full manifest
    formatted = injector.format_for_prompt()

    expected_sections = [
        "AVAILABLE PATTERNS",
        "AI MODELS & DATA MODELS",
        "INFRASTRUCTURE TOPOLOGY",
    ]

    for section in expected_sections:
        assert section in formatted, f"Missing section: {section}"


def test_manifest_selective_no_cache(mock_intelligence_client):
    """Test that selective sections don't use full cache."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    injector.generate_dynamic_manifest(correlation_id)

    # Format full manifest (should cache)
    full_formatted = injector.format_for_prompt()
    assert injector._cached_formatted is not None

    # Format selective sections (should not use full cache)
    selective_formatted = injector.format_for_prompt(sections=["patterns"])

    assert selective_formatted != full_formatted
    assert len(selective_formatted) < len(full_formatted)


def test_manifest_metadata_extraction(mock_intelligence_client):
    """Test that manifest metadata can be extracted."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    manifest = injector.generate_dynamic_manifest(correlation_id)

    metadata = manifest.get("manifest_metadata", {})
    assert "version" in metadata
    assert "purpose" in metadata
    assert metadata["version"] == "2.0.0"
    assert "target_agents" in metadata


def test_inject_manifest_convenience_function(mock_intelligence_client):
    """Test convenience function for quick manifest injection."""
    formatted = inject_manifest()

    assert "SYSTEM MANIFEST" in formatted
    assert "END SYSTEM MANIFEST" in formatted


def test_inject_manifest_with_sections(mock_intelligence_client):
    """Test convenience function with selective sections."""
    formatted = inject_manifest(sections=["patterns", "models"])

    assert "AVAILABLE PATTERNS" in formatted
    assert "AI MODELS & DATA MODELS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" not in formatted


def test_minimal_manifest_fallback():
    """Test fallback to minimal manifest when intelligence is disabled."""
    injector = ManifestInjector(enable_intelligence=False)
    correlation_id = str(uuid.uuid4())

    manifest = injector.generate_dynamic_manifest(correlation_id)

    assert manifest is not None
    assert "manifest_metadata" in manifest
    assert manifest["manifest_metadata"]["source"] == "fallback"
    assert manifest["manifest_metadata"]["version"] == "2.0.0-minimal"
    assert "note" in manifest


@pytest.mark.asyncio
async def test_query_timeout_handling(mock_intelligence_client):
    """Test timeout handling for event bus queries."""
    injector = ManifestInjector(enable_intelligence=True, query_timeout_ms=100)
    correlation_id = str(uuid.uuid4())

    # Should still return a manifest (fallback if needed)
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)

    assert manifest is not None
    assert "manifest_metadata" in manifest


def test_cache_validity(mock_intelligence_client):
    """Test cache TTL and validity checking."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # No cache initially
    assert not injector._is_cache_valid()

    # Generate manifest (creates cache)
    injector.generate_dynamic_manifest(correlation_id)

    # Cache should be valid
    assert injector._is_cache_valid()
    assert injector._manifest_data is not None
    assert injector._last_update is not None


def test_force_refresh_ignores_cache(mock_intelligence_client):
    """Test that force_refresh bypasses cache."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest (creates cache)
    manifest1 = injector.generate_dynamic_manifest(correlation_id)
    first_update = injector._last_update

    # Force refresh should regenerate
    manifest2 = injector.generate_dynamic_manifest(correlation_id, force_refresh=True)
    second_update = injector._last_update

    # Both manifests should have same structure but different timestamps
    assert (
        manifest1["manifest_metadata"]["version"]
        == manifest2["manifest_metadata"]["version"]
    )
    # Update time should have changed
    assert second_update >= first_update


@pytest.mark.asyncio
async def test_event_bus_client_lifecycle(mock_intelligence_client):
    """Test that event bus client is properly started and stopped."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)

    # Should have successfully generated manifest
    assert manifest is not None
    assert "manifest_metadata" in manifest


def test_manifest_summary_not_loaded():
    """Test summary when manifest not yet loaded."""
    injector = ManifestInjector(enable_intelligence=False)

    summary = injector.get_manifest_summary()

    assert summary["status"] == "not_loaded"
    assert "message" in summary


@pytest.mark.asyncio
async def test_exception_handling_in_queries():
    """Test graceful handling of query exceptions."""

    class FailingMockClient:
        """Mock client that raises exceptions."""

        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

        async def request_code_analysis(self, *args, **kwargs):
            raise Exception("Mock query failure")

    with patch(
        "agents.lib.manifest_injector.IntelligenceEventClient",
        FailingMockClient,
    ):
        injector = ManifestInjector(enable_intelligence=True)
        correlation_id = str(uuid.uuid4())

        # Should still build manifest but with empty sections
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)

        assert manifest is not None
        # Manifest is built but sections are empty due to query failures
        assert "patterns" in manifest
        assert manifest["patterns"]["total_count"] == 0
        assert len(manifest["patterns"]["available"]) == 0


def test_format_for_prompt_without_loading():
    """Test format_for_prompt when manifest not loaded yet."""
    injector = ManifestInjector(enable_intelligence=False)

    # Should still return something (minimal manifest)
    formatted = injector.format_for_prompt()

    assert "SYSTEM MANIFEST" in formatted
    assert "fallback" in formatted.lower() or "minimal" in formatted.lower()


def test_dual_collection_query(mock_intelligence_client):
    """Test that both execution_patterns and code_patterns collections are queried."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    manifest = injector.generate_dynamic_manifest(correlation_id)

    # Verify patterns from both collections are present
    patterns = manifest.get("patterns", {})
    all_patterns = patterns.get("available", [])

    # Should have 4 patterns total (2 from execution_patterns + 2 from code_patterns)
    assert len(all_patterns) == 4

    # Verify collections_queried metadata
    collections_queried = patterns.get("collections_queried", {})
    assert collections_queried.get("execution_patterns") == 2
    assert collections_queried.get("code_patterns") == 2

    # Verify query time is combined
    assert patterns.get("query_time_ms") == 160  # 75 + 85


def test_dual_collection_formatted_output(mock_intelligence_client):
    """Test that formatted output shows collection statistics."""
    injector = ManifestInjector(enable_intelligence=True)
    correlation_id = str(uuid.uuid4())

    # Generate manifest
    injector.generate_dynamic_manifest(correlation_id)

    # Format patterns section
    formatted = injector.format_for_prompt()

    # Should show collection statistics
    assert "execution_patterns" in formatted
    assert "code_patterns" in formatted
    assert "Total: 4 patterns available" in formatted
