"""
FastAPI Entry Point for Intelligent Context Proxy

This service sits transparently between Claude Code and Anthropic's API,
providing complete control over conversation context while integrating
with OmniClaude's full intelligence infrastructure.

Architecture:
- FastAPI receives HTTP requests from Claude Code
- Publishes events to Kafka (context.request.received.v1)
- NodeContextRequestReducer consumes events (FSM state tracking)
- NodeContextProxyOrchestrator coordinates workflow
- Returns modified response to Claude Code

Key Features:
- OAuth token passthrough (transparent to Claude Code)
- Event-driven internal architecture (Kafka/Redpanda)
- Correlation ID tracking (end-to-end traceability)
- Graceful error handling with fallbacks

Usage:
    # Set Claude Code to use proxy
    export ANTHROPIC_BASE_URL=http://localhost:8080

    # Start proxy
    uvicorn main:app --host 0.0.0.0 --port 8080

Created: 2025-11-09
Status: Phase 1 - Foundation
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError
from config import settings
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .models.event_envelope import (
    BaseEventEnvelope,
    ContextRequestReceivedEvent,
    EventType,
    KafkaTopics,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global state
kafka_producer: Optional[AIOKafkaProducer] = None
kafka_consumer: Optional[AIOKafkaConsumer] = None
pending_requests: Dict[str, asyncio.Future] = {}  # correlation_id → Future[response]


# ============================================================================
# Lifespan (Startup/Shutdown)
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Kafka producer and consumer lifecycle."""
    global kafka_producer, kafka_consumer

    logger.info("Starting Intelligent Context Proxy...")

    try:
        # Initialize Kafka producer
        kafka_producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await kafka_producer.start()
        logger.info(f"Kafka producer connected: {settings.kafka_bootstrap_servers}")

        # Initialize Kafka consumer (for response events)
        kafka_consumer = AIOKafkaConsumer(
            KafkaTopics.CONTEXT_RESPONSE_COMPLETED,
            KafkaTopics.CONTEXT_FAILED,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="fastapi-proxy-group",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
        )
        await kafka_consumer.start()
        logger.info("Kafka consumer started for response events")

        # Start response consumer task
        asyncio.create_task(consume_responses())

        logger.info("✅ Intelligent Context Proxy started successfully")

    except Exception as e:
        logger.error(f"Failed to start Kafka connections: {e}", exc_info=True)
        raise

    yield

    logger.info("Shutting down Intelligent Context Proxy...")

    if kafka_producer:
        await kafka_producer.stop()
    if kafka_consumer:
        await kafka_consumer.stop()

    logger.info("Intelligent Context Proxy stopped")


# FastAPI app
app = FastAPI(
    title="Intelligent Context Proxy",
    description="Transparent proxy between Claude Code and Anthropic API with intelligence injection",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================================
# Response Consumer (Background Task)
# ============================================================================


async def consume_responses():
    """
    Background task to consume response events from Kafka.

    Listens for:
    - context.response.completed.v1 (successful responses)
    - context.failed.v1 (error responses)

    Resolves pending request futures when responses arrive.
    """
    global kafka_consumer, pending_requests

    logger.info("Response consumer started")

    try:
        async for message in kafka_consumer:
            try:
                event = message.value
                correlation_id = event.get("correlation_id")
                event_type = event.get("event_type")
                payload = event.get("payload", {})

                logger.debug(f"Received response event: {event_type} (correlation_id={correlation_id})")

                # Check if there's a pending request for this correlation_id
                if correlation_id in pending_requests:
                    future = pending_requests[correlation_id]

                    if event_type == EventType.RESPONSE_COMPLETED.value:
                        # Successful response
                        future.set_result(payload)
                    elif event_type == EventType.FAILED.value:
                        # Error response
                        error_message = payload.get("error_message", "Unknown error")
                        future.set_exception(Exception(error_message))

                    # Clean up
                    del pending_requests[correlation_id]

            except Exception as e:
                logger.error(f"Error processing response event: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Response consumer failed: {e}", exc_info=True)


# ============================================================================
# Proxy Endpoints
# ============================================================================


@app.post("/v1/messages")
async def proxy_messages(request: Request) -> Response:
    """
    Proxy endpoint for Claude Code requests.

    Flow:
    1. Receive HTTP request from Claude Code
    2. Extract OAuth token from headers
    3. Publish event to Kafka (context.request.received.v1)
    4. NodeContextRequestReducer consumes event (FSM: idle → request_received)
    5. NodeContextProxyOrchestrator coordinates workflow
    6. Wait for response event (context.response.completed.v1)
    7. Return response to Claude Code

    Args:
        request: FastAPI request object

    Returns:
        Modified response from Anthropic API
    """
    global kafka_producer, pending_requests

    if not kafka_producer:
        raise HTTPException(status_code=503, detail="Kafka producer not available")

    try:
        # Read request body
        body = await request.body()
        request_data = json.loads(body) if body else {}

        # Extract OAuth token from headers
        oauth_token = request.headers.get("authorization", "")
        if not oauth_token:
            raise HTTPException(status_code=401, detail="Missing authorization header")

        # Generate correlation ID
        correlation_id = str(uuid4())

        logger.info(f"Received proxy request (correlation_id={correlation_id})")

        # Create event envelope
        event = ContextRequestReceivedEvent(
            correlation_id=correlation_id,
            payload={
                "request_data": request_data,
                "oauth_token": oauth_token,
                "correlation_id": correlation_id,
            },
        )

        # Create future for response
        response_future = asyncio.get_running_loop().create_future()
        pending_requests[correlation_id] = response_future

        # Publish event to Kafka
        await kafka_producer.send_and_wait(
            topic=KafkaTopics.CONTEXT_REQUEST_RECEIVED,
            value=event.model_dump(),
            key=correlation_id.encode("utf-8"),
        )

        logger.info(f"Published request event (correlation_id={correlation_id})")

        # Wait for response (with timeout)
        try:
            result = await asyncio.wait_for(response_future, timeout=30.0)

            # Extract response data
            response_data = result.get("response_data", {})

            # Return response to Claude Code
            return JSONResponse(
                content=response_data,
                status_code=200,
                headers={"Content-Type": "application/json"},
            )

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response (correlation_id={correlation_id})")

            # Clean up
            pending_requests.pop(correlation_id, None)

            raise HTTPException(
                status_code=504,
                detail="Proxy timeout - request processing took too long",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in proxy endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        Health status with service availability
    """
    global kafka_producer, kafka_consumer

    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "services": {
            "kafka_producer": "connected" if kafka_producer else "disconnected",
            "kafka_consumer": "connected" if kafka_consumer else "disconnected",
        },
        "pending_requests": len(pending_requests),
    }

    # Check if services are healthy
    if not kafka_producer or not kafka_consumer:
        health_status["status"] = "degraded"

    return health_status


@app.get("/metrics")
async def metrics():
    """
    Metrics endpoint.

    Returns:
        Basic metrics (pending requests, uptime, etc.)
    """
    global pending_requests

    return {
        "pending_requests": len(pending_requests),
        "pending_request_ids": list(pending_requests.keys()),
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Intelligent Context Proxy",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "proxy": "POST /v1/messages",
            "health": "GET /health",
            "metrics": "GET /metrics",
        },
    }


# ============================================================================
# Main entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
        reload=False,
    )
