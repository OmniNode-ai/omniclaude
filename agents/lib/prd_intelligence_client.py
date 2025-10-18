#!/usr/bin/env python3
"""
PRD Intelligence Client

Publishes CodegenAnalysisRequest events and awaits CodegenAnalysisResponse by correlation_id.
Prefers aiokafka via KafkaCodegenClient with automatic confluent-kafka fallback.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from uuid import uuid4

from .codegen_events import CodegenAnalysisRequest
from .kafka_codegen_client import KafkaCodegenClient
from .version_config import get_config


class PRDIntelligenceClient:
    def __init__(self, bootstrap_servers: Optional[str] = None) -> None:
        cfg = get_config()
        self.bootstrap_servers = bootstrap_servers or cfg.kafka_bootstrap_servers
        self._kafka = KafkaCodegenClient(bootstrap_servers=self.bootstrap_servers)

    async def analyze(
        self,
        prd_content: str,
        workspace_context: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        req = CodegenAnalysisRequest()
        req.correlation_id = uuid4()
        # Attach request payload
        req.payload = {
            "prd_content": prd_content,
            "workspace_context": workspace_context or {},
        }

        # Publish request
        await self._kafka.publish(req)

        # Await response by correlation id
        topic = "dev.omniclaude.codegen.analyze.response.v1"

        def _matches(payload: Dict[str, Any]) -> bool:
            return payload.get("correlation_id") == str(req.correlation_id)

        try:
            response = await self._kafka.consume_until(
                topic=topic,
                predicate=_matches,
                timeout_seconds=timeout_seconds,
            )
        finally:
            # Best-effort close consumer/producer
            await asyncio.gather(
                self._kafka.stop_consumer(),
                self._kafka.stop_producer(),
                return_exceptions=True,
            )

        return response
