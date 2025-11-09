#!/usr/bin/env python3
"""
Complete Service Runner for Intelligent Context Proxy

Starts all 5 ONEX nodes:
1. NodeContextRequestReducer - FSM state tracker
2. NodeContextProxyOrchestrator - Workflow coordinator
3. NodeIntelligenceQueryEffect - Intelligence queries
4. NodeContextRewriterCompute - Context rewriting
5. NodeAnthropicForwarderEffect - Anthropic forwarding

Usage:
    python services/intelligent_context_proxy/run_all_nodes.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.intelligent_context_proxy.nodes import (
    NodeContextRequestReducer,
    NodeContextProxyOrchestrator,
    NodeIntelligenceQueryEffect,
    NodeContextRewriterCompute,
    NodeAnthropicForwarderEffect,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_all_nodes():
    """
    Run all 5 ONEX nodes concurrently.

    Nodes:
    1. Reducer - FSM state tracker (consumes all events, updates state)
    2. Orchestrator - Workflow coordinator (reads FSM, coordinates workflow)
    3. Intelligence Query - Queries Qdrant, PostgreSQL, Memory via Kafka
    4. Context Rewriter - Prunes messages, formats manifest, manages tokens
    5. Anthropic Forwarder - Forwards to Anthropic API with OAuth passthrough
    """
    logger.info("=" * 80)
    logger.info("Intelligent Context Proxy - Complete Node Runner")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Starting all 5 ONEX nodes:")
    logger.info("  1. NodeContextRequestReducer (FSM state tracker)")
    logger.info("  2. NodeContextProxyOrchestrator (workflow coordinator)")
    logger.info("  3. NodeIntelligenceQueryEffect (intelligence queries)")
    logger.info("  4. NodeContextRewriterCompute (context rewriting)")
    logger.info("  5. NodeAnthropicForwarderEffect (Anthropic forwarding)")
    logger.info("")
    logger.info("Note: FastAPI entry point should be started separately:")
    logger.info("  uvicorn services.intelligent_context_proxy.main:app --host 0.0.0.0 --port 8080")
    logger.info("")
    logger.info("=" * 80)
    logger.info("")

    # Create all nodes
    reducer = NodeContextRequestReducer()
    orchestrator = NodeContextProxyOrchestrator(reducer=reducer)
    intelligence_query = NodeIntelligenceQueryEffect()
    context_rewriter = NodeContextRewriterCompute()
    anthropic_forwarder = NodeAnthropicForwarderEffect()

    try:
        # Start all nodes
        logger.info("Starting all nodes...")
        await reducer.start()
        await orchestrator.start()
        await intelligence_query.start()
        await context_rewriter.start()
        await anthropic_forwarder.start()

        logger.info("✅ All nodes started successfully")
        logger.info("")
        logger.info("Node Status:")
        logger.info("  ✓ Reducer listening for events...")
        logger.info("  ✓ Orchestrator ready to coordinate workflows...")
        logger.info("  ✓ Intelligence Query ready to query...")
        logger.info("  ✓ Context Rewriter ready to rewrite...")
        logger.info("  ✓ Anthropic Forwarder ready to forward...")
        logger.info("")

        # Run all event loops concurrently
        await asyncio.gather(
            reducer.run(),
            orchestrator.run(),
            intelligence_query.run(),
            context_rewriter.run(),
            anthropic_forwarder.run(),
        )

    except KeyboardInterrupt:
        logger.info("\nReceived interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Shutting down all nodes...")
        await orchestrator.stop()
        await intelligence_query.stop()
        await context_rewriter.stop()
        await anthropic_forwarder.stop()
        await reducer.stop()
        logger.info("All nodes stopped")


def main():
    """Main entry point."""
    try:
        asyncio.run(run_all_nodes())
    except KeyboardInterrupt:
        logger.info("\nShutdown complete")


if __name__ == "__main__":
    main()
