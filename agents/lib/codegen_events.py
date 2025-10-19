#!/usr/bin/env python3
"""
Codegen Event Models

Event models and topic helpers for the code generation workflow.
Follows patterns from omninode_bridge event models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BaseEvent:
    id: UUID = field(default_factory=uuid4)
    service: str = "omniclaude"
    timestamp: str = field(default_factory=_now_iso)
    correlation_id: UUID = field(default_factory=uuid4)
    metadata: Dict[str, Any] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_kafka_topic(self) -> str:
        raise NotImplementedError


@dataclass
class CodegenAnalysisRequest(BaseEvent):
    event: str = "codegen.request.analyze"

    def to_kafka_topic(self) -> str:
        return "dev.omniclaude.codegen.analyze.request.v1"


@dataclass
class CodegenAnalysisResponse(BaseEvent):
    event: str = "codegen.response.analyze"

    def to_kafka_topic(self) -> str:
        return "dev.omniclaude.codegen.analyze.response.v1"


@dataclass
class CodegenGenerationRequest(BaseEvent):
    event: str = "codegen.request.generate"

    def to_kafka_topic(self) -> str:
        return "dev.omniclaude.codegen.generate.request.v1"


@dataclass
class CodegenValidationRequest(BaseEvent):
    event: str = "codegen.request.validate"

    def to_kafka_topic(self) -> str:
        return "dev.omniclaude.codegen.validate.request.v1"


@dataclass
class CodegenValidationResponse(BaseEvent):
    event: str = "codegen.response.validate"

    def to_kafka_topic(self) -> str:
        return "dev.omniclaude.codegen.validate.response.v1"


@dataclass
class CodegenStatusEvent(BaseEvent):
    event: str = "codegen.status.update"
    session_id: Optional[UUID] = None

    def to_kafka_topic(self) -> str:
        sid = self.session_id or self.correlation_id
        return f"dev.omniclaude.codegen.status.{sid}.v1"


__all__ = [
    "BaseEvent",
    "CodegenAnalysisRequest",
    "CodegenAnalysisResponse",
    "CodegenGenerationRequest",
    "CodegenValidationRequest",
    "CodegenValidationResponse",
    "CodegenStatusEvent",
]
