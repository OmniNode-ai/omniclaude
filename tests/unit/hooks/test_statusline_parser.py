# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for statusline_parser — limit data extraction from Claude Code sources."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omniclaude.hooks.statusline_parser import (
    ModelLimitStatus,
    parse_statusline_json,
    parse_usage_cache,
    read_limit_status,
)


@pytest.mark.unit
class TestParseStatuslineJson:
    """Tests for parsing context_window from statusline JSON input."""

    def test_extracts_used_percentage(self) -> None:
        result = parse_statusline_json(
            {
                "context_window": {"used_percentage": 87},
            }
        )
        assert result == 87

    def test_float_truncated_to_int(self) -> None:
        result = parse_statusline_json(
            {
                "context_window": {"used_percentage": 45.7},
            }
        )
        assert result == 45

    def test_missing_context_window(self) -> None:
        assert parse_statusline_json({}) is None

    def test_missing_used_percentage(self) -> None:
        assert parse_statusline_json({"context_window": {}}) is None

    def test_none_input(self) -> None:
        assert parse_statusline_json({"context_window": None}) is None

    def test_zero_percent(self) -> None:
        result = parse_statusline_json(
            {
                "context_window": {"used_percentage": 0},
            }
        )
        assert result == 0

    def test_hundred_percent(self) -> None:
        result = parse_statusline_json(
            {
                "context_window": {"used_percentage": 100},
            }
        )
        assert result == 100


@pytest.mark.unit
class TestParseUsageCache:
    """Tests for parsing the OAuth usage API cache."""

    def test_five_hour_and_seven_day(self) -> None:
        status = parse_usage_cache(
            {
                "five_hour": {
                    "utilization": 45.2,
                    "resets_at": "2026-04-02T15:00:00Z",
                },
                "seven_day": {
                    "utilization": 20.1,
                    "resets_at": "2026-04-08T00:00:00Z",
                },
            }
        )
        assert status.session_percent == 45
        assert status.weekly_percent == 20
        assert status.session_reset_at == "2026-04-02T15:00:00Z"
        assert status.weekly_reset_at == "2026-04-08T00:00:00Z"

    def test_fallback_to_current_period(self) -> None:
        status = parse_usage_cache(
            {
                "current_period": {
                    "usage_percentage": 30,
                    "resets_at": "2026-04-02T16:00:00Z",
                },
            }
        )
        assert status.session_percent == 30
        assert status.session_reset_at == "2026-04-02T16:00:00Z"

    def test_empty_cache(self) -> None:
        status = parse_usage_cache({})
        assert status.session_percent is None
        assert status.weekly_percent is None
        assert status.session_reset_at is None
        assert status.weekly_reset_at is None

    def test_five_hour_takes_priority_over_current_period(self) -> None:
        status = parse_usage_cache(
            {
                "five_hour": {"utilization": 45},
                "current_period": {"usage_percentage": 99},
            }
        )
        assert status.session_percent == 45


@pytest.mark.unit
class TestReadLimitStatus:
    """Tests for the combined read_limit_status function."""

    def test_combines_all_sources(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "usage-cache.json"
        cache_file.write_text(
            json.dumps(
                {
                    "five_hour": {
                        "utilization": 45,
                        "resets_at": "2026-04-02T15:00:00Z",
                    },
                    "seven_day": {
                        "utilization": 20,
                        "resets_at": "2026-04-08T00:00:00Z",
                    },
                }
            )
        )

        status = read_limit_status(
            statusline_input={"context_window": {"used_percentage": 87}},
            usage_cache_path=cache_file,
        )
        assert status.context_percent == 87
        assert status.session_percent == 45
        assert status.weekly_percent == 20

    def test_no_statusline_input(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "usage-cache.json"
        cache_file.write_text(
            json.dumps(
                {
                    "five_hour": {"utilization": 30},
                }
            )
        )

        status = read_limit_status(
            statusline_input=None,
            usage_cache_path=cache_file,
        )
        assert status.context_percent is None
        assert status.session_percent == 30

    def test_missing_cache_file(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "nonexistent.json"
        status = read_limit_status(
            statusline_input={"context_window": {"used_percentage": 50}},
            usage_cache_path=cache_file,
        )
        assert status.context_percent == 50
        assert status.session_percent is None

    def test_corrupt_cache_file(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "corrupt.json"
        cache_file.write_text("not valid json {{{")
        status = read_limit_status(
            statusline_input={"context_window": {"used_percentage": 60}},
            usage_cache_path=cache_file,
        )
        assert status.context_percent == 60
        assert status.session_percent is None


@pytest.mark.unit
class TestModelLimitStatus:
    """Tests for ModelLimitStatus model constraints."""

    def test_frozen(self) -> None:
        status = ModelLimitStatus(context_percent=50)
        with pytest.raises(Exception):
            status.context_percent = 60  # type: ignore[misc]

    def test_percent_bounds(self) -> None:
        ModelLimitStatus(context_percent=0)
        ModelLimitStatus(context_percent=100)
        with pytest.raises(Exception):
            ModelLimitStatus(context_percent=-1)
        with pytest.raises(Exception):
            ModelLimitStatus(context_percent=101)
