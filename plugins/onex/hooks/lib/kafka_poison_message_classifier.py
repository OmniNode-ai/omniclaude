# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Kafka poison-message classifier — pure regex matcher.

Detects UnicodeDecodeError crash-loops in aiokafka consumers so the
PostToolUse Bash guard can record structured friction.

Friction source: .onex_state/friction/2026-04-17T15-14-36Z-merge-sweep-orchestrator-down.yaml
Ticket: OMN-9085 (epic OMN-9083).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class KafkaPoisonClassification:
    """Result of classifying a chunk of tool output against poison-message patterns."""

    pattern: str
    severity: str
    matched_text: str


# Ordered most-specific first. First match wins; the hook records verbatim context.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "unicode_decode_consumer_groups",
        re.compile(
            r"UnicodeDecodeError[\s\S]{0,400}?describe_consumer_groups"
            r"|describe_consumer_groups[\s\S]{0,400}?UnicodeDecodeError",
            re.IGNORECASE,
        ),
    ),
    (
        "aiokafka_decode_cascade",
        re.compile(r"aiokafka[\s\S]{0,200}?decode", re.IGNORECASE),
    ),
    (
        "poison_message",
        re.compile(r"poison\s*message", re.IGNORECASE),
    ),
)


def classify_kafka_failure(output: str | None) -> KafkaPoisonClassification | None:
    """Classify tool output against Kafka poison-message patterns.

    Returns a classification on match (severity always CRITICAL for this
    taxonomy), or None when the output is absent, non-string, or does not
    match any known pattern. Never raises.
    """
    if not isinstance(output, str) or not output:
        return None
    try:
        for name, regex in _PATTERNS:
            match = regex.search(output)
            if match is not None:
                return KafkaPoisonClassification(
                    pattern=name,
                    severity="CRITICAL",
                    matched_text=match.group(0),
                )
    except Exception:
        return None
    return None
