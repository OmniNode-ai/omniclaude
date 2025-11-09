#!/usr/bin/env python3
"""
Service Runner for Intelligent Context Proxy

Starts all required components:
1. NodeContextRequestReducer (FSM state tracker)
2. NodeContextProxyOrchestrator (workflow coordinator)
3. FastAPI entry point (HTTP server)

Usage:
    python run.py

    # Or with uvicorn directly:
    uvicorn services.intelligent_context_proxy.main:app --host 0.0.0.0 --port 8080

Note:
    The Reducer and Orchestrator run as background tasks within FastAPI.
    This ensures they share the same process and can reference each other.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.intelligent_context_proxy.nodes.node_reducer import NodeContextRequestReducer
from services.intelligent_context_proxy.nodes.node_orchestrator import (
    NodeContextProxyOrchestrator,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_all_services():
    """
    Run all services concurrently.

    Services:
    1. NodeContextRequestReducer - FSM state tracker
    2. NodeContextProxyOrchestrator - Workflow coordinator
    """
    logger.info("Starting all services...")

    # Create reducer (FSM state tracker)
    reducer = NodeContextRequestReducer()

    # Create orchestrator (with reducer reference)
    orchestrator = NodeContextProxyOrchestrator(reducer=reducer)

    try:
        # Start both nodes
        await reducer.start()
        await orchestrator.start()

        logger.info("✅ All services started successfully")
        logger.info("📡 Reducer listening for events...")
        logger.info("🎯 Orchestrator ready to coordinate workflows...")

        # Run both event loops concurrently
        await asyncio.gather(reducer.run(), orchestrator.run())

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Shutting down services...")
        await orchestrator.stop()
        await reducer.stop()
        logger.info("All services stopped")


def main():
    """Main entry point."""
    logger.info("=" * 80)
    logger.info("Intelligent Context Proxy - Service Runner")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Starting services:")
    logger.info("  1. NodeContextRequestReducer (FSM state tracker)")
    logger.info("  2. NodeContextProxyOrchestrator (workflow coordinator)")
    logger.info("")
    logger.info("Note: FastAPI entry point should be started separately:")
    logger.info("  uvicorn services.intelligent_context_proxy.main:app --host 0.0.0.0 --port 8080")
    logger.info("")
    logger.info("=" * 80)
    logger.info("")

    try:
        asyncio.run(run_all_services())
    except KeyboardInterrupt:
        logger.info("\nShutdown complete")


if __name__ == "__main__":
    main()
