# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Data sensitivity gate for delegation routing.

Checks tool inputs for secrets, credentials, and PII before any cloud routing.
Default policy: sensitive inputs route local-only, never to cloud.
Cloud routing requires explicit opt-in per task class in the contract.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EnumSensitivityPolicy(StrEnum):
    """Routing policy produced by the sensitivity gate."""

    LOCAL_ONLY = "local_only"
    CLOUD_ALLOWED = "cloud_allowed"
    BLOCKED = "blocked"


class ModelSensitivityResult(BaseModel):
    """Result of a sensitivity gate check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_sensitive: bool
    reasons: list[str]
    policy: EnumSensitivityPolicy


# ---------------------------------------------------------------------------
# Compiled patterns — module-level to avoid re-compilation on every call
# ---------------------------------------------------------------------------

# API keys / tokens
_RE_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)  # noqa: secrets
_RE_SK_PREFIX = re.compile(r"\bsk-[A-Za-z0-9]{20,}", re.IGNORECASE)
_RE_PK_PREFIX = re.compile(r"\bpk_[A-Za-z0-9]{20,}", re.IGNORECASE)
_RE_AKIA = re.compile(r"\bAKIA[A-Z0-9]{16}\b")
_RE_GH_TOKEN = re.compile(r"\bghp_[A-Za-z0-9]{36}\b")  # noqa: secrets
_RE_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}", re.IGNORECASE)  # noqa: secrets
_RE_GENERIC_TOKEN = re.compile(  # noqa: secrets
    r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9\-._~+/]{16,}",
    re.IGNORECASE,
)

# Private keys
_RE_PRIVATE_KEY = re.compile(  # noqa: secrets
    r"-----BEGIN\s+(?:[A-Z\s]+\s+)?PRIVATE KEY-----", re.IGNORECASE
)

# Credentials in key=value patterns
_RE_PASSWORD_KV = re.compile(  # noqa: secrets
    r"\b(?:password|passwd|secret|token)\s*[=:]\s*[^\s,;\"']{4,}", re.IGNORECASE
)

# Environment variable dumps containing sensitive keys
_RE_ENV_SENSITIVE = re.compile(
    r"\b(?:AWS_SECRET_ACCESS_KEY|AWS_SECRET_KEY|AWS_SESSION_TOKEN|"
    r"DATABASE_URL|DB_PASSWORD|"
    r"POSTGRES_PASSWORD|MYSQL_PASSWORD|REDIS_PASSWORD|"
    r"SECRET_KEY|PRIVATE_KEY|API_KEY|AUTH_TOKEN)\s*[=:]",
    re.IGNORECASE,
)

# PII patterns
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,255}\.[A-Za-z]{2,}\b"
)
_RE_PHONE_US = re.compile(r"\b(?:\+1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b")
_RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

_CHECKS: list[tuple[re.Pattern[str], str]] = [
    (_RE_BEARER, "Bearer token detected"),
    (_RE_SK_PREFIX, "Secret key (sk-) detected"),
    (_RE_PK_PREFIX, "Public/private key (pk_) detected"),
    (_RE_AKIA, "AWS access key (AKIA) detected"),
    (_RE_GH_TOKEN, "GitHub personal access token detected"),
    (_RE_SLACK_TOKEN, "Slack API token detected"),
    (_RE_GENERIC_TOKEN, "Generic API key or token in key=value form"),
    (_RE_PRIVATE_KEY, "PEM private key block detected"),
    (_RE_PASSWORD_KV, "Password or secret in key=value form"),
    (_RE_ENV_SENSITIVE, "Sensitive environment variable assignment"),
    (_RE_EMAIL, "Email address (PII) detected"),
    (_RE_PHONE_US, "Phone number (PII) detected"),
    (_RE_SSN, "Social Security Number (PII) detected"),
]


class SensitivityGate:
    """Check tool inputs for sensitive data before delegation routing."""

    def check(self, tool_input: str) -> ModelSensitivityResult:
        """Scan tool_input for secrets, credentials, and PII.

        Returns a ModelSensitivityResult. If any pattern matches, is_sensitive
        is True and policy is LOCAL_ONLY. Otherwise policy is CLOUD_ALLOWED.
        """
        reasons: list[str] = []

        for pattern, label in _CHECKS:
            if pattern.search(tool_input):
                reasons.append(label)

        if reasons:
            return ModelSensitivityResult(
                is_sensitive=True,
                reasons=reasons,
                policy=EnumSensitivityPolicy.LOCAL_ONLY,
            )

        return ModelSensitivityResult(
            is_sensitive=False,
            reasons=[],
            policy=EnumSensitivityPolicy.CLOUD_ALLOWED,
        )
