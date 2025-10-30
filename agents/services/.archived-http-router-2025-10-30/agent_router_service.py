#!/usr/bin/env python3
"""
Agent Router REST Service
FastAPI-based synchronous routing service for agent selection

This service provides HTTP endpoints for agent routing:
- POST /route: Route user request to optimal agent
- GET /health: Service health and statistics

Target response time: <50ms
Fallback: Always returns polymorphic-agent on failure
"""

import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Add lib directory to Python path for AgentRouter imports
lib_path = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_path))

try:
    from agent_router import AgentRecommendation, AgentRouter
except ImportError as e:
    logging.error(f"Failed to import AgentRouter: {e}")
    logging.error(f"Python path: {sys.path}")
    raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Agent Router Service",
    description="REST API for intelligent agent routing with confidence scoring",
    version="1.0.0",
)

# CORS configuration for localhost access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global router instance
router: Optional[AgentRouter] = None
service_start_time = time.time()


# Request/Response Models
class RouteRequest(BaseModel):
    """Request to route user input to agent"""

    user_request: str = Field(
        ...,
        description="User's input text to route",
        min_length=1,
        max_length=10000,
    )
    context: Optional[Dict] = Field(
        default=None,
        description="Optional execution context (domain, previous_agent, etc.)",
    )
    max_recommendations: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum number of agent recommendations to return",
    )


class ConfidenceBreakdown(BaseModel):
    """Detailed confidence scoring breakdown"""

    total: float = Field(..., description="Overall confidence score (0.0-1.0)")
    trigger_score: float = Field(..., description="Trigger match score")
    context_score: float = Field(..., description="Context alignment score")
    capability_score: float = Field(..., description="Capability match score")
    historical_score: float = Field(..., description="Historical performance score")
    explanation: str = Field(..., description="Human-readable explanation")


class AgentRecommendationResponse(BaseModel):
    """Agent recommendation with confidence details"""

    agent_name: str = Field(..., description="Internal agent identifier")
    agent_title: str = Field(..., description="Human-readable agent title")
    confidence: ConfidenceBreakdown = Field(..., description="Confidence breakdown")
    reason: str = Field(..., description="Primary match reason")
    definition_path: str = Field(..., description="Path to agent definition file")


class RouteResponse(BaseModel):
    """Response with agent routing recommendation"""

    agent_name: str = Field(..., description="Selected agent identifier")
    agent_title: str = Field(..., description="Human-readable agent title")
    confidence: float = Field(..., description="Overall confidence score (0.0-1.0)")
    confidence_breakdown: ConfidenceBreakdown = Field(
        ..., description="Detailed confidence scores"
    )
    reason: str = Field(..., description="Why this agent was selected")
    alternatives: List[AgentRecommendationResponse] = Field(
        default=[], description="Alternative agent recommendations"
    )
    routing_time_ms: float = Field(..., description="Time taken to route request (ms)")


class HealthResponse(BaseModel):
    """Service health and statistics"""

    status: str = Field(
        ..., description="Service status: healthy | degraded | unhealthy"
    )
    uptime_seconds: float = Field(..., description="Service uptime in seconds")
    agent_count: int = Field(..., description="Number of agents in registry")
    cache_size: int = Field(..., description="Number of cached routing decisions")
    cache_hit_rate: float = Field(..., description="Cache hit rate (0.0-1.0)")
    routing_stats: Dict = Field(..., description="Routing performance statistics")


@app.on_event("startup")
async def startup_event():
    """Initialize AgentRouter on startup"""
    global router

    try:
        logger.info("=" * 60)
        logger.info("Agent Router Service Starting")
        logger.info("=" * 60)

        # Default registry path
        registry_path = (
            Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
        )

        if not registry_path.exists():
            logger.error(f"Registry not found at: {registry_path}")
            raise FileNotFoundError(f"Registry not found: {registry_path}")

        logger.info(f"Loading agent registry from: {registry_path}")
        router = AgentRouter(str(registry_path), cache_ttl=3600)

        agent_count = len(router.registry.get("agents", {}))
        logger.info(f"Loaded {agent_count} agents successfully")
        logger.info("=" * 60)
        logger.info("Service ready on port 8055")
        logger.info("  POST /route - Route user request to agent")
        logger.info("  GET /health - Service health and statistics")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"Failed to initialize AgentRouter: {e}")
        raise


@app.post("/route", response_model=RouteResponse)
async def route_request(request: RouteRequest) -> RouteResponse:
    """
    Route user request to optimal agent with confidence scoring.

    Returns the best matching agent with confidence breakdown and alternatives.
    Always returns a valid response (falls back to polymorphic-agent on error).

    Target response time: <50ms
    """
    start_time = time.time()

    try:
        if router is None:
            raise HTTPException(
                status_code=503, detail="Router not initialized - service starting up"
            )

        # Route request
        recommendations = router.route(
            user_request=request.user_request,
            context=request.context,
            max_recommendations=request.max_recommendations,
        )

        routing_time_ms = (time.time() - start_time) * 1000

        # Handle no recommendations (fallback)
        if not recommendations:
            logger.warning(
                f"No recommendations for request: {request.user_request[:100]}..."
            )
            return _create_fallback_response(routing_time_ms)

        # Primary recommendation
        primary = recommendations[0]

        # Build response
        response = RouteResponse(
            agent_name=primary.agent_name,
            agent_title=primary.agent_title,
            confidence=primary.confidence.total,
            confidence_breakdown=ConfidenceBreakdown(
                total=primary.confidence.total,
                trigger_score=primary.confidence.trigger_score,
                context_score=primary.confidence.context_score,
                capability_score=primary.confidence.capability_score,
                historical_score=primary.confidence.historical_score,
                explanation=primary.confidence.explanation,
            ),
            reason=primary.reason,
            alternatives=[
                AgentRecommendationResponse(
                    agent_name=rec.agent_name,
                    agent_title=rec.agent_title,
                    confidence=ConfidenceBreakdown(
                        total=rec.confidence.total,
                        trigger_score=rec.confidence.trigger_score,
                        context_score=rec.confidence.context_score,
                        capability_score=rec.confidence.capability_score,
                        historical_score=rec.confidence.historical_score,
                        explanation=rec.confidence.explanation,
                    ),
                    reason=rec.reason,
                    definition_path=rec.definition_path,
                )
                for rec in recommendations[1:]
            ],
            routing_time_ms=routing_time_ms,
        )

        logger.info(
            f"Routed request to {primary.agent_name} "
            f"({primary.confidence.total:.2%} confidence) "
            f"in {routing_time_ms:.1f}ms"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Routing failed: {e}")
        routing_time_ms = (time.time() - start_time) * 1000
        return _create_fallback_response(routing_time_ms)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Get service health and statistics.

    Returns service status, uptime, agent count, and routing performance metrics.
    """
    try:
        if router is None:
            return HealthResponse(
                status="unhealthy",
                uptime_seconds=time.time() - service_start_time,
                agent_count=0,
                cache_size=0,
                cache_hit_rate=0.0,
                routing_stats={},
            )

        # Calculate uptime
        uptime = time.time() - service_start_time

        # Get statistics
        routing_stats = router.get_routing_stats()
        cache_stats = router.get_cache_stats()
        agent_count = len(router.registry.get("agents", {}))

        # Determine health status
        cache_hit_rate = cache_stats.get("cache_hit_rate", 0.0)
        status = "healthy"
        if agent_count == 0:
            status = "unhealthy"
        elif cache_hit_rate < 0.3 and routing_stats["total_routes"] > 100:
            status = "degraded"

        return HealthResponse(
            status=status,
            uptime_seconds=uptime,
            agent_count=agent_count,
            cache_size=cache_stats.get("cache_size", 0),
            cache_hit_rate=cache_hit_rate,
            routing_stats=routing_stats,
        )

    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            uptime_seconds=time.time() - service_start_time,
            agent_count=0,
            cache_size=0,
            cache_hit_rate=0.0,
            routing_stats={"error": str(e)},
        )


def _create_fallback_response(routing_time_ms: float) -> RouteResponse:
    """
    Create fallback response when routing fails.

    Always returns polymorphic-agent as a safe default.
    """
    return RouteResponse(
        agent_name="polymorphic-agent",
        agent_title="Polymorphic Agent (Fallback)",
        confidence=0.5,
        confidence_breakdown=ConfidenceBreakdown(
            total=0.5,
            trigger_score=0.5,
            context_score=0.5,
            capability_score=0.5,
            historical_score=0.5,
            explanation="Fallback to polymorphic-agent (routing failed)",
        ),
        reason="Routing failed - using fallback agent",
        alternatives=[],
        routing_time_ms=routing_time_ms,
    )


# Health check for readiness probe
@app.get("/")
async def root():
    """Root endpoint - basic service info"""
    return {
        "service": "agent-router",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "route": "POST /route",
            "health": "GET /health",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8055, log_level="info")
