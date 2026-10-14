# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeTranscriptUsageReadEffect: token use and model per assistant message (OMN-18946).

Capability: transcript.usage.read. Claude Code passes no usage to any hook; this
node reads it from the transcript a Stop, SubagentStop or SessionEnd names.
"""
