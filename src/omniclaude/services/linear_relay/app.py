# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""FastAPI application for the Linear relay service.

Receives Linear webhook POST requests, verifies HMAC-SHA256 signatures,
filters for epic-closed events, deduplicates by webhookId, and publishes
LinearEpicClosedCommand to the feature-dashboard Kafka topic.

See OMN-3502 for specification.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from omniclaude.services.linear_relay.dedup import DedupStore
from omniclaude.services.linear_relay.models import LinearWebhookPayload
from omniclaude.services.linear_relay.publisher import build_command, close_producer
from omniclaude.services.linear_relay.verifier import (
    LINEAR_SIGNATURE_HEADER,
    verify_signature,
)

logger = logging.getLogger(__name__)


# Entity types that trigger the epic-closed flow.
# Defaults to {"Project"}, configurable via LINEAR_EPIC_TYPES env var.
# Example: LINEAR_EPIC_TYPES=Project,Initiative
def _get_epic_closed_types() -> set[str]:
    """Read LINEAR_EPIC_CLOSED_TYPES from environment.

    Returns:
        Set of entity type strings that trigger the epic-closed flow.
        Defaults to ``{"Project"}``.
    """
    raw = os.environ.get("LINEAR_EPIC_TYPES", "Project")
    return {t.strip() for t in raw.split(",") if t.strip()}


# Module-level dedup store (single instance per process)
_dedup_store: DedupStore | None = None


def _get_dedup_store() -> DedupStore:
    """Get or create the module-level dedup store."""
    global _dedup_store  # noqa: PLW0603
    if _dedup_store is None:
        _dedup_store = DedupStore()
    return _dedup_store


def _reset_dedup_store(store: DedupStore | None = None) -> None:
    """Replace the dedup store. For testing only."""
    global _dedup_store  # noqa: PLW0603
    _dedup_store = store


async def _publish(org_id: str, epic_id: str) -> None:
    """Build and publish a LinearEpicClosedCommand.

    Falls back to logging if Kafka is unavailable.

    Args:
        org_id: Linear organization ID.
        epic_id: Linear epic (project/initiative) ID.
    """
    try:
        from omniclaude.services.linear_relay.publisher import publish_command

        command = build_command(org_id, epic_id)
        await publish_command(command)
    except ImportError:
        logger.warning(
            "Kafka publisher not available. Command logged but not published: "
            "org=%s epic=%s",
            org_id,
            epic_id,
        )
    except Exception:
        logger.exception(
            "Failed to publish command for org=%s epic=%s", org_id, epic_id
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan: startup and shutdown."""
    yield
    await close_producer()


def create_app() -> FastAPI:
    """Create and configure the Linear relay FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Linear Relay",
        description=(
            "Receives Linear webhooks and publishes LinearEpicClosedCommand "
            "to the feature-dashboard Kafka topic when an epic is closed."
        ),
        version="1.0.0",
        lifespan=_lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "service": "linear-relay"}

    @app.post("/webhook")
    async def receive_webhook(
        request: Request,
    ) -> dict[str, Any]:  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
        """Receive a Linear webhook event.

        Processing pipeline:
        1. Read raw bytes before parsing (required for HMAC verification).
        2. Verify ``Linear-Signature`` header → 401 if verification fails.
        3. Parse ``LinearWebhookPayload``.
        4. Filter: type in ``LINEAR_EPIC_CLOSED_TYPES``
           AND ``data.state == "completed"`` → skip silently if not matched.
        5. Dedup by ``webhookId`` → 409 if duplicate.
        6. Publish ``LinearEpicClosedCommand`` to Kafka.

        Args:
            request: The incoming FastAPI request.

        Returns:
            Dict with status and relevant identifiers.

        Raises:
            HTTPException 401: If HMAC signature verification fails.
            HTTPException 409: If the webhookId was already processed.
            HTTPException 422: If the request body cannot be parsed.
        """
        # Step 1: read raw bytes before any parsing
        body = await request.body()

        # Step 2: verify HMAC-SHA256 signature
        signature = request.headers.get(LINEAR_SIGNATURE_HEADER, "")
        if not verify_signature(body, signature):
            logger.warning(
                "Webhook signature verification failed (sig=%r)", signature[:20]
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Step 3: parse payload
        try:
            payload = LinearWebhookPayload.model_validate_json(body)
        except Exception as exc:
            logger.warning("Failed to parse webhook payload: %s", exc)
            raise HTTPException(
                status_code=422, detail=f"Invalid webhook payload: {exc}"
            ) from exc

        epic_closed_types = _get_epic_closed_types()

        # Step 4: filter — only process epic-closed events
        if payload.type not in epic_closed_types:
            logger.debug(
                "Skipping webhook: type=%r not in %r",
                payload.type,
                epic_closed_types,
            )
            return {
                "status": "skipped",
                "reason": "type_not_matched",
                "type": payload.type,
            }

        state = payload.data.get("state")
        if state != "completed":
            logger.debug(
                "Skipping webhook: type=%r state=%r (expected 'completed')",
                payload.type,
                state,
            )
            return {
                "status": "skipped",
                "reason": "state_not_completed",
                "state": state,
            }

        # Step 5: dedup by webhookId
        dedup = _get_dedup_store()
        if dedup.is_duplicate(payload.webhookId):
            logger.info("Duplicate webhook dropped: webhookId=%s", payload.webhookId)
            raise HTTPException(
                status_code=409,
                detail=f"Duplicate webhook: {payload.webhookId}",
            )

        # Step 6: determine epic_id and publish
        epic_id = str(payload.data.get("id", payload.webhookId))
        org_id = payload.organizationId

        await _publish(org_id, epic_id)

        logger.info(
            "Published epic-closed command: org=%s epic=%s webhook=%s",
            org_id,
            epic_id,
            payload.webhookId,
        )

        return {
            "status": "published",
            "webhookId": payload.webhookId,
            "org_id": org_id,
            "epic_id": epic_id,
        }

    return app
