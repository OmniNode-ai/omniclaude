# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for SensitivityGate."""

from __future__ import annotations

import pytest

from omniclaude.delegation.sensitivity_gate import (
    EnumSensitivityPolicy,
    SensitivityGate,
)


@pytest.fixture
def gate() -> SensitivityGate:
    return SensitivityGate()


@pytest.mark.unit
class TestSensitivityGateClean:
    def test_clean_code_snippet(self, gate: SensitivityGate) -> None:
        result = gate.check("def add(a: int, b: int) -> int:\n    return a + b\n")
        assert not result.is_sensitive
        assert result.reasons == []
        assert result.policy == EnumSensitivityPolicy.CLOUD_ALLOWED

    def test_normal_documentation(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "This module implements the delegation routing logic for ONEX nodes."
        )
        assert not result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.CLOUD_ALLOWED

    def test_plain_yaml_config(self, gate: SensitivityGate) -> None:
        result = gate.check("name: my-service\nport: 8080\nlog_level: info\n")
        assert not result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.CLOUD_ALLOWED


@pytest.mark.unit
class TestSensitivityGateApiKeys:
    def test_bearer_token(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        )
        assert result.is_sensitive
        assert any("Bearer" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_sk_prefix_key(self, gate: SensitivityGate) -> None:
        result = gate.check("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456")
        assert result.is_sensitive
        assert any("sk-" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_aws_akia_key(self, gate: SensitivityGate) -> None:
        result = gate.check("aws_access_key_id = AKIAIOSFODNN7EXAMPLE")
        assert result.is_sensitive
        assert any("AWS" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_github_pat(self, gate: SensitivityGate) -> None:
        result = gate.check("GITHUB_TOKEN=ghp_" + "A" * 36)
        assert result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_slack_token(self, gate: SensitivityGate) -> None:
        # Prefix assembled at runtime to avoid GitHub push-protection false positive
        prefix = "xox" + "b"
        result = gate.check(f"token = {prefix}-1234567890-abcdefghijklmnop")
        assert result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY


@pytest.mark.unit
class TestSensitivityGatePrivateKey:
    def test_rsa_private_key_block(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        )
        assert result.is_sensitive
        assert any("PEM private key" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_ec_private_key_block(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "-----BEGIN EC PRIVATE KEY-----\nMHQCAQEEIOmXpd...\n-----END EC PRIVATE KEY-----"
        )
        assert result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_generic_private_key_block(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w...\n-----END PRIVATE KEY-----"
        )
        assert result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY


@pytest.mark.unit
class TestSensitivityGateCredentials:
    def test_password_equals(self, gate: SensitivityGate) -> None:
        result = gate.check("password=supersecretvalue123")
        assert result.is_sensitive
        assert any("Password or secret" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_secret_colon(self, gate: SensitivityGate) -> None:
        result = gate.check("secret: my-very-secret-value")
        assert result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_env_dump_postgres_password(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "POSTGRES_PASSWORD=hunter2\nDATABASE_URL=postgres://user:pass@host/db\n"
        )
        assert result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_env_dump_aws_secret(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        )
        assert result.is_sensitive
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY


@pytest.mark.unit
class TestSensitivityGatePII:
    def test_email_address(self, gate: SensitivityGate) -> None:
        result = gate.check("Contact us at jonah@example.com for support.")
        assert result.is_sensitive
        assert any("Email" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_us_phone_number(self, gate: SensitivityGate) -> None:
        result = gate.check("Call me at 555-867-5309 anytime.")
        assert result.is_sensitive
        assert any("Phone" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_ssn(self, gate: SensitivityGate) -> None:
        result = gate.check("SSN: 123-45-6789")
        assert result.is_sensitive
        assert any("Social Security" in r for r in result.reasons)
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY


@pytest.mark.unit
class TestSensitivityGateMultipleFindings:
    def test_multiple_reasons_reported(self, gate: SensitivityGate) -> None:
        result = gate.check(
            "password=abc123\nAuthorization: Bearer some-token-value-here-1234567890"
        )
        assert result.is_sensitive
        assert len(result.reasons) >= 2
        assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY

    def test_result_is_frozen(self, gate: SensitivityGate) -> None:
        from pydantic import ValidationError

        result = gate.check("clean code snippet here")
        with pytest.raises(ValidationError):
            result.is_sensitive = True  # type: ignore[misc]
