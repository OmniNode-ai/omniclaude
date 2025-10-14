"""
MCP Client for calling Archon MCP tools via HTTP (stateless mode).

Uses direct HTTP POST requests to the FastMCP stateless HTTP endpoint.
"""

import asyncio
import json
from typing import Any, Dict, Optional
import httpx
try:
    from agents.lib.llm_logging import log_llm_call  # type: ignore
except Exception:
    log_llm_call = None  # type: ignore

try:
    from agents.lib.circuit_breaker import call_with_breaker, CircuitBreakerConfig  # type: ignore
except Exception:
    call_with_breaker = None  # type: ignore
    CircuitBreakerConfig = None  # type: ignore


class ArchonMCPClient:
    """Client for calling Archon MCP tools via stateless HTTP."""

    def __init__(
        self,
        base_url: str = "http://localhost:8051",
        default_timeout: float = 30.0,
        enable_circuit_breaker: bool = True
    ):
        self.base_url = base_url
        self.mcp_url = f"{base_url}/mcp"
        self.request_id = 0
        self.client = None
        self.default_timeout = default_timeout
        self.enable_circuit_breaker = enable_circuit_breaker
        
        # Circuit breaker configuration for MCP calls
        self.circuit_breaker_config = None
        if enable_circuit_breaker and CircuitBreakerConfig:
            self.circuit_breaker_config = CircuitBreakerConfig(
                failure_threshold=3,      # Open after 3 failures
                timeout_seconds=30.0,     # Wait 30s before trying again
                success_threshold=2,      # Need 2 successes to close
                max_retries=2,            # Max 2 retries per call
                base_delay=1.0,           # 1s base delay
                max_delay=10.0            # Max 10s delay
            )

    def _get_next_id(self) -> int:
        """Get next request ID."""
        self.request_id += 1
        return self.request_id

    async def _ensure_client(self):
        """Ensure HTTP client is created with timeout."""
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.default_timeout)

    async def call_tool(
        self,
        tool_name: str,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call an MCP tool via stateless HTTP POST with timeout and circuit breaker protection.

        Args:
            tool_name: Name of the tool (e.g., "assess_code_quality")
            timeout: Optional timeout in seconds (uses default_timeout if None)
            **kwargs: Tool arguments

        Returns:
            Tool result as dictionary

        Raises:
            asyncio.TimeoutError: If request exceeds timeout
            RuntimeError: If MCP service is unavailable or returns error
        """
        # Use circuit breaker if enabled
        if self.enable_circuit_breaker and call_with_breaker:
            success, result = await call_with_breaker(
                "mcp_client",
                self._call_tool_internal,
                tool_name,
                timeout,
                **kwargs
            )
            if success:
                return result
            else:
                raise result
        else:
            return await self._call_tool_internal(tool_name, timeout, **kwargs)

    async def _call_tool_internal(
        self,
        tool_name: str,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Internal method to call MCP tool without circuit breaker.
        """
        await self._ensure_client()

        timeout_value = timeout if timeout is not None else self.default_timeout

        # Build MCP JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": self._get_next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": kwargs
            }
        }

        try:
            # Wrap HTTP call with asyncio timeout for additional protection
            async def _make_request():
                response = await self.client.post(
                    self.mcp_url,
                    json=request,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    }
                )
                response.raise_for_status()
                return response

            # Apply timeout to the entire request
            response = await asyncio.wait_for(_make_request(), timeout=timeout_value)

            # Parse SSE response
            response_text = response.text

            # Parse SSE events
            events = []
            for line in response_text.strip().split('\n'):
                if line.startswith('data: '):
                    event_data = line[6:]  # Remove 'data: ' prefix
                    try:
                        events.append(json.loads(event_data))
                    except json.JSONDecodeError:
                        pass

            # Get the last event (should be the result)
            if not events:
                raise RuntimeError("No SSE events received")

            result = events[-1]

            if "error" in result:
                error = result["error"]
                raise RuntimeError(f"MCP error: {error.get('message', 'Unknown error')}")

            # Extract result
            mcp_result = result.get("result", {})

            # Handle MCP content format
            if isinstance(mcp_result, dict) and "content" in mcp_result:
                content_items = mcp_result["content"]
                if content_items and isinstance(content_items, list):
                    first_item = content_items[0]
                    if isinstance(first_item, dict) and "text" in first_item:
                        # Try to parse as JSON
                        try:
                            return json.loads(first_item["text"])
                        except json.JSONDecodeError:
                            # Return as plain text
                            return {"result": first_item["text"]}

            # Best-effort logging to llm_calls as an external tool call
            try:
                if log_llm_call is not None:
                    await log_llm_call(
                        run_id=None,
                        model=f"mcp:{tool_name}",
                        provider="archon-mcp",
                        request={"args": kwargs},
                        response={"result": mcp_result} if isinstance(mcp_result, (dict, list, str)) else {"result": str(mcp_result)},
                    )
            except Exception:
                pass

            return mcp_result

        except asyncio.TimeoutError:
            raise RuntimeError(
                f"MCP tool call timed out after {timeout_value}s. "
                f"Tool: {tool_name}, Server: {self.base_url}"
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP error calling MCP tool: {e}")
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to MCP server at {self.base_url}. "
                f"Is the server running? Error: {e}"
            )
        except Exception as e:
            raise RuntimeError(f"Tool call failed: {e}")

    async def assess_code_quality(
        self,
        content: str,
        source_path: str = "",
        language: str = "python",
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Assess code quality using Archon MCP tool."""
        return await self.call_tool(
            "assess_code_quality",
            timeout=timeout,
            content=content,
            source_path=source_path,
            language=language
        )

    async def perform_rag_query(
        self,
        query: str,
        source_domain: Optional[str] = None,
        match_count: int = 5,
        context: str = "general",
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Perform RAG query for intelligence gathering."""
        args = {
            "query": query,
            "max_results_per_source": match_count,
            "context": context
        }
        if source_domain:
            args["source_domain"] = source_domain

        return await self.call_tool(
            "perform_rag_query",
            timeout=timeout,
            **args
        )

    async def search_code_examples(
        self,
        query: str,
        source_domain: Optional[str] = None,
        match_count: int = 3,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Search for code examples using RAG."""
        args = {
            "query": query,
            "max_results_per_source": match_count
        }
        if source_domain:
            args["source_domain"] = source_domain

        return await self.call_tool(
            "search_code_examples",
            timeout=timeout,
            **args
        )

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None
