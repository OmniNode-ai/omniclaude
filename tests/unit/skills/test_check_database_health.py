# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for check_database_health execute [OMN-10492].

Verifies that the database health probe uses the runtime HTTP endpoint
instead of a raw Postgres/psql connection.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_SKILL_EXECUTE = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "system_status"
    / "check_database_health"
    / "_lib"
    / "execute.py"
)


def _load_execute() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_db_health_execute", _SKILL_EXECUTE
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.mark.unit
class TestCheckDatabaseHealthExecute:
    def test_execute_module_exists(self) -> None:
        assert _SKILL_EXECUTE.exists(), f"execute.py not found at {_SKILL_EXECUTE}"

    def test_no_psql_subprocess_calls(self) -> None:
        source = _SKILL_EXECUTE.read_text()
        assert "subprocess" not in source, (
            "execute.py must not use subprocess (no raw psql)"
        )
        assert "psql" not in source, "execute.py must not invoke psql directly"
        assert "psycopg" not in source, (
            "execute.py must not use psycopg2 (direct DB conn from Mac)"
        )

    def test_uses_http_probe(self) -> None:
        source = _SKILL_EXECUTE.read_text()
        assert "requests" in source, "execute.py must use requests for HTTP probe"
        assert "8085" in source or "OMNINODE_RUNTIME_HEALTH_URL" in source, (
            "execute.py must reference the runtime health endpoint"
        )

    def test_healthy_probe_returns_zero_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mod = _load_execute()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}

        with patch.object(mod.requests, "get", return_value=mock_response):
            exit_code = mod.main()

        assert exit_code == 0
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["status"] == "healthy"
        assert report["probe_method"] == "runtime_health_endpoint"

    def test_unhealthy_probe_returns_nonzero_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mod = _load_execute()
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.json.side_effect = Exception("not json")
        mock_response.text = "Service Unavailable"

        with patch.object(mod.requests, "get", return_value=mock_response):
            exit_code = mod.main()

        assert exit_code != 0
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["status"] != "healthy"

    def test_connection_error_returns_nonzero_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import requests as req_lib

        mod = _load_execute()
        with patch.object(
            mod.requests,
            "get",
            side_effect=req_lib.exceptions.ConnectionError("refused"),
        ):
            exit_code = mod.main()

        assert exit_code != 0
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["database"]["status"] == "unreachable"

    def test_timeout_returns_nonzero_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import requests as req_lib

        mod = _load_execute()
        with patch.object(
            mod.requests, "get", side_effect=req_lib.exceptions.Timeout("timed out")
        ):
            exit_code = mod.main()

        assert exit_code != 0
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["database"]["status"] == "timeout"

    def test_env_var_overrides_url(self) -> None:
        import os

        with patch.dict(
            os.environ, {"OMNINODE_RUNTIME_HEALTH_URL": "http://test-host:9999/health"}
        ):
            mod = _load_execute()
            assert mod._RUNTIME_HEALTH_URL == "http://test-host:9999/health"
