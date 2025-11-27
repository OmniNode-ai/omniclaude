#!/usr/bin/env python3
"""
Archon MCP Intelligence Executor
Executes RAG queries and intelligence gathering via Archon MCP.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx


# Add project root to path for config import
project_root = (
    Path(__file__).resolve().parents[2]
)  # lib → claude_hooks → omniclaude root
sys.path.insert(0, str(project_root))

from config import settings


class ArchonIntelligence:
    """Executes intelligence gathering via Archon MCP server."""

    def __init__(self, archon_url: Optional[str] = None, timeout: float = 5.0):
        """
        Initialize Archon Intelligence client.

        Args:
            archon_url: Archon MCP server URL (defaults to settings)
            timeout: Request timeout in seconds
        """
        self.archon_url = archon_url or settings.archon_mcp_url
        self.timeout = timeout

    async def gather_debug_intelligence(
        self, agent_type: str, task_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute IC-001: gather_debug_intelligence

        Learn from previous debugging sessions, error encounters, and successful resolutions.

        Args:
            agent_type: Type of agent executing
            task_context: Context of the task

        Returns:
            Debug intelligence from previous sessions
        """
        query = (
            f"debugging errors failures {agent_type} {task_context.get('domain', '')}"
        )

        return await self._execute_rag_query(
            query=query, context="debugging", match_count=5
        )

    async def gather_domain_standards(
        self, agent_type: str, task_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute IC-002: gather_domain_standards

        Ensure compliance with established standards, patterns, and best practices.

        Args:
            agent_type: Type of agent executing
            task_context: Context of the task

        Returns:
            Domain standards and best practices
        """
        query = f"standards best practices patterns {agent_type} {task_context.get('domain', '')}"

        return await self._execute_rag_query(
            query=query, context="general", match_count=5
        )

    async def gather_performance_quality_intelligence(
        self, agent_type: str, task_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute IC-003: gather_performance_quality_intelligence

        Apply performance optimization and quality improvement patterns.

        Args:
            agent_type: Type of agent executing
            task_context: Context of the task

        Returns:
            Performance and quality optimization patterns
        """
        query = f"performance optimization quality {agent_type} {task_context.get('domain', '')}"

        return await self._execute_rag_query(
            query=query, context="general", match_count=5
        )

    async def gather_collaboration_intelligence(
        self, agent_type: str, task_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute IC-004: gather_collaboration_intelligence

        Leverage insights from other agents and coordination patterns.

        Args:
            agent_type: Type of agent executing
            task_context: Context of the task

        Returns:
            Multi-agent coordination patterns
        """
        query = f"agent coordination collaboration patterns {agent_type}"

        return await self._execute_rag_query(
            query=query, context="architecture", match_count=3
        )

    async def gather_all_intelligence(
        self, agent_type: str, task_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute all intelligence gathering functions in parallel.

        Args:
            agent_type: Type of agent executing
            task_context: Context of the task

        Returns:
            Combined intelligence from all sources
        """
        results = await asyncio.gather(
            self.gather_debug_intelligence(agent_type, task_context),
            self.gather_domain_standards(agent_type, task_context),
            self.gather_performance_quality_intelligence(agent_type, task_context),
            self.gather_collaboration_intelligence(agent_type, task_context),
            return_exceptions=True,
        )

        return {
            "debug_intelligence": (
                results[0] if not isinstance(results[0], Exception) else {}
            ),
            "domain_standards": (
                results[1] if not isinstance(results[1], Exception) else {}
            ),
            "performance_quality": (
                results[2] if not isinstance(results[2], Exception) else {}
            ),
            "collaboration": (
                results[3] if not isinstance(results[3], Exception) else {}
            ),
        }

    async def _execute_rag_query(
        self, query: str, context: str, match_count: int = 5
    ) -> Dict[str, Any]:
        """
        Execute RAG query against Archon MCP server.

        Args:
            query: Search query
            context: Query context (debugging, general, architecture, etc.)
            match_count: Number of results to return

        Returns:
            RAG query results with intelligence
        """
        url = f"{self.archon_url}/api/rag/query"

        payload = {"query": query, "context": context, "match_count": match_count}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result: Dict[str, Any] = response.json()
                return result
        except httpx.TimeoutException:
            print(f"RAG query timeout: {query[:50]}...", file=sys.stderr)
            return {"error": "timeout", "query": query}
        except httpx.HTTPError as e:
            print(f"RAG query HTTP error: {e}", file=sys.stderr)
            return {"error": str(e), "query": query}
        except Exception as e:
            print(f"RAG query failed: {e}", file=sys.stderr)
            return {"error": str(e), "query": query}


# CLI interface for testing
async def main():
    """Test CLI interface."""
    if len(sys.argv) < 3:
        print("Usage: archon_intelligence.py <agent_type> <domain>", file=sys.stderr)
        sys.exit(1)

    agent_type = sys.argv[1]
    domain = sys.argv[2]

    task_context = {"domain": domain}

    intelligence = ArchonIntelligence()

    print(f"Gathering intelligence for {agent_type} in {domain}...")
    results = await intelligence.gather_all_intelligence(agent_type, task_context)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
