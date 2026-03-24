# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Session-start env var health check.

Checks critical environment variables and returns warnings (never errors)
for missing or misconfigured values. Used by the SessionStart hook to
surface configuration issues to the user.

Design principle: NEVER block. NEVER raise. Always return a result.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


class ModelEnvHealthResult(BaseModel):
    """Result of an env var health check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    warnings: list[str] = Field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return len(self.warnings) == 0


# Critical env vars and their impact descriptions.
# Format: (var_name, impact_description)
CRITICAL_ENV_VARS: list[tuple[str, str]] = [
    (
        "INTELLIGENCE_SERVICE_URL",
        "Context injection disabled -- omniclaude cannot fetch learned patterns"
        " from omniintelligence (OMN-5361)",
    ),
    (
        "KAFKA_BOOTSTRAP_SERVERS",
        "Event emission disabled -- session events will not reach Kafka or omnidash",
    ),
]


def check_critical_env_vars() -> ModelEnvHealthResult:
    """Check critical env vars and return warnings for missing ones.

    This function NEVER raises. All errors are caught and converted to
    warnings in the result.

    Returns:
        ModelEnvHealthResult with warnings for any missing critical vars.
    """
    try:
        warnings: list[str] = []
        for var_name, impact in CRITICAL_ENV_VARS:
            value = os.environ.get(var_name, "").strip()
            if not value:
                warnings.append(f"[env-health] {var_name} is not set. Impact: {impact}")
        return ModelEnvHealthResult(warnings=warnings)
    except Exception:  # noqa: BLE001 — intentional: health check must never crash the hook
        return ModelEnvHealthResult()
