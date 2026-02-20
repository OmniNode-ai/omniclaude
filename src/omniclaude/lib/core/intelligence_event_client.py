#!/usr/bin/env python3
"""Intelligence Event Client - Thin wrapper over RequestResponseWiring (OMN-1744)."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from omnibase_core.models.contracts.subcontracts import (
    ModelReplyTopics,
    ModelRequestResponseConfig,
    ModelRequestResponseInstance,
)
from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig
from omnibase_infra.runtime.request_response_wiring import RequestResponseWiring

from omniclaude.config import settings
from omniclaude.lib.errors import EnumCoreErrorCode, OnexError

logger = logging.getLogger(__name__)


class IntelligenceEventClient:
    """Kafka client for intelligence events using RequestResponseWiring."""

    # Canonical topic names per onex.cmd/evt convention (OMN-2367)
    TOPIC_REQUEST = "onex.cmd.omniintelligence.code-analysis.v1"
    TOPIC_COMPLETED = "onex.evt.omniintelligence.code-analysis-completed.v1"
    TOPIC_FAILED = "onex.evt.omniintelligence.code-analysis-failed.v1"

    # Legacy topic — dual-publish migration window only (remove after migration)
    TOPIC_REQUEST_LEGACY = "omninode.intelligence.code-analysis.requested.v1"

    _INSTANCE_NAME = "intelligence"

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        enable_intelligence: bool = True,
        request_timeout_ms: int = 5000,
    ):
        self.bootstrap_servers = (
            bootstrap_servers or settings.get_effective_kafka_bootstrap_servers()
        )
        if not self.bootstrap_servers:
            raise OnexError(
                code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="bootstrap_servers required (set KAFKA_BOOTSTRAP_SERVERS)",
                details={"component": "IntelligenceEventClient"},
            )
        self.enable_intelligence = enable_intelligence
        self.request_timeout_ms = request_timeout_ms
        self._environment: str | None = None  # Validated in start()
        self._event_bus: EventBusKafka | None = None
        self._wiring: RequestResponseWiring | None = None
        self._started = False
        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        if self._started or not self.enable_intelligence:
            return

        # Validate environment (consistent with routing_event_client)
        self._environment = settings.kafka_environment
        if not self._environment:
            raise OnexError(
                code=EnumCoreErrorCode.CONFIGURATION_ERROR,
                message="KAFKA_ENVIRONMENT required",
                details={"component": "IntelligenceEventClient"},
            )

        self.logger.info(
            f"Starting intelligence client (broker: {self.bootstrap_servers})"
        )
        try:
            config = ModelKafkaEventBusConfig(
                bootstrap_servers=self.bootstrap_servers, environment=self._environment
            )
            self._event_bus = EventBusKafka(config)
            await self._event_bus.start()
            self._wiring = RequestResponseWiring(
                event_bus=self._event_bus,
                environment=self._environment,
                app_name="omniclaude",
                bootstrap_servers=self.bootstrap_servers,
            )
            rr_config = ModelRequestResponseConfig(
                instances=[
                    ModelRequestResponseInstance(
                        name=self._INSTANCE_NAME,
                        request_topic=self.TOPIC_REQUEST,
                        reply_topics=ModelReplyTopics(
                            completed=self.TOPIC_COMPLETED, failed=self.TOPIC_FAILED
                        ),
                        timeout_seconds=self.request_timeout_ms // 1000,
                    )
                ]
            )
            await self._wiring.wire_request_response(rr_config)
            self._started = True
            self.logger.info("Intelligence event client started")
        except Exception:
            await self.stop()  # Cleanup partial state
            raise

    async def stop(self) -> None:
        """Close connections gracefully. Safe to call even if start() failed partway."""
        if self._wiring:
            await self._wiring.cleanup()
            self._wiring = None
        if self._event_bus:
            await self._event_bus.stop()
            self._event_bus = None
        self._started = False

    async def health_check(self) -> bool:
        return self.enable_intelligence and self._started and self._wiring is not None

    async def request_pattern_discovery(
        self,
        source_path: str,
        language: str,
        timeout_ms: int | None = None,
        emitted_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if not self._started:
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message="Client not started. Call start() first.",
                details={"component": "IntelligenceEventClient"},
            )
        content = None
        fp = Path(source_path)
        if fp.exists() and fp.is_file():
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception as e:
                self.logger.debug(f"Failed to read file {source_path}: {e}")
        result = await self.request_code_analysis(
            content=content,
            source_path=source_path,
            language=language,
            options={"operation_type": "PATTERN_EXTRACTION", "include_patterns": True},
            timeout_ms=timeout_ms,
            emitted_at=emitted_at,
        )
        return cast("list[dict[str, Any]]", result.get("patterns", []))

    async def request_code_analysis(
        self,
        content: str | None,
        source_path: str,
        language: str,
        options: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
        emitted_at: datetime | None = None,
    ) -> dict[str, Any]:
        if not self._started or self._wiring is None:
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message="Client not started. Call start() first.",
                details={"component": "IntelligenceEventClient"},
            )
        timeout_seconds = (timeout_ms or self.request_timeout_ms) // 1000
        correlation_id = str(uuid4())
        timestamp = (emitted_at if emitted_at is not None else datetime.now(UTC)).isoformat()
        payload = {
            "event_type": self.TOPIC_REQUEST,
            "event_id": str(uuid4()),
            "timestamp": timestamp,
            "tenant_id": os.getenv("TENANT_ID", "default"),
            "namespace": "omninode",
            "source": "omniclaude",
            "correlation_id": correlation_id,
            "causation_id": correlation_id,
            "schema_ref": "registry://omninode/intelligence/code_analysis_requested/v1",
            "payload": {
                "source_path": source_path,
                "content": content,
                "language": language,
                "operation_type": (options or {}).get(
                    "operation_type", "PATTERN_EXTRACTION"
                ),
                "options": options or {},
                "project_id": "omniclaude",
                "user_id": "system",
                "environment": self._environment,
            },
        }
        try:
            # Dual-publish: mirror to legacy topic during migration window (remove after migration)
            if (
                os.environ.get("DUAL_PUBLISH_LEGACY_TOPICS") == "1"
                and self._event_bus is not None
            ):
                try:
                    await self._event_bus.publish(self.TOPIC_REQUEST_LEGACY, payload)
                except Exception as legacy_err:
                    self.logger.debug(
                        f"Dual-publish to legacy topic failed (non-fatal): {legacy_err}"
                    )

            result = await self._wiring.send_request(
                instance_name=self._INSTANCE_NAME,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            return cast("dict[str, Any]", result.get("payload", result))
        except TimeoutError as e:
            raise TimeoutError(f"Request timeout ({correlation_id})") from e


class IntelligenceEventClientContext:
    """Context manager for automatic client lifecycle."""

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        enable_intelligence: bool = True,
        request_timeout_ms: int = 5000,
    ):
        self.client = IntelligenceEventClient(
            bootstrap_servers=bootstrap_servers,
            enable_intelligence=enable_intelligence,
            request_timeout_ms=request_timeout_ms,
        )

    async def __aenter__(self) -> IntelligenceEventClient:
        await self.client.start()
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        await self.client.stop()
        return False


__all__ = ["IntelligenceEventClient", "IntelligenceEventClientContext"]
