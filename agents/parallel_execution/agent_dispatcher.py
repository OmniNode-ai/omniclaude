"""
Parallel Agent Coordinator

Executes multiple agents concurrently with dependency tracking and trace logging.
Enhanced with dynamic agent loading from YAML configurations and intelligent routing.
"""

import asyncio
import time
from typing import Dict, List, Any, Optional
from collections import defaultdict
from pathlib import Path
import sys

from agent_model import AgentTask, AgentResult
from trace_logger import get_trace_logger, TraceEventType, TraceLevel
from agent_coder import CoderAgent
from agent_debug_intelligence import DebugIntelligenceAgent
from agent_testing import TestingAgent
from agent_refactoring import RefactoringAgent
from agent_researcher import ResearcherAgent
from agent_architect import ArchitectAgent
from agent_loader import AgentLoader, AgentLoadStatus

# Import enhanced router components
ROUTER_AVAILABLE = False
EnhancedAgentRouter = None
AgentRecommendation = None
ConfidenceScore = None

try:
    # Add lib directory to path
    lib_path = Path(__file__).parent.parent / "lib"
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))

    # Import router components
    import enhanced_router
    import confidence_scorer

    EnhancedAgentRouter = enhanced_router.EnhancedAgentRouter
    AgentRecommendation = enhanced_router.AgentRecommendation
    ConfidenceScore = confidence_scorer.ConfidenceScore
    ROUTER_AVAILABLE = True
except ImportError as e:
    # Router not available - will fall back to legacy selection
    pass
except Exception as e:
    print(f"Warning: Enhanced router initialization error: {e}")


class ParallelCoordinator:
    """
    Coordinates parallel execution of agents with dependency tracking.

    Features:
    - Concurrent agent execution
    - Dependency graph resolution
    - Trace logging for all operations
    - Result aggregation
    - Dynamic agent loading from YAML configs
    - Hot-reload capability for config changes
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        enable_hot_reload: bool = True,
        use_dynamic_loading: bool = True,
        use_enhanced_router: bool = True,
        router_confidence_threshold: float = 0.6,
        router_cache_ttl: int = 3600,
        registry_path: Optional[str] = None
    ):
        """
        Initialize parallel coordinator.

        Args:
            config_dir: Directory containing agent YAML configs (default: ~/.claude/agents/configs/)
            enable_hot_reload: Enable automatic reload on config changes
            use_dynamic_loading: Use dynamic agent loading (True) or legacy hardcoded agents (False)
            use_enhanced_router: Use EnhancedAgentRouter for intelligent agent selection (default: True)
            router_confidence_threshold: Minimum confidence score for router recommendations (0.0-1.0, default: 0.6)
            router_cache_ttl: Router cache TTL in seconds (default: 3600)
            registry_path: Path to agent registry YAML (default: ~/.claude/agent-definitions/agent-registry.yaml)
        """
        self.trace_logger = get_trace_logger()
        self._coordinator_trace_id: str | None = None
        self.use_dynamic_loading = use_dynamic_loading
        self.use_enhanced_router = use_enhanced_router and ROUTER_AVAILABLE
        self.router_confidence_threshold = router_confidence_threshold

        # Enhanced router initialization
        self.router: Optional[EnhancedAgentRouter] = None
        self.router_stats = {
            'total_routes': 0,
            'router_used': 0,
            'fallback_used': 0,
            'below_threshold': 0,
            'router_errors': 0,
            'average_confidence': 0.0
        }

        if self.use_enhanced_router and ROUTER_AVAILABLE:
            try:
                # Use default registry path if not provided
                if registry_path is None:
                    registry_path = str(Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml")

                # Check if registry exists
                if Path(registry_path).exists():
                    self.router = EnhancedAgentRouter(
                        registry_path=registry_path,
                        cache_ttl=router_cache_ttl
                    )
                    print(f"✓ Enhanced router initialized with registry: {registry_path}")
                else:
                    # Log warning but continue with fallback
                    print(f"⚠ Enhanced router registry not found at {registry_path}")
                    print("  Falling back to legacy agent selection")
                    self.use_enhanced_router = False
            except Exception as e:
                # Log error but continue with fallback
                print(f"⚠ Failed to initialize enhanced router: {e}")
                print("  Falling back to legacy agent selection")
                self.use_enhanced_router = False
                self.router = None
        elif use_enhanced_router and not ROUTER_AVAILABLE:
            print("⚠ Enhanced router requested but dependencies not available")
            print("  Falling back to legacy agent selection")

        # Dynamic agent loader
        if use_dynamic_loading:
            self.agent_loader = AgentLoader(config_dir=config_dir, enable_hot_reload=enable_hot_reload)
            self.agents = {}  # Will be populated after initialization
        else:
            # Legacy: Hardcoded agent registry
            self.agent_loader = None
            self.agents = {
                "agent-contract-driven-generator": CoderAgent(),
                "agent-debug-intelligence": DebugIntelligenceAgent()
            }

    async def initialize(self):
        """Initialize coordinator and load agent configurations."""
        if self.use_dynamic_loading and self.agent_loader:
            await self.trace_logger.log_event(
                event_type=TraceEventType.COORDINATOR_START,
                message="Initializing dynamic agent loading",
                level=TraceLevel.INFO
            )

            # Initialize agent loader
            loaded_agents = await self.agent_loader.initialize()

            # Log loaded agents
            await self.trace_logger.log_event(
                event_type=TraceEventType.COORDINATOR_END,
                message=f"Dynamic loading complete: {len(loaded_agents)} agents available",
                level=TraceLevel.INFO,
                metadata=self.agent_loader.get_agent_stats()
            )

            # Note: Agent instances will be created on-demand during execution
            # This allows for hot-reload without maintaining agent state

    async def execute_parallel(
        self,
        tasks: List[AgentTask]
    ) -> Dict[str, AgentResult]:
        """
        Execute tasks in parallel with dependency resolution.

        Args:
            tasks: List of tasks to execute

        Returns:
            Dictionary mapping task_id to AgentResult
        """
        start_time = time.time()

        # Start coordinator trace
        self._coordinator_trace_id = await self.trace_logger.start_coordinator_trace(
            coordinator_type="parallel",
            total_agents=len(tasks),
            metadata={
                "tasks": [{"task_id": t.task_id, "description": t.description} for t in tasks]
            }
        )

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_START,
            message=f"Starting parallel execution of {len(tasks)} tasks",
            level=TraceLevel.INFO
        )

        # Build dependency graph
        dependency_graph = self._build_dependency_graph(tasks)

        # Execute in waves based on dependencies
        results = {}
        completed_tasks = set()

        while len(completed_tasks) < len(tasks):
            # Find tasks ready to execute (no pending dependencies)
            ready_tasks = [
                task for task in tasks
                if task.task_id not in completed_tasks
                and all(dep in completed_tasks for dep in task.dependencies)
            ]

            if not ready_tasks:
                # Deadlock detected
                pending = [t.task_id for t in tasks if t.task_id not in completed_tasks]
                error_msg = f"Dependency deadlock detected. Pending tasks: {pending}"

                await self.trace_logger.log_event(
                    event_type=TraceEventType.PARALLEL_BATCH_END,
                    message=error_msg,
                    level=TraceLevel.ERROR
                )
                break

            # Log batch start
            await self.trace_logger.log_event(
                event_type=TraceEventType.PARALLEL_BATCH_START,
                message=f"Executing batch of {len(ready_tasks)} tasks in parallel",
                level=TraceLevel.INFO,
                metadata={"task_ids": [t.task_id for t in ready_tasks]}
            )

            # Execute ready tasks in parallel
            batch_results = await self._execute_batch(ready_tasks)

            # Update results and completed set
            results.update(batch_results)
            completed_tasks.update(batch_results.keys())

            # Log batch completion
            await self.trace_logger.log_event(
                event_type=TraceEventType.PARALLEL_BATCH_END,
                message=f"Batch complete: {len(batch_results)} tasks finished",
                level=TraceLevel.INFO,
                metadata={
                    "completed": list(batch_results.keys()),
                    "success_count": sum(1 for r in batch_results.values() if r.success)
                }
            )

        # Calculate total execution time
        total_time_ms = (time.time() - start_time) * 1000

        # End coordinator trace
        await self.trace_logger.end_coordinator_trace(
            trace_id=self._coordinator_trace_id,
            metadata={
                "total_time_ms": total_time_ms,
                "tasks_completed": len(results),
                "success_count": sum(1 for r in results.values() if r.success)
            }
        )

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_END,
            message=f"Parallel execution complete: {len(results)} tasks in {total_time_ms:.2f}ms",
            level=TraceLevel.INFO,
            metadata={
                "total_time_ms": total_time_ms,
                "results": {tid: r.success for tid, r in results.items()}
            }
        )

        return results

    def _build_dependency_graph(self, tasks: List[AgentTask]) -> Dict[str, List[str]]:
        """Build dependency graph from tasks."""
        graph = defaultdict(list)

        for task in tasks:
            for dep in task.dependencies:
                graph[dep].append(task.task_id)

        return dict(graph)

    async def _execute_batch(self, tasks: List[AgentTask]) -> Dict[str, AgentResult]:
        """Execute a batch of tasks in parallel."""
        batch_results = {}

        # Create execution coroutines
        execution_coros = []

        for task in tasks:
            # Determine which agent to use based on task
            agent_name = self._select_agent_for_task(task)

            # Get or create agent instance
            agent = self._get_agent_instance(agent_name)

            if not agent:
                # Create error result for unknown agent
                batch_results[task.task_id] = AgentResult(
                    task_id=task.task_id,
                    agent_name=agent_name,
                    success=False,
                    error=f"Unknown agent: {agent_name}",
                    execution_time_ms=0.0
                )
                continue

            # Log task assignment
            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Task {task.task_id} assigned to {agent_name}",
                level=TraceLevel.INFO,
                agent_name=agent_name,
                task_id=task.task_id
            )

            # Create execution coroutine
            execution_coros.append(self._execute_with_logging(agent, task))

        # Execute all in parallel
        if execution_coros:
            results_list = await asyncio.gather(*execution_coros, return_exceptions=True)

            # Process results
            for i, result in enumerate(results_list):
                task = tasks[i] if i < len(tasks) else None

                if isinstance(result, Exception):
                    # Handle exception
                    error_msg = f"Task execution error: {str(result)}"

                    if task:
                        batch_results[task.task_id] = AgentResult(
                            task_id=task.task_id,
                            agent_name="unknown",
                            success=False,
                            error=error_msg,
                            execution_time_ms=0.0
                        )

                        await self.trace_logger.log_event(
                            event_type=TraceEventType.TASK_FAILED,
                            message=error_msg,
                            level=TraceLevel.ERROR,
                            task_id=task.task_id
                        )
                elif isinstance(result, AgentResult):
                    batch_results[result.task_id] = result

        return batch_results

    async def _execute_with_logging(self, agent: Any, task: AgentTask) -> AgentResult:
        """Execute agent with additional logging."""
        try:
            result = await agent.execute(task)

            # Log completion
            status = "succeeded" if result.success else "failed"
            level = TraceLevel.INFO if result.success else TraceLevel.ERROR

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_COMPLETED if result.success else TraceEventType.TASK_FAILED,
                message=f"Task {task.task_id} {status} in {result.execution_time_ms:.2f}ms",
                level=level,
                agent_name=result.agent_name,
                task_id=task.task_id,
                metadata={"execution_time_ms": result.execution_time_ms}
            )

            return result

        except Exception as e:
            error_msg = f"Agent execution exception: {str(e)}"

            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR,
                task_id=task.task_id
            )

            return AgentResult(
                task_id=task.task_id,
                agent_name=getattr(agent, "config", type(agent)).agent_name if hasattr(agent, "config") else "unknown",
                success=False,
                error=error_msg,
                execution_time_ms=0.0
            )

    def _select_agent_for_task(self, task: AgentTask) -> str:
        """
        Select appropriate agent based on task metadata.

        With dynamic loading:
        - Uses trigger matching from agent configurations
        - Falls back to capability-based selection
        - Uses keyword matching if no dynamic match found

        Without dynamic loading:
        - Uses legacy keyword-based selection
        """
        # Priority 1: Use explicit agent_name if provided
        if hasattr(task, 'agent_name') and task.agent_name:
            return task.agent_name

        # Priority 2: Dynamic agent selection using loader
        if self.use_dynamic_loading and self.agent_loader:
            return self._select_agent_dynamic(task)

        # Priority 3: Legacy keyword-based selection
        return self._select_agent_legacy(task)

    def _select_agent_dynamic(self, task: AgentTask) -> str:
        """
        Select agent using enhanced router with confidence scoring.

        Tries enhanced router first, then falls back to capability matching and legacy selection.

        Args:
            task: Task to assign

        Returns:
            Selected agent name
        """
        self.router_stats['total_routes'] += 1

        # Priority 1: Enhanced router with confidence scoring
        if self.use_enhanced_router and self.router:
            try:
                # Build context from task metadata
                context = {
                    'domain': 'general',
                    'task_id': task.task_id,
                    'has_dependencies': len(task.dependencies) > 0
                }

                # Add any additional context from task input_data
                if hasattr(task, 'input_data') and task.input_data:
                    context.update({
                        k: v for k, v in task.input_data.items()
                        if k in ['domain', 'previous_agent', 'current_file']
                    })

                # Route task using enhanced router
                recommendations = self.router.route(
                    user_request=task.description,
                    context=context,
                    max_recommendations=3
                )

                if recommendations:
                    best_recommendation = recommendations[0]

                    # Check confidence threshold
                    if best_recommendation.confidence.total >= self.router_confidence_threshold:
                        # High confidence - use router recommendation
                        self.router_stats['router_used'] += 1
                        self.router_stats['average_confidence'] = (
                            (self.router_stats['average_confidence'] * (self.router_stats['router_used'] - 1) +
                             best_recommendation.confidence.total) / self.router_stats['router_used']
                        )

                        # Log routing decision
                        print(f"  🎯 Router: {best_recommendation.agent_title}")
                        print(f"     Confidence: {best_recommendation.confidence.total:.2%}")
                        print(f"     Reason: {best_recommendation.reason}")

                        return best_recommendation.agent_name
                    else:
                        # Below threshold - log and fall back
                        self.router_stats['below_threshold'] += 1
                        print(f"  ⚠ Router confidence below threshold:")
                        print(f"     Best match: {best_recommendation.agent_title} ({best_recommendation.confidence.total:.2%})")
                        print(f"     Threshold: {self.router_confidence_threshold:.2%}")
                        print(f"     Falling back to capability matching...")

            except Exception as e:
                # Router error - log and fall back
                self.router_stats['router_errors'] += 1
                print(f"  ⚠ Router error: {e}")
                print(f"     Falling back to capability matching...")

        # Priority 2: Capability-based matching with agent loader
        if self.agent_loader:
            description_lower = task.description.lower()

            # Try trigger-based matching
            for word in description_lower.split():
                matching_agents = self.agent_loader.get_agents_by_trigger(word)
                if matching_agents:
                    self.router_stats['fallback_used'] += 1
                    print(f"  📋 Capability match: {matching_agents[0]}")
                    return matching_agents[0]

            # Try capability-based matching
            capability_keywords = {
                "debug": "quality_intelligence",
                "generate": "quality_assured_generation",
                "contract": "onex_compliance_validation",
                "api": "api_design_consistency_validation",
                "quality": "quality_intelligence"
            }

            for keyword, capability in capability_keywords.items():
                if keyword in description_lower:
                    matching_agents = self.agent_loader.get_agents_by_capability(capability)
                    if matching_agents:
                        self.router_stats['fallback_used'] += 1
                        print(f"  📋 Capability match: {matching_agents[0]}")
                        return matching_agents[0]

        # Priority 3: Fall back to legacy selection
        self.router_stats['fallback_used'] += 1
        print(f"  🔙 Using legacy keyword matching")
        return self._select_agent_legacy(task)

    def _select_agent_legacy(self, task: AgentTask) -> str:
        """
        Legacy keyword-based agent selection.

        Args:
            task: Task to assign

        Returns:
            Selected agent name
        """
        description_lower = task.description.lower()

        # Check for debug keywords first (higher priority)
        if "debug" in description_lower or "investigate" in description_lower or "bug" in description_lower:
            return "agent-debug-intelligence"
        # Then check for generation keywords
        elif "generate" in description_lower or "contract" in description_lower or "build" in description_lower or "create" in description_lower:
            return "agent-contract-driven-generator"
        # If contains "code" but not debug/generate, check context
        elif "code" in description_lower:
            # If it's about analyzing/fixing code, use debug intelligence
            if any(word in description_lower for word in ["analyze", "fix", "error", "issue", "problem"]):
                return "agent-debug-intelligence"
            # Otherwise use code generator
            return "agent-contract-driven-generator"
        else:
            # Default to code generator for unknown tasks
            return "agent-contract-driven-generator"

    def _get_agent_instance(self, agent_name: str) -> Optional[Any]:
        """
        Get or create agent instance.

        With dynamic loading: Creates agent on-demand from config
        Without dynamic loading: Returns existing instance

        Args:
            agent_name: Name of agent to retrieve

        Returns:
            Agent instance or None if not found
        """
        # Check if agent already exists in registry
        if agent_name in self.agents:
            return self.agents[agent_name]

        # With dynamic loading, check if agent config is available
        if self.use_dynamic_loading and self.agent_loader:
            agent_config = self.agent_loader.get_agent_config(agent_name)
            if agent_config:
                # Map agent_domain to agent class (expand as needed)
                agent_class_mapping = {
                    "contract_driven_generator": CoderAgent,
                    "debug_intelligence": DebugIntelligenceAgent,
                    "testing": TestingAgent,
                    "refactoring_intelligence_v2": RefactoringAgent,
                    "research": ResearcherAgent,
                    "architect": ArchitectAgent,
                    # Add more mappings as agent classes are implemented
                }

                agent_class = agent_class_mapping.get(agent_config.agent_domain)
                if agent_class:
                    # Create agent instance with config
                    agent_instance = agent_class()
                    # Store for reuse during this coordinator's lifetime
                    self.agents[agent_name] = agent_instance
                    return agent_instance

        # Fallback: Try stripping "agent-" prefix and looking up directly
        # This handles cases where agent name doesn't match a config but might be a direct agent_domain
        if agent_name.startswith("agent-"):
            agent_domain = agent_name.replace("agent-", "").replace("-", "_")

            agent_class_mapping = {
                "contract_driven_generator": CoderAgent,
                "debug_intelligence": DebugIntelligenceAgent,
                "testing": TestingAgent,
                "refactoring_intelligence_v2": RefactoringAgent,
                "research": ResearcherAgent,
                "architect": ArchitectAgent,
            }

            agent_class = agent_class_mapping.get(agent_domain)
            if agent_class and agent_name not in self.agents:
                agent_instance = agent_class()
                self.agents[agent_name] = agent_instance
                return agent_instance

        return None

    async def cleanup(self):
        """Cleanup all agents and loader."""
        # Cleanup agent instances
        for agent in self.agents.values():
            if hasattr(agent, "cleanup"):
                await agent.cleanup()

        # Cleanup agent loader
        if self.agent_loader:
            await self.agent_loader.cleanup()

    def get_agent_registry_stats(self) -> Dict[str, Any]:
        """
        Get statistics about agent registry.

        Returns:
            Dictionary with registry stats
        """
        stats = {}

        # Agent loader stats
        if self.use_dynamic_loading and self.agent_loader:
            stats.update(self.agent_loader.get_agent_stats())
        else:
            stats.update({
                "total_agents": len(self.agents),
                "mode": "legacy_hardcoded"
            })

        # Add router stats
        stats['router'] = self.get_router_stats()

        return stats

    def get_router_stats(self) -> Dict[str, Any]:
        """
        Get enhanced router statistics.

        Returns:
            Dictionary with routing performance metrics
        """
        stats = {
            'enabled': self.use_enhanced_router,
            'available': ROUTER_AVAILABLE,
            'confidence_threshold': self.router_confidence_threshold,
            **self.router_stats
        }

        # Calculate rates
        if stats['total_routes'] > 0:
            stats['router_usage_rate'] = stats['router_used'] / stats['total_routes']
            stats['fallback_rate'] = stats['fallback_used'] / stats['total_routes']
            stats['below_threshold_rate'] = stats['below_threshold'] / stats['total_routes']
            stats['error_rate'] = stats['router_errors'] / stats['total_routes']

        # Add router-specific stats if available
        if self.router:
            try:
                router_internal_stats = self.router.get_routing_stats()
                stats['router_internal'] = router_internal_stats

                cache_stats = self.router.get_cache_stats()
                stats['cache'] = cache_stats
            except Exception as e:
                stats['router_internal_error'] = str(e)

        return stats
