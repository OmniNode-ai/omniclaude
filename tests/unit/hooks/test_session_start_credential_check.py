# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for session-start.sh credential freshness check (OMN-8798).

Verifies the Mode-A/Mode-B credential UX specified in SD-11:

* Mode A (no kafka in ~/.onex/config.yaml, or no config file at all) must
  emit NO credential warning.
* Mode B with a missing/empty KAFKA_SASL_PASSWORD must emit the exact
  structured warning "ONEX WARNING: credentials expired, run: onex refresh-credentials".
* Mode B with an expired infisical_token_expires_at must emit the same warning.
* Mode B with a populated password and a future expiry must NOT warn.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "session-start.sh"
)

_EXPECTED_WARNING = "ONEX WARNING: credentials expired, run: onex refresh-credentials"


def _run_credential_check(
    *, config_path: Path | None, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    assert _SCRIPT.exists(), f"session-start.sh missing at {_SCRIPT}"
    env = os.environ.copy()
    env.pop("ONEX_EVENT_BUS_TYPE", None)
    if config_path is None:
        env["ONEX_USER_CONFIG"] = "/nonexistent/path/that/should/not/exist.yaml"
    else:
        env["ONEX_USER_CONFIG"] = str(config_path)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(_SCRIPT), "--credential-check-only"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestCredentialCheckModeA:
    """Mode A: no kafka configured → no warning, exit 0."""

    def test_no_config_file_is_silent(self) -> None:
        result = _run_credential_check(config_path=None)
        assert result.returncode == 0, (
            f"expected exit 0 with no config file, stderr={result.stderr!r}"
        )
        assert "ONEX WARNING" not in result.stderr, (
            f"Mode A (no config file) must not warn; stderr={result.stderr!r}"
        )

    def test_config_without_kafka_is_silent(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "mode: local\nlinear_api_key: xxx\ngithub_token: yyy\n",
            encoding="utf-8",
        )
        result = _run_credential_check(config_path=cfg)
        assert result.returncode == 0
        assert "ONEX WARNING" not in result.stderr, (
            f"Mode A (no kafka section) must not warn; stderr={result.stderr!r}"
        )

    def test_commented_kafka_section_is_silent(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "# kafka: disabled via comment\nlinear_api_key: xxx\n",
            encoding="utf-8",
        )
        result = _run_credential_check(config_path=cfg)
        assert result.returncode == 0
        assert "ONEX WARNING" not in result.stderr


class TestCredentialCheckModeB:
    """Mode B: kafka configured → check credentials, warn on absence/expiry."""

    def test_missing_kafka_password_warns(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "kafka:\n"
            "  bootstrap_servers: broker.example.com:9092\n"
            "  sasl_username: svc-account\n"
            "  # sasl_password is absent → should warn\n",
            encoding="utf-8",
        )
        result = _run_credential_check(config_path=cfg)
        assert result.returncode == 0
        assert _EXPECTED_WARNING in result.stderr, (
            f"missing sasl_password must emit exact warning; "
            f"got stderr={result.stderr!r}"
        )

    def test_expired_infisical_token_warns(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "kafka:\n"
            "  sasl_password: hunter2\n"
            "infisical_token_expires_at: 2020-01-01T00:00:00Z\n",
            encoding="utf-8",
        )
        result = _run_credential_check(config_path=cfg)
        assert result.returncode == 0
        assert _EXPECTED_WARNING in result.stderr, (
            f"expired infisical token must emit warning; got stderr={result.stderr!r}"
        )

    def test_valid_credentials_are_silent(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "kafka:\n"
            "  sasl_password: hunter2\n"
            "infisical_token_expires_at: 2099-01-01T00:00:00Z\n",
            encoding="utf-8",
        )
        result = _run_credential_check(config_path=cfg)
        assert result.returncode == 0
        assert "ONEX WARNING" not in result.stderr, (
            f"valid credentials must not warn; stderr={result.stderr!r}"
        )


class TestScriptStructure:
    """Content checks: guarantee key invariants even if subprocess tests drift."""

    def test_script_defines_credential_check_function(self) -> None:
        content = _SCRIPT.read_text(encoding="utf-8")
        assert "_onex_credential_check" in content, (
            "session-start.sh must define _onex_credential_check function for OMN-8798"
        )

    def test_exact_warning_literal_present(self) -> None:
        content = _SCRIPT.read_text(encoding="utf-8")
        assert _EXPECTED_WARNING in content, (
            "session-start.sh must contain the exact SD-11 warning literal"
        )

    def test_credential_check_invoked_in_main_path(self) -> None:
        content = _SCRIPT.read_text(encoding="utf-8")
        # At least two occurrences: one for --credential-check-only branch
        # and one for the end-of-script invocation. The function definition
        # adds a third. Total should be ≥ 3.
        assert content.count("_onex_credential_check") >= 3, (
            "_onex_credential_check must be defined and invoked in both the "
            "short-circuit and the main-path end-of-script sections"
        )

    def test_mode_a_skip_logic_is_documented(self) -> None:
        content = _SCRIPT.read_text(encoding="utf-8")
        assert "Mode A" in content and "Mode B" in content, (
            "credential check block must document Mode A vs Mode B behavior"
        )
