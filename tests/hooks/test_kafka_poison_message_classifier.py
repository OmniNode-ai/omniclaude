# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for kafka_poison_message_classifier — pure regex classifier.

Task 1 of OMN-9083 epic (OMN-9085). Classifier detects Kafka consumer
UnicodeDecodeError crash-loops so the PostToolUse guard can record
structured friction without blocking the tool result.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HOOKS_LIB = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from kafka_poison_message_classifier import (  # noqa: E402
    KafkaPoisonClassification,
    classify_kafka_failure,
)


@pytest.mark.unit
def test_unicode_decode_error_detected() -> None:
    """UnicodeDecodeError in describe_consumer_groups → CRITICAL."""
    output = (
        "Traceback (most recent call last):\n"
        '  File "aiokafka/admin/client.py", line 512, in describe_consumer_groups\n'
        "    return _decode(buf)\n"
        "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 3"
    )
    result = classify_kafka_failure(output)
    assert isinstance(result, KafkaPoisonClassification)
    assert result.severity == "CRITICAL"
    assert result.pattern == "unicode_decode_consumer_groups"


@pytest.mark.unit
def test_normal_kafka_output_passes() -> None:
    """Normal Kafka tool output → None (no friction)."""
    output = "{'status': 'ok', 'groups': 3, 'topics': ['onex.evt.foo.v1']}"
    assert classify_kafka_failure(output) is None


@pytest.mark.unit
def test_cascade_error_detected() -> None:
    """aiokafka decode cascade variants → CRITICAL."""
    output = "aiokafka.errors.KafkaError: failed to decode response header"
    result = classify_kafka_failure(output)
    assert isinstance(result, KafkaPoisonClassification)
    assert result.severity == "CRITICAL"
    assert result.pattern == "aiokafka_decode_cascade"


@pytest.mark.unit
def test_malformed_input_safe() -> None:
    """Binary / null / empty input does not crash the classifier."""
    assert classify_kafka_failure("") is None
    assert classify_kafka_failure("\x00\xff\x01\x02 raw bytes as str") is None
    assert classify_kafka_failure(None) is None  # type: ignore[arg-type]
