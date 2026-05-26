# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Golden fixture tests for ManifestInjector.

Documents current behavior for regression detection during the omniclaude
restructuring program (OMN-11547). These tests PASS on current code and
serve as a behavioral contract: any refactoring step that causes a failure
here has changed observable behavior and must be reviewed.

Scope:
- ManifestInjector.__init__: constructor defaults and feature-flag wiring
- ManifestInjector.generate_dynamic_manifest: sync wrapper with caching
- ManifestInjector.generate_dynamic_manifest_async: async path, intelligence-
  disabled branch (no Kafka/Qdrant needed for unit tests)
- ManifestInjector._get_minimal_manifest: fallback shape contract
- ManifestInjector.format_for_prompt: output shape and required sections
- ManifestInjector._select_sections_for_task: always returns all 6 sections
- ManifestInjector._build_manifest_from_results: manifest key contract
- ManifestInjector._is_cache_valid: cache TTL logic
- ManifestInjectionStorage.store_manifest_injection: OMN-2058 no-op stub
- ManifestCache: get/set/invalidate/hit-rate

All external dependencies (Kafka, Qdrant, PostgreSQL, Valkey, aiohttp) are
mocked. No network calls are made during these tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_CORRELATION_ID = "12345678-1234-5678-1234-567812345678"
_AGENT_NAME = "test-agent"


def _make_injector(
    enable_intelligence: bool = False,
    enable_storage: bool = False,
    enable_cache: bool = False,
) -> Any:
    """
    Construct a ManifestInjector with all heavyweight dependencies mocked.

    enable_intelligence=False prevents Kafka/Qdrant contact.
    enable_storage=False skips ManifestInjectionStorage construction
    (which would try to read DB settings).
    enable_cache=False skips Valkey IntelligenceCache construction.
    """
    from omniclaude.lib.core.manifest_injector import ManifestInjector

    with (
        patch("omniclaude.lib.core.manifest_injector.IntelligenceCache"),
        patch("omniclaude.lib.core.manifest_injector.ManifestInjectionStorage"),
        patch("omniclaude.lib.core.manifest_injector.IntelligenceUsageTracker"),
        patch("omniclaude.lib.core.manifest_injector.PatternQualityScorer"),
        patch("omniclaude.lib.core.manifest_injector.TaskClassifier"),
    ):
        injector = ManifestInjector(
            kafka_brokers="localhost:19092",
            enable_intelligence=enable_intelligence,
            enable_storage=enable_storage,
            enable_cache=enable_cache,
            agent_name=_AGENT_NAME,
        )
    return injector


# ---------------------------------------------------------------------------
# OMN-11547 — ManifestInjector constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestInjectorInit:
    """
    Golden fixture: documents ManifestInjector.__init__ behavior (OMN-11547).
    """

    def test_default_query_timeout_ms(self) -> None:
        """Default query_timeout_ms is 10 000 ms."""
        injector = _make_injector()
        assert injector.query_timeout_ms == 10_000

    def test_kafka_brokers_stored(self) -> None:
        """kafka_brokers is stored on the instance."""
        injector = _make_injector()
        assert injector.kafka_brokers == "localhost:19092"

    def test_agent_name_stored(self) -> None:
        """agent_name from constructor is stored on the instance."""
        injector = _make_injector()
        assert injector.agent_name == _AGENT_NAME

    def test_intelligence_disabled_flag(self) -> None:
        """enable_intelligence=False is stored correctly."""
        injector = _make_injector(enable_intelligence=False)
        assert injector.enable_intelligence is False

    def test_manifest_data_initially_none(self) -> None:
        """_manifest_data starts as None before any generation."""
        injector = _make_injector()
        assert injector._manifest_data is None

    def test_last_update_initially_none(self) -> None:
        """_last_update starts as None before any generation."""
        injector = _make_injector()
        assert injector._last_update is None

    def test_cache_disabled_when_flag_false(self) -> None:
        """_cache is None when enable_cache=False."""
        injector = _make_injector(enable_cache=False)
        assert injector._cache is None

    def test_quality_scorer_present(self) -> None:
        """quality_scorer attribute is always set (mocked but present)."""
        injector = _make_injector()
        assert injector.quality_scorer is not None


# ---------------------------------------------------------------------------
# OMN-11547 — _get_minimal_manifest output shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMinimalManifest:
    """
    Golden fixture: documents _get_minimal_manifest() output shape (OMN-11547).

    This is the fallback that runs when Kafka/Qdrant are unreachable.
    The shape contract must survive refactoring.
    """

    def test_returns_dict(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert isinstance(result, dict)

    def test_manifest_metadata_present(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert "manifest_metadata" in result

    def test_manifest_metadata_version_is_minimal(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert result["manifest_metadata"]["version"] == "2.0.0-minimal"

    def test_manifest_metadata_source_is_fallback(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert result["manifest_metadata"]["source"] == "fallback"

    def test_patterns_section_present_and_empty(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert "patterns" in result
        assert result["patterns"]["available"] == []

    def test_infrastructure_section_present(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert "infrastructure" in result
        infra = result["infrastructure"]
        assert "remote_services" in infra
        assert "postgresql" in infra["remote_services"]
        assert "kafka" in infra["remote_services"]

    def test_models_section_present(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert "models" in result
        assert "onex_models" in result["models"]

    def test_onex_models_has_four_node_types(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        node_types = result["models"]["onex_models"]["node_types"]
        names = {nt["name"] for nt in node_types}
        assert names == {"EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"}

    def test_semantic_search_section_unavailable(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        assert "semantic_search" in result
        assert result["semantic_search"]["status"] == "unavailable"

    def test_generated_at_is_iso_format(self) -> None:
        injector = _make_injector()
        result = injector._get_minimal_manifest()
        ts = result["manifest_metadata"]["generated_at"]
        # Must parse without exception
        datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# OMN-11547 — _is_cache_valid
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsCacheValid:
    """
    Golden fixture: documents _is_cache_valid() behavior (OMN-11547).
    """

    def test_false_when_no_manifest_data(self) -> None:
        injector = _make_injector()
        assert injector._is_cache_valid() is False

    def test_false_when_no_last_update(self) -> None:
        injector = _make_injector()
        injector._manifest_data = {"some": "data"}
        injector._last_update = None
        assert injector._is_cache_valid() is False

    def test_true_when_recently_updated(self) -> None:
        injector = _make_injector()
        injector._manifest_data = {"some": "data"}
        injector._last_update = datetime.now(UTC)
        # cache_ttl_seconds defaults to 300 — a just-set timestamp is valid
        assert injector._is_cache_valid() is True

    def test_false_when_expired(self) -> None:
        from datetime import timedelta

        injector = _make_injector()
        injector._manifest_data = {"some": "data"}
        # Set last_update far in the past
        injector._last_update = datetime.now(UTC) - timedelta(seconds=600)
        assert injector._is_cache_valid() is False


# ---------------------------------------------------------------------------
# OMN-11547 — _select_sections_for_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSelectSectionsForTask:
    """
    Golden fixture: documents _select_sections_for_task() always returning
    all 6 core sections regardless of task context (OMN-11547).
    """

    def test_returns_six_sections_with_no_context(self) -> None:
        injector = _make_injector()
        sections = injector._select_sections_for_task(None)
        assert len(sections) == 6

    def test_contains_all_expected_section_names(self) -> None:
        injector = _make_injector()
        sections = injector._select_sections_for_task(None)
        expected = {
            "patterns",
            "database_schemas",
            "infrastructure",
            "models",
            "debug_intelligence",
            "semantic_search",
        }
        assert set(sections) == expected

    def test_task_context_ignored(self) -> None:
        """Result is identical regardless of task_context value."""
        injector = _make_injector()
        mock_context = MagicMock()
        sections_with_ctx = injector._select_sections_for_task(mock_context)
        sections_without_ctx = injector._select_sections_for_task(None)
        assert set(sections_with_ctx) == set(sections_without_ctx)


# ---------------------------------------------------------------------------
# OMN-11547 — _build_manifest_from_results key contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildManifestFromResults:
    """
    Golden fixture: documents _build_manifest_from_results() key contract
    (OMN-11547). Verifies every top-level key that format_for_prompt depends on.
    """

    def _empty_results(self) -> dict[str, Any]:
        return {
            "patterns": {},
            "infrastructure": {},
            "models": {},
            "database_schemas": {},
            "debug_intelligence": {},
            "filesystem": {},
            "debug_loop": {},
            "semantic_search": {},
        }

    def test_manifest_metadata_always_present(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert "manifest_metadata" in manifest

    def test_manifest_metadata_version_is_v2(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert manifest["manifest_metadata"]["version"] == "2.0.0"

    def test_manifest_metadata_source_is_adapter(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert manifest["manifest_metadata"]["source"] == "onex-intelligence-adapter"

    def test_patterns_key_present(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert "patterns" in manifest

    def test_patterns_has_available_list(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert "available" in manifest["patterns"]
        assert isinstance(manifest["patterns"]["available"], list)

    def test_infrastructure_key_present(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert "infrastructure" in manifest

    def test_models_key_present(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert "models" in manifest

    def test_database_schemas_key_present(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert "database_schemas" in manifest

    def test_action_logging_always_included(self) -> None:
        injector = _make_injector()
        manifest = injector._build_manifest_from_results(self._empty_results())
        assert "action_logging" in manifest
        assert manifest["action_logging"]["status"] == "available"

    def test_exception_result_produces_error_key(self) -> None:
        """An Exception in results dict produces an 'error' key in the section."""
        injector = _make_injector()
        results = self._empty_results()
        results["patterns"] = ValueError("qdrant down")
        manifest = injector._build_manifest_from_results(results)
        assert "error" in manifest["patterns"]

    def test_patterns_with_data_produces_available_list(self) -> None:
        injector = _make_injector()
        results = self._empty_results()
        results["patterns"] = {
            "patterns": [
                {
                    "name": "TestPattern",
                    "file_path": "src/foo.py",
                    "description": "A test pattern",
                    "node_types": ["EFFECT"],
                    "confidence": 0.9,
                    "use_cases": ["testing"],
                }
            ],
            "query_time_ms": 42,
            "total_count": 1,
        }
        manifest = injector._build_manifest_from_results(results)
        available = manifest["patterns"]["available"]
        assert len(available) == 1
        assert available[0]["name"] == "TestPattern"
        assert available[0]["confidence"] == 0.9


# ---------------------------------------------------------------------------
# OMN-11547 — generate_dynamic_manifest (intelligence disabled / fallback path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateDynamicManifestIntelligenceDisabled:
    """
    Golden fixture: documents generate_dynamic_manifest behavior when
    enable_intelligence=False (OMN-11547).

    This path is exercised whenever Kafka is unavailable (the production
    fallback). No network I/O occurs.
    """

    def _injector_no_intel(self) -> Any:
        with (
            patch("omniclaude.lib.core.manifest_injector.IntelligenceCache"),
            patch("omniclaude.lib.core.manifest_injector.ManifestInjectionStorage"),
            patch("omniclaude.lib.core.manifest_injector.IntelligenceUsageTracker"),
            patch("omniclaude.lib.core.manifest_injector.PatternQualityScorer"),
            patch("omniclaude.lib.core.manifest_injector.TaskClassifier"),
        ):
            from omniclaude.lib.core.manifest_injector import ManifestInjector

            injector = ManifestInjector(
                kafka_brokers="localhost:19092",
                enable_intelligence=False,
                enable_storage=False,
                enable_cache=False,
                agent_name=_AGENT_NAME,
            )

        # Mock filesystem query to avoid actual filesystem inspection
        async def _fake_filesystem(_cid: str) -> dict[str, Any]:
            return {
                "root_path": "/fake",
                "file_tree": [],
                "total_files": 0,
                "total_directories": 0,
                "total_size_bytes": 0,
                "file_types": {},
                "onex_files": {},
                "query_time_ms": 0,
            }

        # Mock debug loop query
        async def _fake_debug_loop(_cid: str) -> dict[str, Any]:
            return {
                "available": False,
                "reason": "mocked",
                "stf_count": 0,
                "categories": [],
                "top_stfs": [],
            }

        injector._query_filesystem = _fake_filesystem
        injector._query_debug_loop_context = _fake_debug_loop
        return injector

    def test_returns_dict(self) -> None:
        injector = self._injector_no_intel()
        result = injector.generate_dynamic_manifest(_CORRELATION_ID)
        assert isinstance(result, dict)

    def test_manifest_metadata_present(self) -> None:
        injector = self._injector_no_intel()
        result = injector.generate_dynamic_manifest(_CORRELATION_ID)
        assert "manifest_metadata" in result

    def test_filesystem_section_present(self) -> None:
        injector = self._injector_no_intel()
        result = injector.generate_dynamic_manifest(_CORRELATION_ID)
        assert "filesystem" in result

    def test_debug_loop_section_present(self) -> None:
        injector = self._injector_no_intel()
        result = injector.generate_dynamic_manifest(_CORRELATION_ID)
        assert "debug_loop" in result

    def test_manifest_cached_after_generation(self) -> None:
        injector = self._injector_no_intel()
        injector.generate_dynamic_manifest(_CORRELATION_ID)
        assert injector._manifest_data is not None
        assert injector._last_update is not None

    def test_second_call_returns_cached_result(self) -> None:
        """Second call with same correlation_id returns cached manifest (no recompute)."""
        injector = self._injector_no_intel()
        first = injector.generate_dynamic_manifest(_CORRELATION_ID)
        # Second call must return the same object (from cache)
        second = injector.generate_dynamic_manifest(_CORRELATION_ID)
        assert first is second

    def test_force_refresh_bypasses_cache(self) -> None:
        injector = self._injector_no_intel()
        first = injector.generate_dynamic_manifest(_CORRELATION_ID)
        second = injector.generate_dynamic_manifest(_CORRELATION_ID, force_refresh=True)
        # Content should be equivalent (same structure) but may be different objects
        assert "manifest_metadata" in second


# ---------------------------------------------------------------------------
# OMN-11547 — generate_dynamic_manifest exception fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateDynamicManifestExceptionFallback:
    """
    Golden fixture: documents that generate_dynamic_manifest falls back to
    _get_minimal_manifest() when an unexpected error occurs (OMN-11547).
    """

    def test_returns_minimal_manifest_on_exception(self) -> None:
        with (
            patch("omniclaude.lib.core.manifest_injector.IntelligenceCache"),
            patch("omniclaude.lib.core.manifest_injector.ManifestInjectionStorage"),
            patch("omniclaude.lib.core.manifest_injector.IntelligenceUsageTracker"),
            patch("omniclaude.lib.core.manifest_injector.PatternQualityScorer"),
            patch("omniclaude.lib.core.manifest_injector.TaskClassifier"),
        ):
            from omniclaude.lib.core.manifest_injector import ManifestInjector

            injector = ManifestInjector(
                kafka_brokers="localhost:19092",
                enable_intelligence=False,
                enable_storage=False,
                enable_cache=False,
            )

        # Force the async method to raise
        async def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("simulated failure")

        injector.generate_dynamic_manifest_async = _raise  # type: ignore[method-assign]

        result = injector.generate_dynamic_manifest(_CORRELATION_ID)

        assert "manifest_metadata" in result
        assert result["manifest_metadata"]["source"] == "fallback"


# ---------------------------------------------------------------------------
# OMN-11547 — format_for_prompt output shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatForPrompt:
    """
    Golden fixture: documents format_for_prompt() output shape (OMN-11547).
    """

    def _injector_with_minimal_manifest(self) -> Any:
        injector = _make_injector()
        injector._manifest_data = injector._get_minimal_manifest()
        return injector

    def test_returns_string(self) -> None:
        injector = self._injector_with_minimal_manifest()
        result = injector.format_for_prompt()
        assert isinstance(result, str)

    def test_contains_system_manifest_header(self) -> None:
        injector = self._injector_with_minimal_manifest()
        result = injector.format_for_prompt()
        assert "SYSTEM MANIFEST" in result

    def test_contains_version_line(self) -> None:
        injector = self._injector_with_minimal_manifest()
        result = injector.format_for_prompt()
        assert "Version:" in result

    def test_contains_generated_line(self) -> None:
        injector = self._injector_with_minimal_manifest()
        result = injector.format_for_prompt()
        assert "Generated:" in result

    def test_contains_source_line(self) -> None:
        injector = self._injector_with_minimal_manifest()
        result = injector.format_for_prompt()
        assert "Source:" in result

    def test_sections_filter_works(self) -> None:
        """Requesting a subset of sections produces shorter output."""
        injector = self._injector_with_minimal_manifest()
        full = injector.format_for_prompt()
        filtered = injector.format_for_prompt(sections=["patterns"])
        assert len(filtered) < len(full)

    def test_caches_formatted_output(self) -> None:
        """Second call with no sections returns the same cached string."""
        injector = self._injector_with_minimal_manifest()
        first = injector.format_for_prompt()
        second = injector.format_for_prompt()
        assert first is second


# ---------------------------------------------------------------------------
# OMN-11547 — ManifestInjectionStorage.store_manifest_injection OMN-2058 stub
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestInjectionStorageStub:
    """
    Golden fixture: documents ManifestInjectionStorage.store_manifest_injection
    as a no-op stub during DB-SPLIT (OMN-2058) (OMN-11547).
    """

    def _make_storage(self) -> Any:
        from omniclaude.lib.core.manifest_injector import ManifestInjectionStorage

        with patch("omniclaude.lib.core.manifest_injector.settings") as mock_settings:
            mock_settings.omniclaude_db_url.get_secret_value.return_value = (
                "postgresql://test:test@localhost/test"
            )
            storage = ManifestInjectionStorage()
        return storage

    def test_store_manifest_injection_returns_true(self) -> None:
        """OMN-2058 stub always returns True without touching the DB."""
        storage = self._make_storage()
        result = storage.store_manifest_injection(
            correlation_id=UUID(_CORRELATION_ID),
            agent_name=_AGENT_NAME,
            manifest_data={},
            formatted_text="",
            query_times={},
            sections_included=[],
        )
        assert result is True

    def test_mark_agent_completed_returns_true(self) -> None:
        """OMN-2058 stub always returns True without touching the DB."""
        storage = self._make_storage()
        result = storage.mark_agent_completed(
            correlation_id=UUID(_CORRELATION_ID),
            success=True,
        )
        assert result is True


# ---------------------------------------------------------------------------
# OMN-11547 — ManifestCache behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestCache:
    """
    Golden fixture: documents ManifestCache get/set/invalidate behavior (OMN-11547).
    """

    def _make_cache(self, default_ttl_seconds: int = 300) -> Any:
        from omniclaude.lib.core.manifest_injector import ManifestCache

        return ManifestCache(default_ttl_seconds=default_ttl_seconds)

    def test_get_returns_none_for_missing_key(self) -> None:
        cache = self._make_cache()
        assert cache.get("patterns") is None

    def test_set_then_get_returns_data(self) -> None:
        cache = self._make_cache()
        data = {"patterns": ["a", "b"]}
        cache.set("patterns", data)
        assert cache.get("patterns") == data

    def test_expired_entry_returns_none(self) -> None:
        from datetime import timedelta

        from omniclaude.lib.core.manifest_injector import CacheEntry

        cache = self._make_cache()
        # Manually plant an expired entry
        cache._caches["patterns"] = CacheEntry(
            data={"stale": True},
            timestamp=datetime.now(UTC) - timedelta(seconds=600),
            ttl_seconds=300,
            query_type="patterns",
        )
        assert cache.get("patterns") is None

    def test_invalidate_single_removes_entry(self) -> None:
        cache = self._make_cache()
        cache.set("patterns", {"x": 1})
        count = cache.invalidate("patterns")
        assert count == 1
        assert cache.get("patterns") is None

    def test_invalidate_all_clears_cache(self) -> None:
        cache = self._make_cache()
        cache.set("patterns", {"x": 1})
        cache.set("models", {"y": 2})
        count = cache.invalidate()
        assert count == 2

    def test_hit_rate_zero_initially(self) -> None:
        cache = self._make_cache()
        metrics = cache.get_metrics()
        assert metrics["overall"]["hit_rate_percent"] == 0.0

    def test_hit_rate_increases_after_cache_hit(self) -> None:
        cache = self._make_cache()
        cache.set("patterns", {"data": True})
        cache.get("patterns")  # hit
        metrics = cache.get_metrics()
        assert metrics["overall"]["hit_rate_percent"] > 0


# ---------------------------------------------------------------------------
# OMN-11547 — inject_manifest public API (sync wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInjectManifestPublicAPI:
    """
    Golden fixture: documents the public inject_manifest() sync wrapper
    behavior (OMN-11547).
    """

    def test_inject_manifest_returns_string(self) -> None:
        """inject_manifest() always returns a formatted string."""
        with (
            patch("omniclaude.lib.core.manifest_injector.IntelligenceCache"),
            patch("omniclaude.lib.core.manifest_injector.ManifestInjectionStorage"),
            patch("omniclaude.lib.core.manifest_injector.IntelligenceUsageTracker"),
            patch("omniclaude.lib.core.manifest_injector.PatternQualityScorer"),
            patch("omniclaude.lib.core.manifest_injector.TaskClassifier"),
            patch(
                "omniclaude.lib.core.manifest_injector.ManifestInjector._query_filesystem",
                new_callable=AsyncMock,
                return_value={
                    "root_path": "/fake",
                    "file_tree": [],
                    "total_files": 0,
                    "total_directories": 0,
                    "total_size_bytes": 0,
                    "file_types": {},
                    "onex_files": {},
                    "query_time_ms": 0,
                },
            ),
            patch(
                "omniclaude.lib.core.manifest_injector.ManifestInjector._query_debug_loop_context",
                new_callable=AsyncMock,
                return_value={
                    "available": False,
                    "reason": "mocked",
                    "stf_count": 0,
                    "categories": [],
                    "top_stfs": [],
                },
            ),
        ):
            from omniclaude.lib.core.manifest_injector import inject_manifest

            result = inject_manifest(
                correlation_id=_CORRELATION_ID,
                agent_name=_AGENT_NAME,
            )

        assert isinstance(result, str)
        assert len(result) > 0
