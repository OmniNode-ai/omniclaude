# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""LoggingConfig — YAML-backed runtime configuration for the logging effect node.

Model ownership: PRIVATE to omniclaude.

Supports live reload via watchfiles; switching personality profile requires
no service restart.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ModelThrottleConfig(BaseModel):
    """Rate-limiting configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_per_minute: int = Field(
        default=60,
        ge=1,
        description="Maximum events emitted per minute across all sinks",
    )


class ModelQuietHours(BaseModel):
    """Quiet-hours window: Slack/noisy sinks suppressed during this range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: int = Field(
        default=22,
        ge=0,
        le=23,
        description="Hour (0-23, UTC) at which quiet hours begin",
    )
    end: int = Field(
        default=8,
        ge=0,
        le=23,
        description="Hour (0-23, UTC) at which quiet hours end",
    )


class ModelRoutingRule(BaseModel):
    """A single routing rule: glob on event_name → list of sinks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str = Field(
        ...,
        description=(
            "Glob pattern matched against LogEvent.event_name "
            "(e.g. ``db.*``, ``*.error``)"
        ),
    )
    sinks: list[str] = Field(
        ...,
        min_length=1,
        description="Sink names to route matching events to",
    )


class ModelLoggingConfig(BaseModel):
    """Runtime configuration for NodePersonalityLoggingEffect.

    Loaded from a YAML file at startup and reloaded on file change.

    Attributes:
        personality_profile: Name of the active personality profile.
        routing_rules: Ordered list of glob-pattern → sinks routing rules.
        throttle: Global rate-limit settings.
        quiet_hours: Window during which noisy sinks are suppressed.
        privacy_mode: ``strict`` enforces redaction before any rendering.
        phrase_pack_paths: Optional list of YAML phrase-pack files to load.
        kafka_input_topic: Kafka topic to consume LogEvents from.
        kafka_output_topic: Kafka topic to emit rendered RenderedLog events to.
        slack_webhook_url: Webhook URL for the Slack sink.
        json_output_path: File path for the JSON sink (``-`` for stdout).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    personality_profile: str = Field(
        default="default",
        description="Active personality profile name",
    )
    routing_rules: list[ModelRoutingRule] = Field(
        default_factory=list,
        description="Ordered glob-pattern → sinks routing rules",
    )
    throttle: ModelThrottleConfig = Field(
        default_factory=ModelThrottleConfig,
        description="Global rate-limit settings",
    )
    quiet_hours: ModelQuietHours = Field(
        default_factory=ModelQuietHours,
        description="Quiet-hours window (Slack suppressed)",
    )
    privacy_mode: str = Field(
        default="standard",
        description="``strict`` applies redaction before rendering",
    )
    phrase_pack_paths: list[Path] = Field(
        default_factory=list,
        description="User-supplied YAML phrase-pack files",
    )
    kafka_input_topic: str = Field(
        default="onex.evt.logging.event-emitted.v1",
        description="Kafka topic to consume LogEvents from",
    )
    kafka_output_topic: str = Field(
        default="onex.evt.logging.event-rendered.v1",
        description="Kafka topic to emit rendered events to",
    )
    slack_webhook_url: str | None = Field(
        default=None,
        description="Slack incoming webhook URL for the Slack sink",
    )
    json_output_path: str = Field(
        default="-",
        description="File path for JSON sink output (``-`` for stdout)",
    )


__all__ = [
    "ModelLoggingConfig",
    "ModelQuietHours",
    "ModelRoutingRule",
    "ModelThrottleConfig",
]
