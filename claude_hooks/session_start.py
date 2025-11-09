#!/Users/jonah/Library/Caches/pypoetry/virtualenvs/omniclaude-agents-kzVi5DqF-py3.12/bin/python
"""
Session-Start Hook

This hook runs once when a Claude Code session starts.
It initializes the workspace state in memory without requiring file arguments.

Flow:
1. Collect workspace state (branch, modified files, etc.)
2. Store in memory for later use
3. Return success

Performance Target: <100ms
"""

import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Add project root to path - MUST use .resolve() to follow symlinks!
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from claude_hooks.lib.memory_client import get_memory_client
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_workspace_state() -> Dict[str, Any]:
    """Collect current workspace state"""
    try:
        # Get git information
        try:
            branch = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=os.getcwd()
            ).strip()
        except:
            branch = "unknown"

        try:
            modified_files = subprocess.check_output(
                ['git', 'status', '--porcelain'],
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=os.getcwd()
            ).strip().split('\n')
            modified_files = [f.strip() for f in modified_files if f.strip()]
        except:
            modified_files = []

        try:
            last_commit = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=os.getcwd()
            ).strip()
        except:
            last_commit = "unknown"

        return {
            "branch": branch,
            "modified_files": modified_files[:20],
            "modified_file_count": len(modified_files),
            "last_commit": last_commit,
            "timestamp": datetime.utcnow().isoformat(),
            "cwd": os.getcwd(),
            "session_start": True
        }
    except Exception as e:
        logger.error(f"Failed to collect workspace state: {e}")
        return {
            "branch": "unknown",
            "modified_files": [],
            "modified_file_count": 0,
            "last_commit": "unknown",
            "timestamp": datetime.utcnow().isoformat(),
            "cwd": os.getcwd(),
            "session_start": True,
            "error": str(e)
        }


async def initialize_session() -> None:
    """Initialize session state in memory"""
    memory = get_memory_client()

    try:
        workspace_state = await get_workspace_state()
        await memory.store_memory(
            key="workspace_state",
            value=workspace_state,
            category="workspace",
            metadata={"updated_by": "session_start_hook", "session_start": True}
        )

        await memory.store_memory(
            key="session_info",
            value={
                "start_time": datetime.utcnow().isoformat(),
                "cwd": os.getcwd(),
                "branch": workspace_state.get("branch", "unknown")
            },
            category="workspace",
            metadata={"session_start": True}
        )

        logger.info(f"Session initialized: branch={workspace_state.get('branch')}")

    except Exception as e:
        logger.error(f"Failed to initialize session: {e}")


async def main() -> None:
    """Main hook execution"""
    start_time = datetime.utcnow()

    try:
        if not settings.enable_memory_client:
            logger.info("Memory client disabled, skipping session initialization")
            return

        await initialize_session()

        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.info(f"Session start hook completed in {duration_ms:.0f}ms")

        if duration_ms > 100:
            logger.warning(f"Hook exceeded 100ms target: {duration_ms:.0f}ms")

    except Exception as e:
        logger.error(f"Session start hook failed: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
        logger.info("Session start hook completed successfully")
    except Exception as e:
        logger.error(f"Session start hook failed: {e}")
        sys.exit(0)
