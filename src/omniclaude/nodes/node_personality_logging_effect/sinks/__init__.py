# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Sink adapters for node_personality_logging_effect."""

from omniclaude.nodes.node_personality_logging_effect.sinks.sink_json import JsonSink
from omniclaude.nodes.node_personality_logging_effect.sinks.sink_slack import SlackSink
from omniclaude.nodes.node_personality_logging_effect.sinks.sink_stdout import StdoutSink

__all__ = ["JsonSink", "SlackSink", "StdoutSink"]
