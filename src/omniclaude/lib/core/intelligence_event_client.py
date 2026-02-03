#!/usr/bin/env python3
"""Intelligence Event Client - Thin wrapper over RequestResponseWiring (OMN-1744)."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError
from omnibase_core.models.contracts.subcontracts import (
    ModelReplyTopics,
    ModelRequestResponseConfig,
    ModelRequestResponseInstance,
)
from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig
from omnibase_infra.runtime.request_response_wiring import RequestResponseWiring

from omniclaude.config import settings

logger = logging.getLogger(__name__)


class IntelligenceEventClient:
    """Kafka client for intelligence events using RequestResponseWiring."""

    TOPIC_REQUEST = "omninode.intelligence.code-analysis.requested.v1"
    TOPIC_COMPLETED = "omninode.intelligence.code-analysis.completed.v1"
    TOPIC_FAILED = "omninode.intelligence.code-analysis.failed.v1"
    _INSTANCE_NAME = "intelligence"

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        enable_intelligence: bool = True,
        request_timeout_ms: int = 5000,
        consumer_group_id: str | None = None,
    ):
        self.bootstrap_servers = bootstrap_servers or settings.get_effective_kafka_bootstrap_servers()
        if not self.bootstrap_servers:
            raise ModelOnexError(
                message="bootstrap_servers required", error_code=EnumCoreErrorCode.VALIDATION_ERROR, operation="__init__"
            )
        self.enable_intelligence = enable_intelligence
        self.request_timeout_ms = request_timeout_ms
        self._environment = os.getenv("KAFKA_ENVIRONMENT", "dev")
        self._event_bus: EventBusKafka | None = None
        self._wiring: RequestResponseWiring | None = None
        self._started = False
        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        if self._started or not self.enable_intelligence:
            return
        self.logger.info(f"Starting intelligence client (broker: {self.bootstrap_servers})")
        config = ModelKafkaEventBusConfig(bootstrap_servers=self.bootstrap_servers, environment=self._environment)
        self._event_bus = EventBusKafka(config)
        await self._event_bus.connect()
        self._wiring = RequestResponseWiring(
            event_bus=self._event_bus, environment=self._environment,
            app_name="omniclaude", bootstrap_servers=self.bootstrap_servers,
        )
        rr_config = ModelRequestResponseConfig(instances=[
            ModelRequestResponseInstance(
                name=self._INSTANCE_NAME, request_topic=self.TOPIC_REQUEST,
                reply_topics=ModelReplyTopics(completed=self.TOPIC_COMPLETED, failed=self.TOPIC_FAILED),
                timeout_seconds=self.request_timeout_ms // 1000,
            )
        ])
        await self._wiring.wire_request_response(rr_config)
        self._started = True
        self.logger.info("Intelligence event client started")

    async def stop(self) -> None:
        if not self._started:
            return
        self.logger.info("Stopping intelligence event client")
        if self._wiring:
            await self._wiring.cleanup()
            self._wiring = None
        if self._event_bus:
            await self._event_bus.disconnect()
            self._event_bus = None
        self._started = False

    async def health_check(self) -> bool:
        return self.enable_intelligence and self._started and self._wiring is not None

    async def request_pattern_discovery(
        self, source_path: str, language: str, timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._started:
            raise ModelOnexError(
                message="Client not started", error_code=EnumCoreErrorCode.VALIDATION_ERROR, operation="request_pattern_discovery"
            )
        content = None
        fp = Path(source_path)
        if fp.exists() and fp.is_file():
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception:
                pass
        result = await self.request_code_analysis(
            content=content, source_path=source_path, language=language,
            options={"operation_type": "PATTERN_EXTRACTION", "include_patterns": True}, timeout_ms=timeout_ms,
        )
        return cast(list[dict[str, Any]], result.get("patterns", []))

    async def request_code_analysis(
        self, content: str | None, source_path: str, language: str,
        options: dict[str, Any] | None = None, timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        if not self._started or self._wiring is None:
            raise ModelOnexError(
                message="Client not started", error_code=EnumCoreErrorCode.VALIDATION_ERROR, operation="request_code_analysis"
            )
        timeout_seconds = (timeout_ms or self.request_timeout_ms) // 1000
        correlation_id = str(uuid4())
        payload = {
            "event_type": self.TOPIC_REQUEST, "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(), "tenant_id": os.getenv("TENANT_ID", "default"),
            "namespace": "omninode", "source": "omniclaude",
            "correlation_id": correlation_id, "causation_id": correlation_id,
            "schema_ref": "registry://omninode/intelligence/code_analysis_requested/v1",
            "payload": {
                "source_path": source_path, "content": content, "language": language,
                "operation_type": (options or {}).get("operation_type", "PATTERN_EXTRACTION"),
                "options": options or {}, "project_id": "omniclaude", "user_id": "system", "environment": self._environment,
            },
        }
        try:
            result = await self._wiring.send_request(
                instance_name=self._INSTANCE_NAME, payload=payload, timeout_seconds=timeout_seconds,
            )
            return cast(dict[str, Any], result.get("payload", result))
        except Exception as e:
            if "timeout" in str(e).lower():
                raise TimeoutError(f"Request timeout ({correlation_id})") from e
            raise


class IntelligenceEventClientContext:
    """Context manager for automatic client lifecycle."""

    def __init__(
        self, bootstrap_servers: str | None = None, enable_intelligence: bool = True, request_timeout_ms: int = 5000,
    ):
        self.client = IntelligenceEventClient(
            bootstrap_servers=bootstrap_servers, enable_intelligence=enable_intelligence, request_timeout_ms=request_timeout_ms,
        )

    async def __aenter__(self) -> IntelligenceEventClient:
        await self.client.start()
        return self.client

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        await self.client.stop()
        return False


__all__ = ["IntelligenceEventClient", "IntelligenceEventClientContext"]
