#!/usr/bin/env python3
"""
Workspace-Change Hook (Background)

This hook monitors file changes in the workspace and updates memory
with project context. It runs in the background and is non-blocking.

Triggers:
- File creation/modification/deletion
- Git commits
- Directory changes

Updates:
- File context (type, dependencies, last modified)
- Project structure
- Change history

Performance Target: <20ms per file (background, non-blocking)
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from claude_hooks.lib.memory_client import get_memory_client
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_file_type(file_path: str) -> str:
    """Determine file type from extension"""

    ext = Path(file_path).suffix.lower()

    type_map = {
        # Code
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'react',
        '.tsx': 'react-typescript',
        '.java': 'java',
        '.go': 'go',
        '.rs': 'rust',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'header',

        # Config
        '.yaml': 'config',
        '.yml': 'config',
        '.json': 'config',
        '.toml': 'config',
        '.ini': 'config',
        '.env': 'config',

        # Documentation
        '.md': 'documentation',
        '.rst': 'documentation',
        '.txt': 'documentation',

        # Build/Deploy
        '.sh': 'script',
        '.bash': 'script',
        'Dockerfile': 'docker',
        'docker-compose.yml': 'docker',
        'Makefile': 'build',

        # Data
        '.sql': 'database',
        '.db': 'database',
        '.csv': 'data',
        '.xml': 'data',
    }

    return type_map.get(ext, 'unknown')


def extract_dependencies(file_path: str, content: str) -> List[str]:
    """Extract dependencies from file content (simple heuristic)"""

    dependencies = []

    # Python imports
    if file_path.endswith('.py'):
        import re
        imports = re.findall(r'^import\s+([\w.]+)', content, re.MULTILINE)
        from_imports = re.findall(r'^from\s+([\w.]+)\s+import', content, re.MULTILINE)
        dependencies.extend(imports)
        dependencies.extend(from_imports)

    # JavaScript/TypeScript imports
    elif file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
        import re
        imports = re.findall(r'import.*from\s+[\'"]([^\'"]+)[\'"]', content)
        dependencies.extend(imports)

    # Remove duplicates and limit to first 10
    return list(set(dependencies))[:10]


async def analyze_file_context(file_path: str) -> Dict[str, Any]:
    """Analyze file and extract context"""

    try:
        path = Path(file_path)

        if not path.exists():
            return {
                "type": "deleted",
                "exists": False,
                "timestamp": datetime.utcnow().isoformat()
            }

        # Read file content (limit to 100KB for analysis)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(100000)
        except:
            content = ""

        # Get file stats
        stats = path.stat()

        # Calculate content hash
        content_hash = hashlib.md5(content.encode()).hexdigest()

        # Extract dependencies
        dependencies = extract_dependencies(file_path, content)

        return {
            "type": analyze_file_type(file_path),
            "exists": True,
            "size_bytes": stats.st_size,
            "modified_time": datetime.fromtimestamp(stats.st_mtime).isoformat(),
            "content_hash": content_hash,
            "dependencies": dependencies,
            "line_count": len(content.split('\n')),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to analyze file {file_path}: {e}")
        return {
            "type": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


async def store_file_change_event(
    files: List[str],
    change_type: str = "modified"
) -> None:
    """Store file change event in memory"""

    memory = get_memory_client()

    try:
        # Create change event
        event_id = f"file_change_{int(datetime.utcnow().timestamp())}"
        event = {
            "files": files,
            "change_type": change_type,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Store event
        await memory.store_memory(
            key=event_id,
            value=event,
            category="workspace_events",
            metadata={"change_type": change_type, "file_count": len(files)}
        )

        logger.info(f"Stored file change event: {len(files)} files {change_type}")

    except Exception as e:
        logger.error(f"Failed to store file change event: {e}")


async def update_file_context(file_path: str) -> None:
    """Update memory with file context"""

    memory = get_memory_client()

    try:
        # Analyze file
        context = await analyze_file_context(file_path)

        # Create key (sanitize file path)
        safe_path = file_path.replace('/', '_').replace('\\', '_').replace('.', '_')
        context_key = f"file_context_{safe_path}"

        # Store context
        await memory.store_memory(
            key=context_key,
            value=context,
            category="workspace",
            metadata={"file_path": file_path, "file_type": context.get("type")}
        )

        logger.info(f"Updated file context: {file_path} (type: {context.get('type')})")

    except Exception as e:
        logger.error(f"Failed to update file context for {file_path}: {e}")


async def update_project_context(files: List[str]) -> None:
    """Update overall project context based on changed files"""

    memory = get_memory_client()

    try:
        # Get current project context
        project_ctx = await memory.get_memory("project_context", "workspace") or {}

        # Update file count by type
        file_types = project_ctx.get("file_types", {})

        for file_path in files:
            file_type = analyze_file_type(file_path)
            file_types[file_type] = file_types.get(file_type, 0) + 1

        project_ctx["file_types"] = file_types
        project_ctx["last_updated"] = datetime.utcnow().isoformat()
        project_ctx["total_files_tracked"] = sum(file_types.values())

        # Store updated project context
        await memory.store_memory(
            key="project_context",
            value=project_ctx,
            category="workspace"
        )

        logger.info(f"Updated project context: {project_ctx['total_files_tracked']} files tracked")

    except Exception as e:
        logger.error(f"Failed to update project context: {e}")


async def main(changed_files: List[str], change_type: str = "modified") -> None:
    """
    Main hook execution (background)

    Args:
        changed_files: List of file paths that changed
        change_type: Type of change (created, modified, deleted)
    """
    start_time = datetime.utcnow()

    try:
        # Check if memory client is enabled
        if not settings.enable_memory_client:
            logger.info("Memory client disabled, skipping workspace tracking")
            return

        # Store file change event
        await store_file_change_event(changed_files, change_type)

        # Update context for each file (in parallel)
        tasks = [update_file_context(file) for file in changed_files]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Update overall project context
        await update_project_context(changed_files)

        # Log performance
        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        avg_per_file = duration_ms / len(changed_files) if changed_files else 0
        logger.info(f"Hook completed in {duration_ms:.0f}ms ({avg_per_file:.0f}ms per file)")

        if avg_per_file > 20:
            logger.warning(f"Hook exceeded 20ms/file target: {avg_per_file:.0f}ms")

    except Exception as e:
        logger.error(f"Hook failed: {e}", exc_info=True)


if __name__ == "__main__":
    # Parse arguments: file1 [file2 file3 ...] [--type=created|modified|deleted]
    if len(sys.argv) < 2:
        logger.error("Usage: workspace_change.py <file1> [file2 ...] [--type=created|modified|deleted]")
        sys.exit(1)

    # Parse arguments
    files = []
    change_type = "modified"

    for arg in sys.argv[1:]:
        if arg.startswith('--type='):
            change_type = arg.split('=')[1]
        else:
            files.append(arg)

    if not files:
        logger.error("No files specified")
        sys.exit(1)

    # Run async main (background mode)
    try:
        asyncio.run(main(files, change_type))
        logger.info(f"Workspace tracking complete for {len(files)} files")
    except Exception as e:
        logger.error(f"Background tracking failed: {e}")
        # Don't fail - this is background processing
