#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2026 OmniNode Team
"""OmniClaude Bus Audit (Layer 2) -- Domain schema validation CLI.

Builds on the generic Layer 1 bus audit engine (omnibase_infra.diagnostics)
to add OmniClaude-specific domain validation:

  - Schema validation against 14 Pydantic payload models
  - Emission presence matrix per hook lifecycle
  - Misroute detection (observability events on restricted cmd topics)
  - Verdict upgrades for core lifecycle topics
  - Unmapped / untyped topic detection
  - Emit daemon health check

Usage:
    python scripts/bus_audit.py
    python scripts/bus_audit.py --json
    python scripts/bus_audit.py --failures-only -v
    python scripts/bus_audit.py --broker 192.168.86.200:29092

Related tickets: OMN-2116
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sys
import tempfile
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Graceful import of confluent-kafka
# ---------------------------------------------------------------------------
try:
    from confluent_kafka import Consumer, KafkaException, TopicPartition
except ImportError:
    print(
        "ERROR: confluent-kafka is required but not installed.\n"
        "  Install with:  uv sync --group kafka\n"
        "  Or:            uv pip install confluent-kafka",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Graceful import of pydantic
# ---------------------------------------------------------------------------
try:
    from pydantic import BaseModel, ValidationError
except ImportError:
    print(
        "ERROR: pydantic is required but not installed.\n"
        "  Install with:  uv pip install pydantic",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# OmniClaude domain imports
# ---------------------------------------------------------------------------
try:
    from omniclaude.hooks.event_registry import EVENT_REGISTRY
    from omniclaude.hooks.schemas import (
        ModelAgentMatchPayload,
        ModelAgentStatusPayload,
        ModelContextUtilizationPayload,
        ModelHookContextInjectedPayload,
        ModelHookManifestInjectedPayload,
        ModelHookPromptSubmittedPayload,
        ModelHookSessionEndedPayload,
        ModelHookSessionStartedPayload,
        ModelHookToolExecutedPayload,
        ModelLatencyBreakdownPayload,
        ModelRoutingFeedbackPayload,
        ModelRoutingFeedbackSkippedPayload,
        ModelSessionOutcome,
    )
    from omniclaude.hooks.topics import TopicBase
except ImportError as exc:
    print(
        f"ERROR: Failed to import OmniClaude domain modules: {exc}\n"
        "  Ensure you are running from the omniclaude3 project root with\n"
        "  the virtual environment activated.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Optional Layer 1 availability check
# ---------------------------------------------------------------------------
try:
    import omnibase_infra.diagnostics  # noqa: F401

    _LAYER1_AVAILABLE = True
except ImportError:
    _LAYER1_AVAILABLE = False


# =============================================================================
# Enums (Layer 2 standalone definitions)
# =============================================================================


class EnumVerdict(StrEnum):
    PASS = "PASS"  # noqa: S105
    WARN = "WARN"
    FAIL = "FAIL"


class EnumTopicStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EMPTY = "EMPTY"
    MISSING = "MISSING"


class EnumNamingCompliance(StrEnum):
    ONEX = "ONEX"
    LEGACY = "LEGACY"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# Domain Configuration Constants (R1)
# =============================================================================

# Fields injected by daemon that are not in payload models
DAEMON_INJECTED_FIELDS: set[str] = {"schema_version"}

# 14 topics with Pydantic models
TOPIC_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "onex.evt.omniclaude.session-started.v1": ModelHookSessionStartedPayload,
    "onex.evt.omniclaude.session-ended.v1": ModelHookSessionEndedPayload,
    "onex.cmd.omniintelligence.session-outcome.v1": ModelSessionOutcome,
    "onex.evt.omniclaude.session-outcome.v1": ModelSessionOutcome,
    "onex.evt.omniclaude.prompt-submitted.v1": ModelHookPromptSubmittedPayload,
    "onex.evt.omniclaude.tool-executed.v1": ModelHookToolExecutedPayload,
    "onex.evt.omniclaude.context-injected.v1": ModelHookContextInjectedPayload,
    "onex.evt.omniclaude.context-utilization.v1": ModelContextUtilizationPayload,
    "onex.evt.omniclaude.agent-match.v1": ModelAgentMatchPayload,
    "onex.evt.omniclaude.latency-breakdown.v1": ModelLatencyBreakdownPayload,
    "onex.evt.omniclaude.manifest-injected.v1": ModelHookManifestInjectedPayload,
    "onex.evt.omniclaude.routing-feedback.v1": ModelRoutingFeedbackPayload,
    "onex.evt.omniclaude.routing-feedback-skipped.v1": ModelRoutingFeedbackSkippedPayload,
    "onex.evt.agent.status.v1": ModelAgentStatusPayload,
}

# Topics where certain required fields are legitimately missing from wire format.
# entity_id: shell hooks don't send it, daemon doesn't inject it.
# causation_id: daemon injects None, models require UUID.
# These exemptions apply to ALL topics emitted through the daemon pipeline --
# if a topic is in TOPIC_SCHEMA_MAP it should be listed here.
FIELD_EXEMPTIONS: dict[str, set[str]] = {
    "onex.evt.omniclaude.session-started.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.session-ended.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.prompt-submitted.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.tool-executed.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.context-injected.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.context-utilization.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.agent-match.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.latency-breakdown.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.manifest-injected.v1": {"entity_id", "causation_id"},
    # Previously missing -- same daemon pipeline, same missing fields
    "onex.cmd.omniintelligence.session-outcome.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.session-outcome.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.routing-feedback.v1": {"entity_id", "causation_id"},
    "onex.evt.omniclaude.routing-feedback-skipped.v1": {"entity_id", "causation_id"},
    # agent.status.v1: also has schema_version mismatch (model expects Literal[1],
    # daemon injects "1.0.0"). This is a known daemon/model mismatch to be fixed
    # upstream. For now, exempt schema_version as a field-level exemption rather
    # than skipping all validation on this topic.
    "onex.evt.agent.status.v1": {"entity_id", "causation_id", "schema_version"},
}

# Topics where domain validation is skipped entirely (with reason).
# Prefer FIELD_EXEMPTIONS for individual field mismatches instead of skipping
# all validation on a topic. This dict should only be used when the topic's
# wire format is fundamentally incompatible with the model.
VALIDATION_SKIP_TOPICS: dict[str, str] = {
    # agent.status.v1 moved to FIELD_EXEMPTIONS (schema_version field-level exemption)
}

LEGACY_TOPICS: set[str] = {
    "agent-actions",
    "router-performance-metrics",
    "agent-transformation-events",
    "agent-detection-failures",
}

CORE_SCHEMA_TOPICS: set[str] = {
    "onex.evt.omniclaude.session-started.v1",
    "onex.evt.omniclaude.session-ended.v1",
    "onex.evt.omniclaude.prompt-submitted.v1",
    "onex.evt.omniclaude.tool-executed.v1",
}

CORE_PRESENCE_TOPICS: set[str] = {
    "onex.cmd.omniintelligence.claude-hook-event.v1",
}

DUAL_EMISSION_ALLOWLIST: set[tuple[str, str]] = {
    (
        "onex.evt.omniclaude.prompt-submitted.v1",
        "onex.cmd.omniintelligence.claude-hook-event.v1",
    ),
    (
        "onex.evt.omniclaude.session-outcome.v1",
        "onex.cmd.omniintelligence.session-outcome.v1",
    ),
}

# Hook -> expected topics (4 hooks that emit Kafka events)
HOOK_EMISSIONS: dict[str, list[str]] = {
    "SessionStart": ["onex.evt.omniclaude.session-started.v1"],
    "SessionEnd": [
        "onex.evt.omniclaude.session-ended.v1",
        "onex.cmd.omniintelligence.session-outcome.v1",
        "onex.evt.omniclaude.session-outcome.v1",
        "onex.evt.omniclaude.routing-feedback.v1",
        "onex.evt.omniclaude.routing-feedback-skipped.v1",
    ],
    "UserPromptSubmit": [
        "onex.evt.omniclaude.prompt-submitted.v1",
        "onex.cmd.omniintelligence.claude-hook-event.v1",
    ],
    "PostToolUse": ["onex.evt.omniclaude.tool-executed.v1"],
}


# =============================================================================
# Startup Validation: TOPIC_SCHEMA_MAP keys must be valid TopicBase values
# =============================================================================

_topicbase_values: set[str] = {m.value for m in TopicBase}
_schema_map_orphans = set(TOPIC_SCHEMA_MAP.keys()) - _topicbase_values
if _schema_map_orphans:
    raise AssertionError(
        f"TOPIC_SCHEMA_MAP contains keys not in TopicBase: {sorted(_schema_map_orphans)}. "
        "Update TopicBase or remove stale entries from TOPIC_SCHEMA_MAP."
    )
del _topicbase_values, _schema_map_orphans


# =============================================================================
# Topic Discovery
# =============================================================================


def discover_topics(broker: str, timeout: float = 10.0) -> set[str]:
    """Discover all topics from the Kafka broker.

    Args:
        broker: Kafka bootstrap servers string.
        timeout: Cluster metadata timeout in seconds.

    Returns:
        Set of topic names present on the broker.
    """
    # Ephemeral group ID per invocation is intentional -- these are cleaned up
    # automatically by Redpanda's group_topic_partitions_timeout_sec (default 7 days).
    consumer = Consumer(
        {
            "bootstrap.servers": broker,
            "group.id": f"bus-audit-discovery.{int(time.time())}",
            "session.timeout.ms": 6000,
        }
    )
    try:
        metadata = consumer.list_topics(timeout=timeout)
        return set(metadata.topics)
    finally:
        consumer.close()


# =============================================================================
# Message Sampling
# =============================================================================


def sample_messages(
    broker: str, topics: list[str], sample_count: int, timeout: float = 10.0
) -> dict[str, list[dict[str, Any]]]:
    """Sample raw messages from topics for Layer 2 validation.

    For each topic, seeks to tail - sample_count and polls messages.

    Args:
        broker: Kafka bootstrap servers string.
        topics: List of topic names to sample.
        sample_count: Number of messages to sample per topic.
        timeout: Metadata/poll timeout in seconds.

    Returns:
        Dict of topic -> list of parsed JSON message dicts.
    """
    if not topics:
        return {}

    # Ephemeral group ID per invocation is intentional -- these are cleaned up
    # automatically by Redpanda's group_topic_partitions_timeout_sec (default 7 days).
    consumer = Consumer(
        {
            "bootstrap.servers": broker,
            "group.id": f"bus-audit-l2.{int(time.time())}",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
            "session.timeout.ms": 6000,
        }
    )

    result: dict[str, list[dict[str, Any]]] = {}

    try:
        metadata = consumer.list_topics(timeout=timeout)
        available_topics = set(metadata.topics.keys())

        for topic in topics:
            if topic not in available_topics:
                result[topic] = []
                continue

            topic_meta = metadata.topics[topic]
            partitions = list(topic_meta.partitions.keys())
            if not partitions:
                result[topic] = []
                continue

            messages: list[dict[str, Any]] = []

            # Distribute sample budget evenly across partitions to avoid
            # biasing toward lower-numbered partitions.
            per_partition = math.ceil(sample_count / len(partitions))

            for part_id in partitions:
                tp = TopicPartition(topic, part_id)

                # Get watermarks
                try:
                    low, high = consumer.get_watermark_offsets(tp, timeout=timeout)
                except KafkaException:
                    continue

                if high <= low:
                    continue  # No messages in this partition

                # Seek to tail - per_partition
                seek_offset = max(low, high - per_partition)
                tp.offset = seek_offset
                consumer.assign([tp])

                # Poll messages from this partition
                partition_collected = 0
                polls_remaining = per_partition * 2  # safety factor
                while partition_collected < per_partition and polls_remaining > 0:
                    polls_remaining -= 1
                    msg = consumer.poll(timeout=1.0)
                    if msg is None:
                        break
                    if msg.error():
                        continue
                    value = msg.value()
                    if value is None:
                        continue  # Tombstone
                    try:
                        parsed = json.loads(value.decode("utf-8"))
                        if isinstance(parsed, dict):
                            messages.append(parsed)
                            partition_collected += 1
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue

                consumer.unassign()

            result[topic] = messages[:sample_count]
    finally:
        consumer.close()

    return result


# =============================================================================
# Schema Validation with Exemptions
# =============================================================================


def validate_with_exemptions(
    topic: str,
    messages: list[dict[str, Any]],
    model: type[BaseModel],
    exemptions: set[str],
) -> tuple[int, int, int, list[str]]:
    """Validate messages, classifying errors as real or exempted.

    Strips DAEMON_INJECTED_FIELDS before validation. If all error fields
    for a message are within the exemption set, the error is counted as
    an exemption rather than a real failure.

    Args:
        topic: Topic name (for diagnostics).
        messages: List of raw message dicts.
        model: Pydantic model to validate against.
        exemptions: Set of field names that are known-missing from wire format.

    Returns:
        Tuple of (valid_count, real_error_count, exempted_count, error_details).
    """
    valid = 0
    real_errors = 0
    exempted = 0
    details: list[str] = []

    for msg in messages:
        # Strip daemon-injected fields that are not part of the payload model
        cleaned = {k: v for k, v in msg.items() if k not in DAEMON_INJECTED_FIELDS}
        try:
            model.model_validate(cleaned)
            valid += 1
        except ValidationError as e:
            # Check if ALL error locations are for exempted fields
            error_fields: set[str] = set()
            for err in e.errors():
                loc = err.get("loc")
                if loc and len(loc) > 0:
                    error_fields.add(str(loc[0]))

            if error_fields and error_fields <= exemptions:
                exempted += 1
            elif not error_fields:
                # Model-level (non-field) validation errors have empty loc
                # tuples, so error_fields is empty. These cannot be matched
                # against field-name exemptions -- treat as real errors with
                # an explicit diagnostic note.
                real_errors += 1
                detail = (
                    f"[{topic}] model-level validation error "
                    f"(non-field validator, empty loc): {str(e)[:250]}"
                )
                if len(details) < 20:
                    details.append(detail)
            else:
                real_errors += 1
                detail = f"[{topic}] {str(e)[:300]}"
                if len(details) < 20:
                    details.append(detail)

    return valid, real_errors, exempted, details


# =============================================================================
# Misroute Detection (R3)
# =============================================================================


def detect_misroutes(
    sampled: dict[str, list[dict[str, Any]]],
    expected_canonical: set[str] | None = None,
) -> list[dict[str, str]]:
    """Detect event types appearing on wrong topics.

    Checks cmd topics for event types that should only appear on evt topics,
    respecting the DUAL_EMISSION_ALLOWLIST.

    Args:
        sampled: Dict of topic -> list of message dicts.
        expected_canonical: Set of canonical (non-prefixed) topic names. Only
            these topics are considered for cross-topic event type comparison.
            If None, all sampled topics are considered.

    Returns:
        List of misroute dicts with keys: topic, event_type, reason.
    """
    # Build map of event_type -> set of topics it appears on
    event_type_topics: dict[str, set[str]] = {}
    for topic, messages in sampled.items():
        for msg in messages:
            et = msg.get("event_type") or msg.get("event_name")
            if et and isinstance(et, str):
                event_type_topics.setdefault(et, set()).add(topic)

    misroutes: list[dict[str, str]] = []

    # Build allowlist lookup: cmd_topic -> set of allowed evt partner topics
    allowlist_cmd: dict[str, set[str]] = {}
    for evt_topic, cmd_topic in DUAL_EMISSION_ALLOWLIST:
        allowlist_cmd.setdefault(cmd_topic, set()).add(evt_topic)

    for topic, messages in sampled.items():
        # Only check canonical cmd topics (skip env-prefixed duplicates)
        if ".cmd." not in topic:
            continue
        if expected_canonical is not None and topic not in expected_canonical:
            continue

        distinct_event_types: set[str] = set()
        for msg in messages:
            et = msg.get("event_type") or msg.get("event_name")
            if et and isinstance(et, str):
                distinct_event_types.add(et)

        allowed_partners = allowlist_cmd.get(topic, set())

        for et in distinct_event_types:
            # If this event_type also appears on an evt topic that is NOT
            # in the allowlist partner for this cmd topic, flag as misroute.
            # Only consider canonical (TopicBase) evt topics, not env-prefixed
            # duplicates on the broker.
            evt_topics = {
                t
                for t in event_type_topics.get(et, set())
                if ".evt." in t
                and t != topic
                and (expected_canonical is None or t in expected_canonical)
            }
            non_allowed = evt_topics - allowed_partners
            for evt_t in non_allowed:
                misroutes.append(
                    {
                        "topic": topic,
                        "event_type": et,
                        "reason": (
                            f"Event type '{et}' also appears on evt topic "
                            f"'{evt_t}' which is not in dual-emission allowlist"
                        ),
                    }
                )

    return misroutes


# =============================================================================
# Unmapped Topic Detection (R4)
# =============================================================================


def find_unmapped_topics() -> list[str]:
    """Find TopicBase members not in TOPIC_SCHEMA_MAP and not covered by EVENT_REGISTRY.

    Returns:
        List of topic names that have no Pydantic schema and no registry entry.
    """
    schema_mapped = set(TOPIC_SCHEMA_MAP.keys())
    registry_topics: set[str] = set()
    for reg in EVENT_REGISTRY.values():
        for rule in reg.fan_out:
            registry_topics.add(rule.topic_base.value)

    unmapped: list[str] = []
    for member in TopicBase:
        topic_val = member.value
        if topic_val in LEGACY_TOPICS:
            continue
        if topic_val not in schema_mapped and topic_val not in registry_topics:
            unmapped.append(topic_val)

    return sorted(unmapped)


# =============================================================================
# Daemon Health Check (R6)
# =============================================================================


def check_daemon_health(
    socket_path: str = str(Path(tempfile.gettempdir()) / "omniclaude-emit.sock"),
) -> dict[str, Any]:
    """Check emit daemon health via Unix socket.

    Attempts raw socket connect to the daemon socket. If connectable,
    sends a JSON status request and validates the response to distinguish
    between a healthy daemon and a degraded one.

    Status values:
      - RUNNING: Socket connected AND daemon returned valid JSON status.
      - DEGRADED: Socket connected but daemon returned invalid/empty response.
      - NOT_RUNNING: Socket does not exist or connection refused.

    Args:
        socket_path: Path to the daemon Unix socket.

    Returns:
        Dict with keys: status, queue, spool, error.
    """
    result: dict[str, Any] = {
        "status": "NOT_RUNNING",
        "queue": None,
        "spool": None,
        "error": None,
    }

    if not os.path.exists(socket_path):
        result["error"] = f"Socket not found: {socket_path}"
        return result

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect(socket_path)

        # Socket is connectable -- tentatively mark as DEGRADED until we
        # confirm a valid health response from the daemon.
        result["status"] = "DEGRADED"

        # Try sending a status request
        status_request = json.dumps({"action": "status"}) + "\n"
        sock.sendall(status_request.encode("utf-8"))

        # Read response (capped at 64 KB to prevent unbounded memory growth
        # from a misbehaving daemon before the 2s timeout fires).
        _MAX_RESPONSE_BYTES = 65536
        response_data = b""
        _cap_exceeded = False
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break
                if len(response_data) > _MAX_RESPONSE_BYTES:
                    result["error"] = (
                        f"Daemon response exceeded {_MAX_RESPONSE_BYTES} bytes, "
                        "aborting read"
                    )
                    _cap_exceeded = True
                    break
        except TimeoutError:
            pass

        if _cap_exceeded:
            pass  # result["error"] already set by the cap guard above
        elif response_data:
            try:
                resp = json.loads(response_data.decode("utf-8").strip())
                if isinstance(resp, dict):
                    # Valid JSON dict response -- daemon is healthy
                    result["status"] = "RUNNING"
                    result["queue"] = resp.get("queue_size", resp.get("queue", 0))
                    result["spool"] = resp.get("spool_size", resp.get("spool", 0))
                else:
                    # Parseable JSON but not a dict -- unexpected format
                    result["error"] = (
                        f"Daemon returned unexpected JSON type: {type(resp).__name__}"
                    )
            except (json.JSONDecodeError, UnicodeDecodeError) as parse_exc:
                result["error"] = f"Daemon response not valid JSON: {parse_exc}"
        else:
            result["error"] = "Daemon connected but returned empty response"

    except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
        result["status"] = "NOT_RUNNING"
        result["error"] = str(exc)
    finally:
        sock.close()

    return result


# =============================================================================
# Topic Status Classification
# =============================================================================


def classify_topic_status(
    topic: str,
    broker_topics: set[str],
    sampled: dict[str, list[dict[str, Any]]],
) -> str:
    """Classify a topic's status as ACTIVE, EMPTY, or MISSING.

    Args:
        topic: Topic name.
        broker_topics: Set of topics present on the broker.
        sampled: Dict of topic -> sampled messages.

    Returns:
        One of "ACTIVE", "EMPTY", "MISSING".
    """
    if topic not in broker_topics:
        return EnumTopicStatus.MISSING
    messages = sampled.get(topic, [])
    if len(messages) > 0:
        return EnumTopicStatus.ACTIVE
    return EnumTopicStatus.EMPTY


def classify_naming(topic: str) -> str:
    """Classify topic naming compliance.

    Args:
        topic: Topic name.

    Returns:
        One of "ONEX", "LEGACY", "UNKNOWN".
    """
    if topic.startswith("onex."):
        return EnumNamingCompliance.ONEX
    if topic in LEGACY_TOPICS:
        return EnumNamingCompliance.LEGACY
    return EnumNamingCompliance.UNKNOWN


# =============================================================================
# Verdict Logic (R5)
# =============================================================================


def compute_verdict(
    topic: str,
    status: str,
    real_errors: int,
    is_skip: bool,
) -> str:
    """Compute per-topic verdict with core/non-core distinction.

    Args:
        topic: Topic name.
        status: Topic status (ACTIVE/EMPTY/MISSING).
        real_errors: Count of real (non-exempted) schema validation errors.
        is_skip: Whether schema validation was skipped for this topic.

    Returns:
        One of "PASS", "WARN", "FAIL".
    """
    is_core_schema = topic in CORE_SCHEMA_TOPICS
    is_core_presence = topic in CORE_PRESENCE_TOPICS
    is_core = is_core_schema or is_core_presence

    # Missing or empty core topic -> FAIL
    if is_core and status in (EnumTopicStatus.MISSING, EnumTopicStatus.EMPTY):
        return EnumVerdict.FAIL

    # Missing or empty non-core topic -> WARN
    if not is_core and status in (EnumTopicStatus.MISSING, EnumTopicStatus.EMPTY):
        return EnumVerdict.WARN

    # Skipped validation -> PASS (no schema check was done)
    if is_skip:
        return EnumVerdict.PASS

    # Core schema topic with real schema errors -> FAIL
    if is_core_schema and real_errors > 0:
        return EnumVerdict.FAIL

    # Core presence topic (not a core schema topic) with real schema errors -> WARN
    # These topics are important enough to flag but don't have strict schema contracts.
    if is_core_presence and real_errors > 0:
        return EnumVerdict.WARN

    # Non-core topic with schema errors -> WARN
    if not is_core and real_errors > 0:
        return EnumVerdict.WARN

    return EnumVerdict.PASS


def compute_overall_verdict(verdicts: list[str]) -> str:
    """Compute overall verdict from per-topic verdicts.

    Args:
        verdicts: List of per-topic verdict strings.

    Returns:
        "FAIL" if any FAIL, "WARN" if any WARN, else "PASS".
    """
    if EnumVerdict.FAIL in verdicts:
        return EnumVerdict.FAIL
    if EnumVerdict.WARN in verdicts:
        return EnumVerdict.WARN
    return EnumVerdict.PASS


# =============================================================================
# Main Audit Pipeline
# =============================================================================


def run_bus_audit(
    broker: str,
    sample_count: int = 20,
    skip_daemon: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run the full Layer 2 bus audit pipeline.

    Args:
        broker: Kafka bootstrap servers.
        sample_count: Number of messages to sample per topic.
        skip_daemon: Whether to skip daemon health check.
        verbose: Whether to include extra detail in results.

    Returns:
        Audit result dict suitable for JSON serialization or human display.
    """
    now = datetime.now(UTC).isoformat()

    # Expected topics from TopicBase
    all_expected: set[str] = {m.value for m in TopicBase}
    schema_mapped_topics = set(TOPIC_SCHEMA_MAP.keys())
    validatable_topics = {
        t for t in schema_mapped_topics if t not in VALIDATION_SKIP_TOPICS
    }

    # -------------------------------------------------------------------------
    # Step 1: Topic discovery
    # -------------------------------------------------------------------------
    try:
        broker_topics = discover_topics(broker)
    except KafkaException as exc:
        return {
            "broker": broker,
            "timestamp": now,
            "error": f"Failed to connect to broker: {exc}",
            "overall_verdict": EnumVerdict.FAIL,
        }

    # -------------------------------------------------------------------------
    # Step 2: Sample messages for schema validation and misroute detection
    # -------------------------------------------------------------------------
    topics_to_sample = sorted(
        validatable_topics | CORE_PRESENCE_TOPICS | set(VALIDATION_SKIP_TOPICS.keys())
    )
    # Also sample cmd and evt topics for misroute detection
    cmd_topics_on_broker = {
        t for t in broker_topics if ".cmd." in t and t not in topics_to_sample
    }
    evt_topics_on_broker = {
        t for t in broker_topics if ".evt." in t and t not in topics_to_sample
    }
    # Include canonical evt topics from TopicBase that exist on the broker so
    # misroute detection can compare event types across cmd/evt pairs (OMN-2116).
    # Only broker-present topics are included to avoid unnecessary network
    # round-trips for topics that sample_messages would return empty anyway.
    canonical_evt_topics = {
        t.value for t in TopicBase if ".evt." in t.value
    } & broker_topics
    all_sample_targets = sorted(
        set(topics_to_sample)
        | cmd_topics_on_broker
        | evt_topics_on_broker
        | canonical_evt_topics
    )

    sampled = sample_messages(broker, all_sample_targets, sample_count)

    # -------------------------------------------------------------------------
    # Step 3: Layer 2 schema validation
    # -------------------------------------------------------------------------
    topic_results: list[dict[str, Any]] = []
    verdicts: list[str] = []

    # Process schema-mapped topics
    for topic in sorted(TOPIC_SCHEMA_MAP.keys()):
        model = TOPIC_SCHEMA_MAP[topic]
        status = classify_topic_status(topic, broker_topics, sampled)
        naming = classify_naming(topic)
        exemptions = FIELD_EXEMPTIONS.get(topic, set())

        if topic in VALIDATION_SKIP_TOPICS:
            skip_reason = VALIDATION_SKIP_TOPICS[topic]
            verdict = compute_verdict(topic, status, 0, is_skip=True)
            verdicts.append(verdict)
            topic_results.append(
                {
                    "topic": topic,
                    "status": status,
                    "naming": naming,
                    "verdict": verdict,
                    "schema_validation": {
                        "skipped": True,
                        "skip_reason": skip_reason,
                    },
                    "is_core": topic in CORE_SCHEMA_TOPICS,
                    "is_core_presence": topic in CORE_PRESENCE_TOPICS,
                }
            )
            continue

        messages = sampled.get(topic, [])
        if messages:
            valid, real_errors, exempted_count, error_details = (
                validate_with_exemptions(topic, messages, model, exemptions)
            )
        else:
            valid, real_errors, exempted_count, error_details = 0, 0, 0, []

        verdict = compute_verdict(topic, status, real_errors, is_skip=False)
        verdicts.append(verdict)

        entry: dict[str, Any] = {
            "topic": topic,
            "status": status,
            "naming": naming,
            "verdict": verdict,
            "schema_validation": {
                "skipped": False,
                "sampled": len(messages),
                "valid": valid,
                "real_errors": real_errors,
                "exempted": exempted_count,
                "exempted_fields": sorted(exemptions) if exemptions else [],
            },
            "is_core": topic in CORE_SCHEMA_TOPICS,
            "is_core_presence": topic in CORE_PRESENCE_TOPICS,
        }
        if verbose and error_details:
            entry["schema_validation"]["error_details"] = error_details

        topic_results.append(entry)

    # Process core presence topics (no schema, just presence check)
    for topic in sorted(CORE_PRESENCE_TOPICS):
        if topic in TOPIC_SCHEMA_MAP:
            continue  # Already processed above
        status = classify_topic_status(topic, broker_topics, sampled)
        verdict = compute_verdict(topic, status, 0, is_skip=True)
        verdicts.append(verdict)
        topic_results.append(
            {
                "topic": topic,
                "status": status,
                "naming": classify_naming(topic),
                "verdict": verdict,
                "schema_validation": {"skipped": True, "skip_reason": "presence-only"},
                "is_core": False,
                "is_core_presence": True,
            }
        )

    # -------------------------------------------------------------------------
    # Step 4: Emission presence matrix (R2)
    # -------------------------------------------------------------------------
    emission_matrix: dict[str, dict[str, str]] = {}
    for hook, topics_list in HOOK_EMISSIONS.items():
        hook_map: dict[str, str] = {}
        for topic in topics_list:
            hook_map[topic] = classify_topic_status(topic, broker_topics, sampled)
        emission_matrix[hook] = hook_map

    # -------------------------------------------------------------------------
    # Step 5: Misroute detection (R3)
    # -------------------------------------------------------------------------
    canonical_topics = {t.value for t in TopicBase}
    misroutes = detect_misroutes(sampled, expected_canonical=canonical_topics)

    # -------------------------------------------------------------------------
    # Step 6: Unmapped topic detection (R4)
    # -------------------------------------------------------------------------
    unmapped = find_unmapped_topics()

    # -------------------------------------------------------------------------
    # Step 7: Daemon health (R6)
    # -------------------------------------------------------------------------
    daemon_health: dict[str, Any] | None = None
    if not skip_daemon:
        daemon_health = check_daemon_health()

    # -------------------------------------------------------------------------
    # Step 8: Overall verdict
    # -------------------------------------------------------------------------
    overall = compute_overall_verdict(verdicts)

    # Summary counts
    pass_count = sum(1 for v in verdicts if v == EnumVerdict.PASS)
    warn_count = sum(1 for v in verdicts if v == EnumVerdict.WARN)
    fail_count = sum(1 for v in verdicts if v == EnumVerdict.FAIL)

    return {
        "broker": broker,
        "timestamp": now,
        "layer1_available": _LAYER1_AVAILABLE,
        "topic_counts": {
            "expected_topicbase": len(all_expected),
            "schema_mapped": len(schema_mapped_topics),
            "legacy": len(LEGACY_TOPICS),
            "broker_discovered": len(broker_topics),
        },
        "daemon_health": daemon_health,
        "topics": topic_results,
        "emission_matrix": emission_matrix,
        "misroutes": misroutes,
        "unmapped": unmapped,
        "overall_verdict": overall,
        "summary": {
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
        },
    }


# =============================================================================
# Output Formatting
# =============================================================================

# Box drawing characters
_HEADER = "\u2550"  # double horizontal
_SECTION_L = "\u2500"  # single horizontal


def _short_topic(topic: str) -> str:
    """Extract short name from full topic for display."""
    # e.g. "onex.evt.omniclaude.session-started.v1" -> "session-started.v1"
    parts = topic.split(".")
    if len(parts) >= 4:
        return ".".join(parts[3:])
    return topic


def _verdict_symbol(verdict: str) -> str:
    """Return a text symbol for a verdict."""
    if verdict == EnumVerdict.PASS:
        return "ok"
    if verdict == EnumVerdict.WARN:
        return "!!"
    return "XX"


def format_human(
    report: dict[str, Any],
    failures_only: bool = False,
    verbose: bool = False,
) -> str:
    """Format audit report for human-readable terminal output.

    Args:
        report: Audit result dict from run_bus_audit().
        failures_only: If True, only show topics with WARN or FAIL verdicts.
        verbose: If True, show error detail snippets inline.

    Returns:
        Multi-line string for terminal display.
    """
    lines: list[str] = []

    # Check for connection error
    if "error" in report:
        lines.append(f"ERROR: {report['error']}")
        return "\n".join(lines)

    counts = report["topic_counts"]
    lines.append(f"{_HEADER * 3} OmniClaude Bus Audit (Layer 2) {_HEADER * 3}")
    lines.append(f"Broker: {report['broker']}")
    lines.append(
        f"Topics: {counts['expected_topicbase']} expected (TopicBase), "
        f"{counts['schema_mapped']} schema-mapped, "
        f"{counts['legacy']} legacy"
    )
    if not report.get("layer1_available"):
        lines.append("Layer 1: not available (standalone mode)")
    lines.append("")

    # -- Daemon Health ---------------------------------------------------------
    daemon = report.get("daemon_health")
    if daemon is not None:
        lines.append(f"{_SECTION_L * 2} Daemon Health {_SECTION_L * 40}"[:60])
        if daemon["status"] == "RUNNING":
            q = daemon.get("queue", "?")
            s = daemon.get("spool", "?")
            lines.append(f"  RUNNING (queue: {q}, spool: {s})")
        elif daemon["status"] == "DEGRADED":
            err = daemon.get("error", "unknown")
            lines.append(f"  DEGRADED -- socket connectable but unhealthy ({err})")
        else:
            err = daemon.get("error", "unknown")
            lines.append(f"  NOT_RUNNING ({err})")
        lines.append("")

    # -- Core Lifecycle --------------------------------------------------------
    lines.append(f"{_SECTION_L * 2} Core Lifecycle {_SECTION_L * 39}"[:60])
    core_topics = [
        r for r in report["topics"] if r.get("is_core") or r.get("is_core_presence")
    ]
    for r in core_topics:
        verdict = r["verdict"]
        if failures_only and verdict == EnumVerdict.PASS:
            continue
        sym = _verdict_symbol(verdict)
        short = _short_topic(r["topic"])
        status = r["status"]
        sv = r.get("schema_validation", {})

        extra = ""
        if sv.get("skipped"):
            reason = sv.get("skip_reason", "")
            if reason == "presence-only":
                extra = "(presence only, no schema)"
            elif reason:
                extra = f"(SKIP: {reason})"
        else:
            parts: list[str] = []
            real_errors = sv.get("real_errors", 0)
            exempted_count = sv.get("exempted", 0)
            exempted_fields = sv.get("exempted_fields", [])
            sampled = sv.get("sampled", 0)
            valid_count = sv.get("valid", 0)
            if real_errors > 0:
                parts.append(f"{real_errors} schema errors")
            if exempted_count > 0 and exempted_fields:
                parts.append(f"{exempted_count} exempted: {', '.join(exempted_fields)}")
            if valid_count > 0 and sampled > 0:
                parts.append(f"{valid_count}/{sampled} valid")
            if parts:
                extra = f"({'; '.join(parts)})"

        lines.append(f"  [{sym}] {short:<35s} {status:<8s} {verdict:<5s} {extra}")

        # Verbose: show error details inline
        if verbose and sv.get("error_details"):
            for detail in sv["error_details"][:3]:
                for detail_line in detail.split("\n")[:4]:
                    lines.append(f"         {detail_line}")
                lines.append("")

    lines.append("")

    # -- Emission Presence -----------------------------------------------------
    emission = report.get("emission_matrix", {})
    if emission:
        lines.append(f"{_SECTION_L * 2} Emission Presence {_SECTION_L * 36}"[:60])
        for hook, topic_map in emission.items():
            first = True
            for topic, status in topic_map.items():
                short = _short_topic(topic)
                hook_label = hook if first else ""
                marker = ""
                if status in (EnumTopicStatus.EMPTY, EnumTopicStatus.MISSING):
                    marker = " !!"
                lines.append(f"  {hook_label:<20s} -> {short:<35s} {status}{marker}")
                first = False
        lines.append("")

    # -- Non-Core Topics -------------------------------------------------------
    non_core = [
        r
        for r in report["topics"]
        if not r.get("is_core") and not r.get("is_core_presence")
    ]
    if non_core:
        lines.append(f"{_SECTION_L * 2} Non-Core Topics {_SECTION_L * 38}"[:60])
        for r in non_core:
            verdict = r["verdict"]
            if failures_only and verdict == EnumVerdict.PASS:
                continue
            sym = _verdict_symbol(verdict)
            short = _short_topic(r["topic"])
            status = r["status"]
            sv = r.get("schema_validation", {})

            extra = ""
            if sv.get("skipped"):
                reason = sv.get("skip_reason", "")
                extra = f"(SKIP: {reason[:60]})" if reason else "(SKIP)"
            else:
                parts_nc: list[str] = []
                real_errors = sv.get("real_errors", 0)
                exempted_count = sv.get("exempted", 0)
                exempted_fields = sv.get("exempted_fields", [])
                if real_errors > 0:
                    parts_nc.append(f"{real_errors} schema errors")
                if exempted_count > 0 and exempted_fields:
                    parts_nc.append(
                        f"{exempted_count} exempted: {', '.join(exempted_fields)}"
                    )
                if parts_nc:
                    extra = f"({'; '.join(parts_nc)})"

            lines.append(f"  [{sym}] {short:<35s} {status:<8s} {verdict:<5s} {extra}")

            if verbose and sv.get("error_details"):
                for detail in sv["error_details"][:3]:
                    for detail_line in detail.split("\n")[:4]:
                        lines.append(f"         {detail_line}")
                    lines.append("")

        lines.append("")

    # -- Misroutes -------------------------------------------------------------
    misroutes = report.get("misroutes", [])
    if misroutes:
        lines.append(f"{_SECTION_L * 2} Misroutes {_SECTION_L * 44}"[:60])
        for m in misroutes:
            lines.append(f"  MISROUTE: {m['event_type']} on {_short_topic(m['topic'])}")
            lines.append(f"           {m['reason']}")
        lines.append("")

    # -- Unmapped Topics -------------------------------------------------------
    unmapped = report.get("unmapped", [])
    if unmapped:
        lines.append(f"{_SECTION_L * 2} Unmapped {_SECTION_L * 45}"[:60])
        for t in unmapped:
            lines.append(f"  UNTYPED: {t}")
        lines.append("")

    # -- Overall Verdict -------------------------------------------------------
    summary = report.get("summary", {})
    overall = report.get("overall_verdict", "UNKNOWN")
    lines.append(
        f"{_SECTION_L * 2} Verdict: {overall} "
        f"({summary.get('warn', 0)} WARN, {summary.get('fail', 0)} FAIL) "
        f"{_SECTION_L * 2}"
    )

    return "\n".join(lines)


# =============================================================================
# CLI Entry Point (R7)
# =============================================================================


def main() -> None:
    """CLI entry point for OmniClaude Bus Audit (Layer 2)."""
    parser = argparse.ArgumentParser(
        description="OmniClaude Bus Audit (Layer 2) -- Domain schema validation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/bus_audit.py\n"
            "  python scripts/bus_audit.py --json\n"
            "  python scripts/bus_audit.py --failures-only -v\n"
            "  python scripts/bus_audit.py --broker 192.168.86.200:29092\n"
        ),
    )
    parser.add_argument(
        "--broker",
        default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092"),
        help="Kafka bootstrap servers (default: $KAFKA_BOOTSTRAP_SERVERS or 192.168.86.200:29092)",
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=20,
        help="Number of messages to sample per topic (default: 20)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--failures-only",
        action="store_true",
        help="Only show topics with WARN or FAIL verdicts",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Include extra detail (sample payloads for failures)",
    )
    parser.add_argument(
        "--skip-daemon",
        action="store_true",
        help="Skip emit daemon health check",
    )

    args = parser.parse_args()

    # Exit codes:
    #   0 = success (PASS or WARN verdict)
    #   1 = Kafka connection failure
    #   2 = FAIL verdict (audit found critical issues)
    #   3 = unexpected error (script bug or unforeseen exception)
    try:
        report = run_bus_audit(
            broker=args.broker,
            sample_count=args.sample_count,
            skip_daemon=args.skip_daemon,
            verbose=args.verbose,
        )
    except KafkaException as exc:
        print(f"ERROR: Kafka connection failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(3)

    if args.json_output:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(
            format_human(
                report,
                failures_only=args.failures_only,
                verbose=args.verbose,
            )
        )

    # Exit code: 1=Kafka connection failure (report contains "error" key)
    if "error" in report:
        sys.exit(1)

    # Exit code: 0=PASS/WARN, 2=FAIL verdict
    elif report.get("overall_verdict") == EnumVerdict.FAIL:
        sys.exit(2)


if __name__ == "__main__":
    main()
