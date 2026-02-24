# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Default NL Intent Pipeline handler.

Classifies raw NL input into a typed ModelIntentObject using pattern-based
keyword matching plus an optional HTTP call to the OMN-2348 Intent Intelligence
Framework (omniintelligence service).

Design decisions:
- HTTP call to external service is *optional* and always non-blocking:
  if the service is unavailable, the handler falls back to keyword matching.
- No LLM calls in this handler — classification is deterministic by default.
- The handler is pure input→output; no I/O side effects (COMPUTE node).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import uuid

from omniclaude.nodes.node_nl_intent_pipeline.enums.enum_intent_type import (
    EnumIntentType,
)
from omniclaude.nodes.node_nl_intent_pipeline.enums.enum_resolution_path import (
    EnumResolutionPath,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_classification_response import (
    ModelClassificationResponse,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_extracted_entity import (
    ModelExtractedEntity,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_intent_object import (
    ModelIntentObject,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_nl_parse_request import (
    ModelNlParseRequest,
)

__all__ = ["HandlerNlIntentDefault"]

logger = logging.getLogger(__name__)

# Keyword patterns: (pattern_substring, EnumIntentType, base_confidence_boost)
# Evaluated in order; first match wins if no service classification is available.
_KEYWORD_PATTERNS: list[tuple[str, EnumIntentType, float]] = [
    ("security", EnumIntentType.SECURITY, 0.10),
    ("vulnerability", EnumIntentType.SECURITY, 0.10),
    ("auth", EnumIntentType.SECURITY, 0.08),
    ("refactor", EnumIntentType.REFACTOR, 0.10),
    ("clean up", EnumIntentType.REFACTOR, 0.08),
    ("test", EnumIntentType.TESTING, 0.10),
    ("spec", EnumIntentType.TESTING, 0.06),
    ("doc", EnumIntentType.DOCUMENTATION, 0.10),
    ("readme", EnumIntentType.DOCUMENTATION, 0.10),
    ("bug", EnumIntentType.BUG_FIX, 0.10),
    ("fix", EnumIntentType.BUG_FIX, 0.08),
    ("infra", EnumIntentType.INFRASTRUCTURE, 0.10),
    ("deploy", EnumIntentType.INFRASTRUCTURE, 0.08),
    ("k8s", EnumIntentType.INFRASTRUCTURE, 0.08),
    ("epic", EnumIntentType.EPIC_DECOMPOSITION, 0.10),
    ("decompose", EnumIntentType.EPIC_DECOMPOSITION, 0.10),
    ("feature", EnumIntentType.FEATURE, 0.10),
    ("implement", EnumIntentType.CODE, 0.08),
    ("add", EnumIntentType.CODE, 0.06),
    ("review", EnumIntentType.REVIEW, 0.10),
    ("debug", EnumIntentType.DEBUGGING, 0.10),
]

# Map intent_class strings (from OMN-2348 service) to EnumIntentType
_SERVICE_CLASS_MAP: dict[str, EnumIntentType] = {
    "SECURITY": EnumIntentType.SECURITY,
    "CODE": EnumIntentType.CODE,
    "REFACTOR": EnumIntentType.REFACTOR,
    "TESTING": EnumIntentType.TESTING,
    "DOCUMENTATION": EnumIntentType.DOCUMENTATION,
    "REVIEW": EnumIntentType.REVIEW,
    "DEBUGGING": EnumIntentType.DEBUGGING,
    "GENERAL": EnumIntentType.GENERAL,
    "FEATURE": EnumIntentType.FEATURE,
    "BUG_FIX": EnumIntentType.BUG_FIX,
    "EPIC_DECOMPOSITION": EnumIntentType.EPIC_DECOMPOSITION,
    "INFRASTRUCTURE": EnumIntentType.INFRASTRUCTURE,
}

# HTTP timeout for external classification service
_SERVICE_TIMEOUT_S = 0.9


class HandlerNlIntentDefault:
    """Default handler for NL → Intent Object classification.

    Classification flow:
    1. If request.force_intent_type is set, use that type with confidence=1.0.
    2. Try calling the OMN-2348 intent intelligence service (non-blocking).
    3. Fall back to keyword matching if the service is unavailable.
    4. If no keywords match, classify as UNKNOWN with confidence=0.0.

    Entity extraction is keyword-based in this implementation.  A future
    handler can plug in NER models without changing the public interface.
    """

    @property
    def handler_key(self) -> str:
        """Registry key for handler lookup."""
        return "default"

    def parse_intent(
        self,
        request: ModelNlParseRequest,
        *,
        classification_url: str | None = None,
    ) -> ModelIntentObject:
        """Parse raw NL input into a typed ModelIntentObject.

        Args:
            request: Parse request containing raw NL and correlation metadata.
            classification_url: Optional override for the classification service
                URL.  Defaults to the standard OMN-2348 endpoint.

        Returns:
            Typed ModelIntentObject (frozen, JSON-serializable).
        """
        intent_id = str(uuid.uuid4())

        # 1. Forced intent type (test/routing override)
        if request.force_intent_type is not None:
            resolved_type = _SERVICE_CLASS_MAP.get(
                request.force_intent_type.upper(), EnumIntentType.UNKNOWN
            )
            return ModelIntentObject.build(
                intent_id=intent_id,
                nl_input=request.raw_nl,
                intent_type=resolved_type,
                confidence=1.0,
                entities=_extract_entities(request.raw_nl),
                summary=f"Forced intent: {resolved_type.value}",
                resolution_path=EnumResolutionPath.INFERENCE,
            )

        # 2. Try external classification service (OMN-2348 integration)
        service_result = _call_classification_service(
            prompt=request.raw_nl,
            session_id=request.session_id,
            correlation_id=str(request.correlation_id),
            timeout_s=_SERVICE_TIMEOUT_S,
            url_override=classification_url,
        )

        if service_result is not None and service_result.success:
            intent_class_str = service_result.intent_class.upper()
            intent_type = _SERVICE_CLASS_MAP.get(
                intent_class_str, EnumIntentType.UNKNOWN
            )
            confidence = service_result.confidence
            logger.debug(
                "Service classification: %s (confidence=%.2f, correlation_id=%s)",
                intent_type.value,
                confidence,
                request.correlation_id,
            )
            return ModelIntentObject.build(
                intent_id=intent_id,
                nl_input=request.raw_nl,
                intent_type=intent_type,
                confidence=confidence,
                entities=_extract_entities(request.raw_nl),
                summary=_build_summary(request.raw_nl, intent_type),
                resolution_path=EnumResolutionPath.NONE,
            )

        # 3. Fall back to keyword matching
        keyword_type, keyword_confidence = _keyword_classify(request.raw_nl)
        logger.debug(
            "Keyword classification: %s (confidence=%.2f, correlation_id=%s)",
            keyword_type.value,
            keyword_confidence,
            request.correlation_id,
        )
        return ModelIntentObject.build(
            intent_id=intent_id,
            nl_input=request.raw_nl,
            intent_type=keyword_type,
            confidence=keyword_confidence,
            entities=_extract_entities(request.raw_nl),
            summary=_build_summary(request.raw_nl, keyword_type),
            resolution_path=EnumResolutionPath.INFERENCE,
        )


# ---------------------------------------------------------------------------
# Internal helpers (module-level, importable for testing)
# ---------------------------------------------------------------------------


def _keyword_classify(text: str) -> tuple[EnumIntentType, float]:
    """Classify NL text by keyword matching.

    Evaluates patterns in order and accumulates a confidence score.
    Returns the best-matching intent type and its confidence.

    Args:
        text: Raw NL text (lowercased internally).

    Returns:
        (intent_type, confidence) tuple. UNKNOWN/0.0 if no match.
    """
    text_lower = text.lower()
    scores: dict[EnumIntentType, float] = {}

    for keyword, intent_type, boost in _KEYWORD_PATTERNS:
        if keyword in text_lower:
            current = scores.get(intent_type, 0.5)
            scores[intent_type] = min(1.0, current + boost)

    if not scores:
        return EnumIntentType.UNKNOWN, 0.0

    best_type = max(scores, key=lambda t: scores[t])
    return best_type, scores[best_type]


def _extract_entities(text: str) -> tuple[ModelExtractedEntity, ...]:
    """Extract simple named entities from NL text.

    Recognises:
    - Ticket references: OMN-NNNN, LIN-NNN patterns
    - Repository names: omniclaude, omnibase-core, omnibase-spi, etc.

    Args:
        text: Raw NL text.

    Returns:
        Tuple of ModelExtractedEntity (may be empty).
    """
    import re

    entities: list[ModelExtractedEntity] = []

    # Ticket references (e.g. OMN-2501, LIN-123)
    for match in re.finditer(r"\b([A-Z]{2,6}-\d{3,6})\b", text):
        entities.append(
            ModelExtractedEntity(
                entity_type="TICKET",
                value=match.group(1),
                raw_span=match.group(0),
                confidence=0.95,
            )
        )

    # Known repo names
    known_repos = [
        "omniclaude",
        "omnibase-core",
        "omnibase-spi",
        "omnibase-infra",
    ]
    for repo in known_repos:
        if repo.lower() in text.lower():
            entities.append(
                ModelExtractedEntity(
                    entity_type="REPOSITORY",
                    value=repo,
                    raw_span=repo,
                    confidence=0.90,
                )
            )

    return tuple(entities)


def _build_summary(text: str, intent_type: EnumIntentType) -> str:
    """Build a one-sentence summary of the intent.

    Args:
        text: Raw NL text.
        intent_type: Classified intent type.

    Returns:
        Summary string (max 200 chars).
    """
    prefix = intent_type.value.replace("_", " ").title()
    snippet = text.strip()[:100].replace("\n", " ")
    return f"{prefix} intent: {snippet}"[:200]


def _call_classification_service(
    *,
    prompt: str,
    session_id: str,
    correlation_id: str,
    timeout_s: float,
    url_override: str | None,
) -> ModelClassificationResponse | None:
    """Call the OMN-2348 intent classification service.

    Non-blocking: returns None on any error or timeout so callers can fall
    back gracefully.

    Args:
        prompt: Raw NL text to classify.
        session_id: Session identifier.
        correlation_id: Correlation UUID string.
        timeout_s: HTTP request timeout.
        url_override: Override URL (for tests or alternative deployments).

    Returns:
        ModelClassificationResponse on success, None on failure.
    """
    import os

    if url_override is None:
        explicit = os.environ.get("OMNICLAUDE_INTENT_API_URL", "").strip()
        if explicit:
            url = explicit
        else:
            base = os.environ.get("INTELLIGENCE_SERVICE_URL", "").strip()
            url = (base.rstrip("/") + "/api/v1/intent/classify") if base else ""

        if not url:
            return None  # Service not configured; skip without logging
    else:
        url = url_override

    try:
        start = time.monotonic()
        intent_id = str(uuid.uuid4())
        payload = json.dumps(
            {
                "prompt": prompt,
                "session_id": session_id,
                "correlation_id": correlation_id,
                "intent_id": intent_id,
            }
        ).encode("utf-8")

        req = urllib.request.Request(  # noqa: S310  # nosec B310
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310  # nosec B310
            raw = resp.read().decode("utf-8")

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.debug("Intent service responded in %dms", elapsed_ms)
        return ModelClassificationResponse.model_validate_json(raw)

    except (urllib.error.URLError, TimeoutError, OSError):
        logger.debug("Intent classification service unavailable (non-fatal)")
        return None
    except Exception:  # noqa: BLE001
        logger.debug(
            "Intent classification service call failed (non-fatal)", exc_info=True
        )
        return None
