# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for omniclaude.lib.utils.sanitize.

Covers:
- sanitize_log_input: log injection prevention (OMN-5413)
- _redact_dsn: cleartext password redaction in DSNs (OMN-5414)
- redact_config_dict: safe config dict logging (OMN-5414)

Note: Imports are done lazily via pytest fixtures to avoid triggering
``omniclaude.lib.utils.__init__``, which pulls in ``debug_utils`` → a pre-existing
circular-import issue (``settings.intelligence_service_url``) unrelated to this PR.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _sanitize():  # type: ignore[return]
    """Lazy import of the sanitize submodule (avoids triggering utils.__init__)."""
    from omniclaude.lib.utils import sanitize as _mod  # noqa: PLC0415

    return _mod


# ---------------------------------------------------------------------------
# sanitize_log_input
# ---------------------------------------------------------------------------


class TestSanitizeLogInput:
    @pytest.mark.unit
    def test_normal_string_unchanged(self, _sanitize: object) -> None:
        assert hasattr(_sanitize, "sanitize_log_input")
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        value = "OmniNode-ai/omniclaude"
        assert fn(value) == value

    @pytest.mark.unit
    def test_strips_newline(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        value = "repo/name\nINFO fake-log-entry"
        result = fn(value)
        assert "\n" not in result
        assert "fake-log-entry" in result

    @pytest.mark.unit
    def test_strips_carriage_return(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        assert "\r" not in fn("foo\rbar")

    @pytest.mark.unit
    def test_strips_null_byte(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        assert "\x00" not in fn("foo\x00bar")

    @pytest.mark.unit
    def test_strips_all_common_control_chars(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        control_chars = (
            "".join(chr(i) for i in range(0x20) if chr(i) not in ("\t", " ")) + "\x7f"
        )
        result = fn(f"before{control_chars}after")
        assert "before" in result
        assert "after" in result
        for ch in control_chars:
            assert ch not in result

    @pytest.mark.unit
    def test_preserves_tab_and_space(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        value = "word1\tword2 word3"
        assert fn(value) == value

    @pytest.mark.unit
    def test_returns_string(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        assert isinstance(fn("anything"), str)

    @pytest.mark.unit
    def test_empty_string(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        assert fn("") == ""

    @pytest.mark.unit
    def test_log_injection_attack_vector(self, _sanitize: object) -> None:
        """Simulate a log-injection attack embedding a forged log line."""
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        malicious = "abc\nERROR: security breach detected\nuser=admin"
        result = fn(malicious)
        assert "\n" not in result
        assert "abc" in result

    @pytest.mark.unit
    def test_sha_value_safe(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        assert fn(sha) == sha

    @pytest.mark.unit
    def test_conclusion_value_safe(self, _sanitize: object) -> None:
        fn = _sanitize.sanitize_log_input  # type: ignore[attr-defined]
        assert fn("success") == "success"
        assert fn("failure") == "failure"


# ---------------------------------------------------------------------------
# _redact_dsn
# ---------------------------------------------------------------------------


class TestRedactDsn:
    @pytest.mark.unit
    def test_redacts_url_form_password(self, _sanitize: object) -> None:
        fn = _sanitize._redact_dsn  # type: ignore[attr-defined]
        dsn = "postgresql://user:s3cr3t@localhost:5432/mydb"
        result = fn(dsn)
        assert "s3cr3t" not in result
        assert "***" in result
        assert "localhost:5432/mydb" in result

    @pytest.mark.unit
    def test_redacts_keyword_form_password(self, _sanitize: object) -> None:
        fn = _sanitize._redact_dsn  # type: ignore[attr-defined]
        dsn = "host=localhost password=s3cr3t dbname=mydb"
        result = fn(dsn)
        assert "s3cr3t" not in result
        assert "***" in result
        assert "host=localhost" in result

    @pytest.mark.unit
    def test_no_password_unchanged(self, _sanitize: object) -> None:
        fn = _sanitize._redact_dsn  # type: ignore[attr-defined]
        dsn = "host=localhost port=5432 dbname=mydb"
        assert fn(dsn) == dsn

    @pytest.mark.unit
    def test_redacts_asyncpg_dsn(self, _sanitize: object) -> None:
        fn = _sanitize._redact_dsn  # type: ignore[attr-defined]
        dsn = "postgresql+asyncpg://admin:MyP@ssw0rd@db.host/omnibase"
        result = fn(dsn)
        assert "MyP@ssw0rd" not in result
        assert "admin" in result

    @pytest.mark.unit
    def test_empty_string(self, _sanitize: object) -> None:
        fn = _sanitize._redact_dsn  # type: ignore[attr-defined]
        assert fn("") == ""


# ---------------------------------------------------------------------------
# redact_config_dict
# ---------------------------------------------------------------------------


class TestRedactConfigDict:
    @pytest.mark.unit
    def test_redacts_password_key(self, _sanitize: object) -> None:
        fn = _sanitize.redact_config_dict  # type: ignore[attr-defined]
        config = {"host": "localhost", "password": "s3cr3t", "port": 5432}
        result = fn(config)
        assert result["password"] == "***"
        assert result["host"] == "localhost"
        assert result["port"] == 5432

    @pytest.mark.unit
    def test_redacts_secret_key(self, _sanitize: object) -> None:
        fn = _sanitize.redact_config_dict  # type: ignore[attr-defined]
        config = {"api_secret": "abc123", "endpoint": "http://example.com"}
        result = fn(config)
        assert result["api_secret"] == "***"
        assert result["endpoint"] == "http://example.com"

    @pytest.mark.unit
    def test_redacts_token_key(self, _sanitize: object) -> None:
        fn = _sanitize.redact_config_dict  # type: ignore[attr-defined]
        config = {"auth_token": "tok123", "name": "test"}
        result = fn(config)
        assert result["auth_token"] == "***"

    @pytest.mark.unit
    def test_redacts_key_key(self, _sanitize: object) -> None:
        fn = _sanitize.redact_config_dict  # type: ignore[attr-defined]
        config = {"api_key": "key123", "region": "us-east-1"}
        result = fn(config)
        assert result["api_key"] == "***"

    @pytest.mark.unit
    def test_case_insensitive(self, _sanitize: object) -> None:
        fn = _sanitize.redact_config_dict  # type: ignore[attr-defined]
        config = {"PASSWORD": "secret", "ApiKey": "key123"}
        result = fn(config)
        assert result["PASSWORD"] == "***"
        assert result["ApiKey"] == "***"

    @pytest.mark.unit
    def test_empty_dict(self, _sanitize: object) -> None:
        fn = _sanitize.redact_config_dict  # type: ignore[attr-defined]
        assert fn({}) == {}

    @pytest.mark.unit
    def test_does_not_mutate_original(self, _sanitize: object) -> None:
        fn = _sanitize.redact_config_dict  # type: ignore[attr-defined]
        config = {"password": "s3cr3t"}
        original = dict(config)
        fn(config)
        assert config == original
