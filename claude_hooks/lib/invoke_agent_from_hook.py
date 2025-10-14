#!/usr/bin/env python3
"""
Hook Agent Invocation Integration
Called by UserPromptSubmit hook to process agent invocations.

Workflow:
1. Detect invocation pathway (coordinator/direct_single/direct_parallel)
2. Execute via appropriate pathway
3. Return result for hook to process

For direct_single mode: Returns agent YAML for context injection
For coordinator/parallel mode: Triggers actual agent execution

Author: OmniClaude Framework
Version: 1.0.0
"""

import sys
import os
import json
import asyncio
from pathlib import Path
from typing import Dict, Any

# Add hooks lib to path
HOOKS_LIB_PATH = Path("/Users/jonah/.claude/hooks/lib")
sys.path.insert(0, str(HOOKS_LIB_PATH))

try:
    from agent_pathway_detector import AgentPathwayDetector
    from agent_invoker import AgentInvoker
except ImportError as e:
    print(json.dumps({
        "success": False,
        "error": f"Failed to import agent modules: {e}",
        "context_injection": None
    }))
    sys.exit(1)


async def process_agent_invocation(
    prompt: str,
    correlation_id: str,
    session_id: str,
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process agent invocation from hook.

    Args:
        prompt: User prompt
        correlation_id: Request correlation ID
        session_id: Claude session ID
        context: Additional context from hook

    Returns:
        Result dictionary with pathway-specific data
    """
    # Create invoker
    invoker = AgentInvoker(
        correlation_id=correlation_id,
        use_enhanced_router=True,
        router_confidence_threshold=0.6,
        enable_database_logging=True
    )

    try:
        # Invoke agent
        result = await invoker.invoke(prompt, context)

        # Handle pathway-specific processing
        if result.get("pathway") == "direct_single":
            # For direct single, prepare context injection
            agent_config = result.get("agent_config", {})
            agent_name = result.get("agent_name", "unknown")

            # Format YAML for context injection
            context_yaml = format_agent_context(agent_name, agent_config)

            return {
                "success": True,
                "pathway": "direct_single",
                "agent_name": agent_name,
                "context_injection": context_yaml,
                "execution_time_ms": result.get("execution_time_ms", 0),
                "message": f"Context prepared for agent: {agent_name}"
            }

        elif result.get("pathway") == "coordinator":
            # For coordinator, prepare coordinator invocation
            return {
                "success": True,
                "pathway": "coordinator",
                "coordinator_invocation_required": True,
                "task_description": result.get("task", prompt),
                "execution_time_ms": result.get("execution_time_ms", 0),
                "message": "Coordinator invocation prepared"
            }

        elif result.get("pathway") == "direct_parallel":
            # For parallel, prepare parallel execution
            return {
                "success": True,
                "pathway": "direct_parallel",
                "agents": result.get("agents_invoked", []),
                "parallel_execution_required": True,
                "task_description": result.get("task", prompt),
                "execution_time_ms": result.get("execution_time_ms", 0),
                "message": f"Parallel execution prepared for {len(result.get('agents_invoked', []))} agents"
            }

        else:
            # No agent invocation needed
            return {
                "success": True,
                "pathway": None,
                "context_injection": None,
                "message": "No agent invocation required"
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "context_injection": None
        }

    finally:
        await invoker.cleanup()


def format_agent_context(agent_name: str, agent_config: Dict[str, Any]) -> str:
    """
    Format agent configuration as YAML for context injection.

    Args:
        agent_name: Agent name
        agent_config: Agent configuration dictionary

    Returns:
        Formatted YAML string for injection
    """
    import yaml

    # Format as YAML with proper indentation
    try:
        yaml_str = yaml.dump(agent_config, default_flow_style=False, sort_keys=False)

        # Add header
        header = f"""
# ============================================================================
# POLYMORPHIC AGENT IDENTITY INJECTION
# ============================================================================
# Agent: {agent_name}
# Detected by: UserPromptSubmit hook
# Injection Mode: Direct Single Agent
#
# IMPORTANT: You are now assuming the identity and capabilities of this agent.
# Adapt your behavior, expertise, and response patterns accordingly.
# ============================================================================

"""
        return header + yaml_str

    except Exception as e:
        return f"# ERROR: Failed to format agent config: {e}\n"


def main():
    """
    CLI entry point called by UserPromptSubmit hook.

    Expected input (JSON via stdin):
    {
        "prompt": "User prompt text",
        "correlation_id": "uuid",
        "session_id": "uuid",
        "context": {}
    }

    Output (JSON to stdout):
    {
        "success": true/false,
        "pathway": "coordinator|direct_single|direct_parallel|null",
        "context_injection": "YAML string or null",
        "message": "Status message"
    }
    """
    try:
        # Read input from stdin
        input_data = sys.stdin.read()

        if not input_data.strip():
            print(json.dumps({
                "success": False,
                "error": "No input provided",
                "context_injection": None
            }))
            sys.exit(1)

        # Parse JSON input
        try:
            data = json.loads(input_data)
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "error": f"Invalid JSON input: {e}",
                "context_injection": None
            }))
            sys.exit(1)

        # Extract parameters
        prompt = data.get("prompt", "")
        correlation_id = data.get("correlation_id", "")
        session_id = data.get("session_id", "")
        context = data.get("context", {})

        if not prompt:
            print(json.dumps({
                "success": False,
                "error": "No prompt provided",
                "context_injection": None
            }))
            sys.exit(1)

        # Process agent invocation
        result = asyncio.run(process_agent_invocation(
            prompt=prompt,
            correlation_id=correlation_id,
            session_id=session_id,
            context=context
        ))

        # Output result
        print(json.dumps(result, indent=2))

        # Exit with success
        sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"Unexpected error: {e}",
            "context_injection": None
        }), file=sys.stderr)

        import traceback
        traceback.print_exc(file=sys.stderr)

        sys.exit(1)


if __name__ == "__main__":
    main()
