# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the env_sync_alert skill check module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from plugins.onex.skills.env_sync_alert._lib.check import (
    EnvSyncAlertConfig,
    LogScanEnvResult,
    _create_or_update_linear_ticket,
    check_critical_log_patterns,
    check_env_sync_log,
    run_alert_check,
)


def _write_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


class TestCheckEnvSyncLog:
    def test_no_errors_returns_clean(self, tmp_path: Path) -> None:
        log = tmp_path / "env-sync.log"
        now = datetime.now(UTC)
        _write_log(
            log,
            [
                f"{(now - timedelta(minutes=30)).isoformat()} SUCCESS seed-infisical exit=0",
            ],
        )
        result = check_env_sync_log(log, now=now)
        assert result.error_count == 0
        assert result.last_success_age_seconds is not None
        assert result.last_success_age_seconds < 3600

    def test_three_errors_no_recent_success(self, tmp_path: Path) -> None:
        log = tmp_path / "env-sync.log"
        now = datetime.now(UTC)
        two_hours_ago = now - timedelta(hours=2)
        _write_log(
            log,
            [
                f"{two_hours_ago.isoformat()} SUCCESS seed-infisical exit=0",
                f"{(now - timedelta(minutes=45)).isoformat()} FAILURE seed-infisical exit=1",
                f"{(now - timedelta(minutes=30)).isoformat()} FAILURE seed-infisical exit=1",
                f"{(now - timedelta(minutes=15)).isoformat()} FAILURE seed-infisical exit=1",
            ],
        )
        result = check_env_sync_log(log, now=now)
        assert result.error_count == 3
        assert result.last_success_age_seconds is not None
        assert result.last_success_age_seconds > 3600

    def test_missing_log_is_error(self, tmp_path: Path) -> None:
        log = tmp_path / "nonexistent.log"
        result = check_env_sync_log(log, now=datetime.now(UTC))
        assert result.error_count >= 1
        assert result.last_success_age_seconds is None

    def test_errors_after_success_not_counted(self, tmp_path: Path) -> None:
        log = tmp_path / "env-sync.log"
        now = datetime.now(UTC)
        _write_log(
            log,
            [
                f"{(now - timedelta(hours=3)).isoformat()} FAILURE seed-infisical exit=1",
                f"{(now - timedelta(hours=2)).isoformat()} FAILURE seed-infisical exit=1",
                f"{(now - timedelta(minutes=30)).isoformat()} SUCCESS seed-infisical exit=0",
            ],
        )
        result = check_env_sync_log(log, now=now)
        # Errors before last success don't count
        assert result.error_count == 0


class TestCheckCriticalLogPatterns:
    def test_no_errors_returns_empty(self, tmp_path: Path) -> None:
        log = tmp_path / "hooks.log"
        _write_log(log, ["INFO: session started", "INFO: tool executed"])
        results = check_critical_log_patterns([log])
        assert len(results) == 0

    def test_error_pattern_detected(self, tmp_path: Path) -> None:
        log = tmp_path / "hooks.log"
        _write_log(
            log,
            [
                "INFO: session started",
                "ERROR: failed to emit event to kafka",
                "CRITICAL: cannot connect to postgres",
            ],
        )
        results = check_critical_log_patterns([log])
        assert len(results) == 2

    def test_missing_log_skipped(self, tmp_path: Path) -> None:
        log = tmp_path / "nonexistent.log"
        results = check_critical_log_patterns([log])
        assert len(results) == 0


class TestRunAlertCheck:
    def test_writes_friction_entry_when_env_sync_failing(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "onex_state"
        friction_dir = state_dir / "friction"
        log_dir = state_dir / "logs"

        now = datetime.now(UTC)
        two_hours_ago = now - timedelta(hours=2)
        _write_log(
            log_dir / "env-sync.log",
            [
                f"{two_hours_ago.isoformat()} SUCCESS seed-infisical exit=0",
                f"{(now - timedelta(minutes=45)).isoformat()} FAILURE seed-infisical exit=1",
                f"{(now - timedelta(minutes=30)).isoformat()} FAILURE seed-infisical exit=1",
                f"{(now - timedelta(minutes=15)).isoformat()} FAILURE seed-infisical exit=1",
            ],
        )

        config = EnvSyncAlertConfig(
            state_dir=state_dir,
            error_threshold=0,
            success_age_threshold_seconds=3600,
            create_linear_ticket=False,
        )
        result = run_alert_check(config, now=now)

        assert result.alert_fired
        friction_files = list(friction_dir.glob("env-sync-alert-*.yaml"))
        assert len(friction_files) == 1

        import yaml

        data = yaml.safe_load(friction_files[0].read_text())
        assert data["surface"] == "config/env-sync-infisical"
        assert data["severity"] in ("high", "critical")

    def test_no_friction_when_clean(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "onex_state"
        friction_dir = state_dir / "friction"
        log_dir = state_dir / "logs"

        now = datetime.now(UTC)
        _write_log(
            log_dir / "env-sync.log",
            [
                f"{(now - timedelta(minutes=10)).isoformat()} SUCCESS seed-infisical exit=0",
            ],
        )

        config = EnvSyncAlertConfig(
            state_dir=state_dir,
            error_threshold=0,
            success_age_threshold_seconds=3600,
            create_linear_ticket=False,
        )
        result = run_alert_check(config, now=now)

        assert not result.alert_fired
        assert not list(friction_dir.glob("*.yaml")) if friction_dir.exists() else True


class TestCreateLinearTicket:
    def test_graphql_errors_logged_and_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When Linear returns HTTP 200 with a GraphQL `errors` field, the
        helper must log the errors and return None (per OMN-9033 CR thread)."""
        import json as _json
        import logging
        import urllib.request

        monkeypatch.setenv("LINEAR_API_KEY", "test-key")

        class _FakeResp:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def read(self) -> bytes:
                return self._body

            def __enter__(self) -> _FakeResp:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        error_body = _json.dumps(
            {
                "errors": [{"message": "Argument Validation Failed"}],
                "data": None,
            }
        ).encode()

        def _fake_urlopen(*args: object, **kwargs: object) -> _FakeResp:
            return _FakeResp(error_body)

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

        env_result = LogScanEnvResult(
            error_count=3,
            last_success_age_seconds=7200,
            last_success_ts="2026-04-18T00:00:00+00:00",
            last_run_line="FAILURE",
        )
        friction_data: dict[str, object] = {"description": "test"}

        with caplog.at_level(logging.WARNING):
            result = _create_or_update_linear_ticket(friction_data, env_result)

        assert result is None
        assert any("linear GraphQL errors" in rec.message for rec in caplog.records)
