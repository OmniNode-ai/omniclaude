#!/usr/bin/env python3
"""
OmniClaude FastAPI Application

Main FastAPI application with Prometheus metrics, health checks, and observability.

Features:
- Prometheus metrics endpoint (/metrics)
- Health check endpoint (/health)
- Request instrumentation middleware
- OpenTelemetry integration
- Service health monitoring
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST


# Import Pydantic Settings for configuration
try:
    from config import settings
except ImportError:
    settings = None

# Import Prometheus metrics
from agents.lib.prometheus_metrics import (
    get_metrics_text,
    http_request_counter,
    http_request_duration,
    http_request_size_bytes,
    http_response_size_bytes,
    initialize_metrics,
    service_health_status,
    service_startup_time,
)


logger = logging.getLogger(__name__)

# ============================================================================
# Application Lifecycle
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Handles startup and shutdown logic including:
    - Prometheus metrics initialization
    - Service health status updates
    - Cleanup on shutdown
    """
    # Startup
    logger.info("Starting OmniClaude application...")

    # Initialize Prometheus metrics
    version = app.version
    environment = settings.environment if settings else "production"
    agent_registry_path = (
        settings.agent_registry_path
        if settings
        else "~/.claude/agents/omniclaude/agent-registry.yaml"
    )

    initialize_metrics(
        version=version,
        environment=environment,
        agent_registry_path=agent_registry_path,
    )

    # Record startup time
    service_startup_time.labels(service_name="omniclaude").set(time.time())
    service_health_status.labels(service_name="omniclaude").set(1)

    logger.info(
        f"Application started successfully: version={version}, "
        f"environment={environment}"
    )

    yield

    # Shutdown
    logger.info("Shutting down OmniClaude application...")
    service_health_status.labels(service_name="omniclaude").set(0)
    logger.info("Application shutdown complete")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="OmniClaude",
    description="Multi-provider AI toolkit with agent framework and observability",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ============================================================================
# Middleware
# ============================================================================

# CORS middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request instrumentation middleware
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """
    Middleware to instrument HTTP requests with Prometheus metrics.

    Tracks:
    - Request count by method, endpoint, and status code
    - Request duration by method, endpoint, and status code
    - Request/response sizes by method and endpoint
    """
    # Start timer
    start_time = time.time()

    # Get request size
    request_size = int(request.headers.get("content-length", 0))

    # Process request
    response: Response = await call_next(request)

    # Calculate duration
    duration = time.time() - start_time

    # Extract endpoint and method
    # Use route template instead of raw path to avoid cardinality explosion
    route = request.scope.get("route")
    endpoint = getattr(route, "path", request.url.path)
    method = request.method
    status_code = response.status_code

    # Get response size
    response_size = int(response.headers.get("content-length", 0))

    # Record metrics (skip /metrics and /health endpoints to avoid metric explosion)
    if endpoint not in ["/metrics", "/health"]:
        http_request_counter.labels(
            method=method, endpoint=endpoint, status_code=status_code
        ).inc()

        http_request_duration.labels(
            method=method, endpoint=endpoint, status_code=status_code
        ).observe(duration)

        if request_size > 0:
            http_request_size_bytes.labels(method=method, endpoint=endpoint).observe(
                request_size
            )

        if response_size > 0:
            http_response_size_bytes.labels(method=method, endpoint=endpoint).observe(
                response_size
            )

    return response


# ============================================================================
# Routes
# ============================================================================


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint - API information.

    Returns:
        dict: API information and available endpoints
    """
    return {
        "name": "OmniClaude",
        "version": app.version,
        "description": "Multi-provider AI toolkit with agent framework",
        "endpoints": {
            "health": "/health",
            "metrics": "/metrics",
            "docs": "/docs",
            "redoc": "/redoc",
        },
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.

    Returns:
        dict: Health status information

    Status Codes:
        200: Service is healthy
        503: Service is unhealthy
    """
    # TODO: Add actual health checks for dependencies
    # - Database connectivity
    # - Kafka connectivity
    # - Cache connectivity
    # - Qdrant connectivity

    return {
        "status": "healthy",
        "service": "omniclaude",
        "version": app.version,
        "timestamp": time.time(),
    }


@app.get("/metrics", response_class=PlainTextResponse, tags=["Metrics"])
async def metrics():
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text-based exposition format for scraping.

    Returns:
        PlainTextResponse: Prometheus metrics in text format

    Example Response:
        # HELP omniclaude_http_request_total Total number of HTTP requests
        # TYPE omniclaude_http_request_total counter
        omniclaude_http_request_total{method="GET",endpoint="/api/v1/health",status_code="200"} 42.0

        # HELP omniclaude_http_request_duration_seconds HTTP request duration
        # TYPE omniclaude_http_request_duration_seconds histogram
        omniclaude_http_request_duration_seconds_bucket{method="GET",endpoint="/api/v1/health",status_code="200",le="0.005"} 40.0
        ...
    """
    return Response(
        content=get_metrics_text(),
        media_type=CONTENT_TYPE_LATEST,
    )


# ============================================================================
# API v1 Routes (Placeholder for future endpoints)
# ============================================================================

# TODO: Add API v1 routes
# - Agent routing endpoints
# - Action logging endpoints
# - Manifest injection endpoints
# - Intelligence query endpoints


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handle 404 errors with custom response."""
    return {
        "error": "Not Found",
        "message": f"The requested path '{request.url.path}' was not found",
        "status_code": 404,
    }


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Handle 500 errors with custom response."""
    logger.error(f"Internal server error: {exc}", exc_info=True)
    return {
        "error": "Internal Server Error",
        "message": "An unexpected error occurred",
        "status_code": 500,
    }


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # Development server configuration
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104  # Bind to all interfaces for Docker development
        port=8000,
        reload=True,
        log_level="info",
    )
