"""
Tests for P2 code quality fixes (TASK-8 and TASK-9).

Verifies:
- TASK-8: AST-based code normalization in node_stf_hash_compute.py
- TASK-9: Provider validation in node_model_price_catalog_effect.py

NOTE: This test file references archived code (omniclaude.debug_loop) that has been
moved to _archive/. The tests are skipped until the code is migrated or removed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# Skip entire module - these tests reference archived code
# The omniclaude.debug_loop module has been moved to _archive/omniclaude_legacy_root/debug_loop/
# This test file should be removed or migrated when the debug_loop code is properly refactored
pytest.skip(
    "Skipping test_p2_fixes.py - references archived code (omniclaude.debug_loop)",
    allow_module_level=True,
)

# These imports are guarded because the omnibase components are not available in omniclaude.
# The module is skipped above, so these will never actually execute, but we need to define
# the names to satisfy static analysis (Ruff F821).
try:
    from omnibase_core.enums import EnumCoreErrorCode, EnumProvider
    from omnibase_core.models import ModelONEXContainer, ModelOnexError
    from omnibase_core.nodes import NodeModelPriceCatalogEffect, NodeSTFHashCompute
except ImportError:
    # Define placeholders for static analysis - module is skipped so these won't be used
    EnumProvider = None  # type: ignore[misc, assignment]
    NodeSTFHashCompute = None  # type: ignore[misc, assignment]
    NodeModelPriceCatalogEffect = None  # type: ignore[misc, assignment]
    ModelONEXContainer = None  # type: ignore[misc, assignment]
    ModelOnexError = None  # type: ignore[misc, assignment]
    EnumCoreErrorCode = None  # type: ignore[misc, assignment]


@pytest.fixture
def container():
    """Create a test container for ONEX nodes."""
    return ModelONEXContainer()


# ============================================================================
# TASK-8: STF Hash Compute - AST-based normalization tests
# ============================================================================


@pytest.mark.asyncio
async def test_ast_based_comment_removal(container):
    """Test that comments are removed using AST (not regex)."""
    node = NodeSTFHashCompute(container=container)

    code = """
def hello():
    # This is a comment
    x = 1  # Inline comment
    return x
"""

    contract = {
        "stf_code": code,
        "normalization_options": {
            "strip_comments": True,
            "remove_docstrings": False,
            "normalize_indentation": False,
            "strip_whitespace": False,
        },
    }

    result = await node.execute_compute(contract)

    # AST automatically removes comments
    assert "# This is a comment" not in result["normalized_code"]
    assert "# Inline comment" not in result["normalized_code"]
    assert "strip_comments" in result["normalization_applied"]


@pytest.mark.asyncio
async def test_ast_based_docstring_removal(container):
    """Test that ONLY actual docstrings are removed (not all triple-quoted strings)."""
    node = NodeSTFHashCompute(container=container)

    code = '''
def hello():
    """This is a docstring and should be removed."""
    message = """This is a string literal and should be kept."""
    return message
'''

    contract = {
        "stf_code": code,
        "normalization_options": {
            "strip_comments": False,
            "remove_docstrings": True,
            "normalize_indentation": False,
            "strip_whitespace": False,
        },
    }

    result = await node.execute_compute(contract)

    # Docstring should be removed
    assert "This is a docstring" not in result["normalized_code"]

    # String literal should be kept
    assert "This is a string literal" in result["normalized_code"]
    assert "remove_docstrings" in result["normalization_applied"]


@pytest.mark.asyncio
async def test_ast_handles_edge_cases(container):
    """Test that AST handles edge cases that regex would break on."""
    node = NodeSTFHashCompute(container=container)

    # Edge case: # in strings, nested quotes, etc.
    code = """
def test():
    url = "https://example.com#anchor"  # URL with # in string
    query = "SELECT * FROM users WHERE name LIKE '%#%'"  # SQL with #
    return url, query
"""

    contract = {
        "stf_code": code,
        "normalization_options": {
            "strip_comments": True,
            "remove_docstrings": False,
            "normalize_indentation": False,
            "strip_whitespace": False,
        },
    }

    result = await node.execute_compute(contract)

    # String literals with # should be preserved
    assert "https://example.com#anchor" in result["normalized_code"]
    assert "LIKE '%#%'" in result["normalized_code"]

    # Comments should be removed
    assert "# URL with # in string" not in result["normalized_code"]
    assert "# SQL with #" not in result["normalized_code"]


@pytest.mark.asyncio
async def test_hash_consistency(container):
    """Test that identical code produces identical hashes."""
    node = NodeSTFHashCompute(container=container)

    code1 = """
def hello():
    return "world"
"""

    code2 = """
def hello():
    # Different comment
    return "world"  # Another comment
"""

    contract1 = {"stf_code": code1, "normalization_options": {"strip_comments": True}}
    contract2 = {"stf_code": code2, "normalization_options": {"strip_comments": True}}

    result1 = await node.execute_compute(contract1)
    result2 = await node.execute_compute(contract2)

    # Same functional code should produce same hash
    assert result1["stf_hash"] == result2["stf_hash"]


# ============================================================================
# TASK-9: Model Price Catalog - Provider validation tests
# ============================================================================


@pytest.mark.asyncio
async def test_update_pricing_validates_provider(container):
    """Test that update_pricing validates provider using EnumProvider."""
    mock_db = AsyncMock()
    node = NodeModelPriceCatalogEffect(db_protocol=mock_db, container=container)

    contract = {
        "operation": "update_pricing",
        "model_data": {
            "provider": "invalid_provider",  # Invalid provider
            "model_name": "test-model",
            "input_price_per_million": 1.0,
        },
    }

    with pytest.raises(ModelOnexError) as exc_info:
        await node.execute_effect(contract)

    assert exc_info.value.error_code == EnumCoreErrorCode.VALIDATION_ERROR
    assert "Invalid provider: invalid_provider" in str(exc_info.value.message)
    assert "Must be one of:" in str(exc_info.value.message)


@pytest.mark.asyncio
async def test_get_pricing_validates_provider(container):
    """Test that get_pricing validates provider using EnumProvider."""
    mock_db = AsyncMock()
    node = NodeModelPriceCatalogEffect(db_protocol=mock_db, container=container)

    contract = {
        "operation": "get_pricing",
        "provider": "invalid_provider",  # Invalid provider
        "model_name": "test-model",
    }

    with pytest.raises(ModelOnexError) as exc_info:
        await node.execute_effect(contract)

    assert exc_info.value.error_code == EnumCoreErrorCode.VALIDATION_ERROR
    assert "Invalid provider: invalid_provider" in str(exc_info.value.message)


@pytest.mark.asyncio
async def test_list_models_validates_provider(container):
    """Test that list_models validates provider filter using EnumProvider."""
    mock_db = AsyncMock()
    node = NodeModelPriceCatalogEffect(db_protocol=mock_db, container=container)

    contract = {
        "operation": "list_models",
        "filter": {
            "provider": "invalid_provider",  # Invalid provider
        },
    }

    with pytest.raises(ModelOnexError) as exc_info:
        await node.execute_effect(contract)

    assert exc_info.value.error_code == EnumCoreErrorCode.VALIDATION_ERROR
    assert "Invalid provider: invalid_provider" in str(exc_info.value.message)


@pytest.mark.asyncio
async def test_valid_provider_accepted(container):
    """Test that valid providers are accepted."""
    mock_db = AsyncMock()
    mock_db.fetch_one.return_value = {
        "catalog_id": "test-id",
        "provider": "anthropic",
        "model_name": "claude-3-opus",
        "input_price_per_million": 15.0,
        "output_price_per_million": 75.0,
        "is_active": True,
        "model_version": "20240307",
        "max_tokens": 4096,
        "context_window": 200000,
        "supports_streaming": True,
        "supports_function_calling": True,
        "supports_vision": True,
        "requests_per_minute": 50,
        "tokens_per_minute": 100000,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }

    node = NodeModelPriceCatalogEffect(db_protocol=mock_db, container=container)

    contract = {
        "operation": "get_pricing",
        "provider": "anthropic",  # Valid provider
        "model_name": "claude-3-opus",
    }

    result = await node.execute_effect(contract)

    assert result["success"] is True
    assert "model_pricing" in result
    assert mock_db.fetch_one.called


@pytest.mark.asyncio
async def test_all_enum_providers_valid():
    """Test that all EnumProvider values are recognized as valid."""
    valid_providers = EnumProvider.get_valid_providers()

    # Verify common providers are in the enum
    # Note: EnumProvider uses "google" not "gemini" for Google models
    expected_providers = ["anthropic", "openai", "google"]
    for provider in expected_providers:
        assert provider in valid_providers, f"Expected provider '{provider}' not in EnumProvider"
        assert EnumProvider.is_valid(provider), f"Provider '{provider}' should be valid"


# ============================================================================
# Integration test
# ============================================================================


@pytest.mark.asyncio
async def test_integration_both_nodes_work(container):
    """Integration test: verify both nodes can be imported and instantiated."""
    # TASK-8: STF Hash Compute
    hash_node = NodeSTFHashCompute(container=container)
    assert hash_node is not None

    # TASK-9: Model Price Catalog
    mock_db = AsyncMock()
    catalog_node = NodeModelPriceCatalogEffect(db_protocol=mock_db, container=container)
    assert catalog_node is not None

    # Verify AST is being used (not regex)
    code = 'def test(): """doc"""\n    return 1'
    contract = {"stf_code": code, "normalization_options": {"remove_docstrings": True}}
    result = await hash_node.execute_compute(contract)
    assert result["stf_hash"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
