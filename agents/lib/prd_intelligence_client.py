#!/usr/bin/env python3
"""
Event-driven Intelligence Client for PRD Analysis

Publishes CodegenAnalysisRequest and awaits CodegenAnalysisResponse via Kafka.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from .codegen_events import CodegenAnalysisRequest
from .kafka_codegen_client import KafkaCodegenClient


class PRDIntelligenceClient:
    def __init__(self, bootstrap_servers: Optional[str] = None) -> None:
        self.client = KafkaCodegenClient(bootstrap_servers=bootstrap_servers)

    async def analyze(
        self,
        prd_content: str,
        workspace_context: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        correlation_id = uuid4()
        req = CodegenAnalysisRequest()
        req.correlation_id = correlation_id
        req.payload = {
            "prd_content": prd_content,
            "workspace_context": workspace_context or {},
        }
        await self.client.publish(req)

        def matches(payload: Dict[str, Any]) -> bool:
            return payload.get("correlation_id") == str(correlation_id)

        topic = "dev.omniclaude.codegen.analyze.response.v1"
        resp = await self.client.consume_until(topic, matches, timeout_seconds=timeout_seconds)
        await self.client.stop_producer()
        await self.client.stop_consumer()
        return resp


