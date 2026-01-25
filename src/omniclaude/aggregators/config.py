"""Configuration for session aggregation.

Defines timeouts and thresholds per the aggregation contract.
Loads from environment variables with OMNICLAUDE_AGGREGATOR_ prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigSessionAggregator(BaseSettings):
    """Configuration for session event aggregation.

    Environment variables use the OMNICLAUDE_AGGREGATOR_ prefix.
    Example: OMNICLAUDE_AGGREGATOR_SESSION_INACTIVITY_TIMEOUT_SECONDS=3600
    """

    model_config = SettingsConfigDict(
        env_prefix="OMNICLAUDE_AGGREGATOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Session timeouts (from aggregation contract)
    session_inactivity_timeout_seconds: int = Field(
        default=3600,  # 1 hour
        ge=60,
        le=86400,
        description="Timeout for session inactivity before auto-finalization",
    )
    session_max_duration_seconds: int = Field(
        default=2592000,  # 30 days
        ge=3600,
        le=7776000,  # 90 days max - gives headroom for customization
        description="Maximum session duration",
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
        description="Tolerance for future timestamps due to clock skew",
    )
    seal_delay_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Delay after finalization before sealing",
    )

    # Capacity
    tool_count_streaming_threshold: int = Field(
        default=1000,
        ge=100,
        le=100000,
        description="Tool count threshold for streaming mode",
    )
    max_orphan_sessions: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Maximum orphan sessions to prevent memory exhaustion",
    )

    # Idempotency
    duplicate_detection_window_seconds: int = Field(
        default=86400,  # 24 hours
        ge=3600,
        le=604800,
        description="How long to remember seen event IDs",
    )

    # Sweep interval
    timeout_sweep_interval_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Interval for running timeout sweep",
    )
