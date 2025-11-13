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

Performance Targets:
- Publish time: <10ms p95
- Memory overhead: <10MB
- Success rate: >99%
- Non-blocking: Never blocks application execution

Created: 2025-11-13
Reference: EVENT_ALIGNMENT_PLAN.md Phase 2 (Tasks 2.1, 2.2, 2.3)
          EVENT_BUS_INTEGRATION_GUIDE.md (event structure standards)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from config import settings

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_events: bool = True,
    ):
        """
        Initialize logging event publisher.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - External host: "localhost:9092" or "192.168.86.200:9092"
                - Docker internal: "omninode-bridge-redpanda:9092"
            enable_events: Enable event publishing (feature flag)
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
            self.logger.info("Logging event publisher started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start logging event publisher: {e}")
            await self.stop()
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
            self.logger.info("Logging event publisher stopped successfully")

        except Exception as e:
            self.logger.error(f"Error stopping logging event publisher: {e}")

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

        Returns:
            True if event published successfully, False otherwise

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
            )
        """
        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        try:
            # Create event envelope
            envelope = self._create_application_log_envelope(
                service_name=service_name,
                instance_id=instance_id,
                level=level,
                logger_name=logger_name,
                message=message,
                code=code,
                context=context or {},
                correlation_id=correlation_id,
            )

            # Publish event with partition key (service_name for application logs)
            partition_key = service_name.encode("utf-8")

            # Build required Kafka headers
            headers = [
                ("x-tenant", envelope.get("tenant_id", "default").encode("utf-8")),
                ("x-schema-hash", envelope.get("schema_ref", "").encode("utf-8")),
            ]

            # Add correlation ID to headers if provided
            if correlation_id:
                headers.extend(
                    [
                        (
                            "x-traceparent",
                            f"00-{correlation_id.replace('-', '')}-0000000000000000-01".encode(),
                        ),
                        ("x-correlation-id", correlation_id.encode("utf-8")),
                        ("x-causation-id", correlation_id.encode("utf-8")),
                    ]
                )

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await self._producer.send_and_wait(
                self.TOPIC_APPLICATION_LOG,
                value=envelope,
                key=partition_key,
                headers=headers,
            )

            self.logger.debug(
                f"Published application log event (service: {service_name}, level: {level}, code: {code})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to publish application log event (service: {service_name}, code: {code}): {e}"
            )
            return False

    async def publish_audit_log(
        self,
        tenant_id: str,
        action: str,
        actor: str,
        resource: str,
        outcome: str,
        correlation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Publish audit log event.

        This event captures audit trail information for compliance and
        regulatory requirements.

        Args:
            tenant_id: Tenant identifier (UUID or string)
            action: Action performed (e.g., "agent.execution", "api.call")
            actor: User or service that performed the action
            resource: Resource that was accessed (e.g., agent name, API endpoint)
            outcome: Outcome of the action ("success" or "failure")
            correlation_id: Optional correlation ID for request tracing
            context: Optional context dictionary (additional metadata)

        Returns:
            True if event published successfully, False otherwise

        Example:
            success = await publisher.publish_audit_log(
                tenant_id="tenant-123",
                action="agent.execution",
                actor="user-456",
                resource="agent-api-architect",
                outcome="success",
                correlation_id="abc-123-def-456",
                context={"duration_ms": 1234, "quality_score": 0.95},
            )
        """
        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        try:
            # Create event envelope
            envelope = self._create_audit_log_envelope(
                tenant_id=tenant_id,
                action=action,
                actor=actor,
                resource=resource,
                outcome=outcome,
                correlation_id=correlation_id,
                context=context or {},
            )

            # Publish event with partition key (tenant_id for audit logs)
            partition_key = tenant_id.encode("utf-8")

            # Build required Kafka headers
            headers = [
                ("x-tenant", tenant_id.encode("utf-8")),
                ("x-schema-hash", envelope.get("schema_ref", "").encode("utf-8")),
            ]

            # Add correlation ID to headers if provided
            if correlation_id:
                headers.extend(
                    [
                        (
                            "x-traceparent",
                            f"00-{correlation_id.replace('-', '')}-0000000000000000-01".encode(),
                        ),
                        ("x-correlation-id", correlation_id.encode("utf-8")),
                        ("x-causation-id", correlation_id.encode("utf-8")),
                    ]
                )

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await self._producer.send_and_wait(
                self.TOPIC_AUDIT_LOG,
                value=envelope,
                key=partition_key,
                headers=headers,
            )

            self.logger.debug(
                f"Published audit log event (tenant: {tenant_id}, action: {action}, outcome: {outcome})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to publish audit log event (tenant: {tenant_id}, action: {action}): {e}"
            )
            return False

    async def publish_security_log(
        self,
        tenant_id: str,
        event_type: str,
        user_id: str,
        resource: str,
        decision: str,
        correlation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Publish security log event.

        This event captures security-relevant actions for audit and
        security monitoring purposes.

        Args:
            tenant_id: Tenant identifier (UUID or string)
            event_type: Type of security event (e.g., "api_key_used", "permission_check")
            user_id: User identifier
            resource: Resource being accessed
            decision: Security decision ("allow" or "deny")
            correlation_id: Optional correlation ID for request tracing
            context: Optional context dictionary (additional metadata)

        Returns:
            True if event published successfully, False otherwise

        Example:
            success = await publisher.publish_security_log(
                tenant_id="tenant-123",
                event_type="api_key_used",
                user_id="user-456",
                resource="gemini-api",
                decision="allow",
                correlation_id="abc-123-def-456",
                context={"api_key_hash": "sha256:abc123", "ip_address": "192.168.1.1"},
            )
        """
        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        try:
            # Create event envelope
            envelope = self._create_security_log_envelope(
                tenant_id=tenant_id,
                event_type=event_type,
                user_id=user_id,
                resource=resource,
                decision=decision,
                correlation_id=correlation_id,
                context=context or {},
            )

            # Publish event with partition key (tenant_id for security logs)
            partition_key = tenant_id.encode("utf-8")

            # Build required Kafka headers
            headers = [
                ("x-tenant", tenant_id.encode("utf-8")),
                ("x-schema-hash", envelope.get("schema_ref", "").encode("utf-8")),
            ]

            # Add correlation ID to headers if provided
            if correlation_id:
                headers.extend(
                    [
                        (
                            "x-traceparent",
                            f"00-{correlation_id.replace('-', '')}-0000000000000000-01".encode(),
                        ),
                        ("x-correlation-id", correlation_id.encode("utf-8")),
                        ("x-causation-id", correlation_id.encode("utf-8")),
                    ]
                )

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await self._producer.send_and_wait(
                self.TOPIC_SECURITY_LOG,
                value=envelope,
                key=partition_key,
                headers=headers,
            )

            self.logger.debug(
                f"Published security log event (tenant: {tenant_id}, event_type: {event_type}, decision: {decision})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to publish security log event (tenant: {tenant_id}, event_type: {event_type}): {e}"
            )
            return False

    def _create_application_log_envelope(
        self,
        service_name: str,
        instance_id: str,
        level: str,
        logger_name: str,
        message: str,
        code: str,
        context: Dict[str, Any],
        correlation_id: Optional[str],
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

        Returns:
            Event envelope dictionary with complete structure
        """
        envelope = {
            "event_type": "omninode.logging.application.v1",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": os.getenv("TENANT_ID", "default"),
            "namespace": "omninode",
            "source": "omniclaude",
            "correlation_id": correlation_id or str(uuid4()),
            "causation_id": correlation_id or str(uuid4()),
            "schema_ref": "registry://omninode/logging/application/v1",
            "payload": {
                "service_name": service_name,
                "instance_id": instance_id,
                "level": level,
                "logger": logger_name,
                "message": message,
                "code": code,
                "context": context,
            },
        }

        return envelope

    def _create_audit_log_envelope(
        self,
        tenant_id: str,
        action: str,
        actor: str,
        resource: str,
        outcome: str,
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
        envelope = {
            "event_type": "omninode.logging.audit.v1",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
            "namespace": "omninode",
            "source": "omniclaude",
            "correlation_id": correlation_id or str(uuid4()),
            "causation_id": correlation_id or str(uuid4()),
            "schema_ref": "registry://omninode/logging/audit/v1",
            "payload": {
                "tenant_id": tenant_id,
                "action": action,
                "actor": actor,
                "resource": resource,
                "timestamp": datetime.now(UTC).isoformat(),
                "outcome": outcome,
                "context": context,
            },
        }

        return envelope

    def _create_security_log_envelope(
        self,
        tenant_id: str,
        event_type: str,
        user_id: str,
        resource: str,
        decision: str,
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
        envelope = {
            "event_type": "omninode.logging.security.v1",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
            "namespace": "omninode",
            "source": "omniclaude",
            "correlation_id": correlation_id or str(uuid4()),
            "causation_id": correlation_id or str(uuid4()),
            "schema_ref": "registry://omninode/logging/security/v1",
            "payload": {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "user_id": user_id,
                "resource": resource,
                "decision": decision,
                "timestamp": datetime.now(UTC).isoformat(),
                "context": context,
            },
        }

        return envelope


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
        enable_events: bool = True,
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


# Convenience functions for one-off event publishing
async def publish_application_log(
    service_name: str,
    instance_id: str,
    level: str,
    logger_name: str,
    message: str,
    code: str,
    context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> bool:
    """
    Convenience function for one-off application log event publishing.

    Args:
        service_name: Service name
        instance_id: Instance ID
        level: Log level
        logger_name: Logger name
        message: Log message
        code: Log code
        context: Optional context dictionary
        correlation_id: Optional correlation ID

    Returns:
        True if event published successfully, False otherwise

    Example:
        success = await publish_application_log(
            service_name="omniclaude",
            instance_id="omniclaude-1",
            level="INFO",
            logger_name="router.pipeline",
            message="Agent execution completed",
            code="AGENT_EXECUTION_COMPLETED",
        )
    """
    async with LoggingEventPublisherContext() as publisher:
        return await publisher.publish_application_log(
            service_name=service_name,
            instance_id=instance_id,
            level=level,
            logger_name=logger_name,
            message=message,
            code=code,
            context=context,
            correlation_id=correlation_id,
        )


async def publish_audit_log(
    tenant_id: str,
    action: str,
    actor: str,
    resource: str,
    outcome: str,
    correlation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Convenience function for one-off audit log event publishing.

    Args:
        tenant_id: Tenant ID
        action: Action performed
        actor: Actor identifier
        resource: Resource accessed
        outcome: Outcome of action
        correlation_id: Optional correlation ID
        context: Optional context dictionary

    Returns:
        True if event published successfully, False otherwise

    Example:
        success = await publish_audit_log(
            tenant_id="tenant-123",
            action="agent.execution",
            actor="user-456",
            resource="agent-api-architect",
            outcome="success",
        )
    """
    async with LoggingEventPublisherContext() as publisher:
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
    tenant_id: str,
    event_type: str,
    user_id: str,
    resource: str,
    decision: str,
    correlation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Convenience function for one-off security log event publishing.

    Args:
        tenant_id: Tenant ID
        event_type: Security event type
        user_id: User identifier
        resource: Resource accessed
        decision: Security decision
        correlation_id: Optional correlation ID
        context: Optional context dictionary

    Returns:
        True if event published successfully, False otherwise

    Example:
        success = await publish_security_log(
            tenant_id="tenant-123",
            event_type="api_key_used",
            user_id="user-456",
            resource="gemini-api",
            decision="allow",
        )
    """
    async with LoggingEventPublisherContext() as publisher:
        return await publisher.publish_security_log(
            tenant_id=tenant_id,
            event_type=event_type,
            user_id=user_id,
            resource=resource,
            decision=decision,
            correlation_id=correlation_id,
            context=context,
        )
