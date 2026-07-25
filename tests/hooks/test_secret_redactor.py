# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for secret redactor.

Tests verify:
- Secret pattern detection (API keys, tokens, passwords)
- Redaction of secrets in text
- Count tracking for redacted secrets
- Edge cases (no secrets, multiple secrets)

Part of OMN-1889: Emit injection metrics + utilization signal.
"""

from __future__ import annotations

import pytest

from plugins.onex.hooks.lib.secret_redactor import (
    SECRET_PATTERNS,
    RedactionResult,
    contains_secrets,
    redact_secrets,
    redact_secrets_with_count,
)

pytestmark = pytest.mark.unit


class TestRedactSecrets:
    """Test secret redaction function."""

    def test_redacts_openai_key(self) -> None:
        """Test redaction of OpenAI API keys."""
        text = "My key is sk-1234567890abcdefghij1234567890"
        result = redact_secrets(text)
        assert "sk-1234567890" not in result
        assert "REDACTED" in result

    def test_redacts_aws_key(self) -> None:
        """Test redaction of AWS access keys."""
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "REDACTED" in result

    def test_redacts_github_pat(self) -> None:
        """Test redaction of GitHub personal access tokens (36 alphanumeric chars)."""
        # ghp_ + 36 alphanumeric characters
        text = "Token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = redact_secrets(text)
        assert "ghp_xxxxxxx" not in result
        assert "REDACTED" in result

    def test_redacts_bearer_token(self) -> None:
        """Test redaction of Bearer tokens."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "REDACTED" in result

    def test_redacts_password_in_url(self) -> None:
        """Test redaction of passwords in URLs."""
        text = "postgres://user:secretpassword@host:5432/db"
        result = redact_secrets(text)
        assert "secretpassword" not in result
        assert "REDACTED" in result

    def test_redacts_generic_password(self) -> None:
        """Test redaction of generic password patterns."""
        text = "password=mysecretpassword123"
        result = redact_secrets(text)
        assert "mysecretpassword123" not in result
        assert "REDACTED" in result

    def test_preserves_non_secret_text(self) -> None:
        """Test that non-secret text is preserved."""
        text = "This is a normal message without secrets"
        result = redact_secrets(text)
        assert result == text

    def test_redacts_multiple_secrets(self) -> None:
        """Test redaction of multiple secrets in same text."""
        # OpenAI key (20+ chars) and password pattern
        text = "Keys: sk-abc123def456789012345 and password=secretpassword123"
        result = redact_secrets(text)
        assert "sk-abc123" not in result
        assert "secretpassword123" not in result
        assert result.count("REDACTED") >= 2

    def test_empty_input(self) -> None:
        """Test redaction of empty string."""
        result = redact_secrets("")
        assert result == ""

    def test_jwt_token_redaction(self) -> None:
        """Test redaction of JWT tokens."""
        text = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123"
        result = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "REDACTED" in result

    def test_redacts_prose_form_postgres_password(self) -> None:
        """OMN-15062: 'the Postgres password is <token>' (no '=' or ':') is redacted.

        This is the exact shape that leaked on 2026-07-24 — a credential
        severity probe narrated the value in prose rather than key=value
        form, which the pre-existing strict key=value pattern did not
        catch (it requires '=' or ':' immediately after the label).
        """
        text = "The Postgres password is xK9mP2vL8nQ4wR2ne and appears in 3 files."
        result = redact_secrets(text)
        assert "xK9mP2vL8nQ4wR2ne" not in result
        assert "REDACTED" in result

    def test_redacts_prose_form_backtick_credential(self) -> None:
        """OMN-15062: credential mentioned with intervening words + backticks."""
        text = "the leaked credential value is `s3cr3tTok3nHere123`, rotate it"
        result = redact_secrets(text)
        assert "s3cr3tTok3nHere123" not in result
        assert "REDACTED" in result

    def test_bare_unlabeled_high_entropy_string_not_caught(self) -> None:
        """OMN-15062 documented limit: a bare high-entropy string with no
        provider prefix and no label word (password/secret/token/credential/
        api_key) nearby is indistinguishable from a hash, UUID, or
        correlation ID by pattern matching, and is intentionally NOT
        redacted. This test pins the limit so it is not silently "fixed"
        into a blanket entropy heuristic that would mass-false-positive on
        this codebase's own SHAs/UUIDs/correlation IDs.
        """
        text = "The value is xK9mP2vL8nQ4wR2ne2f8Ta1"
        # No label word ("password"/"secret"/"token"/"credential"/"api_key")
        # anywhere near the value -> not matched. This is the hard case the
        # module docstring calls out explicitly.
        assert not contains_secrets(text)


class TestRedactSecretsWithCount:
    """Test secret redaction with count tracking."""

    def test_returns_redaction_result(self) -> None:
        """Test returns RedactionResult namedtuple."""
        result = redact_secrets_with_count("some text")
        assert isinstance(result, RedactionResult)
        assert hasattr(result, "text")
        assert hasattr(result, "redacted_count")

    def test_counts_single_secret(self) -> None:
        """Test count of single secret."""
        result = redact_secrets_with_count("Key: sk-1234567890abcdefghij12345")
        assert result.redacted_count >= 1
        assert "REDACTED" in result.text

    def test_counts_multiple_secrets(self) -> None:
        """Test count of multiple secrets."""
        # OpenAI key (20+ chars) and password pattern
        text = "Keys: sk-abc123def456789012345 password=secretpassword123"
        result = redact_secrets_with_count(text)
        assert result.redacted_count >= 2

    def test_zero_count_for_no_secrets(self) -> None:
        """Test zero count when no secrets present."""
        result = redact_secrets_with_count("No secrets here")
        assert result.redacted_count == 0
        assert result.text == "No secrets here"


class TestContainsSecrets:
    """Test secret detection function."""

    def test_detects_openai_key(self) -> None:
        """Test detection of OpenAI API keys."""
        assert contains_secrets("sk-1234567890abcdefghij12345")

    def test_detects_github_token(self) -> None:
        """Test detection of GitHub tokens (36 alphanumeric chars after ghp_)."""
        # ghp_ + 36 alphanumeric characters
        assert contains_secrets("ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

    def test_no_secrets_returns_false(self) -> None:
        """Test false for text without secrets."""
        assert not contains_secrets("This is a normal message")

    def test_empty_returns_false(self) -> None:
        """Test false for empty string."""
        assert not contains_secrets("")

    def test_partial_match_returns_false(self) -> None:
        """Test false for patterns that don't fully match."""
        # sk- without enough characters
        assert not contains_secrets("sk-short")


class TestSecretPatterns:
    """Test SECRET_PATTERNS constant."""

    def test_patterns_list_not_empty(self) -> None:
        """Test SECRET_PATTERNS is not empty."""
        assert len(SECRET_PATTERNS) > 0

    def test_patterns_are_tuples(self) -> None:
        """Test each pattern is a tuple of (pattern, replacement)."""
        for item in SECRET_PATTERNS:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_patterns_have_compiled_regex(self) -> None:
        """Test patterns are compiled regex objects."""

        for pattern, _ in SECRET_PATTERNS:
            assert hasattr(pattern, "search")  # Compiled regex has search method
            assert hasattr(pattern, "sub")  # Compiled regex has sub method


class TestRedactionResult:
    """Test RedactionResult namedtuple."""

    def test_is_namedtuple(self) -> None:
        """Test RedactionResult is a NamedTuple."""
        result = RedactionResult(text="test", redacted_count=0)
        assert result.text == "test"
        assert result.redacted_count == 0

    def test_is_immutable(self) -> None:
        """Test RedactionResult is immutable."""
        result = RedactionResult(text="test", redacted_count=0)
        with pytest.raises(AttributeError):
            result.text = "changed"  # type: ignore[misc]
