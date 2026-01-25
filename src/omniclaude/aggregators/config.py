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

    Currently Implemented Fields:
        - session_inactivity_timeout_seconds: Used by timeout sweep to finalize inactive sessions
        - orphan_buffer_duration_seconds: Used for orphan event buffering before synthetic start
        - out_of_order_buffer_seconds: Used for accepting late-arriving events
        - max_orphan_sessions: Used to cap memory usage from orphan sessions
        - timeout_sweep_interval_seconds: Used to configure sweep frequency

    Reserved for Future Implementation:
        - session_max_duration_seconds: Max duration enforcement not yet implemented
        - clock_skew_tolerance_seconds: Future timestamp handling not yet implemented
        - seal_delay_seconds: Session sealing logic not yet implemented
        - tool_count_streaming_threshold: Streaming mode not yet implemented
        - duplicate_detection_window_seconds: Time-windowed dedup not yet implemented
          (current dedup uses natural key only)
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
