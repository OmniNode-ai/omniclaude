#!/usr/bin/env python3
"""
Agent Router Service Launcher
Starts the FastAPI router service with uvicorn

Usage:
    python3 run_router_service.py

Environment Variables:
    HOST: Bind address (default: 0.0.0.0)
    PORT: Bind port (default: 8055)
    LOG_LEVEL: Logging level (default: info)
    WORKERS: Number of worker processes (default: 1)
"""

import logging
import os
import signal
import sys

import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum} - shutting down gracefully")
    sys.exit(0)


def main():
    """Launch uvicorn server"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8055"))
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    workers = int(os.getenv("WORKERS", "1"))

    logger.info("=" * 60)
    logger.info("Starting Agent Router Service")
    logger.info("=" * 60)
    logger.info(f"  Host: {host}")
    logger.info(f"  Port: {port}")
    logger.info(f"  Log Level: {log_level}")
    logger.info(f"  Workers: {workers}")
    logger.info("=" * 60)

    try:
        # Start uvicorn server
        uvicorn.run(
            "agent_router_service:app",
            host=host,
            port=port,
            log_level=log_level,
            workers=workers,
            reload=False,  # Set to True for development
            access_log=True,
        )
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.exception(f"Service failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
