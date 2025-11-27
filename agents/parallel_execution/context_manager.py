"""
Context Manager for Parallel Agent Dispatcher

Handles intelligent context gathering and filtering to provide agents
with focused, relevant information instead of requiring each agent to
gather context independently.

Architecture:
- Phase 0: Global context gathering (once per dispatch)
- Phase 2: Context filtering (per task, based on requirements)

Reduces token usage by 60-80% and eliminates duplicate context gathering.
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .mcp_client import ArchonMCPClient


# Import context optimizer for intelligent context selection
try:
    from agents.lib.context_optimizer import predict_context_needs

    CONTEXT_OPTIMIZER_AVAILABLE = True
except ImportError:
    CONTEXT_OPTIMIZER_AVAILABLE = False


@dataclass
class ContextItem:
    """Single context item with type and content."""

    context_type: str  # "file", "pattern", "rag", "structure"
    key: str  # Identifier (e.g., "file:auth.py", "pattern:jwt-validation")
    content: Any  # Actual content
    tokens_estimate: int  # Estimated token count
    metadata: Dict[str, Any]  # Additional metadata


class ContextManager:
    """
    Manages intelligent context gathering and filtering for parallel agents.

    Features:
    - One-time global context gathering
    - Efficient context filtering per task
    - Support for multiple context types (file, pattern, rag, structure)
    - Token usage optimization
    - Performance target: <200ms overhead
    """

    def __init__(self, mcp_client: Optional[ArchonMCPClient] = None):
        """
        Initialize context manager.

        Args:
            mcp_client: Optional MCP client for RAG queries (creates new if None)
        """
        self.mcp_client = mcp_client or ArchonMCPClient()
        self._owns_mcp_client = mcp_client is None
        self.global_context: Dict[str, ContextItem] = {}
        self._context_cache: Dict[str, Any] = {}

    async def gather_global_context(
        self,
        user_prompt: str,
        workspace_path: Optional[str] = None,
        rag_queries: Optional[List[str]] = None,
        max_rag_results: int = 5,
        enable_optimization: bool = True,
    ) -> Dict[str, ContextItem]:
        """
        Gather comprehensive global context once per dispatch.

        This is Phase 0 of the enhanced dispatcher workflow.

        Args:
            user_prompt: User's original request
            workspace_path: Optional workspace directory for file scanning
            rag_queries: Optional list of RAG queries to execute
            max_rag_results: Maximum results per RAG query

        Returns:
            Dictionary of context items keyed by context identifier
        """
        start_time = time.time()
        context_items: Dict[str, ContextItem] = {}

        # 0. Predictive context gathering (if optimization enabled)
        predicted_queries = []
        if enable_optimization and CONTEXT_OPTIMIZER_AVAILABLE:
            try:
                predicted_queries = await predict_context_needs(user_prompt)
                print(
                    f"[ContextManager] Predicted context needs: {predicted_queries}",
                    file=sys.stderr,
                )
            except Exception as e:
                print(
                    f"[ContextManager] Context prediction failed: {e}", file=sys.stderr
                )

        # Merge predicted queries with provided queries
        if predicted_queries:
            if rag_queries:
                rag_queries = list(set(rag_queries + predicted_queries))
            else:
                rag_queries = predicted_queries

        # 1. RAG Queries for domain patterns and code examples (PARALLEL)
        if rag_queries:
            # Create parallel tasks for RAG queries
            rag_tasks = [
                self._execute_rag_query(query, max_rag_results, "general")
                for query in rag_queries
            ]

            # Execute all RAG queries in parallel
            rag_results = await asyncio.gather(*rag_tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(rag_results):
                query = rag_queries[i]
                if isinstance(result, BaseException):
                    print(f"Warning: RAG query failed for '{query}': {result}")
                elif isinstance(result, dict):
                    # Store RAG result as context item
                    key = f"rag:{query[:50]}"  # Truncate for key
                    context_items[key] = ContextItem(
                        context_type="rag",
                        key=key,
                        content=result,
                        tokens_estimate=self._estimate_tokens(result),
                        metadata={
                            "query": query,
                            "result_count": len(result.get("results", [])),
                            "timestamp": time.time(),
                        },
                    )

        # 2-4. Parallel execution of default RAG, file scanning, and pattern recognition
        parallel_tasks: List[Any] = []

        # Default domain pattern query
        parallel_tasks.append(
            self._execute_default_rag_query(user_prompt, max_rag_results)
        )

        # File system scanning (if workspace provided)
        if workspace_path:
            parallel_tasks.append(self._scan_workspace(workspace_path))
        else:
            parallel_tasks.append(self._create_empty_result())

        # Pattern recognition
        parallel_tasks.append(self._execute_pattern_recognition())

        # Execute all tasks in parallel
        parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)

        # Process results
        default_rag_result = parallel_results[0]
        file_scan_result = parallel_results[1] if workspace_path else None
        pattern_result = parallel_results[2] if workspace_path else parallel_results[1]

        # Handle default RAG result
        if not isinstance(default_rag_result, BaseException):
            key = "rag:domain-patterns"
            context_items[key] = ContextItem(
                context_type="rag",
                key=key,
                content=default_rag_result["content"],
                tokens_estimate=self._estimate_tokens(default_rag_result["content"]),
                metadata=default_rag_result["metadata"],
            )
        else:
            print(f"Warning: Default RAG query failed: {default_rag_result}")

        # Handle file scan result
        if file_scan_result and not isinstance(file_scan_result, BaseException):
            key = f"structure:{workspace_path}"
            context_items[key] = ContextItem(
                context_type="structure",
                key=key,
                content=file_scan_result["content"],
                tokens_estimate=file_scan_result["tokens_estimate"],
                metadata=file_scan_result["metadata"],
            )
        elif isinstance(file_scan_result, BaseException):
            print(f"Warning: File system scan failed: {file_scan_result}")

        # Handle pattern result
        if not isinstance(pattern_result, BaseException):
            key = "pattern:onex-architecture"
            context_items[key] = ContextItem(
                context_type="pattern",
                key=key,
                content=pattern_result["content"],
                tokens_estimate=self._estimate_tokens(pattern_result["content"]),
                metadata=pattern_result["metadata"],
            )
        else:
            print(f"Warning: Pattern recognition failed: {pattern_result}")

        # Store in global context
        self.global_context = context_items

        elapsed_ms = (time.time() - start_time) * 1000
        print(
            f"[ContextManager] Gathered {len(context_items)} context items in {elapsed_ms:.0f}ms"
        )

        return context_items

    async def _predict_context_needs(self, user_prompt: str) -> List[str]:
        """
        Predicts what context types might be needed based on the user prompt.
        """
        if not CONTEXT_OPTIMIZER_AVAILABLE:
            return []

        try:
            # Use the context optimizer to predict needs
            predicted_needs = await predict_context_needs(user_prompt)
            return predicted_needs
        except Exception as e:
            print(f"[ContextManager] Context prediction failed: {e}", file=sys.stderr)
            return []

    def filter_context(
        self, context_requirements: List[str], max_tokens: int = 5000
    ) -> Dict[str, Any]:
        """
        Filter global context to extract only required items for a specific task.

        This is Phase 2 of the enhanced dispatcher workflow.

        Args:
            context_requirements: List of context identifiers needed
                Examples: ["file:auth.py", "pattern:jwt-validation", "rag:jwt-refresh-tokens"]
            max_tokens: Maximum tokens to include (helps keep context lean)

        Returns:
            Filtered context dictionary with only required items
        """
        start_time = time.time()
        filtered_context: Dict[str, Any] = {}
        total_tokens = 0

        for requirement in context_requirements:
            # Parse requirement
            req_type, req_key = self._parse_requirement(requirement)

            # Find matching context items
            matching_items = self._find_matching_context(req_type, req_key)

            for item in matching_items:
                # Check token budget
                if total_tokens + item.tokens_estimate > max_tokens:
                    print(
                        f"[ContextManager] Token budget exceeded, skipping {item.key}"
                    )
                    break

                # Add to filtered context
                filtered_context[item.key] = {
                    "type": item.context_type,
                    "content": item.content,
                    "metadata": item.metadata,
                }
                total_tokens += item.tokens_estimate

        elapsed_ms = (time.time() - start_time) * 1000
        print(
            f"[ContextManager] Filtered to {len(filtered_context)} items ({total_tokens} tokens) in {elapsed_ms:.0f}ms"
        )

        return filtered_context

    def add_file_context(self, file_path: str, content: str) -> str:
        """
        Add a file to the global context.

        Args:
            file_path: Absolute path to the file
            content: File content

        Returns:
            Context key for the file
        """
        key = f"file:{Path(file_path).name}"

        self.global_context[key] = ContextItem(
            context_type="file",
            key=key,
            content=content,
            tokens_estimate=len(content) // 4,  # Rough estimate: 4 chars per token
            metadata={
                "file_path": file_path,
                "size_bytes": len(content),
                "timestamp": time.time(),
            },
        )

        return key

    def add_pattern_context(
        self, pattern_name: str, pattern_data: Dict[str, Any]
    ) -> str:
        """
        Add a code pattern to the global context.

        Args:
            pattern_name: Name/identifier for the pattern
            pattern_data: Pattern information and examples

        Returns:
            Context key for the pattern
        """
        key = f"pattern:{pattern_name}"

        self.global_context[key] = ContextItem(
            context_type="pattern",
            key=key,
            content=pattern_data,
            tokens_estimate=self._estimate_tokens(pattern_data),
            metadata={"pattern_name": pattern_name, "timestamp": time.time()},
        )

        return key

    def _parse_requirement(self, requirement: str) -> tuple[str, str]:
        """
        Parse a context requirement string.

        Args:
            requirement: Format "type:key" (e.g., "file:auth.py", "pattern:jwt")

        Returns:
            Tuple of (type, key)
        """
        if ":" in requirement:
            parts = requirement.split(":", 1)
            return parts[0], parts[1]
        else:
            # Default to RAG query if no type specified
            return "rag", requirement

    def _find_matching_context(self, req_type: str, req_key: str) -> List[ContextItem]:
        """
        Find context items matching the requirement.

        Args:
            req_type: Context type (file, pattern, rag, structure)
            req_key: Context key or search pattern

        Returns:
            List of matching context items
        """
        matching = []

        for key, item in self.global_context.items():
            # Type must match
            if item.context_type != req_type:
                continue

            # Check if key matches
            if req_key.lower() in key.lower():
                matching.append(item)

        return matching

    def _estimate_tokens(self, data: Any) -> int:
        """
        Estimate token count for data.

        Args:
            data: Data to estimate tokens for

        Returns:
            Estimated token count
        """
        if isinstance(data, str):
            return len(data) // 4
        elif isinstance(data, dict):
            # Estimate based on JSON string length
            import json

            try:
                json_str = json.dumps(data)
                return len(json_str) // 4
            except Exception:
                return 100  # Fallback
        elif isinstance(data, list):
            return sum(self._estimate_tokens(item) for item in data)
        else:
            return 50  # Default estimate

    def get_context_summary(self) -> Dict[str, Any]:
        """
        Get summary of global context.

        Returns:
            Summary statistics
        """
        total_tokens = sum(
            item.tokens_estimate for item in self.global_context.values()
        )

        by_type: Dict[str, int] = {}
        for item in self.global_context.values():
            by_type[item.context_type] = by_type.get(item.context_type, 0) + 1

        return {
            "total_items": len(self.global_context),
            "total_tokens_estimate": total_tokens,
            "items_by_type": by_type,
            "keys": list(self.global_context.keys()),
        }

    async def _execute_rag_query(
        self, query: str, match_count: int, context: str
    ) -> Dict[str, Any]:
        """
        Execute a single RAG query with error handling.

        Args:
            query: The RAG query string
            match_count: Maximum number of results
            context: Context type for the query

        Returns:
            RAG result dictionary
        """
        try:
            result: Dict[str, Any] = await self.mcp_client.perform_rag_query(
                query=query, match_count=match_count, context=context
            )
            return result
        except Exception as e:
            # Re-raise the exception to be handled by the caller
            raise e

    async def _execute_default_rag_query(
        self, user_prompt: str, max_rag_results: int
    ) -> Dict[str, Any]:
        """
        Execute the default domain pattern query based on user prompt.

        Args:
            user_prompt: The user's original request
            max_rag_results: Maximum number of results

        Returns:
            Dictionary with content and metadata
        """
        try:
            # Detect query type for intelligent query construction
            query_lower = user_prompt.lower()
            architecture_terms = [
                "onex",
                "architecture",
                "pattern",
                "node",
                "effect",
                "compute",
                "reducer",
                "validator",
                "orchestrator",
                "protocol",
                "spi",
                "omninode",
                "omnibase",
                "omniagent",
                "omnimcp",
            ]

            is_architecture = any(term in query_lower for term in architecture_terms)

            # Construct optimized query
            if is_architecture:
                # Preserve user's query terms (highest signal) and add ONEX context
                query = f"{user_prompt} ONEX architecture patterns best practices"
                context = "architecture"
            else:
                # For non-architecture queries, preserve original terms with minimal additions
                query = f"{user_prompt} patterns and best practices"
                context = "api_development"

            default_rag = await self.mcp_client.perform_rag_query(
                query=query, match_count=max_rag_results, context=context
            )

            return {
                "content": default_rag,
                "metadata": {
                    "original_prompt": user_prompt,
                    "optimized_query": query,
                    "context_type": context,
                    "is_architecture_query": is_architecture,
                    "result_count": len(default_rag.get("results", [])),
                    "timestamp": time.time(),
                },
            }
        except Exception as e:
            raise e

    async def _scan_workspace(self, workspace_path: str) -> Dict[str, Any]:
        """
        Scan workspace for Python files and structure.

        Args:
            workspace_path: Path to the workspace directory

        Returns:
            Dictionary with content and metadata
        """
        try:
            workspace = Path(workspace_path)
            if not workspace.exists() or not workspace.is_dir():
                raise ValueError(
                    f"Workspace path does not exist or is not a directory: {workspace_path}"
                )

            # Scan for relevant Python files
            python_files = list(workspace.rglob("*.py"))

            return {
                "content": {
                    "workspace": str(workspace),
                    "python_files": [
                        str(f.relative_to(workspace)) for f in python_files[:50]
                    ],
                    "total_files": len(python_files),
                },
                "tokens_estimate": len(python_files) * 10,  # Rough estimate
                "metadata": {
                    "workspace_path": str(workspace),
                    "file_count": len(python_files),
                },
            }
        except Exception as e:
            raise e

    async def _execute_pattern_recognition(self) -> Dict[str, Any]:
        """
        Execute pattern recognition for ONEX patterns.

        Returns:
            Dictionary with content and metadata
        """
        try:
            pattern_result = await self.mcp_client.search_code_examples(
                query="ONEX architecture patterns and best practices", match_count=3
            )

            return {
                "content": pattern_result,
                "metadata": {
                    "pattern_type": "onex",
                    "result_count": len(pattern_result.get("results", [])),
                    "timestamp": time.time(),
                },
            }
        except Exception as e:
            raise e

    async def _create_empty_result(self) -> Dict[str, Any]:
        """Create an empty result placeholder for parallel tasks."""
        return {"content": None, "metadata": {}, "tokens_estimate": 0}

    async def cleanup(self):
        """Cleanup resources."""
        if self._owns_mcp_client and self.mcp_client:
            await self.mcp_client.close()
