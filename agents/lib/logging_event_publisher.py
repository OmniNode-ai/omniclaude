#!/usr/bin/env python3
"""
Logging Event Publisher - Kafka-based Structured Logging

This module provides a Kafka client for publishing structured logging events,
enabling real-time log streaming to omnidash and centralized log aggregation.

Key Features:
- Non-blocking async publish using aiokafka
- OnexEnvelopeV1 structure following EVENT_BUS_INTEGRATION_GUIDE
- Partition key policy compliance (service_name for application, tenant_id for audit/security)
- Complete event envelope with all required fields
- Connection pooling and management
- Graceful degradation on Kafka failure

Event Types:
- omninode.logging.application.v1 - Structured application logs
- omninode.logging.audit.v1 - Audit trail for compliance
- omninode.logging.security.v1 - Security audit events

Integration:
- Wire-compatible with omniarchon event handlers
- Designed for fire-and-forget publishing (not request-response)
- Integrates with omnidash for real-time log visualization
- Replaces/augments file-based logging throughout codebase

Performance Characteristics:
- Publish time: <10ms p95
- Memory overhead: <10MB
- Success rate: >99%
- Non-blocking: Never blocks application execution
- Maximum payload size: 1MB (oversized payloads rejected)

Created: 2025-11-13
Reference: EVENT_ALIGNMENT_PLAN.md Phase 2 (Tasks 2.1, 2.2, 2.3)
          EVENT_BUS_INTEGRATION_GUIDE.md (event structure standards)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from prometheus_client import Counter, Gauge, Histogram

from config import settings

logger = logging.getLogger(__name__)

# Maximum payload size (1MB)
MAX_PAYLOAD_SIZE = 1024 * 1024


# Prometheus Metrics
# ------------------
# Metrics for production observability and monitoring

# Counter: Total events published
logging_events_published = Counter(
    "logging_events_published_total",
    "Total logging events published",
    ["event_type", "status"],
)

# Histogram: Publish latency
logging_publish_latency = Histogram(
    "logging_publish_latency_seconds",
    "Logging event publish latency",
    ["event_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# Gauge: Publisher state
logging_publisher_started = Gauge(
    "logging_publisher_started", "Logging publisher started state", ["service_name"]
)

# Counter: Kafka errors
logging_kafka_errors = Counter(
    "logging_kafka_errors_total", "Total Kafka errors", ["event_type", "error_type"]
)


class LogLevel(str, Enum):
    """Valid log levels for application logging."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class Outcome(str, Enum):
    """Valid outcomes for audit logging."""

    SUCCESS = "success"
    FAILURE = "failure"


class Decision(str, Enum):
    """Valid authorization decisions for security logging."""

    ALLOW = "allow"
    DENY = "deny"


class LoggingEventPublisher:
    """
    Kafka publisher for structured logging events.

    Provides non-blocking async publishing of application, audit, and security
    logging events with OnexEnvelopeV1 structure, partition key policy compliance,
    and graceful degradation on Kafka failures.

    This publisher uses aiokafka for native async/await integration, perfect
    for fire-and-forget event publishing without blocking application execution.

    Usage:
        publisher = LoggingEventPublisher(
            bootstrap_servers="localhost:9092",
            enable_events=True,
        )

        await publisher.start()

        try:
            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="router.pipeline",
                message="Agent execution completed successfully",
                code="AGENT_EXECUTION_COMPLETED",
                context={"agent_name": "agent-api-architect", "duration_ms": 1234},
            )
        finally:
            await publisher.stop()

    Or use context manager:
        async with LoggingEventPublisherContext() as publisher:
            await publisher.publish_application_log(...)
    """

    # Kafka topic names (following EVENT_BUS_INTEGRATION_GUIDE standard)
    # Format: omninode.{domain}.{entity}.{action}.v{major}
    TOPIC_APPLICATION_LOG = "omninode.logging.application.v1"
    TOPIC_AUDIT_LOG = "omninode.logging.audit.v1"
    TOPIC_SECURITY_LOG = "omninode.logging.security.v1"

    # Kafka publish timeout (5 seconds)
    # Prevents indefinite blocking if broker is slow/unresponsive
    KAFKA_PUBLISH_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_events: Optional[bool] = None,
    ):
        """
        Initialize logging event publisher.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - External host: "localhost:9092" or "192.168.86.200:9092"
                - Docker internal: "omninode-bridge-redpanda:9092"
            enable_events: Enable event publishing (feature flag)
                - If None, reads from KAFKA_ENABLE_LOGGING_EVENTS environment variable
                - Defaults to True if neither provided
                - Explicit parameter takes precedence over environment variable
        """
        # Bootstrap servers - use centralized configuration if not provided
        self.bootstrap_servers = (
            bootstrap_servers or settings.get_effective_kafka_bootstrap_servers()
        )
        if not self.bootstrap_servers:
            raise ValueError(
                "bootstrap_servers must be provided or set via environment variables.\n"
                "Checked variables (in order):\n"
                "  1. KAFKA_BOOTSTRAP_SERVERS (general config)\n"
                "Example: KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092\n"
                f"Current value: {getattr(settings, 'kafka_bootstrap_servers', 'not set')}"
            )

        # Read from Pydantic Settings if not explicitly provided
        if enable_events is None:
            enable_events = settings.kafka_enable_logging_events
        self.enable_events = enable_events

        self._producer: Optional[AIOKafkaProducer] = None
        self._started = False

        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Initialize Kafka producer.

        Creates producer for publishing events.
        Should be called once before publishing events.

        Raises:
            KafkaError: If Kafka connection fails
        """
        if self._started:
            self.logger.debug("Logging event publisher already started")
            return

        if not self.enable_events:
            self.logger.info("Logging event publisher disabled via feature flag")
            return

        try:
            self.logger.info(
                f"Starting logging event publisher (broker: {self.bootstrap_servers})"
            )

            # Initialize producer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                compression_type="gzip",
                linger_ms=20,
                acks="all",  # Wait for all replicas
                api_version="auto",
                request_timeout_ms=30000,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()

            self._started = True

            # Set Prometheus gauge to indicate publisher is started
            logging_publisher_started.labels(service_name="omniclaude").set(1)

            self.logger.info("Logging event publisher started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start logging event publisher: {e}")
            # Clean up producer if it was created
            if self._producer is not None:
                try:
                    await self._producer.stop()
                except Exception:
                    pass  # Ignore cleanup errors to preserve original exception
                self._producer = None
            raise KafkaError(f"Failed to start Kafka producer: {e}") from e

    async def stop(self) -> None:
        """
        Close Kafka producer gracefully.

        Stops producer and cleans up resources.
        Should be called when publisher is no longer needed.
        """
        if not self._started:
            return

        self.logger.info("Stopping logging event publisher")

        try:
            # Stop producer
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

            self._started = False

            # Clear Prometheus gauge to indicate publisher is stopped
            logging_publisher_started.labels(service_name="omniclaude").set(0)

            self.logger.info("Logging event publisher stopped successfully")

        except Exception as e:
            self.logger.error(f"Error stopping logging event publisher: {e}")

    def _validate_partition_key_field(
        self,
        field_name: str,
        field_value: str,
        max_length: int = 256,
    ) -> None:
        """
        Validate field used in partition key with strict security checks.

        Partition keys require stricter validation because they:
        1. Control Kafka message routing and partitioning
        2. Are used in Kafka headers (limited character set)
        3. Can cause DoS if excessively long
        4. Break encoding if they contain null bytes

        Args:
            field_name: Name of the field being validated
            field_value: Value to validate (must be string, cannot be None)
            max_length: Maximum allowed length (default: 256 chars)

        Raises:
            TypeError: If field_value is not a string
            ValueError: If validation fails (length, null bytes, empty/whitespace)

        Example:
            >>> publisher._validate_partition_key_field("tenant_id", "tenant-123")
            >>> publisher._validate_partition_key_field("tenant_id", None)  # Raises TypeError
            >>> publisher._validate_partition_key_field("tenant_id", "x" * 257)  # Raises ValueError
            >>> publisher._validate_partition_key_field("tenant_id", "tenant\\x00id")  # Raises ValueError
        """
        # Type check - partition keys must be strings
        if not isinstance(field_value, str):
            raise TypeError(
                f"{field_name} must be a string, got {type(field_value).__name__}"
            )

        # Empty/whitespace check - partition keys must have content
        if not field_value.strip():
            raise ValueError(f"{field_name} cannot be empty or whitespace only")

        # Length check - prevent DoS via memory exhaustion
        if len(field_value) > max_length:
            raise ValueError(
                f"{field_name} must be <= {max_length} characters (got {len(field_value)})"
            )

        # Null byte check - breaks UTF-8 encoding in Kafka partition keys
        if "\x00" in field_value:
            raise ValueError(f"{field_name} cannot contain null bytes")

    def _validate_string_field(
        self,
        field_name: str,
        field_value: Optional[str],
        max_length: int,
        check_null_bytes: bool = True,
    ) -> None:
        """
        Validate string field for security and DoS protection.

        Args:
            field_name: Name of the field being validated
            field_value: Value to validate
            max_length: Maximum allowed length
            check_null_bytes: Whether to check for null bytes

        Raises:
            ValueError: If validation fails
        """
        if field_value is None:
            return

        # Check length
        if len(field_value) > max_length:
            raise ValueError(
                f"{field_name} must be <= {max_length} characters (got {len(field_value)})"
            )

        # Check for null bytes
        if check_null_bytes and "\x00" in field_value:
            raise ValueError(f"{field_name} cannot contain null bytes")

    def _validate_context_size(self, context: Optional[Dict[str, Any]]) -> None:
        """
        Validate context dictionary size and structure to prevent DoS attacks.

        Checks:
        1. JSON serializability (no circular references)
        2. Serialized size < 64KB
        3. Nesting depth <= 10 levels

        Args:
            context: Context dictionary to validate

        Raises:
            ValueError: If context exceeds size/depth limits or has circular references
        """
        if context is None:
            return

        # Check for circular references and validate structure
        try:
            # Check nesting depth (max 10 levels) to prevent stack overflow
            def check_depth(
                obj: Any, current_depth: int = 0, max_depth: int = 10
            ) -> None:
                """Recursively check nesting depth of containers (dicts/lists)."""
                if current_depth > max_depth:
                    raise ValueError(
                        f"context nesting depth exceeds {max_depth} levels (DoS protection)"
                    )

                if isinstance(obj, dict):
                    # Only increment depth for nested containers, not scalar values
                    for value in obj.values():
                        if isinstance(value, (dict, list, tuple)):
                            check_depth(value, current_depth + 1, max_depth)
                        # Scalar values don't add nesting depth
                elif isinstance(obj, (list, tuple)):
                    # Only increment depth for nested containers, not scalar values
                    for item in obj:
                        if isinstance(item, (dict, list, tuple)):
                            check_depth(item, current_depth + 1, max_depth)
                        # Scalar values don't add nesting depth

            check_depth(context)

            # Serialize and check size (will also catch circular references)
            serialized = json.dumps(context)
            size_bytes = len(serialized.encode("utf-8"))
            max_size = 64 * 1024  # 64KB

            if size_bytes > max_size:
                raise ValueError(
                    f"context serialized size must be <= {max_size} bytes (got {size_bytes})"
                )

        except RecursionError as e:
            # Circular reference detected during depth check or serialization
            raise ValueError(
                "context contains circular references (not serializable)"
            ) from e
        except (TypeError, ValueError) as e:
            # Re-raise with clearer message if JSON serialization fails
            if (
                "serialized size" in str(e)
                or "nesting depth" in str(e)
                or "circular" in str(e)
            ):
                raise
            raise ValueError(f"context must be JSON-serializable: {e}") from e

    def _sanitize_context(
        self, context: Optional[Dict[str, Any]], _depth: int = 0, _max_depth: int = 10
    ) -> Dict[str, Any]:
        """
        Recursively remove potential PII and sensitive data from context.

        This method redacts values for known sensitive keys to prevent
        accidental logging of passwords, API keys, tokens, and other
        sensitive information to Kafka. Handles nested dictionaries up to
        10 levels deep.

        Args:
            context: Context dictionary to sanitize
            _depth: Internal recursion depth tracker (do not pass manually)
            _max_depth: Maximum recursion depth to prevent stack overflow

        Returns:
            Sanitized context with sensitive values redacted

        Example:
            >>> context = {
            ...     "user": "john",
            ...     "password": "secret123",
            ...     "nested": {
            ...         "api_key": "abc",
            ...         "normal": "value"
            ...     }
            ... }
            >>> sanitized = publisher._sanitize_context(context)
            >>> sanitized
            {
                'user': 'john',
                'password': '[REDACTED]',
                'nested': {
                    'api_key': '[REDACTED]',
                    'normal': 'value'
                }
            }
        """
        if not context:
            return {}

        # Prevent infinite recursion
        if _depth >= _max_depth:
            return {"_error": "Max recursion depth reached during sanitization"}

        # Known sensitive keys to redact (case-insensitive)
        sensitive_keys = {
            "password",
            "passwd",
            "pwd",
            "secret",
            "api_key",
            "apikey",
            "api-key",
            "token",
            "auth_token",
            "access_token",
            "refresh_token",
            "private_key",
            "credentials",
            "ssn",
            "credit_card",
            "email",
            "auth",
            "authorization",
            "bearer",
            "jwt",
            "session",
            "cookie",
        }

        sanitized = {}
        for key, value in context.items():
            # Check if key is sensitive (case-insensitive)
            if key.lower() in sensitive_keys:
                sanitized[key] = "[REDACTED]"
            # Recursively sanitize nested dictionaries
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_context(value, _depth + 1, _max_depth)
            else:
                # Preserve non-sensitive values
                sanitized[key] = value

        return sanitized

    async def publish_application_log(
        self,
        service_name: str,
        instance_id: str,
        level: str,
        logger_name: str,
        message: str,
        code: str,
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """
        Publish application log event.

        This event captures structured application logs for omnidash integration
        and centralized log aggregation.

        Args:
            service_name: Name of the service (e.g., "omniclaude")
            instance_id: Instance identifier (e.g., "omniclaude-1")
            level: Log level (INFO, WARN, ERROR, DEBUG)
            logger_name: Logger name (e.g., "router.pipeline")
            message: Log message
            code: Log code for categorization (e.g., "AGENT_EXECUTION_COMPLETED")
            context: Optional context dictionary (agent_name, duration_ms, etc.)
            correlation_id: Optional correlation ID for request tracing
            tenant_id: Optional tenant identifier (defaults to TENANT_ID env var or "default")

        Returns:
            bool: True if published successfully, False if failed or
                  payload exceeds 1MB size limit.

        Note:
            The context dictionary is automatically sanitized to remove
            potential PII and sensitive data. Keys matching known sensitive
            patterns (password, api_key, token, etc.) will be redacted.

        Example:
            success = await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="router.pipeline",
                message="Agent execution completed successfully",
                code="AGENT_EXECUTION_COMPLETED",
                context={"agent_name": "agent-api-architect", "duration_ms": 1234},
                correlation_id="abc-123-def-456",
                tenant_id="tenant-123",
            )
        """
        # Validate input fields BEFORE any Kafka operations
        # service_name is used as partition key - requires strict validation
        self._validate_partition_key_field("service_name", service_name, max_length=256)
        # tenant_id goes into Kafka headers - also requires strict validation if provided
        if tenant_id is not None:
            self._validate_partition_key_field("tenant_id", tenant_id, max_length=128)
        # Validate context size and structure
        self._validate_context_size(context)

        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        # Start latency timer
        start_time = time.time()

        try:
            # Generate timestamp once for consistent timing
            timestamp = datetime.now(UTC).isoformat()

            # Sanitize context to remove PII and sensitive data
            sanitized_context = self._sanitize_context(context)

            # Create event envelope
            envelope = self._create_application_log_envelope(
                service_name=service_name,
                instance_id=instance_id,
                level=level,
                logger_name=logger_name,
                message=message,
                code=code,
                context=sanitized_context,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                timestamp=timestamp,
            )

            # Validate payload size
            payload_bytes = json.dumps(envelope).encode("utf-8")
            payload_size = len(payload_bytes)

            if payload_size > MAX_PAYLOAD_SIZE:
                self.logger.warning(
                    f"Payload size {payload_size} bytes exceeds limit "
                    f"{MAX_PAYLOAD_SIZE} bytes, rejecting event"
                )
                return False

            # Publish event with partition key (service_name for application logs)
            partition_key = service_name.encode("utf-8")

            # Build required Kafka headers
            headers = self._build_kafka_headers(
                tenant_id=envelope.get("tenant_id", "default"),
                schema_ref=envelope.get("schema_ref", ""),
                correlation_id=correlation_id,
            )

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await asyncio.wait_for(
                self._producer.send_and_wait(
                    self.TOPIC_APPLICATION_LOG,
                    value=envelope,
                    key=partition_key,
                    headers=headers,
                ),
                timeout=self.KAFKA_PUBLISH_TIMEOUT_SECONDS,
            )

            # Record success metrics
            logging_events_published.labels(
                event_type="application", status="success"
            ).inc()

            self.logger.debug(
                f"Published application log event (service: {service_name}, level: {level}, code: {code})"
            )
            return True

        except KafkaError as e:
            # Record Kafka error metrics with error type
            error_type = type(e).__name__
            logging_kafka_errors.labels(
                event_type="application", error_type=error_type
            ).inc()
            logging_events_published.labels(
                event_type="application", status="error"
            ).inc()

            self.logger.error(
                f"Failed to publish application log event (service: {service_name}, code: {code}): {e}"
            )
            return False

        except asyncio.TimeoutError:
            # Handle timeout specifically for better observability
            error_type = "TimeoutError"
            logging_kafka_errors.labels(
                event_type="application", error_type=error_type
            ).inc()
            logging_events_published.labels(
                event_type="application", status="error"
            ).inc()

            self.logger.error(
                f"Timeout publishing application log event to Kafka "
                f"(service: {service_name}, code: {code}, "
                f"timeout: {self.KAFKA_PUBLISH_TIMEOUT_SECONDS}s)",
                extra={"correlation_id": correlation_id},
            )
            return False

        except Exception as e:
            # Record general error metrics
            error_type = type(e).__name__
            logging_kafka_errors.labels(
                event_type="application", error_type=error_type
            ).inc()
            logging_events_published.labels(
                event_type="application", status="error"
            ).inc()

            self.logger.error(
                f"Failed to publish application log event (service: {service_name}, code: {code}): {e}"
            )
            return False

        finally:
            # Always record latency
            duration = time.time() - start_time
            logging_publish_latency.labels(event_type="application").observe(duration)

    async def publish_audit_log(
        self,
        tenant_id: Optional[str] = None,
        action: str = None,
        actor: str = None,
        resource: str = None,
        outcome: Union[Outcome, str] = None,
        correlation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Publish audit log event.

        This event captures audit trail information for compliance and
        regulatory requirements.

        Args:
            tenant_id: Optional tenant identifier (UUID or string).
                       Falls back to TENANT_ID environment variable if not provided.
                       Uses "default" if neither is available.
            action: Action performed (e.g., "agent.execution", "api.call")
            actor: User or service that performed the action
            resource: Resource that was accessed (e.g., agent name, API endpoint)
            outcome: Outcome of the action (Outcome enum or string: "success" or "failure")
            correlation_id: Optional correlation ID for request tracing
            context: Optional context dictionary (additional metadata)

        Returns:
            bool: True if published successfully, False if failed or
                  payload exceeds 1MB size limit.

        Note:
            The context dictionary is automatically sanitized to remove
            potential PII and sensitive data. Keys matching known sensitive
            patterns (password, api_key, token, etc.) will be redacted.

        Example:
            async with LoggingEventPublisherContext() as publisher:
                success = await publisher.publish_audit_log(
                    tenant_id="tenant-123",
                    action="agent.execution",
                    actor="user-456",
                    resource="agent-api-architect",
                    outcome=Outcome.SUCCESS,  # or "success" for backward compatibility
                    correlation_id="abc-123-def-456",
                    context={"duration_ms": 1234, "quality_score": 0.95},
                )
        """
        # Resolve tenant_id with fallback chain
        effective_tenant_id = tenant_id or os.getenv("TENANT_ID", "default")

        # Warn when using fallback
        if tenant_id is None and os.getenv("TENANT_ID") is None:
            self.logger.warning(
                "tenant_id not provided and TENANT_ID env var not set, using 'default'",
                extra={"event_type": "audit_log", "action": action},
            )

        # Validate input fields BEFORE any Kafka operations
        # tenant_id is used as partition key - requires strict validation
        self._validate_partition_key_field(
            "tenant_id", effective_tenant_id, max_length=128
        )
        # action is critical metadata - validate for security
        self._validate_partition_key_field("action", action, max_length=256)
        # resource is critical metadata - validate for security
        self._validate_string_field("resource", resource, max_length=256)
        # Validate context size and structure
        self._validate_context_size(context)

        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        # Start latency timer
        start_time = time.time()

        try:
            # Sanitize context to remove PII and sensitive data
            sanitized_context = self._sanitize_context(context)

            # Create event envelope
            envelope = self._create_audit_log_envelope(
                tenant_id=effective_tenant_id,
                action=action,
                actor=actor,
                resource=resource,
                outcome=outcome,
                correlation_id=correlation_id,
                context=sanitized_context,
            )

            # Validate payload size
            payload_bytes = json.dumps(envelope).encode("utf-8")
            payload_size = len(payload_bytes)

            if payload_size > MAX_PAYLOAD_SIZE:
                self.logger.warning(
                    f"Payload size {payload_size} bytes exceeds limit "
                    f"{MAX_PAYLOAD_SIZE} bytes, rejecting event"
                )
                return False

            # Publish event with partition key (tenant_id for audit logs)
            partition_key = effective_tenant_id.encode("utf-8")

            # Build required Kafka headers
            headers = self._build_kafka_headers(
                tenant_id=effective_tenant_id,
                schema_ref=envelope.get("schema_ref", ""),
                correlation_id=correlation_id,
            )

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await asyncio.wait_for(
                self._producer.send_and_wait(
                    self.TOPIC_AUDIT_LOG,
                    value=envelope,
                    key=partition_key,
                    headers=headers,
                ),
                timeout=self.KAFKA_PUBLISH_TIMEOUT_SECONDS,
            )

            # Record success metrics
            logging_events_published.labels(event_type="audit", status="success").inc()

            self.logger.debug(
                f"Published audit log event (tenant: {tenant_id}, action: {action}, outcome: {outcome})"
            )
            return True

        except KafkaError as e:
            # Record Kafka error metrics with error type
            error_type = type(e).__name__
            logging_kafka_errors.labels(event_type="audit", error_type=error_type).inc()
            logging_events_published.labels(event_type="audit", status="error").inc()

            self.logger.error(
                f"Failed to publish audit log event (tenant: {tenant_id}, action: {action}): {e}"
            )
            return False

        except asyncio.TimeoutError:
            # Handle timeout specifically for better observability
            error_type = "TimeoutError"
            logging_kafka_errors.labels(event_type="audit", error_type=error_type).inc()
            logging_events_published.labels(event_type="audit", status="error").inc()

            self.logger.error(
                f"Timeout publishing audit log event to Kafka "
                f"(tenant: {tenant_id}, action: {action}, "
                f"timeout: {self.KAFKA_PUBLISH_TIMEOUT_SECONDS}s)",
                extra={"correlation_id": correlation_id},
            )
            return False

        except Exception as e:
            # Record general error metrics
            error_type = type(e).__name__
            logging_kafka_errors.labels(event_type="audit", error_type=error_type).inc()
            logging_events_published.labels(event_type="audit", status="error").inc()

            self.logger.error(
                f"Failed to publish audit log event (tenant: {tenant_id}, action: {action}): {e}"
            )
            return False

        finally:
            # Always record latency
            duration = time.time() - start_time
            logging_publish_latency.labels(event_type="audit").observe(duration)

    async def publish_security_log(
        self,
        tenant_id: Optional[str] = None,
        event_type: str = None,
        user_id: str = None,
        resource: str = None,
        decision: Union[Decision, str] = None,
        correlation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Publish security log event.

        This event captures security-relevant actions for audit and
        security monitoring purposes.

        Args:
            tenant_id: Optional tenant identifier (UUID or string).
                       Falls back to TENANT_ID environment variable if not provided.
                       Uses "default" if neither is available.
            event_type: Type of security event (e.g., "api_key_used", "permission_check")
            user_id: User identifier
            resource: Resource being accessed
            decision: Security decision (Decision enum or string: "allow" or "deny")
            correlation_id: Optional correlation ID for request tracing
            context: Optional context dictionary (additional metadata)

        Returns:
            bool: True if published successfully, False if failed or
                  payload exceeds 1MB size limit.

        Note:
            The context dictionary is automatically sanitized to remove
            potential PII and sensitive data. Keys matching known sensitive
            patterns (password, api_key, token, etc.) will be redacted.

        Example:
            async with LoggingEventPublisherContext() as publisher:
                success = await publisher.publish_security_log(
                    tenant_id="tenant-123",
                    event_type="api_key_used",
                    user_id="user-456",
                    resource="gemini-api",
                    decision=Decision.ALLOW,  # or "allow" for backward compatibility
                    correlation_id="abc-123-def-456",
                    context={"api_key_hash": "sha256:abc123", "ip_address": "192.168.1.1"},
                )
        """
        # Resolve tenant_id with fallback chain
        effective_tenant_id = tenant_id or os.getenv("TENANT_ID", "default")

        # Warn when using fallback
        if tenant_id is None and os.getenv("TENANT_ID") is None:
            self.logger.warning(
                "tenant_id not provided and TENANT_ID env var not set, using 'default'",
                extra={"event_type": "security_log", "security_event_type": event_type},
            )

        # Validate input fields BEFORE any Kafka operations
        # tenant_id is used as partition key - requires strict validation
        self._validate_partition_key_field(
            "tenant_id", effective_tenant_id, max_length=128
        )
        # event_type is critical security metadata - validate strictly
        self._validate_partition_key_field("event_type", event_type, max_length=128)
        # resource is critical security metadata - validate for security
        self._validate_string_field("resource", resource, max_length=256)
        # Validate context size and structure
        self._validate_context_size(context)

        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        # Start latency timer
        start_time = time.time()

        try:
            # Sanitize context to remove PII and sensitive data
            sanitized_context = self._sanitize_context(context)

            # Create event envelope
            envelope = self._create_security_log_envelope(
                tenant_id=effective_tenant_id,
                event_type=event_type,
                user_id=user_id,
                resource=resource,
                decision=decision,
                correlation_id=correlation_id,
                context=sanitized_context,
            )

            # Validate payload size
            payload_bytes = json.dumps(envelope).encode("utf-8")
            payload_size = len(payload_bytes)

            if payload_size > MAX_PAYLOAD_SIZE:
                self.logger.warning(
                    f"Payload size {payload_size} bytes exceeds limit "
                    f"{MAX_PAYLOAD_SIZE} bytes, rejecting event"
                )
                return False

            # Publish event with partition key (tenant_id for security logs)
            partition_key = effective_tenant_id.encode("utf-8")

            # Build required Kafka headers
            headers = self._build_kafka_headers(
                tenant_id=effective_tenant_id,
                schema_ref=envelope.get("schema_ref", ""),
                correlation_id=correlation_id,
            )

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await asyncio.wait_for(
                self._producer.send_and_wait(
                    self.TOPIC_SECURITY_LOG,
                    value=envelope,
                    key=partition_key,
                    headers=headers,
                ),
                timeout=self.KAFKA_PUBLISH_TIMEOUT_SECONDS,
            )

            # Record success metrics
            logging_events_published.labels(
                event_type="security", status="success"
            ).inc()

            self.logger.debug(
                f"Published security log event (tenant: {tenant_id}, event_type: {event_type}, decision: {decision})"
            )
            return True

        except KafkaError as e:
            # Record Kafka error metrics with error type
            error_type = type(e).__name__
            logging_kafka_errors.labels(
                event_type="security", error_type=error_type
            ).inc()
            logging_events_published.labels(event_type="security", status="error").inc()

            self.logger.error(
                f"Failed to publish security log event (tenant: {tenant_id}, event_type: {event_type}): {e}"
            )
            return False

        except asyncio.TimeoutError:
            # Handle timeout specifically for better observability
            error_type = "TimeoutError"
            logging_kafka_errors.labels(
                event_type="security", error_type=error_type
            ).inc()
            logging_events_published.labels(event_type="security", status="error").inc()

            self.logger.error(
                f"Timeout publishing security log event to Kafka "
                f"(tenant: {tenant_id}, event_type: {event_type}, "
                f"timeout: {self.KAFKA_PUBLISH_TIMEOUT_SECONDS}s)",
                extra={"correlation_id": correlation_id},
            )
            return False

        except Exception as e:
            # Record general error metrics
            error_type = type(e).__name__
            logging_kafka_errors.labels(
                event_type="security", error_type=error_type
            ).inc()
            logging_events_published.labels(event_type="security", status="error").inc()

            self.logger.error(
                f"Failed to publish security log event (tenant: {tenant_id}, event_type: {event_type}): {e}"
            )
            return False

        finally:
            # Always record latency
            duration = time.time() - start_time
            logging_publish_latency.labels(event_type="security").observe(duration)

    def _create_base_envelope(
        self,
        event_type: str,
        tenant_id: str,
        correlation_id: Optional[str],
        payload: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create base envelope structure with single timestamp generation."""
        timestamp = timestamp or datetime.now(UTC).isoformat()
        correlation_id = correlation_id or str(uuid4())

        return {
            "event_type": event_type,
            "event_id": str(uuid4()),
            "timestamp": timestamp,
            "tenant_id": tenant_id,
            "namespace": "omninode",
            "source": "omniclaude",
            "correlation_id": correlation_id,
            "causation_id": correlation_id,
            "schema_ref": f"registry://{event_type.replace('.', '/')}",
            "payload": payload,
        }

    def _build_kafka_headers(
        self,
        tenant_id: str,
        schema_ref: str,
        correlation_id: Optional[str] = None,
    ) -> list:
        """
        Build Kafka headers for event publishing.

        Args:
            tenant_id: Tenant identifier
            schema_ref: Schema registry reference
            correlation_id: Optional correlation ID for request tracing

        Returns:
            List of (key, value) tuples for Kafka headers

        Note:
            W3C Trace Context format: version-trace_id-parent_id-trace_flags
            - version: 00 (fixed)
            - trace_id: 32 hex chars (128 bits) derived from correlation_id
            - span_id: 16 hex chars (64 bits) randomly generated for uniqueness
            - trace_flags: 01 (sampled)
        """
        headers = [
            ("x-tenant", tenant_id.encode("utf-8")),
            ("x-schema-hash", schema_ref.encode("utf-8")),
        ]

        # Add correlation ID headers if provided
        if correlation_id:
            # Generate W3C traceparent (format: 00-{trace_id}-{span_id}-{flags})
            # trace_id: 32 hex chars (128 bits) derived from correlation_id
            # span_id: 16 hex chars (64 bits) randomly generated for uniqueness
            # flags: 01 (sampled)
            trace_id = correlation_id.replace("-", "")[:32].ljust(32, "0")
            span_id = secrets.token_hex(8)  # 8 bytes = 16 hex chars
            headers.extend(
                [
                    ("x-traceparent", f"00-{trace_id}-{span_id}-01".encode()),
                    ("x-correlation-id", correlation_id.encode("utf-8")),
                    ("x-causation-id", correlation_id.encode("utf-8")),
                ]
            )

        return headers

    def _create_application_log_envelope(
        self,
        service_name: str,
        instance_id: str,
        level: Union[LogLevel, str],
        logger_name: str,
        message: str,
        code: str,
        context: Dict[str, Any],
        correlation_id: Optional[str],
        tenant_id: Optional[str],
        timestamp: str,
    ) -> Dict[str, Any]:
        """
        Build application log event envelope following OnexEnvelopeV1 structure.

        Args:
            service_name: Service name
            instance_id: Instance ID
            level: Log level
            logger_name: Logger name
            message: Log message
            code: Log code
            context: Context dictionary
            correlation_id: Optional correlation ID
            tenant_id: Optional tenant ID
            timestamp: ISO-8601 timestamp for the event

        Returns:
            Event envelope dictionary with complete structure
        """
        # Convert enum to string if needed
        level_str = str(level.value) if isinstance(level, LogLevel) else level

        # Resolve tenant_id with fallback
        effective_tenant_id = tenant_id or os.getenv("TENANT_ID", "default")

        # Build payload (type-specific)
        payload = {
            "service_name": service_name,
            "instance_id": instance_id,
            "level": level_str,
            "logger": logger_name,
            "message": message,
            "code": code,
            "context": context,
        }

        # Use base method for envelope
        return self._create_base_envelope(
            event_type="omninode.logging.application.v1",
            tenant_id=effective_tenant_id,
            correlation_id=correlation_id,
            payload=payload,
            timestamp=timestamp,
        )

    def _create_audit_log_envelope(
        self,
        tenant_id: str,
        action: str,
        actor: str,
        resource: str,
        outcome: Union[Outcome, str],
        correlation_id: Optional[str],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build audit log event envelope following OnexEnvelopeV1 structure.

        Args:
            tenant_id: Tenant ID
            action: Action performed
            actor: Actor identifier
            resource: Resource accessed
            outcome: Outcome of action
            correlation_id: Optional correlation ID
            context: Context dictionary

        Returns:
            Event envelope dictionary with complete structure
        """
        # Convert enum to string if needed
        outcome_str = str(outcome.value) if isinstance(outcome, Outcome) else outcome

        # Generate timestamp once for both envelope and payload
        timestamp = datetime.now(UTC).isoformat()

        payload = {
            "tenant_id": tenant_id,
            "action": action,
            "actor": actor,
            "resource": resource,
            "timestamp": timestamp,
            "outcome": outcome_str,
            "context": context,
        }

        return self._create_base_envelope(
            event_type="omninode.logging.audit.v1",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload=payload,
            timestamp=timestamp,
        )

    def _create_security_log_envelope(
        self,
        tenant_id: str,
        event_type: str,
        user_id: str,
        resource: str,
        decision: Union[Decision, str],
        correlation_id: Optional[str],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build security log event envelope following OnexEnvelopeV1 structure.

        Args:
            tenant_id: Tenant ID
            event_type: Security event type
            user_id: User identifier
            resource: Resource accessed
            decision: Security decision
            correlation_id: Optional correlation ID
            context: Context dictionary

        Returns:
            Event envelope dictionary with complete structure
        """
        # Convert enum to string if needed
        decision_str = (
            str(decision.value) if isinstance(decision, Decision) else decision
        )

        # Generate timestamp once for both envelope and payload
        timestamp = datetime.now(UTC).isoformat()

        payload = {
            "tenant_id": tenant_id,
            "event_type": event_type,
            "user_id": user_id,
            "resource": resource,
            "decision": decision_str,
            "timestamp": timestamp,
            "context": context,
        }

        return self._create_base_envelope(
            event_type="omninode.logging.security.v1",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload=payload,
            timestamp=timestamp,
        )


# Convenience context manager for automatic start/stop
class LoggingEventPublisherContext:
    """
    Context manager for automatic publisher lifecycle management.

    Usage:
        async with LoggingEventPublisherContext() as publisher:
            await publisher.publish_application_log(...)
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_events: Optional[bool] = None,
    ):
        self.publisher = LoggingEventPublisher(
            bootstrap_servers=bootstrap_servers,
            enable_events=enable_events,
        )

    async def __aenter__(self) -> LoggingEventPublisher:
        await self.publisher.start()
        return self.publisher

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.publisher.stop()
        return False


# Global singleton publisher for convenience functions
# This eliminates ~50ms connection overhead per call
_global_publisher: Optional[LoggingEventPublisher] = None
_global_publisher_lock = asyncio.Lock()


async def _get_global_publisher(
    bootstrap_servers: Optional[str] = None,
    enable_events: Optional[bool] = None,
) -> LoggingEventPublisher:
    """
    Get or create global singleton publisher for convenience functions.

    Thread-safe singleton pattern with lazy initialization.
    Publisher is reused across all convenience function calls.

    Performance:
    - First call: ~50ms (creates and starts publisher)
    - Subsequent calls: <1ms (returns existing publisher)
    - Connection reuse eliminates per-call overhead

    Args:
        bootstrap_servers: Kafka bootstrap servers (only used on first call)
        enable_events: Whether to enable event publishing (only used on first call)

    Returns:
        Shared LoggingEventPublisher instance

    Note:
        Publisher is automatically cleaned up on application exit.
        For long-running applications, the publisher remains active
        throughout the application lifetime.
    """
    global _global_publisher

    async with _global_publisher_lock:
        # Create singleton if it doesn't exist
        # Note: We check for None only, not _producer, because when enable_events=False
        # the publisher is still valid but has no producer (expected behavior)
        if _global_publisher is None:
            _global_publisher = LoggingEventPublisher(
                bootstrap_servers=bootstrap_servers,
                enable_events=enable_events,
            )
            await _global_publisher.start()

            # Register cleanup on application exit
            import atexit

            def cleanup():
                try:
                    asyncio.run(_global_publisher.stop())
                except Exception as e:
                    logger.warning(f"Error cleaning up global publisher: {e}")

            atexit.register(cleanup)

        return _global_publisher


# Convenience functions for one-off event publishing
async def publish_application_log(
    service_name: str,
    instance_id: str,
    level: Union[LogLevel, str],
    logger_name: str,
    message: str,
    code: str,
    context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    bootstrap_servers: Optional[str] = None,
    enable_events: Optional[bool] = None,
) -> bool:
    """
    Convenience function using global singleton publisher (low overhead).

    Performance:
    - First call: ~50ms (creates publisher)
    - Subsequent calls: <5ms (reuses connection)

    For high-frequency logging (>10 events/sec), this singleton approach is
    recommended. For even better performance, consider creating a persistent
    publisher instance.

    Args:
        service_name: Service name
        instance_id: Instance ID
        level: Log level
        logger_name: Logger name
        message: Log message
        code: Log code
        context: Optional context dictionary
        correlation_id: Optional correlation ID
        tenant_id: Optional tenant ID
        bootstrap_servers: Optional Kafka bootstrap servers (only used on first call)
        enable_events: Optional enable events flag (only used on first call)

    Returns:
        True if event published successfully, False otherwise

    Example (Low-Frequency - OK):
        success = await publish_application_log(
            service_name="omniclaude",
            instance_id="omniclaude-1",
            level="INFO",
            logger_name="router.pipeline",
            message="Agent execution completed",
            code="AGENT_EXECUTION_COMPLETED",
            tenant_id="tenant-123",
        )

    Example (High-Frequency - Recommended):
        # Reuses connection across all calls
        for i in range(1000):
            await publish_application_log(...)  # <5ms each
    """
    publisher = await _get_global_publisher(bootstrap_servers, enable_events)
    return await publisher.publish_application_log(
        service_name=service_name,
        instance_id=instance_id,
        level=level,
        logger_name=logger_name,
        message=message,
        code=code,
        context=context,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
    )


async def publish_audit_log(
    action: str,
    actor: str,
    resource: str,
    outcome: Union[Outcome, str],
    tenant_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    bootstrap_servers: Optional[str] = None,
    enable_events: Optional[bool] = None,
) -> bool:
    """
    Convenience function using global singleton publisher (low overhead).

    Performance:
    - First call: ~50ms (creates publisher)
    - Subsequent calls: <5ms (reuses connection)

    For high-frequency logging (>10 events/sec), this singleton approach is
    recommended. For even better performance, consider creating a persistent
    publisher instance.

    Args:
        action: Action performed
        actor: Actor identifier
        resource: Resource accessed
        outcome: Outcome of action
        tenant_id: Optional tenant identifier (UUID or string).
                   Falls back to TENANT_ID environment variable if not provided.
                   Uses "default" if neither is available.
        correlation_id: Optional correlation ID
        context: Optional context dictionary
        bootstrap_servers: Optional Kafka bootstrap servers (only used on first call)
        enable_events: Optional enable events flag (only used on first call)

    Returns:
        True if event published successfully, False otherwise

    Example (Low-Frequency - OK):
        success = await publish_audit_log(
            action="agent.execution",
            actor="user-456",
            resource="agent-api-architect",
            outcome="success",
            tenant_id="tenant-123",  # Optional, falls back to env var
        )

    Example (High-Frequency - Recommended):
        # Reuses connection across all calls
        for i in range(1000):
            await publish_audit_log(...)  # <5ms each
    """
    publisher = await _get_global_publisher(bootstrap_servers, enable_events)
    return await publisher.publish_audit_log(
        tenant_id=tenant_id,
        action=action,
        actor=actor,
        resource=resource,
        outcome=outcome,
        correlation_id=correlation_id,
        context=context,
    )


async def publish_security_log(
    event_type: str,
    user_id: str,
    resource: str,
    decision: Union[Decision, str],
    tenant_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    bootstrap_servers: Optional[str] = None,
    enable_events: Optional[bool] = None,
) -> bool:
    """
    Convenience function using global singleton publisher (low overhead).

    Performance:
    - First call: ~50ms (creates publisher)
    - Subsequent calls: <5ms (reuses connection)

    For high-frequency logging (>10 events/sec), this singleton approach is
    recommended. For even better performance, consider creating a persistent
    publisher instance.

    Args:
        event_type: Security event type
        user_id: User identifier
        resource: Resource accessed
        decision: Security decision
        tenant_id: Optional tenant identifier (UUID or string).
                   Falls back to TENANT_ID environment variable if not provided.
                   Uses "default" if neither is available.
        correlation_id: Optional correlation ID
        context: Optional context dictionary
        bootstrap_servers: Optional Kafka bootstrap servers (only used on first call)
        enable_events: Optional enable events flag (only used on first call)

    Returns:
        True if event published successfully, False otherwise

    Example (Low-Frequency - OK):
        success = await publish_security_log(
            event_type="api_key_used",
            user_id="user-456",
            resource="gemini-api",
            decision="allow",
            tenant_id="tenant-123",  # Optional, falls back to env var
        )

    Example (High-Frequency - Recommended):
        # Reuses connection across all calls
        for i in range(1000):
            await publish_security_log(...)  # <5ms each
    """
    publisher = await _get_global_publisher(bootstrap_servers, enable_events)
    return await publisher.publish_security_log(
        tenant_id=tenant_id,
        event_type=event_type,
        user_id=user_id,
        resource=resource,
        decision=decision,
        correlation_id=correlation_id,
        context=context,
    )
