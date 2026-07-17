# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for omniclaude.lib.utils.pattern_tracker.

Covers the pure-compute surface of the pattern tracker without touching any
real infrastructure (no network, no on-disk state directory):

* ``ProcessingMode`` enum values.
* ``PerformanceMetrics`` metric math (processing time, weighted API time,
  success rate, cache-hit rate) including divide-by-zero guards.
* The config dataclasses (``BatchProcessingConfig`` / ``CacheConfig`` /
  ``ConnectionPoolConfig``) defaults.
* ``PatternTrackerConfig`` YAML loading, defaults, and derived properties
  (driven from a temp YAML file so ``onex_state`` is never touched).
* ``PerformanceMonitor`` operation/cache recording and snapshot behavior.
* ``PatternTracker`` construction, id generation, and the async
  ``track_*`` flows with the HTTP boundary mocked at ``_send_to_api_optimized``.

All async tests run under pytest-asyncio ``auto`` mode (see pyproject). HTTP is
patched at the module boundary so no live intelligence service is required.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from omniclaude.lib.utils import pattern_tracker
from omniclaude.lib.utils.pattern_tracker import (
    BatchProcessingConfig,
    CacheConfig,
    ConnectionPoolConfig,
    PatternTracker,
    PatternTrackerConfig,
    PerformanceMetrics,
    PerformanceMonitor,
    ProcessingMode,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict | None) -> Path:
    """Write a YAML config file (or an empty path) and return it."""
    cfg = tmp_path / "config.yaml"
    if data is not None:
        cfg.write_text(yaml.safe_dump(data))
    return cfg


@pytest.fixture
def tracker(tmp_path: Path) -> PatternTracker:
    """A PatternTracker backed by an empty temp config.

    The config gets a ``log_file`` attribute set so ``_setup_logging`` uses the
    temp path instead of reaching into the real onex state directory.
    """
    config = PatternTrackerConfig(config_path=_write_config(tmp_path, {}))
    config.log_file = tmp_path / "tracker.log"  # type: ignore[attr-defined]
    return PatternTracker(config=config)


# ---------------------------------------------------------------------------
# ProcessingMode
# ---------------------------------------------------------------------------


class TestProcessingMode:
    @pytest.mark.unit
    def test_enum_values(self) -> None:
        assert ProcessingMode.SYNC.value == "sync"
        assert ProcessingMode.ASYNC.value == "async"
        assert ProcessingMode.BATCH.value == "batch"
        assert ProcessingMode.QUEUED.value == "queued"

    @pytest.mark.unit
    def test_round_trip_from_value(self) -> None:
        assert ProcessingMode("batch") is ProcessingMode.BATCH

    @pytest.mark.unit
    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            ProcessingMode("nope")


# ---------------------------------------------------------------------------
# PerformanceMetrics
# ---------------------------------------------------------------------------


class TestPerformanceMetrics:
    @pytest.mark.unit
    def test_defaults(self) -> None:
        m = PerformanceMetrics()
        assert m.total_operations == 0
        assert m.successful_operations == 0
        assert m.failed_operations == 0
        assert m.cache_hits == 0
        assert m.cache_misses == 0
        assert m.total_api_calls == 0
        assert m.avg_processing_time_ms == 0.0
        assert m.avg_api_response_time_ms == 0.0
        # last_updated is an ISO timestamp string
        assert isinstance(m.last_updated, str)
        assert "T" in m.last_updated

    @pytest.mark.unit
    def test_update_processing_time_without_operations(self) -> None:
        m = PerformanceMetrics()
        m.update_processing_time(120.0)
        # total accumulates, but avg stays 0 because total_operations == 0
        assert m.total_processing_time_ms == 120.0
        assert m.avg_processing_time_ms == 0.0

    @pytest.mark.unit
    def test_update_processing_time_with_operations(self) -> None:
        m = PerformanceMetrics(total_operations=2)
        m.update_processing_time(100.0)
        m.update_processing_time(300.0)
        assert m.total_processing_time_ms == 400.0
        assert m.avg_processing_time_ms == 200.0  # 400 / 2

    @pytest.mark.unit
    def test_update_api_time_first_call_sets_value(self) -> None:
        m = PerformanceMetrics()
        m.update_api_time(50.0)
        assert m.total_api_calls == 1
        assert m.avg_api_response_time_ms == 50.0

    @pytest.mark.unit
    def test_update_api_time_uses_weighted_average(self) -> None:
        m = PerformanceMetrics()
        m.update_api_time(100.0)  # seeds avg at 100
        m.update_api_time(200.0)  # 100*0.9 + 200*0.1 = 110
        assert m.total_api_calls == 2
        assert m.avg_api_response_time_ms == pytest.approx(110.0)

    @pytest.mark.unit
    def test_get_success_rate_zero_operations(self) -> None:
        assert PerformanceMetrics().get_success_rate() == 0.0

    @pytest.mark.unit
    def test_get_success_rate_computes_percentage(self) -> None:
        m = PerformanceMetrics(total_operations=4, successful_operations=3)
        assert m.get_success_rate() == 75.0

    @pytest.mark.unit
    def test_get_cache_hit_rate_zero_operations(self) -> None:
        assert PerformanceMetrics().get_cache_hit_rate() == 0.0

    @pytest.mark.unit
    def test_get_cache_hit_rate_computes_percentage(self) -> None:
        m = PerformanceMetrics(cache_hits=3, cache_misses=1)
        assert m.get_cache_hit_rate() == 75.0


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


class TestConfigDataclassDefaults:
    @pytest.mark.unit
    def test_batch_processing_config_defaults(self) -> None:
        c = BatchProcessingConfig()
        assert c.enabled is True
        assert c.max_batch_size == 50
        assert c.max_batch_wait_time == 1.0
        assert c.max_queue_size == 1000
        assert c.worker_count == 4

    @pytest.mark.unit
    def test_cache_config_defaults(self) -> None:
        c = CacheConfig()
        assert c.pattern_id_cache_size == 1000
        assert c.api_response_cache_size == 500
        assert c.cache_ttl_seconds == 300
        assert c.enable_pattern_caching is True
        assert c.enable_response_caching is True

    @pytest.mark.unit
    def test_connection_pool_config_defaults(self) -> None:
        c = ConnectionPoolConfig()
        assert c.max_connections == 100
        assert c.max_keepalive_connections == 20
        assert c.keepalive_expiry == 300.0
        assert c.max_connection_reuse == 1000

    @pytest.mark.unit
    def test_dataclasses_accept_overrides(self) -> None:
        c = BatchProcessingConfig(enabled=False, max_batch_size=10, worker_count=1)
        assert c.enabled is False
        assert c.max_batch_size == 10
        assert c.worker_count == 1


# ---------------------------------------------------------------------------
# PatternTrackerConfig
# ---------------------------------------------------------------------------


class TestPatternTrackerConfig:
    @pytest.mark.unit
    def test_missing_config_file_yields_empty(self, tmp_path: Path) -> None:
        cfg = PatternTrackerConfig(config_path=tmp_path / "does-not-exist.yaml")
        # Defaults apply when nothing is loaded.
        assert cfg.enabled is True
        assert cfg.processing_mode is ProcessingMode.ASYNC
        assert cfg.timeout_seconds == 5.0
        assert cfg.max_retries == 3

    @pytest.mark.unit
    def test_malformed_yaml_falls_back_to_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "config.yaml"
        bad.write_text("::: not: valid: yaml: [")
        cfg = PatternTrackerConfig(config_path=bad)
        # A parse failure is swallowed and treated as empty config → defaults.
        assert cfg.enabled is True
        assert cfg.max_retries == 3

    @pytest.mark.unit
    def test_get_returns_default_when_path_absent(self, tmp_path: Path) -> None:
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, {}))
        assert cfg.get("KEY", ["a", "b", "c"], "fallback") == "fallback"

    @pytest.mark.unit
    def test_get_traverses_nested_yaml_path(self, tmp_path: Path) -> None:
        cfg = PatternTrackerConfig(
            config_path=_write_config(tmp_path, {"a": {"b": {"c": "deep"}}})
        )
        assert cfg.get("KEY", ["a", "b", "c"], "fallback") == "deep"

    @pytest.mark.unit
    def test_get_returns_default_on_partial_path(self, tmp_path: Path) -> None:
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, {"a": {"b": 1}}))
        # "a.b" is an int, not a dict → traversal stops and default returns.
        assert cfg.get("KEY", ["a", "b", "c"], "fallback") == "fallback"

    @pytest.mark.unit
    def test_scalar_properties_from_yaml(self, tmp_path: Path) -> None:
        data = {
            "pattern_tracking": {
                "intelligence_url": "http://intel.test",
                "enabled": False,
                "processing_mode": "batch",
                "timeout_seconds": 12.5,
                "max_retries": 7,
            }
        }
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, data))
        assert cfg.intelligence_url == "http://intel.test"
        assert cfg.enabled is False
        assert cfg.processing_mode is ProcessingMode.BATCH
        assert cfg.timeout_seconds == 12.5
        assert cfg.max_retries == 7

    @pytest.mark.unit
    def test_processing_mode_invalid_falls_back_to_async(self, tmp_path: Path) -> None:
        data = {"pattern_tracking": {"processing_mode": "not-a-mode"}}
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, data))
        assert cfg.processing_mode is ProcessingMode.ASYNC

    @pytest.mark.unit
    def test_intelligence_url_defaults_to_settings(self, tmp_path: Path) -> None:
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, {}))
        # Falls back to the pydantic settings value; just assert it is a str URL.
        assert isinstance(cfg.intelligence_url, str)
        assert cfg.intelligence_url

    @pytest.mark.unit
    def test_batch_config_property_defaults(self, tmp_path: Path) -> None:
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, {}))
        bc = cfg.batch_config
        assert isinstance(bc, BatchProcessingConfig)
        assert bc.enabled is True
        assert bc.max_batch_size == 50

    @pytest.mark.unit
    def test_batch_config_property_overrides(self, tmp_path: Path) -> None:
        data = {
            "batch_processing": {
                "enabled": False,
                "max_batch_size": 5,
                "worker_count": 2,
            }
        }
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, data))
        bc = cfg.batch_config
        assert bc.enabled is False
        assert bc.max_batch_size == 5
        assert bc.worker_count == 2

    @pytest.mark.unit
    def test_cache_config_property_overrides(self, tmp_path: Path) -> None:
        data = {
            "caching": {"pattern_id_cache_size": 42, "enable_response_caching": False}
        }
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, data))
        cc = cfg.cache_config
        assert isinstance(cc, CacheConfig)
        assert cc.pattern_id_cache_size == 42
        assert cc.enable_response_caching is False
        # Untouched keys keep their defaults.
        assert cc.api_response_cache_size == 500

    @pytest.mark.unit
    def test_connection_pool_config_property_overrides(self, tmp_path: Path) -> None:
        data = {"connection_pool": {"max_connections": 7, "keepalive_expiry": 9.0}}
        cfg = PatternTrackerConfig(config_path=_write_config(tmp_path, data))
        pc = cfg.connection_pool_config
        assert isinstance(pc, ConnectionPoolConfig)
        assert pc.max_connections == 7
        assert pc.keepalive_expiry == 9.0
        assert pc.max_keepalive_connections == 20


# ---------------------------------------------------------------------------
# PerformanceMonitor
# ---------------------------------------------------------------------------


class TestPerformanceMonitor:
    @pytest.mark.unit
    def test_record_success_operation(self) -> None:
        mon = PerformanceMonitor("t-1")
        mon.record_operation(
            "op", success=True, duration_ms=100.0, api_response_time_ms=40.0
        )
        m = mon.get_metrics()
        assert m.total_operations == 1
        assert m.successful_operations == 1
        assert m.failed_operations == 0
        assert m.total_api_calls == 1
        assert m.avg_api_response_time_ms == 40.0
        assert m.avg_processing_time_ms == 100.0

    @pytest.mark.unit
    def test_record_failure_operation(self) -> None:
        mon = PerformanceMonitor("t-2")
        mon.record_operation("op", success=False, duration_ms=10.0)
        m = mon.get_metrics()
        assert m.total_operations == 1
        assert m.successful_operations == 0
        assert m.failed_operations == 1
        # No api_response_time supplied → no api call counted.
        assert m.total_api_calls == 0

    @pytest.mark.unit
    def test_record_cache_hit_and_miss(self) -> None:
        mon = PerformanceMonitor("t-3")
        mon.record_cache_hit()
        mon.record_cache_hit()
        mon.record_cache_miss()
        m = mon.get_metrics()
        assert m.cache_hits == 2
        assert m.cache_misses == 1
        assert m.get_cache_hit_rate() == pytest.approx(66.6667, rel=1e-3)

    @pytest.mark.unit
    def test_get_recent_performance_empty(self) -> None:
        mon = PerformanceMonitor("t-4")
        recent = mon.get_recent_performance()
        assert recent == {
            "avg_time_ms": 0,
            "operations_per_second": 0,
            "p95_time_ms": 0,
        }

    @pytest.mark.unit
    def test_get_recent_performance_populated(self) -> None:
        mon = PerformanceMonitor("t-5")
        for d in (10.0, 20.0, 30.0):
            mon.record_operation("op", success=True, duration_ms=d)
        recent = mon.get_recent_performance(window_seconds=60)
        assert recent["avg_time_ms"] == pytest.approx(20.0)
        assert recent["operations_per_second"] > 0
        assert recent["p95_time_ms"] > 0


# ---------------------------------------------------------------------------
# PatternTracker
# ---------------------------------------------------------------------------


class TestPatternTrackerConstruction:
    @pytest.mark.unit
    def test_construction_sets_ids_and_components(
        self, tracker: PatternTracker
    ) -> None:
        assert tracker.session_id
        assert tracker.tracker_id.startswith("tracker-")
        assert isinstance(tracker.http_client, httpx.AsyncClient)
        assert isinstance(tracker.monitor, PerformanceMonitor)
        assert tracker.log_file is not None

    @pytest.mark.unit
    def test_correlation_ids_are_unique(self, tracker: PatternTracker) -> None:
        a = tracker.generate_correlation_id()
        b = tracker.generate_correlation_id()
        assert a != b

    @pytest.mark.unit
    def test_uncached_pattern_id_is_deterministic(
        self, tracker: PatternTracker
    ) -> None:
        pid1 = tracker._generate_pattern_id_uncached("print('x')")
        pid2 = tracker._generate_pattern_id_uncached("print('x')")
        assert pid1 == pid2
        assert len(pid1) == 16

    @pytest.mark.unit
    def test_cached_pattern_id_records_hit_on_second_call(
        self, tracker: PatternTracker
    ) -> None:
        code = "def f():\n    return 1"
        pid1 = tracker._generate_pattern_id_cached(code, {"k": "v"})
        pid2 = tracker._generate_pattern_id_cached(code, {"k": "v"})
        assert pid1 == pid2
        metrics = tracker.get_performance_metrics()
        assert metrics.cache_hits >= 1
        assert metrics.cache_misses >= 1

    @pytest.mark.unit
    def test_get_performance_summary_shape(self, tracker: PatternTracker) -> None:
        summary = tracker.get_performance_summary()
        assert summary["tracker_id"] == tracker.tracker_id
        assert "uptime_seconds" in summary
        assert isinstance(summary["metrics"], PerformanceMetrics)
        assert "cache_stats" in summary
        assert "connection_pool" in summary
        assert (
            summary["batch_processing"]["worker_count"]
            == tracker.config.batch_config.worker_count
        )


class TestPatternTrackerAsyncFlows:
    @pytest.mark.unit
    async def test_track_pattern_creation_disabled_returns_id_without_api(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = {"pattern_tracking": {"enabled": False}}
        config = PatternTrackerConfig(config_path=_write_config(tmp_path, data))
        config.log_file = tmp_path / "t.log"  # type: ignore[attr-defined]
        trk = PatternTracker(config=config)

        async def _boom(*_a: object, **_k: object) -> None:
            raise AssertionError("API must not be called when disabled")

        monkeypatch.setattr(trk, "_send_to_api_optimized", _boom)
        pid = await trk.track_pattern_creation("code", {"tool": "Write"})
        assert len(pid) == 16
        await trk.close()

    @pytest.mark.unit
    async def test_track_pattern_creation_success_records_operation(
        self, tracker: PatternTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def _fake_send(
            endpoint_key: str, data: dict, retry_count: int = 0
        ) -> dict:
            calls.append(endpoint_key)
            return {"status": "ok"}

        monkeypatch.setattr(tracker, "_send_to_api_optimized", _fake_send)
        pid = await tracker.track_pattern_creation(
            "print('hello')", {"tool": "Write", "file_path": "a.py"}
        )
        assert len(pid) == 16
        assert calls == ["track_lineage"]
        m = tracker.get_performance_metrics()
        assert m.total_operations == 1
        assert m.successful_operations == 1

    @pytest.mark.unit
    async def test_track_pattern_creation_api_error_marks_failure(
        self, tracker: PatternTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fail(*_a: object, **_k: object) -> dict:
            raise httpx.ConnectError("down")

        monkeypatch.setattr(tracker, "_send_to_api_optimized", _fail)
        pid = await tracker.track_pattern_creation("x = 1", {"tool": "Edit"})
        assert len(pid) == 16
        m = tracker.get_performance_metrics()
        assert m.total_operations == 1
        assert m.failed_operations == 1

    @pytest.mark.unit
    async def test_track_pattern_execution_records_operation(
        self, tracker: PatternTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_send(
            endpoint_key: str, data: dict, retry_count: int = 0
        ) -> dict:
            return {"ok": True}

        monkeypatch.setattr(tracker, "_send_to_api_optimized", _fake_send)
        await tracker.track_pattern_execution("pid-1", {"latency_ms": 5}, success=True)
        m = tracker.get_performance_metrics()
        assert m.total_operations == 1
        assert m.successful_operations == 1

    @pytest.mark.unit
    async def test_track_pattern_execution_disabled_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = PatternTrackerConfig(
            config_path=_write_config(
                tmp_path, {"pattern_tracking": {"enabled": False}}
            )
        )
        config.log_file = tmp_path / "t.log"  # type: ignore[attr-defined]
        trk = PatternTracker(config=config)
        await trk.track_pattern_execution("pid", {})
        assert trk.get_performance_metrics().total_operations == 0
        await trk.close()

    @pytest.mark.unit
    async def test_track_pattern_creation_batch_returns_ids(
        self, tracker: PatternTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_send(
            endpoint_key: str, data: dict, retry_count: int = 0
        ) -> dict:
            assert endpoint_key == "track_lineage_batch"
            return {"ok": True}

        monkeypatch.setattr(tracker, "_send_to_api_optimized", _fake_send)
        patterns = [
            ("a = 1", {"tool": "Write"}, None),
            ("b = 2", {"tool": "Write"}, {"note": "x"}),
        ]
        ids = await tracker.track_pattern_creation_batch(patterns)
        assert len(ids) == 2
        assert all(len(i) == 16 for i in ids)

    @pytest.mark.unit
    async def test_track_pattern_creation_batch_empty_returns_empty(
        self, tracker: PatternTracker
    ) -> None:
        assert await tracker.track_pattern_creation_batch([]) == []

    @pytest.mark.unit
    async def test_send_to_api_optimized_stops_at_max_retries(
        self, tracker: PatternTracker
    ) -> None:
        # retry_count already at the ceiling → returns None without any HTTP call.
        result = await tracker._send_to_api_optimized(
            "track_lineage", {}, retry_count=tracker.config.max_retries
        )
        assert result is None

    @pytest.mark.unit
    async def test_close_is_idempotent(self, tracker: PatternTracker) -> None:
        await tracker.close()
        # A second close on an already-closed client should not raise loudly.
        await tracker.close()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestGetTracker:
    @pytest.mark.unit
    def test_get_tracker_returns_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reset the module-level singleton and substitute a cheap sentinel
        # factory so no real PatternTracker (HTTP client, state dir) is built.
        monkeypatch.setattr(pattern_tracker, "_tracker_instance", None)
        sentinel = object()
        monkeypatch.setattr(pattern_tracker, "PatternTracker", lambda: sentinel)

        first = pattern_tracker.get_tracker()
        second = pattern_tracker.get_tracker()
        assert first is sentinel
        assert first is second  # lazy singleton returns the same instance

        # Clean up so we do not leak the sentinel into other tests.
        monkeypatch.setattr(pattern_tracker, "_tracker_instance", None)
