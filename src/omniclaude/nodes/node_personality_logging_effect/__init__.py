# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodePersonalityLoggingEffect — personality-aware structured logging.

Implements OMN-2575: Personality Logging Effect Node.

Exported Components:
    Node:
        NodePersonalityLoggingEffect — ONEX effect node

    Models:
        ModelLogEvent — canonical structured log event
        ModelRenderedLog — output of PersonalityAdapter
        ModelPersonalityProfile — phrase-pack-driven rendering profile
        ModelLoggingConfig — YAML-backed runtime configuration

    Adapter:
        PersonalityAdapter — pure LogEvent → RenderedLog transformation
        apply_redaction — scrub redaction_rules patterns from attrs

    Config:
        LiveConfigLoader — watches YAML config file and reloads on change
        load_config_from_yaml — load LoggingConfig from a YAML file

    Sinks:
        StdoutSink — writes rendered messages to stdout
        SlackSink — posts to Slack webhook (Block Kit, rate-limited, dedup)
        JsonSink — writes raw LogEvent as newline-delimited JSON
"""

from omniclaude.nodes.node_personality_logging_effect.config_loader import (
    LiveConfigLoader,
    load_config_from_yaml,
)
from omniclaude.nodes.node_personality_logging_effect.models import (
    EnumLogSeverity,
    ModelLogEvent,
    ModelLoggingConfig,
    ModelPersonalityProfile,
    ModelRenderedLog,
)
from omniclaude.nodes.node_personality_logging_effect.node import (
    NodePersonalityLoggingEffect,
)
from omniclaude.nodes.node_personality_logging_effect.personality_adapter import (
    PersonalityAdapter,
    apply_redaction,
)
from omniclaude.nodes.node_personality_logging_effect.sinks import (
    JsonSink,
    SlackSink,
    StdoutSink,
)

__all__ = [
    # Node
    "NodePersonalityLoggingEffect",
    # Models
    "EnumLogSeverity",
    "ModelLogEvent",
    "ModelLoggingConfig",
    "ModelPersonalityProfile",
    "ModelRenderedLog",
    # Adapter
    "PersonalityAdapter",
    "apply_redaction",
    # Config
    "LiveConfigLoader",
    "load_config_from_yaml",
    # Sinks
    "JsonSink",
    "SlackSink",
    "StdoutSink",
]
