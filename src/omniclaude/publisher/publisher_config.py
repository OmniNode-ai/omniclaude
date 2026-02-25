# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Publisher Configuration Model.

Simplified from omnibase_infra.runtime.emit_daemon.config (OMN-1944).
Uses pydantic-settings for automatic environment variable loading.
No CLI support — publisher is started/stopped programmatically.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_socket_path() -> Path:
    return Path(tempfile.gettempdir()) / "omniclaude-emit.sock"


def _default_pid_path() -> Path:
    return Path(tempfile.gettempdir()) / "omniclaude-emit.pid"


class PublisherConfig(BaseSettings):
    """Configuration for the Embedded Event Publisher."""

    model_config = SettingsConfigDict(
        env_prefix="OMNICLAUDE_PUBLISHER_",
        frozen=True,
        extra="ignore",
        validate_default=True,
    )

    # Path configurations
    socket_path: Path = Field(
        default_factory=_default_socket_path,
        description="Unix domain socket path",
    )
    pid_path: Path = Field(
        default_factory=_default_pid_path,
        description="PID file path",
    )
    spool_dir: Path = Field(
        default_factory=lambda: Path.home() / ".claude" / "event-spool",
        description="Disk spool directory",
    )

    # Limit configurations
    max_payload_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    max_memory_queue: int = Field(default=100, ge=1, le=10_000)
    max_spool_messages: int = Field(default=1000, ge=0, le=100_000)
    max_spool_bytes: int = Field(default=10_485_760, ge=0, le=1_073_741_824)

    # Kafka configurations
    kafka_bootstrap_servers: str = Field(
        ...,
        min_length=1,
        description="Kafka broker addresses (host:port, comma-separated). IPv6 addresses must use bracket notation, e.g. [::1]:9092",
    )
    kafka_client_id: str = Field(
        default="omniclaude-publisher",
        min_length=1,
        max_length=255,
    )
    environment: str = Field(
        default="dev",
        pattern=r"^[a-z][a-z0-9-]*$",
    )

    # Socket permissions
    socket_permissions: int = Field(default=0o660, ge=0, le=0o777)

    # Timeouts
    socket_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    kafka_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    shutdown_drain_seconds: float = Field(default=10.0, ge=0.0, le=300.0)

    # Retry configurations
    max_retry_attempts: int = Field(default=3, ge=1, le=10)
    backoff_base_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    max_backoff_seconds: float = Field(default=60.0, ge=1.0, le=300.0)

    # Secondary Kafka cluster (cloud Redpanda / kafka.omninode.ai)
    # All secondary fields use KAFKA_SECONDARY_* prefix so they cannot collide
    # with primary KAFKA_* env vars processed by apply_environment_overrides().
    kafka_secondary_bootstrap_servers: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OMNICLAUDE_PUBLISHER_KAFKA_SECONDARY_BOOTSTRAP_SERVERS",
            "KAFKA_SECONDARY_BOOTSTRAP_SERVERS",
        ),
        description=(
            "Secondary Kafka bootstrap servers (host:port, comma-separated). "
            "When set, events are published to both primary and secondary clusters. "
            "Secondary failures are non-fatal and do not affect primary publish."
        ),
    )
    kafka_secondary_security_protocol: str = Field(
        default="PLAINTEXT",
        validation_alias=AliasChoices("KAFKA_SECONDARY_SECURITY_PROTOCOL"),
        pattern=r"^(PLAINTEXT|SSL|SASL_PLAINTEXT|SASL_SSL)$",
        description="Security protocol for the secondary Kafka cluster.",
    )
    kafka_secondary_sasl_mechanism: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KAFKA_SECONDARY_SASL_MECHANISM"),
        description="SASL mechanism for secondary cluster (e.g. OAUTHBEARER, PLAIN, SCRAM-SHA-256).",
    )
    kafka_secondary_sasl_oauthbearer_token_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "KAFKA_SECONDARY_SASL_OAUTHBEARER_TOKEN_ENDPOINT_URL"
        ),
        description="Token endpoint URL for OAUTHBEARER on secondary cluster.",
    )
    kafka_secondary_sasl_oauthbearer_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KAFKA_SECONDARY_SASL_OAUTHBEARER_CLIENT_ID"),
        description="OAuth2 client ID for secondary cluster OAUTHBEARER auth.",
    )
    kafka_secondary_sasl_oauthbearer_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KAFKA_SECONDARY_SASL_OAUTHBEARER_CLIENT_SECRET"),
        description="OAuth2 client secret for secondary cluster OAUTHBEARER auth.",
    )
    kafka_secondary_ssl_ca_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KAFKA_SECONDARY_SSL_CA_FILE"),
        description="Path to CA certificate file for secondary cluster TLS (optional; omit for Let's Encrypt certs).",
    )
    kafka_secondary_timeout_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        validation_alias=AliasChoices("KAFKA_SECONDARY_TIMEOUT_SECONDS"),
        description=(
            "Timeout in seconds for secondary cluster publish. "
            "Smaller than primary's kafka_timeout_seconds — secondary stalls must not block primary."
        ),
    )

    @field_validator("socket_path", "pid_path", mode="after")
    @classmethod
    def validate_file_path_parent(cls, v: Path) -> Path:
        parent = v.parent
        if parent.exists():
            if not parent.is_dir():
                raise ValueError(f"Parent path exists but is not a directory: {parent}")
            return v
        grandparent = parent.parent
        if grandparent.exists() and grandparent.is_dir():
            return v
        raise ValueError(
            f"Parent directory does not exist and cannot be created: {parent}"
        )

    @field_validator("spool_dir", mode="after")
    @classmethod
    def validate_spool_dir_creatable(cls, v: Path) -> Path:
        if v.exists():
            if not v.is_dir():
                raise ValueError(f"Spool path exists but is not a directory: {v}")
            return v
        current = v
        while current != current.parent:
            current = current.parent
            if current.exists():
                if current.is_dir():
                    return v
                raise ValueError(
                    f"Ancestor path exists but is not a directory: {current}"
                )
        raise ValueError(f"No valid ancestor directory found for spool path: {v}")

    @field_validator("kafka_bootstrap_servers", mode="after")
    @classmethod
    def validate_bootstrap_servers_format(cls, v: str) -> str:
        servers = v.strip().split(",")
        for server in servers:
            server = server.strip()
            if not server:
                raise ValueError("Bootstrap servers cannot contain empty entries")
            if ":" not in server:
                raise ValueError(
                    f"Invalid bootstrap server format '{server}'. Expected 'host:port'"
                )
            host, port_str = server.rsplit(":", 1)
            if ":" in host and not host.startswith("["):
                raise ValueError(
                    f"IPv6 address in '{server}' must use bracket notation, "
                    "e.g. '[::1]:9092'"
                )
            if not host:
                raise ValueError(
                    f"Invalid bootstrap server format '{server}'. Host cannot be empty"
                )
            try:
                port = int(port_str)
            except ValueError as e:
                raise ValueError(
                    f"Invalid port '{port_str}' in '{server}'. "
                    "Port must be a valid integer"
                ) from e
            if port < 1 or port > 65535:
                raise ValueError(
                    f"Invalid port {port} in '{server}'. "
                    "Port must be between 1 and 65535"
                )
        return v.strip()

    @model_validator(mode="after")
    def validate_spool_limits_consistency(self) -> PublisherConfig:
        if self.max_spool_messages == 0 and self.max_spool_bytes > 0:
            raise ValueError(
                "Inconsistent spool limits: max_spool_messages is 0 "
                "but max_spool_bytes is non-zero. Set both to 0 to disable spooling."
            )
        if self.max_spool_bytes == 0 and self.max_spool_messages > 0:
            raise ValueError(
                "Inconsistent spool limits: max_spool_bytes is 0 "
                "but max_spool_messages is non-zero. Set both to 0 to disable spooling."
            )
        return self

    @property
    def spooling_enabled(self) -> bool:
        return self.max_spool_messages > 0 and self.max_spool_bytes > 0


__all__: list[str] = ["PublisherConfig"]
