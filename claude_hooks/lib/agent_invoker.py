#!/usr/bin/env python3
"""
Agent Invocation Module
Bridges hook detection to agent execution frameworks.

Supports three invocation pathways:
1. Coordinator dispatch: Spawn agent-workflow-coordinator
2. Direct single: Execute single agent with context injection
3. Direct parallel: Execute multiple agents in parallel

Author: OmniClaude Framework
Version: 1.0.0
"""

import sys
import os
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

# Add agent framework to path
AGENT_FRAMEWORK_PATH = Path("/Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution")
sys.path.insert(0, str(AGENT_FRAMEWORK_PATH))

# Add hooks lib to path
HOOKS_LIB_PATH = Path("/Users/jonah/.claude/hooks/lib")
sys.path.insert(0, str(HOOKS_LIB_PATH))

try:
    from agent_model import AgentTask, AgentResult
    from agent_dispatcher import ParallelCoordinator
    from agent_pathway_detector import AgentPathwayDetector, PathwayDetection
except ImportError as e:
    print(f"ERROR: Failed to import agent framework: {e}", file=sys.stderr)
    sys.exit(1)


class AgentInvoker:
    """
    Invokes agents via detected pathway.

    Pathways:
    - coordinator: Full orchestration with agent-workflow-coordinator
    - direct_single: Single agent with context injection (lightweight)
    - direct_parallel: Multiple agents with parallel coordination
    """

    def __init__(
        self,
        correlation_id: Optional[str] = None,
        use_enhanced_router: bool = True,
        router_confidence_threshold: float = 0.6,
        enable_database_logging: bool = True
    ):
        """
        Initialize agent invoker.

        Args:
            correlation_id: Request correlation ID for tracking
            use_enhanced_router: Enable enhanced router for coordinator mode
            router_confidence_threshold: Minimum confidence for router selection
            enable_database_logging: Enable database event logging
        """
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.use_enhanced_router = use_enhanced_router
        self.router_confidence_threshold = router_confidence_threshold
        self.enable_database_logging = enable_database_logging

        # Pathway detector
        self.detector = AgentPathwayDetector()

        # Coordinator (lazy initialized)
        self._coordinator: Optional[ParallelCoordinator] = None

        # Invocation stats
        self.stats = {
            "total_invocations": 0,
            "coordinator_invocations": 0,
            "direct_single_invocations": 0,
            "direct_parallel_invocations": 0,
            "failed_invocations": 0
        }

    async def invoke(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        force_pathway: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Invoke agent(s) based on prompt analysis.

        Args:
            prompt: User prompt
            context: Additional context for agent execution
            force_pathway: Force specific pathway (override detection)

        Returns:
            Execution result with agent outputs and metadata
        """
        start_time = datetime.now()
        self.stats["total_invocations"] += 1

        try:
            # Detect pathway
            if force_pathway:
                detection = self._create_forced_detection(prompt, force_pathway)
            else:
                detection = self.detector.detect(prompt)

            # Route to appropriate pathway
            if detection.pathway == "coordinator":
                result = await self._invoke_coordinator(detection, context)
                self.stats["coordinator_invocations"] += 1

            elif detection.pathway == "direct_single":
                result = await self._invoke_direct_single(detection, context)
                self.stats["direct_single_invocations"] += 1

            elif detection.pathway == "direct_parallel":
                result = await self._invoke_direct_parallel(detection, context)
                self.stats["direct_parallel_invocations"] += 1

            else:
                # No agent invocation needed
                return {
                    "success": True,
                    "pathway": None,
                    "message": "No agent invocation required",
                    "detection": {
                        "confidence": detection.confidence,
                        "task": detection.task
                    }
                }

            # Add execution metadata
            result["execution_metadata"] = {
                "correlation_id": self.correlation_id,
                "total_time_ms": (datetime.now() - start_time).total_seconds() * 1000,
                "detection_confidence": detection.confidence,
                "trigger_pattern": detection.trigger_pattern
            }

            return result

        except Exception as e:
            self.stats["failed_invocations"] += 1
            return {
                "success": False,
                "error": f"Agent invocation failed: {str(e)}",
                "pathway": detection.pathway if 'detection' in locals() else None,
                "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
            }

    async def _invoke_coordinator(
        self,
        detection: PathwayDetection,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Invoke agent-workflow-coordinator for complex orchestration.

        This pathway spawns the coordinator which then uses enhanced router
        to select and delegate to specialized agents.
        """
        start_time = datetime.now()

        # Initialize coordinator if needed
        if not self._coordinator:
            self._coordinator = ParallelCoordinator(
                use_dynamic_loading=True,
                use_enhanced_router=self.use_enhanced_router,
                router_confidence_threshold=self.router_confidence_threshold
            )
            await self._coordinator.initialize()

        # Create coordinator task
        task = AgentTask(
            task_id=f"{self.correlation_id}-coordinator",
            description=detection.task,
            agent_name="agent-workflow-coordinator",
            dependencies=[],
            input_data=context or {}
        )

        # Execute via coordinator
        results = await self._coordinator.execute_parallel([task])
        result = results.get(task.task_id)

        if not result:
            return {
                "success": False,
                "pathway": "coordinator",
                "error": "Coordinator did not return result",
                "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
            }

        # Get router stats
        router_stats = self._coordinator.get_router_stats() if hasattr(self._coordinator, 'get_router_stats') else {}

        return {
            "success": result.success,
            "pathway": "coordinator",
            "agent_name": result.agent_name,
            "execution_time_ms": result.execution_time_ms,
            "result_data": getattr(result, 'result_data', None),
            "error": result.error if not result.success else None,
            "router_stats": router_stats,
            "agents_invoked": [detection.agents[0]],
            "total_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }

    async def _invoke_direct_single(
        self,
        detection: PathwayDetection,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Invoke single agent directly with context injection.

        This is the lightweight pathway - loads agent YAML config and
        injects it into Claude's context. No orchestration overhead.
        """
        start_time = datetime.now()
        agent_name = detection.agents[0]

        # Load agent config
        agent_config = await self._load_agent_config(agent_name)

        if not agent_config:
            return {
                "success": False,
                "pathway": "direct_single",
                "error": f"Agent config not found: {agent_name}",
                "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
            }

        # For direct single mode, we return the config for hook to inject
        # The actual execution happens via Claude reading the context
        return {
            "success": True,
            "pathway": "direct_single",
            "agent_name": agent_name,
            "agent_config": agent_config,
            "task": detection.task,
            "context_injection_required": True,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000,
            "message": f"Agent config loaded for context injection: {agent_name}"
        }

    async def _invoke_direct_parallel(
        self,
        detection: PathwayDetection,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Invoke multiple agents in parallel with coordination.

        This pathway uses ParallelCoordinator but with direct agent
        execution rather than coordinator orchestration.
        """
        start_time = datetime.now()

        # Initialize coordinator if needed
        if not self._coordinator:
            self._coordinator = ParallelCoordinator(
                use_dynamic_loading=True,
                use_enhanced_router=False,  # Direct mode, no routing needed
                router_confidence_threshold=self.router_confidence_threshold
            )
            await self._coordinator.initialize()

        # Create tasks for each agent
        tasks = []
        for idx, agent_name in enumerate(detection.agents):
            task = AgentTask(
                task_id=f"{self.correlation_id}-parallel-{idx}",
                description=detection.task,
                agent_name=agent_name,
                dependencies=[],
                input_data=context or {}
            )
            tasks.append(task)

        # Execute in parallel
        results = await self._coordinator.execute_parallel(tasks)

        # Aggregate results
        successful_agents = []
        failed_agents = []
        agent_outputs = {}

        for task in tasks:
            result = results.get(task.task_id)
            if result and result.success:
                successful_agents.append(result.agent_name)
                agent_outputs[result.agent_name] = {
                    "success": True,
                    "execution_time_ms": result.execution_time_ms,
                    "result_data": getattr(result, 'result_data', None)
                }
            else:
                failed_agents.append(task.agent_name)
                agent_outputs[task.agent_name] = {
                    "success": False,
                    "error": result.error if result else "No result returned"
                }

        return {
            "success": len(failed_agents) == 0,
            "pathway": "direct_parallel",
            "agents_invoked": detection.agents,
            "successful_agents": successful_agents,
            "failed_agents": failed_agents,
            "agent_outputs": agent_outputs,
            "total_agents": len(detection.agents),
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }

    async def _load_agent_config(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Load agent configuration from YAML file.

        Args:
            agent_name: Name of agent to load

        Returns:
            Agent config dictionary or None if not found
        """
        import yaml

        config_paths = [
            Path.home() / ".claude" / "agents" / "configs" / f"{agent_name}.yaml",
            Path.home() / ".claude" / "agent-definitions" / f"{agent_name}.yaml",
            Path.home() / ".claude" / "agent-definitions" / f"{agent_name.replace('agent-', '')}.yaml"
        ]

        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        return yaml.safe_load(f)
                except Exception as e:
                    print(f"ERROR: Failed to load {config_path}: {e}", file=sys.stderr)

        return None

    def _create_forced_detection(
        self,
        prompt: str,
        pathway: str
    ) -> PathwayDetection:
        """Create PathwayDetection for forced pathway."""
        if pathway == "coordinator":
            return PathwayDetection(
                pathway="coordinator",
                agents=["agent-workflow-coordinator"],
                task=prompt,
                confidence=1.0,
                trigger_pattern="forced"
            )
        elif pathway == "direct_single":
            # Extract agent name from prompt
            agents = self.detector._extract_agent_names(prompt)
            return PathwayDetection(
                pathway="direct_single",
                agents=agents[:1] if agents else ["unknown"],
                task=prompt,
                confidence=1.0,
                trigger_pattern="forced"
            )
        elif pathway == "direct_parallel":
            # Extract all agent names from prompt
            agents = self.detector._extract_agent_names(prompt)
            return PathwayDetection(
                pathway="direct_parallel",
                agents=agents,
                task=prompt,
                confidence=1.0,
                trigger_pattern="forced"
            )
        else:
            return PathwayDetection(
                pathway=None,
                agents=[],
                task=prompt,
                confidence=1.0,
                trigger_pattern="forced"
            )

    async def cleanup(self):
        """Cleanup resources."""
        if self._coordinator:
            await self._coordinator.cleanup()

    def get_stats(self) -> Dict[str, Any]:
        """Get invocation statistics."""
        return {
            **self.stats,
            "detection_stats": self.detector.get_stats()
        }

    def invoke_sync(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        force_pathway: Optional[str] = None
    ) -> Dict[str, Any]:
        """Synchronous wrapper for async invoke."""
        return asyncio.run(self.invoke(prompt, context, force_pathway))


# ============================================================================
# CLI Interface
# ============================================================================

async def main():
    """CLI entry point for agent invocation."""
    import argparse

    parser = argparse.ArgumentParser(description="Agent Invocation System")
    parser.add_argument("prompt", help="User prompt to process")
    parser.add_argument("--mode", choices=["coordinator", "direct_single", "direct_parallel", "auto"],
                       default="auto", help="Invocation mode")
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument("--context", help="JSON context for agent execution")
    parser.add_argument("--stats", action="store_true", help="Show statistics after execution")

    args = parser.parse_args()

    # Parse context
    context = None
    if args.context:
        try:
            context = json.loads(args.context)
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON context: {args.context}", file=sys.stderr)
            sys.exit(1)

    # Create invoker
    invoker = AgentInvoker(correlation_id=args.correlation_id)

    try:
        # Invoke agent
        force_pathway = None if args.mode == "auto" else args.mode
        result = await invoker.invoke(args.prompt, context, force_pathway)

        # Output result
        print(json.dumps(result, indent=2))

        # Show stats if requested
        if args.stats:
            print("\n--- Statistics ---", file=sys.stderr)
            print(json.dumps(invoker.get_stats(), indent=2), file=sys.stderr)

        # Exit with appropriate code
        sys.exit(0 if result.get("success", False) else 1)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    finally:
        await invoker.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
