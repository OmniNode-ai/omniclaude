# Intelligent Context Management Proxy

**Status**: Phase 1 - Foundation (Implementation in Progress)
**Version**: 1.0.0
**Created**: 2025-11-09

---

## Overview

The **Intelligent Context Management Proxy** is a revolutionary service that sits transparently between Claude Code and Anthropic's API, providing complete control over conversation context while integrating with OmniClaude's full intelligence infrastructure.

## Key Features

- ✅ **Infinite conversations** - Never hit 200K token limit, never compact
- ✅ **Intelligence injection** - 50K+ tokens from Qdrant, PostgreSQL, Memgraph, Memory
- ✅ **Context control** - Prune stale messages, keep relevant ones
- ✅ **Graceful degradation** - Hook-based memory still works if proxy down
- ✅ **OAuth transparent** - Passes through Claude Code authentication
- ✅ **Pattern learning** - System improves from every conversation
- ✅ **Event-driven** - Kafka/Redpanda for scalable, distributed architecture

## Architecture

### Event-Driven ONEX with FSM Pattern

```
FastAPI Entry (HTTP) → Reducer (FSM State) → Orchestrator (Workflow) → Nodes (Execution)
```

**5 ONEX Nodes**:
1. **NodeContextRequestReducer** (Reducer) - FSM state tracker
2. **NodeContextProxyOrchestrator** (Orchestrator) - Workflow coordinator
3. **NodeIntelligenceQueryEffect** (Effect) - Intelligence queries via Kafka
4. **NodeContextRewriterCompute** (Compute) - Pure context rewriting logic
5. **NodeAnthropicForwarderEffect** (Effect) - HTTP forwarding to Anthropic

### FSM-Driven Pattern

**Reducer Role**:
- Consumes ALL domain events (*.completed.v1)
- Updates FSM state (idle → request_received → intelligence_queried → context_rewritten → completed)
- Emits persistence intents (PERSIST_STATE)
- Single source of truth for workflow state

**Orchestrator Role**:
- Reads FSM state from Reducer
- Coordinates workflow based on FSM state
- Publishes domain events to trigger node execution
- Drives workflow to completion

## Quick Start

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env

# Required variables:
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
ANTHROPIC_API_URL=https://api.anthropic.com
QDRANT_URL=http://192.168.86.101:6333
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
```

### Deployment

```bash
# Start proxy services
cd deployment
docker-compose -f docker-compose.proxy.yml up -d

# Check health
curl http://localhost:8080/health

# Configure Claude Code to use proxy
export ANTHROPIC_BASE_URL=http://localhost:8080
```

### Testing

```bash
# Run tests
pytest services/intelligent_context_proxy/tests/

# Integration test
python services/intelligent_context_proxy/tests/test_integration.py
```

## Development

### Project Structure

```
services/intelligent_context_proxy/
├── __init__.py               # Package initialization
├── README.md                 # This file
├── main.py                   # FastAPI entry point
├── config.py                 # Service configuration
├── nodes/                    # ONEX node implementations
│   ├── __init__.py
│   ├── node_reducer.py       # FSM state tracker
│   ├── node_orchestrator.py  # Workflow coordinator
│   ├── node_intelligence_query.py  # Intelligence queries
│   ├── node_context_rewriter.py    # Context rewriting
│   └── node_anthropic_forwarder.py # Anthropic forwarding
├── models/                   # Pydantic data models
│   ├── __init__.py
│   ├── event_envelope.py     # Event envelope models
│   ├── fsm_state.py          # FSM state models
│   └── contracts.py          # ONEX contracts
├── schemas/                  # API schemas
│   ├── __init__.py
│   └── anthropic.py          # Anthropic API schemas
├── utils/                    # Utility functions
│   ├── __init__.py
│   ├── token_counter.py      # Token estimation
│   └── message_pruner.py     # Message pruning logic
└── tests/                    # Test suite
    ├── __init__.py
    ├── test_main.py
    ├── test_reducer.py
    ├── test_orchestrator.py
    └── test_integration.py
```

### Implementation Phases

**Phase 1: Foundation** (Days 1-5) - ✅ IN PROGRESS
- FastAPI entry point with Kafka event publishing
- Event envelope models
- Reducer skeleton (FSM state tracking)
- Orchestrator skeleton (round-trip event flow)
- Docker deployment configuration

**Phase 2: Node Implementations** (Days 6-12)
- Complete all 5 ONEX nodes
- Event-driven communication
- Error handling and fallbacks
- Testing and optimization

**Phase 3: Integration & Testing** (Days 13-17)
- Claude Code integration
- Hook enhancement
- Intelligence integration
- End-to-end testing

**Phase 4: Learning & Optimization** (Days 18-22)
- Response capture
- Pattern learning
- Caching layer
- Performance optimization

**Phase 5: Production Hardening** (Days 23-28)
- Error handling
- Monitoring & alerting
- Load testing
- Documentation
- Security review

## Performance Targets

| Operation | Target | Acceptable | Critical |
|-----------|--------|------------|----------|
| FastAPI → Orchestrator | <10ms | <50ms | >100ms |
| Intelligence queries | <2000ms | <3000ms | >5000ms |
| Context rewriting | <100ms | <200ms | >500ms |
| Anthropic forwarding | <500ms | <1000ms | >2000ms |
| Total overhead | <3000ms | <5000ms | >10000ms |

## Reused Components

The proxy **REUSES** existing code (no reimplementation):
- ✅ `agents/lib/manifest_injector.py` (3300 LOC) - Intelligence queries
- ✅ `agents/lib/intelligence_event_client.py` - Kafka event bus
- ✅ `claude_hooks/lib/memory/` - Memory storage
- ✅ `claude_hooks/lib/intent_extractor.py` - Intent extraction

## Documentation

- **Architecture Spec**: See project root planning document
- **ONEX Patterns**: `agents/polymorphic-agent.md`
- **Configuration**: `config/README.md`
- **Deployment**: `deployment/README.md`
- **Event Bus**: `docs/architecture/EVENT_BUS_ARCHITECTURE.md`

## Support

For issues or questions:
1. Check this README
2. Review the architecture specification document
3. Check logs: `docker-compose -f deployment/docker-compose.proxy.yml logs -f`
4. Open an issue in the repository

---

**Last Updated**: 2025-11-09
**Status**: Phase 1 Implementation
**Next Milestone**: Complete FastAPI entry point and Reducer FSM state tracking
