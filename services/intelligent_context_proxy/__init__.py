"""
Intelligent Context Management Proxy

A revolutionary proxy service that sits transparently between Claude Code and
Anthropic's API, providing complete control over conversation context while
integrating with OmniClaude's full intelligence infrastructure.

Architecture:
    - FastAPI HTTP entry point (Claude Code compatibility)
    - Event-driven ONEX architecture (Kafka/Redpanda communication)
    - 5 ONEX nodes (Reducer, Orchestrator, 2 Effects, 1 Compute)
    - FSM-driven pattern (Reducer tracks state → Orchestrator coordinates workflow)

Key Features:
    - Infinite conversations (never compact)
    - 50K+ token intelligence injection (Qdrant, PostgreSQL, Memgraph, Memory)
    - Complete context control (prune stale, keep relevant)
    - Graceful degradation (hooks still work if proxy down)
    - OAuth transparent (no API key needed)
    - Pattern learning (continuous improvement)

Created: 2025-11-09
Version: 1.0.0
Status: Phase 1 - Foundation
"""

__version__ = "1.0.0"
__author__ = "OmniClaude"
__status__ = "Phase 1 - Foundation"
