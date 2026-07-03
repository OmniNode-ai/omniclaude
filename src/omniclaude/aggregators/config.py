# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Configuration for session aggregation.

Defines timeouts and thresholds per the aggregation contract.

OMN-13560 Wave-2 config->overlay migration (epic OMN-13556). The tunables were
previously bound via pydantic-settings ``env_file``/``.env`` with the
``OMNICLAUDE_AGGREGATOR_`` prefix. They are now declared in
``contracts/contract_omniclaude_runtime.yaml`` under the ``aggregator:`` section
with the ``${env.VAR:default}`` overlay convention. :meth:`from_contract`
resolves each value via :func:`_expand_contract_env_refs` — the single
sanctioned ``os.environ`` boundary in this module, mirroring the canonical
``omnibase_infra.runtime.overlay.contract_env_ref.expand_contract_env_refs``
semantics (a local copy is kept consistent with the Wave-1 diagnostics
descriptor because the pinned ``omnibase_infra`` release does not yet vendor the
helper) — and applies the field-level pydantic bounds. The class itself is a
plain ``BaseModel`` so direct construction with defaults / explicit kwargs keeps
working; the overlay seam is reached through :meth:`from_contract`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ``${env.VAR}`` / ``${env.VAR:default}`` — the same env-overlay convention the
# canonical overlay resolver (``contract_env_ref.expand_contract_env_refs``)
# uses, matching the Wave-1 diagnostics descriptor seam.
_ENV_REF = re.compile(
    r"\$\{env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}"
)

# The omniclaude runtime contract that declares the aggregator tunables.
# Resolved relative to this module so it is portable across machines / install
# layouts (no hardcoded absolute path).
_CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)


def _expand_contract_env_refs(value: str) -> str:
    """Expand ``${env.VAR}`` / ``${env.VAR:default}`` references in ``value``.

    The single sanctioned ``os.environ`` boundary in this module. An unset var
    with no inline default expands to the empty string so the caller fails
    closed at the pydantic validation boundary rather than passing a literal
    ``${env.…}`` placeholder downstream.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        return os.environ.get(name, default if default is not None else "")

    return _ENV_REF.sub(_sub, value)


def _load_aggregator_section(contract_path: Path = _CONTRACT) -> dict[str, object]:
    with contract_path.open(encoding="utf-8") as contract_file:
        raw = yaml.safe_load(contract_file)
    if not isinstance(raw, dict):
        raise ValueError(f"contract {contract_path} must contain a mapping")
    section = raw.get("aggregator")
    if not isinstance(section, dict):
        raise ValueError(
            f"contract {contract_path} must declare an 'aggregator' mapping with "
            "the session-aggregation tunable fields"
        )
    return section


class ConfigSessionAggregator(BaseModel):
    """Configuration for session event aggregation.

    Construct via :meth:`from_contract` for the canonical contract+overlay
    resolution path; direct construction uses the in-source defaults (or
    explicit field overrides). The per-lane overlay supplies values through the
    ``OMNICLAUDE_AGGREGATOR_`` ``${env.VAR}`` references declared in the runtime
    contract's ``aggregator:`` section.
    Example: OMNICLAUDE_AGGREGATOR_SESSION_INACTIVITY_TIMEOUT_SECONDS=3600

    Currently Implemented Fields:
        - session_inactivity_timeout_seconds: Used by timeout sweep to finalize inactive sessions
        - orphan_buffer_duration_seconds: Used for orphan event buffering before synthetic start
        - out_of_order_buffer_seconds: Used for accepting late-arriving events
        - max_orphan_sessions: Used to cap memory usage from orphan sessions
        - timeout_sweep_interval_seconds: Used to configure sweep frequency
        - finalized_session_warning_threshold: Warn when finalized session count exceeds this
        - finalized_session_warning_interval_seconds: Rate-limit for finalized-session warnings

    Reserved for Future Implementation:
        - session_max_duration_seconds: Max duration enforcement not yet implemented
        - clock_skew_tolerance_seconds: Future timestamp handling not yet implemented
        - seal_delay_seconds: Session sealing logic not yet implemented
        - tool_count_streaming_threshold: Streaming mode not yet implemented
        - duplicate_detection_window_seconds: Time-windowed dedup not yet implemented
          (current dedup uses natural key only)
    """

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_contract(cls, contract_path: Path = _CONTRACT) -> ConfigSessionAggregator:
        """Build the config from the runtime contract's ``aggregator:`` section.

        Each declared ``${env.VAR:default}`` value is overlay-resolved through
        :func:`_expand_contract_env_refs` (the single sanctioned env boundary),
        then handed to pydantic which coerces and validates against the
        field-level bounds. A value that resolves empty (unset env, no inline
        default) fails closed at the pydantic validation boundary rather than
        silently substituting a placeholder.
        """
        section = _load_aggregator_section(contract_path)
        resolved: dict[str, object] = {}
        for field_name in cls.model_fields:
            declared = section.get(field_name)
            if isinstance(declared, str):
                resolved[field_name] = _expand_contract_env_refs(declared).strip()
            elif declared is not None:
                resolved[field_name] = declared
        return cls.model_validate(resolved)

    # Session timeouts (from aggregation contract)
    session_inactivity_timeout_seconds: int = Field(
        default=3600,  # 1 hour - typical Claude Code sessions are interactive bursts
        ge=60,
        le=86400,  # 24h max - longer gaps indicate new logical session
        description="Timeout for session inactivity before auto-finalization",
    )
    session_max_duration_seconds: int = Field(
        default=2592000,  # 30 days
        ge=3600,
        le=7776000,  # 90 days max - beyond this, treat as abandoned or data corruption
        description="RESERVED FOR FUTURE USE: Maximum session duration enforcement",
    )
    orphan_buffer_duration_seconds: int = Field(
        default=300,  # 5 minutes
        ge=30,
        le=3600,
        description="Buffer time for orphan events before synthetic start",
    )

    # Out-of-order handling
    out_of_order_buffer_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Buffer window for accepting out-of-order events",
    )
    clock_skew_tolerance_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="RESERVED FOR FUTURE USE: Tolerance for future timestamps due to clock skew",
    )
    seal_delay_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="RESERVED FOR FUTURE USE: Delay after finalization before sealing",
    )

    # Capacity limits - balance memory usage vs operational flexibility
    tool_count_streaming_threshold: int = Field(
        default=1000,
        ge=100,
        le=100000,
        description="RESERVED FOR FUTURE USE: Tool count threshold for streaming mode",
    )
    max_orphan_sessions: int = Field(
        default=10000,  # ~40MB at 4KB/session - reasonable for most deployments
        ge=100,
        le=1000000,  # 1M cap prevents runaway memory in pathological cases
        description="Maximum orphan sessions to prevent memory exhaustion",
    )

    # Idempotency - retain event IDs long enough for retry storms to settle
    duplicate_detection_window_seconds: int = Field(
        default=86400,  # 24h covers overnight retries and timezone edge cases
        ge=3600,
        le=604800,  # 7 days max - longer retention has diminishing returns vs memory
        description="RESERVED FOR FUTURE USE: Time-windowed dedup (current dedup uses natural key only)",
    )

    # Sweep interval
    timeout_sweep_interval_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Interval for running timeout sweep",
    )

    # Memory growth warnings
    finalized_session_warning_threshold: int = Field(
        default=10000,
        ge=1,
        le=10000000,
        description=(
            "Warn when finalized session count exceeds this threshold. "
            "Indicates that cleanup_finalized_sessions() is not being called "
            "often enough. Set to 0 to disable warnings (not allowed; use a "
            "large value to effectively disable)."
        ),
    )
    finalized_session_warning_interval_seconds: int = Field(
        default=3600,  # 1 hour
        ge=60,
        le=86400,
        description=(
            "Minimum seconds between repeated finalized-session warnings "
            "to avoid log spam."
        ),
    )
