"""Tests for manifest injector."""

import pytest

from agents.lib.manifest_injector import ManifestInjector, inject_manifest


def test_manifest_injector_loads_yaml():
    """Test that injector loads the manifest YAML."""
    injector = ManifestInjector()
    manifest = injector.load_manifest()

    assert manifest is not None
    assert "patterns" in manifest
    assert "infrastructure" in manifest
    assert "models" in manifest


def test_manifest_injector_formats_for_prompt():
    """Test that injector formats manifest for prompt injection."""
    injector = ManifestInjector()
    formatted = injector.format_for_prompt()

    assert "SYSTEM MANIFEST" in formatted
    assert "AVAILABLE PATTERNS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" in formatted
    assert "AI MODELS & DATA MODELS" in formatted


def test_manifest_injector_selective_sections():
    """Test that injector can format specific sections."""
    injector = ManifestInjector()
    formatted = injector.format_for_prompt(sections=["patterns"])

    assert "AVAILABLE PATTERNS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" not in formatted


def test_manifest_injector_multiple_sections():
    """Test that injector can format multiple specific sections."""
    injector = ManifestInjector()
    formatted = injector.format_for_prompt(sections=["patterns", "infrastructure"])

    assert "AVAILABLE PATTERNS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" in formatted
    assert "AI MODELS & DATA MODELS" not in formatted


def test_inject_manifest_convenience_function():
    """Test convenience function."""
    formatted = inject_manifest()
    assert "SYSTEM MANIFEST" in formatted
    assert "END SYSTEM MANIFEST" in formatted


def test_manifest_summary():
    """Test summary statistics."""
    injector = ManifestInjector()
    summary = injector.get_manifest_summary()

    assert "version" in summary
    assert summary["patterns_count"] >= 4  # At least 4 patterns
    assert summary["file_size_bytes"] > 0


def test_manifest_caching():
    """Test that full manifest is cached after first load."""
    injector = ManifestInjector()

    # First call should load and cache
    formatted1 = injector.format_for_prompt()

    # Second call should use cache
    formatted2 = injector.format_for_prompt()

    assert formatted1 == formatted2
    assert injector._cached_formatted is not None


def test_manifest_patterns_section():
    """Test patterns section formatting."""
    injector = ManifestInjector()
    manifest = injector.load_manifest()

    formatted = injector._format_patterns(manifest.get("patterns", {}))

    assert "AVAILABLE PATTERNS" in formatted
    assert "CRUD Pattern" in formatted or "Transformation Pattern" in formatted


def test_manifest_infrastructure_section():
    """Test infrastructure section formatting."""
    injector = ManifestInjector()
    manifest = injector.load_manifest()

    formatted = injector._format_infrastructure(manifest.get("infrastructure", {}))

    assert "INFRASTRUCTURE TOPOLOGY" in formatted
    # Should contain at least one service
    assert "PostgreSQL" in formatted or "Kafka" in formatted or "Qdrant" in formatted


def test_manifest_file_not_found():
    """Test error handling when manifest file doesn't exist."""
    injector = ManifestInjector(manifest_path="/nonexistent/path/manifest.yaml")

    with pytest.raises(FileNotFoundError) as exc_info:
        injector.load_manifest()

    assert "System manifest not found" in str(exc_info.value)


def test_manifest_contains_all_sections():
    """Test that formatted output contains all expected sections."""
    injector = ManifestInjector()
    formatted = injector.format_for_prompt()

    expected_sections = [
        "AVAILABLE PATTERNS",
        "AI MODELS & DATA MODELS",
        "INFRASTRUCTURE TOPOLOGY",
        "FILE STRUCTURE",
        "DEPENDENCIES",
        "INTERFACES",
        "AGENT FRAMEWORK",
        "AVAILABLE SKILLS",
    ]

    for section in expected_sections:
        assert section in formatted, f"Missing section: {section}"


def test_manifest_selective_no_cache():
    """Test that selective sections don't use cache."""
    injector = ManifestInjector()

    # Load full manifest (should cache)
    full_formatted = injector.format_for_prompt()
    assert injector._cached_formatted is not None

    # Request selective sections (should not use cache)
    selective_formatted = injector.format_for_prompt(sections=["patterns"])

    assert selective_formatted != full_formatted
    assert len(selective_formatted) < len(full_formatted)


def test_manifest_metadata_extraction():
    """Test that manifest metadata can be extracted."""
    injector = ManifestInjector()
    manifest = injector.load_manifest()

    metadata = manifest.get("manifest_metadata", {})
    assert "version" in metadata
    assert "purpose" in metadata


def test_convenience_function_with_sections():
    """Test convenience function with selective sections."""
    formatted = inject_manifest(sections=["patterns", "models"])

    assert "AVAILABLE PATTERNS" in formatted
    assert "AI MODELS & DATA MODELS" in formatted
    assert "INFRASTRUCTURE TOPOLOGY" not in formatted
