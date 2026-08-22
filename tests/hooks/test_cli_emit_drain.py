# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the `omniclaude-emit drain` CLI wiring (OMN-16090)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from omniclaude.hooks.cli_emit import cli

pytestmark = pytest.mark.unit


def _write_spool_file(spool_dir: Path, name: str) -> None:
    spool_dir.mkdir(parents=True, exist_ok=True)
    (spool_dir / name).write_text(
        json.dumps(
            {
                "event_type": "artifact.captured",
                "payload": {"x": 1},
                "spooled_at_utc": "2026-06-28T17:25:25.517566+00:00",
                "spool_reason": "FileNotFoundError: nope",
            }
        )
    )


class TestDrainCli:
    def test_dry_run_exits_zero_and_needs_no_credential(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY", raising=False)
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY_FILE", raising=False)
        _write_spool_file(tmp_path, "a.json")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "drain",
                "--spool-dir",
                str(tmp_path),
                "--base-url",
                "https://gw.example",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "DRY-RUN" in result.output

    def test_missing_credential_fails_fast(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY", raising=False)
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY_FILE", raising=False)
        _write_spool_file(tmp_path, "a.json")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["drain", "--spool-dir", str(tmp_path), "--base-url", "https://gw.example"],
        )
        assert result.exit_code == 2
        assert "ONEX_GATEWAY_API_KEY" in result.output

    def test_missing_base_url_fails_fast(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_API_BASE_URL", raising=False)
        _write_spool_file(tmp_path, "a.json")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["drain", "--spool-dir", str(tmp_path), "--dry-run"]
        )
        assert result.exit_code == 2
        assert "ONEX_API_BASE_URL" in result.output

    def test_json_output_is_valid_json(self, tmp_path: Path) -> None:
        _write_spool_file(tmp_path, "a.json")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "drain",
                "--spool-dir",
                str(tmp_path),
                "--base-url",
                "https://gw.example",
                "--dry-run",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["dry_run"] is True
        assert parsed["unique_events"] == 1
