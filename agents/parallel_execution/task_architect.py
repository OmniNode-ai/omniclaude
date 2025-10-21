#!/usr/bin/env python3
"""
Task Architect Service

Converts natural language prompts into structured task definitions
for parallel agent execution.

Uses LLM to analyze user requests and plan optimal task breakdown.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from mcp_client import ArchonMCPClient


class TaskArchitect:
    """
    Analyzes user prompts and generates structured task definitions.
    """

    def __init__(self):
        self.mcp = ArchonMCPClient()

    async def analyze_prompt(
        self, user_prompt: str, global_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze user prompt and generate task breakdown.

        Args:
            user_prompt: Natural language request from user
            global_context: Optional pre-gathered global context from ContextManager

        Returns:
            Dictionary with task definitions including context_requirements per task
        """
        # Build context summary if provided
        context_summary = ""
        if global_context:
            context_keys = list(global_context.keys())
            context_summary = f"""

Available Context (pre-gathered):
{chr(10).join(f"  - {key}" for key in context_keys[:20])}
{"  ... and more" if len(context_keys) > 20 else ""}

Each task should specify which context items it needs via 'context_requirements' array.
Examples: ["file:auth.py", "pattern:onex-compute-node", "rag:jwt-refresh-tokens"]
"""

        # Build analysis prompt for LLM
        analysis_prompt = f"""Analyze this user request and break it down into tasks for parallel agent execution.

Available Agents:
1. agent_coder - Code generation for any Python code (functions, classes, APIs, scripts)
   - Input: description (what to build), language, context
   - Optional: contract, node_type (only for ONEX architecture requests)

2. agent_debug_intelligence - Debugging, quality analysis, root cause analysis
   - Input: code, issue_description, file_path, language

User Request: {user_prompt}

Task Planning Rules:
- Use agent_coder for: "create", "generate", "implement", "build" requests
- Use agent_debug_intelligence for: "debug", "fix", "analyze", "investigate" requests
- Tasks can run in parallel if independent (no dependencies)
- Tasks must be sequential if one depends on output of another (add dependencies)
- Each task needs unique task_id
- Task descriptions should clearly indicate which agent to use (keywords matter)
- IMPORTANT: Each task must declare context_requirements array with specific context items needed
- ONEX architecture (node_type, contracts) should ONLY be used if explicitly requested
{context_summary}

CRITICAL: Do NOT repeat or echo the context in your response. Only return the JSON task breakdown.

Return ONLY valid JSON in this exact format:
{{
  "analysis": "brief analysis of the request",
  "tasks": [
    {{
      "task_id": "unique-id",
      "description": "what this task does (use keywords for agent routing)",
      "agent": "coder" or "debug",
      "input_data": {{
        // agent-specific fields
      }},
      "context_requirements": ["file:example.py", "pattern:onex-compute", "rag:relevant-query"],
      "dependencies": []
    }}
  ]
}}"""

        try:
            # Use RAG query to get intelligent task planning
            result = await self.mcp.perform_rag_query(
                query=analysis_prompt, match_count=3
            )

            # Ensure result is a dictionary
            if not isinstance(result, dict):
                return self._fallback_task_generation(user_prompt)

            # Extract task plan from RAG result
            if result.get("success") and "results" in result:
                # Parse LLM response to extract task definitions
                task_plan = self._parse_rag_response(result, user_prompt)
                return task_plan
            else:
                # Fallback: Simple heuristic-based task generation
                return self._fallback_task_generation(user_prompt)

        except Exception as e:
            import traceback

            print(f"Error in task planning: {e}", file=sys.stderr)
            print(f"Traceback: {traceback.format_exc()}", file=sys.stderr)
            # Fallback on error
            return self._fallback_task_generation(user_prompt)

    def _parse_rag_response(
        self, rag_result: Dict[str, Any], user_prompt: str
    ) -> Dict[str, Any]:
        """
        Parse RAG query response to extract task definitions.

        Args:
            rag_result: Result from MCP RAG query
            user_prompt: Original user prompt

        Returns:
            Structured task definitions
        """
        # Try to extract JSON from RAG results
        results = rag_result.get("results", [])

        if results:
            # Look for JSON-like content in results
            for result in results:
                # Handle both dict and string results
                if isinstance(result, dict):
                    content = result.get("content", "")
                elif isinstance(result, str):
                    content = result
                else:
                    continue

                # Try to find JSON structure
                if "{" in content and "tasks" in content:
                    try:
                        # Extract JSON portion
                        start = content.find("{")
                        end = content.rfind("}") + 1
                        json_str = content[start:end]
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

        # If no valid JSON found, use fallback
        return self._fallback_task_generation(user_prompt)

    def _fallback_task_generation(self, user_prompt: str) -> Dict[str, Any]:
        """
        Fallback heuristic-based task generation when LLM unavailable.

        Args:
            user_prompt: User's natural language request

        Returns:
            Basic task structure with context_requirements
        """
        prompt_lower = user_prompt.lower()

        # Determine task type from keywords
        is_generation = any(
            kw in prompt_lower
            for kw in ["create", "generate", "build", "implement", "make"]
        )
        is_debug = any(
            kw in prompt_lower
            for kw in ["debug", "fix", "analyze", "investigate", "error", "bug"]
        )

        # Detect if ONEX architecture is explicitly requested
        is_onex = any(
            kw in prompt_lower
            for kw in ["onex", "node", "effect", "compute", "reducer", "orchestrator"]
        )

        tasks = []

        if is_generation:
            # Build input_data dynamically based on whether ONEX is needed
            input_data = {
                "description": user_prompt,
                "language": "python",
                "context": user_prompt,
            }

            # Only add ONEX-specific fields if explicitly requested
            if is_onex:
                input_data["contract"] = {
                    "name": "UserRequest",
                    "description": user_prompt,
                    "type": "application",
                }
                input_data["node_type"] = "Compute"

            # Build context requirements dynamically
            context_reqs = ["rag:domain-patterns"]
            if is_onex:
                context_reqs.append("pattern:onex-architecture")

            # Code generation task
            tasks.append(
                {
                    "task_id": "gen-1",
                    "description": f"Generate code for: {user_prompt}",
                    "agent": "coder",
                    "input_data": input_data,
                    "context_requirements": context_reqs,
                    "dependencies": [],
                }
            )

        if is_debug:
            # Build context requirements for debug
            debug_context_reqs = ["rag:domain-patterns"]
            if is_onex:
                debug_context_reqs.append("pattern:onex-architecture")

            # Debug task
            tasks.append(
                {
                    "task_id": "debug-1",
                    "description": f"Debug issue: {user_prompt}",
                    "agent": "debug",
                    "input_data": {
                        "code": "# Code to be provided by user",
                        "issue_description": user_prompt,
                        "file_path": "unknown.py",
                        "language": "python",
                    },
                    "context_requirements": debug_context_reqs,
                    "dependencies": [],
                }
            )

        if not tasks:
            # Default to generation
            input_data = {"description": user_prompt, "language": "python"}

            # Only add ONEX fields if detected
            if is_onex:
                input_data["contract"] = user_prompt
                input_data["node_type"] = "Compute"

            tasks.append(
                {
                    "task_id": "gen-1",
                    "description": f"Generate: {user_prompt}",
                    "agent": "coder",
                    "input_data": input_data,
                    "context_requirements": ["rag:domain-patterns"],
                    "dependencies": [],
                }
            )

        return {
            "analysis": f"Interpreted as {'generation' if is_generation else 'debug' if is_debug else 'generation'} task",
            "tasks": tasks,
        }

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp, "cleanup"):
            await self.mcp.cleanup()


async def main():
    """Main entry point for task architect service."""

    # Read input from stdin or args
    # Input can be either:
    # 1. Simple string: user prompt
    # 2. JSON object: {"prompt": "...", "global_context": {...}}
    if len(sys.argv) > 1:
        input_str = " ".join(sys.argv[1:])
    else:
        # Read from stdin
        input_str = sys.stdin.read().strip()

    if not input_str:
        print(json.dumps({"success": False, "error": "No input provided"}))
        sys.exit(1)

    # Try to parse as JSON (with global_context)
    user_prompt = None
    global_context = None

    try:
        input_data = json.loads(input_str)
        if isinstance(input_data, dict):
            user_prompt = input_data.get("prompt")
            global_context = input_data.get("global_context")
    except json.JSONDecodeError:
        # Not JSON, treat as plain prompt
        user_prompt = input_str

    if not user_prompt:
        print(json.dumps({"success": False, "error": "No prompt provided"}))
        sys.exit(1)

    architect = TaskArchitect()

    try:
        # Generate task plan with optional global context
        task_plan = await architect.analyze_prompt(user_prompt, global_context)

        # Debug: Check type
        if not isinstance(task_plan, dict):
            raise RuntimeError(
                f"Task plan is not a dict, got: {type(task_plan)}, value: {task_plan}"
            )

        # Output as JSON
        output = {
            "success": True,
            "prompt": user_prompt,
            "analysis": task_plan.get("analysis", "Task plan generated"),
            "tasks": task_plan.get("tasks", []),
            "context_enabled": global_context is not None,
        }

        print(json.dumps(output, indent=2))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}), file=sys.stderr)
        sys.exit(1)

    finally:
        await architect.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
