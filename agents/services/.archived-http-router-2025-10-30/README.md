# Archived HTTP-Based Router Service

**Archived Date**: 2025-10-30
**Reason**: Replaced by event-based routing architecture

## Overview

This directory contains the old HTTP-based agent router service that has been replaced by the event-driven architecture using Kafka.

## What Was Archived

### Service Files
- `agent_router_service.py` - FastAPI HTTP service (port 8055)
- `run_router_service.py` - Service launcher script
- `start_router_service.sh` - Docker startup script
- `agent-router-service/` - Service directory with main.py and README

### Testing Files
- `test_router_service.py` - Integration tests for HTTP service
- `benchmark_router.py` - Performance benchmarks for HTTP service

### Docker Files
- `Dockerfile.router` - Docker image for HTTP service
- `requirements.txt` - Python dependencies

## Replacement

The HTTP-based service has been replaced by:

- **Service**: `agent_router_event_service.py` (Kafka consumer)
- **Dockerfile**: `Dockerfile.router-consumer`
- **Architecture**: Event-driven via Kafka topics:
  - `agent.routing.requested.v1` - Routing requests
  - `agent.routing.completed.v1` - Successful routing
  - `agent.routing.failed.v1` - Failed routing

## Why Event-Based?

The migration from HTTP to event-based routing provides:

1. **Better Scalability** - Horizontal scaling with Kafka partitions
2. **Decoupling** - Loose coupling between hook and routing service
3. **Durability** - Messages persisted in Kafka (replay capability)
4. **Observability** - Complete event history for debugging
5. **Resilience** - Service failures don't block hook execution

## Migration Details

- **Hook Updated**: `claude_hooks/user-prompt-submit.sh` now uses `route_via_events_wrapper.py`
- **No HTTP Endpoint**: Port 8055 no longer exposed
- **Database Logging**: Still uses `agent_routing_decisions` table
- **Same Router Logic**: Reuses existing `AgentRouter` class (no logic changes)

## References

- **Documentation**: `docs/HOOK_ROUTER_SERVICE_INTEGRATION.md` (contains HTTP examples - now deprecated)
- **Event Architecture**: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`
- **Implementation**: Phase 2 of event-driven routing architecture

## Notes

- This code is kept for reference only
- Do not use these files in production
- The HTTP service is no longer running or maintained
- All routing now happens via Kafka events

## Contact

For questions about the event-based routing architecture, see:
- `agents/services/agent_router_event_service.py`
- `agents/lib/routing_event_client.py`
