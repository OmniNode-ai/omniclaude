# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Characterization tests for ManifestInjector format helper methods (OMN-12389).

Extends the golden fixture coverage in test_manifest_injector_golden.py to lock
the output contract of the internal format helpers:

- _format_patterns: text output shape (header, bullet format, empty fallback)
- _format_infrastructure: text output shape (PostgreSQL, Kafka lines)
- _format_patterns_result: dict shape (available list, dedup fields)
- _format_infrastructure_result: passthrough when already structured; legacy reshape
- ManifestInjectionStorage._serialize_for_json: recursive serialization contract

These tests do NOT test network I/O, Kafka, or DB. All external deps mocked.
Any refactoring that causes a failure here has changed prompt-visible behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_injector() -> Any:
    """Construct a ManifestInjector with all heavyweight deps mocked."""
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
            enable_intelligence=False,
            enable_storage=False,
            enable_cache=False,
            agent_name="test-agent",
        )
    return injector


def _make_pattern(
    name: str = "TestPattern",
    confidence: float = 0.9,
    file_path: str = "src/foo.py",
    node_types: list[str] | None = None,
    use_cases: list[str] | None = None,
    content: str = "",
    language: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "confidence": confidence,
        "file_path": file_path,
        "node_types": node_types or ["EFFECT"],
        "use_cases": use_cases or ["testing"],
        "description": f"Description of {name}",
        "content": content,
        "language": language,
    }


# ---------------------------------------------------------------------------
# _format_patterns: text output contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatPatternsText:
    """Golden fixture: _format_patterns() text output shape (OMN-12389)."""

    def test_starts_with_available_patterns_header(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns({"available": [_make_pattern()]})
        assert result.startswith("AVAILABLE PATTERNS:")

    def test_empty_patterns_shows_fallback_message(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns({"available": []})
        assert "No patterns discovered" in result

    def test_pattern_name_in_output(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns(
            {"available": [_make_pattern(name="MyPattern")]}
        )
        assert "MyPattern" in result

    def test_confidence_formatted_as_percentage(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns(
            {"available": [_make_pattern(confidence=0.85)]}
        )
        assert "85%" in result

    def test_none_confidence_shows_na(self) -> None:
        injector = _make_injector()
        p = _make_pattern()
        p["confidence"] = None
        result = injector._format_patterns({"available": [p]})
        assert "N/A" in result

    def test_file_path_shown_when_present(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns(
            {"available": [_make_pattern(file_path="src/bar.py")]}
        )
        assert "src/bar.py" in result

    def test_node_types_shown_when_present(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns(
            {"available": [_make_pattern(node_types=["COMPUTE"])]}
        )
        assert "COMPUTE" in result

    def test_bullet_point_format(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns({"available": [_make_pattern()]})
        assert "  •" in result

    def test_total_count_at_bottom(self) -> None:
        injector = _make_injector()
        patterns = [_make_pattern(f"P-{i}") for i in range(3)]
        result = injector._format_patterns({"available": patterns})
        assert "Total: 3" in result

    def test_overflow_shows_remaining_count(self) -> None:
        """More than 20 patterns: shows '... and N more patterns'."""
        injector = _make_injector()
        patterns = [_make_pattern(f"P-{i}") for i in range(25)]
        result = injector._format_patterns({"available": patterns})
        assert "and 5 more patterns" in result

    def test_multi_instance_shows_instance_count(self) -> None:
        injector = _make_injector()
        p = _make_pattern()
        p["instance_count"] = 3
        result = injector._format_patterns({"available": [p]})
        assert "3 instances" in result

    def test_single_instance_no_instance_count_shown(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns({"available": [_make_pattern()]})
        assert "instances" not in result

    def test_language_shown_when_present(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns(
            {"available": [_make_pattern(language="python")]}
        )
        assert "Language: python" in result

    def test_deduplication_stats_shown_when_duplicates_removed(self) -> None:
        injector = _make_injector()
        data = {
            "available": [_make_pattern()],
            "duplicates_removed": 5,
            "original_count": 6,
            "collections_queried": {"archon_vectors": 3, "code_generation_patterns": 3},
        }
        result = injector._format_patterns(data)
        assert "duplicates removed" in result

    def test_collections_stats_shown_when_present(self) -> None:
        injector = _make_injector()
        data = {
            "available": [_make_pattern()],
            "collections_queried": {"archon_vectors": 2, "code_generation_patterns": 3},
        }
        result = injector._format_patterns(data)
        assert "archon_vectors" in result
        assert "code_generation_patterns" in result


# ---------------------------------------------------------------------------
# _format_infrastructure: text output contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatInfrastructureText:
    """Golden fixture: _format_infrastructure() text output shape (OMN-12389)."""

    def _pg_infra(
        self,
        *,
        host: str = "db.test.internal",
        port: str = "5432",
        database: str = "onex",
        status: str = "connected",
        tables: int = 42,
    ) -> dict[str, Any]:
        return {
            "remote_services": {
                "postgresql": {
                    "host": host,
                    "port": port,
                    "database": database,
                    "status": status,
                    "tables": tables,
                }
            }
        }

    def test_starts_with_infrastructure_topology_header(self) -> None:
        injector = _make_injector()
        result = injector._format_infrastructure(self._pg_infra())
        assert result.startswith("INFRASTRUCTURE TOPOLOGY:")

    def test_postgresql_host_port_db_in_output(self) -> None:
        injector = _make_injector()
        result = injector._format_infrastructure(
            self._pg_infra(host="db-host", port="5436", database="mydb")
        )
        assert "db-host:5436/mydb" in result

    def test_postgresql_status_in_output(self) -> None:
        injector = _make_injector()
        result = injector._format_infrastructure(self._pg_infra(status="connected"))
        assert "connected" in result

    def test_postgresql_tables_count_shown(self) -> None:
        injector = _make_injector()
        result = injector._format_infrastructure(self._pg_infra(tables=17))
        assert "17" in result

    def test_empty_postgresql_shows_scan_failed(self) -> None:
        injector = _make_injector()
        data = {"remote_services": {"postgresql": {}}}
        result = injector._format_infrastructure(data)
        assert "scan failed" in result

    def test_kafka_section_present_when_provided(self) -> None:
        injector = _make_injector()
        data = {
            "remote_services": {
                "kafka": {
                    "bootstrap_servers": "localhost:19092",
                    "status": "connected",
                    "topics": 5,
                }
            }
        }
        result = injector._format_infrastructure(data)
        assert "Kafka" in result or "kafka" in result.lower()
        assert "localhost:19092" in result


# ---------------------------------------------------------------------------
# _format_patterns_result: dict shape contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatPatternsResult:
    """Golden fixture: _format_patterns_result() dict shape (OMN-12389)."""

    def test_returns_dict(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns_result({"patterns": [], "query_time_ms": 10})
        assert isinstance(result, dict)

    def test_available_key_present(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns_result({"patterns": [], "query_time_ms": 0})
        assert "available" in result

    def test_available_is_list(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns_result({"patterns": [], "query_time_ms": 0})
        assert isinstance(result["available"], list)

    def test_total_count_matches_deduplicated(self) -> None:
        injector = _make_injector()
        patterns = [_make_pattern("A"), _make_pattern("B")]
        result = injector._format_patterns_result(
            {"patterns": patterns, "query_time_ms": 5}
        )
        assert result["total_count"] == 2

    def test_original_count_preserved(self) -> None:
        injector = _make_injector()
        patterns = [_make_pattern("A"), _make_pattern("B")]
        result = injector._format_patterns_result(
            {"patterns": patterns, "query_time_ms": 5}
        )
        assert result["original_count"] == 2

    def test_duplicates_removed_key_present(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns_result({"patterns": [], "query_time_ms": 0})
        assert "duplicates_removed" in result

    def test_query_time_ms_forwarded(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns_result({"patterns": [], "query_time_ms": 99})
        assert result["query_time_ms"] == 99

    def test_available_entry_has_name_key(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns_result(
            {"patterns": [_make_pattern("MyPat")], "query_time_ms": 0}
        )
        assert result["available"][0]["name"] == "MyPat"

    def test_available_entry_has_confidence_key(self) -> None:
        injector = _make_injector()
        result = injector._format_patterns_result(
            {"patterns": [_make_pattern(confidence=0.75)], "query_time_ms": 0}
        )
        assert result["available"][0]["confidence"] == pytest.approx(0.75)

    def test_deduplication_removes_same_name_pattern(self) -> None:
        """Two patterns with identical names → deduplicated to one."""
        injector = _make_injector()
        # Identical names → dedup
        patterns = [
            _make_pattern("SameName", confidence=0.8),
            _make_pattern("SameName", confidence=0.9),
        ]
        result = injector._format_patterns_result(
            {"patterns": patterns, "query_time_ms": 0}
        )
        assert result["duplicates_removed"] >= 1
        assert result["total_count"] < 2


# ---------------------------------------------------------------------------
# _format_infrastructure_result: passthrough vs legacy reshape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatInfrastructureResult:
    """Golden fixture: _format_infrastructure_result() shape contract (OMN-12389)."""

    def test_passthrough_when_remote_services_present(self) -> None:
        """Already-structured result passes through unchanged."""
        injector = _make_injector()
        structured = {"remote_services": {"postgresql": {}}, "local_services": {}}
        result = injector._format_infrastructure_result(structured)
        assert result is structured

    def test_passthrough_when_local_services_present(self) -> None:
        injector = _make_injector()
        structured = {"local_services": {"qdrant": {}}}
        result = injector._format_infrastructure_result(structured)
        assert result is structured

    def test_legacy_format_reshaped_to_remote_services(self) -> None:
        """Old flat format gets reshaped into nested remote_services dict."""
        injector = _make_injector()
        legacy = {"postgresql": {"host": "db"}, "kafka": {"bootstrap": "kf"}}
        result = injector._format_infrastructure_result(legacy)
        assert "remote_services" in result
        assert "postgresql" in result["remote_services"]
        assert "kafka" in result["remote_services"]

    def test_legacy_format_has_local_services(self) -> None:
        injector = _make_injector()
        legacy = {"qdrant": {"status": "ok"}}
        result = injector._format_infrastructure_result(legacy)
        assert "local_services" in result
        assert "qdrant" in result["local_services"]


# ---------------------------------------------------------------------------
# ManifestInjectionStorage._serialize_for_json: recursive serialization
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerializeForJson:
    """Golden fixture: ManifestInjectionStorage._serialize_for_json() (OMN-12389)."""

    def _serialize(self, obj: Any) -> Any:
        from omniclaude.lib.core.manifest_injector import ManifestInjectionStorage

        return ManifestInjectionStorage._serialize_for_json(obj)

    def test_none_returns_none(self) -> None:
        assert self._serialize(None) is None

    def test_str_passthrough(self) -> None:
        assert self._serialize("hello") == "hello"

    def test_int_passthrough(self) -> None:
        assert self._serialize(42) == 42

    def test_bool_passthrough(self) -> None:
        assert self._serialize(True) is True

    def test_dict_recursed(self) -> None:
        result = self._serialize({"a": 1, "b": None})
        assert result == {"a": 1, "b": None}

    def test_list_recursed(self) -> None:
        result = self._serialize([1, "two", None])
        assert result == [1, "two", None]

    def test_tuple_recursed_to_list(self) -> None:
        result = self._serialize((1, 2, 3))
        assert result == [1, 2, 3]

    def test_nested_dict_recursed(self) -> None:
        nested = {"outer": {"inner": "value"}}
        result = self._serialize(nested)
        assert result == {"outer": {"inner": "value"}}

    def test_pydantic_model_serialized_to_dict(self) -> None:
        from pydantic import BaseModel

        class _Simple(BaseModel):
            x: int = 1
            y: str = "hello"

        result = self._serialize(_Simple())
        assert isinstance(result, dict)
        assert result["x"] == 1
        assert result["y"] == "hello"

    def test_pydantic_url_type_serialized_to_str(self) -> None:
        """Pydantic URL objects must be serialized to str (avoids JSON errors)."""
        from pydantic import AnyUrl, TypeAdapter

        url = TypeAdapter(AnyUrl).validate_python("https://example.com")
        result = self._serialize(url)
        assert isinstance(result, str)
        assert result == "https://example.com/"

    def test_nested_list_in_dict_recursed(self) -> None:
        data = {"items": [1, 2, {"nested": True}]}
        result = self._serialize(data)
        assert result["items"][2]["nested"] is True
