"""
Dynamic Agent Loader with YAML Configuration Support

Loads agent definitions from YAML files with validation, hot-reload, and lifecycle management.
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from enum import Enum

import yaml
from pydantic import BaseModel, Field, field_validator, ConfigDict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from trace_logger import get_trace_logger, TraceEventType, TraceLevel


class AgentCapabilities(BaseModel):
    """Agent capability flags."""
    mandatory_functions: bool = False
    template_system: bool = False
    enhanced_patterns: bool = False
    quality_intelligence: bool = False
    onex_compliance_validation: bool = False
    quality_assured_generation: bool = False
    anti_pattern_prevention: bool = False
    historical_pattern_learning: bool = False
    automated_quality_gates: bool = False
    performance_impact_assessment: bool = False
    quality_correlation_analysis: bool = False
    root_cause_confidence_scoring: bool = False
    api_design_consistency_validation: bool = False
    best_practice_pattern_enforcement: bool = False
    historical_api_pattern_reuse: bool = False
    quality_driven_endpoint_design: bool = False
    performance_aware_architecture: bool = False

    model_config = ConfigDict(extra="allow")  # Allow extra capabilities not in base schema


class IntelligenceConfig(BaseModel):
    """Intelligence integration configuration."""
    enabled: bool = False
    patterns: List[str] = Field(default_factory=list)
    quality_analysis: bool = False
    pattern_recognition: bool = False
    performance_correlation: bool = False
    quality_threshold: float = 0.6
    compliance_type: str = "onex"
    pre_generation_validation: bool = False
    post_generation_validation: bool = False
    template_learning: bool = False
    pre_design_analysis: bool = False
    during_design_validation: bool = False
    post_design_quality_gates: bool = False
    continuous_pattern_learning: bool = False
    pattern_library_enabled: bool = False

    model_config = ConfigDict(extra="allow")


class QualityGates(BaseModel):
    """Quality gate thresholds."""
    minimum_quality_score: float = 0.7
    minimum_onex_compliance: int = 70
    zero_critical_antipatterns: bool = True
    require_type_annotations: bool = True

    model_config = ConfigDict(extra="allow")


class IntelligenceIntegration(BaseModel):
    """Extended intelligence integration with quality gates."""
    enabled: bool = True
    pre_generation_validation: bool = False
    post_generation_validation: bool = False
    template_learning: bool = False
    quality_gates: Optional[QualityGates] = None
    pre_design_analysis: bool = False
    during_design_validation: bool = False
    post_design_quality_gates: bool = False
    continuous_pattern_learning: bool = False
    pattern_library_enabled: bool = False

    model_config = ConfigDict(extra="allow")


class AgentConfig(BaseModel):
    """Complete agent configuration from YAML."""
    agent_domain: str
    agent_purpose: str
    agent_title: str
    agent_description: str
    agent_context: str
    domain_query: str
    implementation_query: str
    match_count: int = 5
    confidence_threshold: float = 0.6
    knowledge_capture_level: str = "comprehensive"
    capabilities: AgentCapabilities
    archon_mcp_enabled: bool = True
    correlation_tracking: bool = True
    parallel_capable: bool = True
    triggers: List[str] = Field(default_factory=list)
    instructions: str = ""
    intelligence: Optional[IntelligenceConfig] = None
    intelligence_integration: Optional[IntelligenceIntegration] = None

    # Metadata
    config_path: Optional[Path] = None
    loaded_at: Optional[datetime] = None
    file_version: str = "1.0.0"

    @field_validator("confidence_threshold")
    @classmethod
    def validate_confidence(cls, v):
        """Ensure confidence threshold is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        return v

    @field_validator("triggers")
    @classmethod
    def validate_triggers(cls, v):
        """Ensure at least one trigger is defined."""
        if not v:
            raise ValueError("Agent must have at least one trigger")
        return v

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AgentLoadStatus(str, Enum):
    """Agent load status."""
    LOADED = "loaded"
    FAILED = "failed"
    RELOADING = "reloading"
    UNLOADED = "unloaded"


class LoadedAgent(BaseModel):
    """Metadata for a loaded agent."""
    agent_name: str
    config: Optional[AgentConfig] = None
    status: AgentLoadStatus
    load_time_ms: float
    error: Optional[str] = None
    version: str = "1.0.0"

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AgentConfigChangeHandler(FileSystemEventHandler):
    """Watches for agent config file changes and triggers reload."""

    def __init__(self, loader: "AgentLoader"):
        self.loader = loader
        self.trace_logger = get_trace_logger()

    def on_modified(self, event):
        """Handle file modification events."""
        if isinstance(event, FileModifiedEvent) and event.src_path.endswith(('.yaml', '.yml')):
            asyncio.create_task(self._handle_config_change(event.src_path))

    def on_created(self, event):
        """Handle file creation events."""
        if isinstance(event, FileCreatedEvent) and event.src_path.endswith(('.yaml', '.yml')):
            asyncio.create_task(self._handle_config_change(event.src_path))

    async def _handle_config_change(self, file_path: str):
        """Handle configuration file change."""
        agent_name = Path(file_path).stem

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_START,
            message=f"Detected config change for {agent_name}",
            level=TraceLevel.INFO,
            metadata={"file_path": file_path}
        )

        # Reload the specific agent
        await self.loader.reload_agent(agent_name)


class AgentLoader:
    """
    Dynamic agent loader with YAML configuration support.

    Features:
    - Load agents from YAML configuration files
    - Pydantic validation for configuration schema
    - Hot-reload capability with file watching
    - Agent lifecycle management (load/unload/reload)
    - Version compatibility checking
    - Capability indexing for enhanced routing
    """

    def __init__(self, config_dir: Optional[Path] = None, enable_hot_reload: bool = True):
        """
        Initialize agent loader.

        Args:
            config_dir: Directory containing agent YAML configs (default: ~/.claude/agents/configs/)
            enable_hot_reload: Enable automatic reload on config changes
        """
        self.config_dir = config_dir or Path.home() / ".claude" / "agents" / "configs"
        self.enable_hot_reload = enable_hot_reload
        self.trace_logger = get_trace_logger()

        # Agent registry
        self.agents: Dict[str, LoadedAgent] = {}
        self.capability_index: Dict[str, Set[str]] = {}  # capability -> agent_names

        # File watching
        self.observer: Optional[Observer] = None
        self._is_initialized = False

    async def initialize(self) -> Dict[str, LoadedAgent]:
        """
        Initialize loader and load all agent configurations.

        Returns:
            Dictionary of loaded agents
        """
        start_time = time.time()

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_START,
            message=f"Initializing agent loader from {self.config_dir}",
            level=TraceLevel.INFO
        )

        # Ensure config directory exists
        if not self.config_dir.exists():
            error_msg = f"Agent config directory not found: {self.config_dir}"
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR
            )
            raise FileNotFoundError(error_msg)

        # Load all agent configs
        await self._load_all_agents()

        # Build capability index
        self._build_capability_index()

        # Setup hot-reload if enabled
        if self.enable_hot_reload:
            await self._setup_hot_reload()

        self._is_initialized = True
        load_time_ms = (time.time() - start_time) * 1000

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_END,
            message=f"Agent loader initialized: {len(self.agents)} agents in {load_time_ms:.2f}ms",
            level=TraceLevel.INFO,
            metadata={
                "agent_count": len(self.agents),
                "load_time_ms": load_time_ms,
                "capability_count": len(self.capability_index)
            }
        )

        return self.agents

    async def _load_all_agents(self):
        """Load all agent configurations from directory."""
        config_files = list(self.config_dir.glob("*.yaml")) + list(self.config_dir.glob("*.yml"))

        await self.trace_logger.log_event(
            event_type=TraceEventType.PARALLEL_BATCH_START,
            message=f"Loading {len(config_files)} agent configurations",
            level=TraceLevel.INFO
        )

        loaded_count = 0
        failed_count = 0

        for config_file in config_files:
            agent_name = config_file.stem
            try:
                loaded_agent = await self._load_agent_config(config_file)
                self.agents[agent_name] = loaded_agent
                loaded_count += 1

                await self.trace_logger.log_event(
                    event_type=TraceEventType.TASK_COMPLETED,
                    message=f"Loaded agent: {agent_name}",
                    level=TraceLevel.INFO,
                    agent_name=agent_name,
                    metadata={"load_time_ms": loaded_agent.load_time_ms}
                )

            except Exception as e:
                failed_count += 1
                error_msg = f"Failed to load {agent_name}: {str(e)}"

                self.agents[agent_name] = LoadedAgent(
                    agent_name=agent_name,
                    config=None,
                    status=AgentLoadStatus.FAILED,
                    load_time_ms=0.0,
                    error=error_msg
                )

                await self.trace_logger.log_event(
                    event_type=TraceEventType.TASK_FAILED,
                    message=error_msg,
                    level=TraceLevel.ERROR,
                    agent_name=agent_name
                )

        await self.trace_logger.log_event(
            event_type=TraceEventType.PARALLEL_BATCH_END,
            message=f"Batch load complete: {loaded_count} loaded, {failed_count} failed",
            level=TraceLevel.INFO,
            metadata={"loaded": loaded_count, "failed": failed_count}
        )

    async def _load_agent_config(self, config_file: Path) -> LoadedAgent:
        """
        Load and validate a single agent configuration.

        Args:
            config_file: Path to agent YAML config

        Returns:
            LoadedAgent instance with validated config
        """
        start_time = time.time()

        # Read YAML file
        with open(config_file, 'r') as f:
            raw_config = yaml.safe_load(f)

        # Validate with Pydantic
        config = AgentConfig(**raw_config)
        config.config_path = config_file
        config.loaded_at = datetime.now()

        load_time_ms = (time.time() - start_time) * 1000

        return LoadedAgent(
            agent_name=config_file.stem,
            config=config,
            status=AgentLoadStatus.LOADED,
            load_time_ms=load_time_ms
        )

    def _build_capability_index(self):
        """Build inverted index of capabilities to agents."""
        self.capability_index.clear()

        for agent_name, loaded_agent in self.agents.items():
            if loaded_agent.status != AgentLoadStatus.LOADED:
                continue

            # Index all capabilities
            capabilities = loaded_agent.config.capabilities.model_dump()
            for capability, enabled in capabilities.items():
                if enabled:
                    if capability not in self.capability_index:
                        self.capability_index[capability] = set()
                    self.capability_index[capability].add(agent_name)

            # Index triggers for fast lookup
            for trigger in loaded_agent.config.triggers:
                trigger_key = f"trigger:{trigger.lower()}"
                if trigger_key not in self.capability_index:
                    self.capability_index[trigger_key] = set()
                self.capability_index[trigger_key].add(agent_name)

    async def _setup_hot_reload(self):
        """Setup file watcher for hot-reload."""
        try:
            self.observer = Observer()
            event_handler = AgentConfigChangeHandler(self)
            self.observer.schedule(event_handler, str(self.config_dir), recursive=False)
            self.observer.start()

            await self.trace_logger.log_event(
                event_type=TraceEventType.COORDINATOR_START,
                message=f"Hot-reload enabled for {self.config_dir}",
                level=TraceLevel.INFO
            )

        except Exception as e:
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=f"Failed to setup hot-reload: {str(e)}",
                level=TraceLevel.WARNING
            )

    async def reload_agent(self, agent_name: str) -> Optional[LoadedAgent]:
        """
        Reload a specific agent configuration.

        Args:
            agent_name: Name of agent to reload

        Returns:
            Updated LoadedAgent instance or None if failed
        """
        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_START,
            message=f"Reloading agent: {agent_name}",
            level=TraceLevel.INFO,
            agent_name=agent_name
        )

        # Mark as reloading
        if agent_name in self.agents:
            self.agents[agent_name].status = AgentLoadStatus.RELOADING

        # Find config file
        config_file = self.config_dir / f"{agent_name}.yaml"
        if not config_file.exists():
            config_file = self.config_dir / f"{agent_name}.yml"

        if not config_file.exists():
            error_msg = f"Config file not found for {agent_name}"
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR,
                agent_name=agent_name
            )
            return None

        try:
            # Load new config
            loaded_agent = await self._load_agent_config(config_file)
            self.agents[agent_name] = loaded_agent

            # Rebuild capability index
            self._build_capability_index()

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_COMPLETED,
                message=f"Agent reloaded successfully: {agent_name}",
                level=TraceLevel.INFO,
                agent_name=agent_name,
                metadata={"load_time_ms": loaded_agent.load_time_ms}
            )

            return loaded_agent

        except Exception as e:
            error_msg = f"Failed to reload {agent_name}: {str(e)}"

            self.agents[agent_name] = LoadedAgent(
                agent_name=agent_name,
                config=None,
                status=AgentLoadStatus.FAILED,
                load_time_ms=0.0,
                error=error_msg
            )

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_FAILED,
                message=error_msg,
                level=TraceLevel.ERROR,
                agent_name=agent_name
            )

            return None

    async def unload_agent(self, agent_name: str) -> bool:
        """
        Unload an agent from registry.

        Args:
            agent_name: Name of agent to unload

        Returns:
            True if successfully unloaded
        """
        if agent_name not in self.agents:
            return False

        self.agents[agent_name].status = AgentLoadStatus.UNLOADED

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_END,
            message=f"Agent unloaded: {agent_name}",
            level=TraceLevel.INFO,
            agent_name=agent_name
        )

        # Rebuild capability index
        self._build_capability_index()

        return True

    def get_agent_config(self, agent_name: str) -> Optional[AgentConfig]:
        """
        Get configuration for a specific agent.

        Args:
            agent_name: Name of agent

        Returns:
            AgentConfig or None if not found/loaded
        """
        loaded_agent = self.agents.get(agent_name)
        if loaded_agent and loaded_agent.status == AgentLoadStatus.LOADED:
            return loaded_agent.config
        return None

    def get_agents_by_capability(self, capability: str) -> List[str]:
        """
        Get all agents with a specific capability.

        Args:
            capability: Capability name

        Returns:
            List of agent names
        """
        return list(self.capability_index.get(capability, set()))

    def get_agents_by_trigger(self, trigger: str) -> List[str]:
        """
        Get all agents matching a trigger phrase.

        Args:
            trigger: Trigger phrase

        Returns:
            List of agent names
        """
        trigger_key = f"trigger:{trigger.lower()}"
        return list(self.capability_index.get(trigger_key, set()))

    def get_all_agents(self) -> Dict[str, LoadedAgent]:
        """
        Get all loaded agents.

        Returns:
            Dictionary of agent_name to LoadedAgent
        """
        return {
            name: agent
            for name, agent in self.agents.items()
            if agent.status == AgentLoadStatus.LOADED
        }

    def get_agent_stats(self) -> Dict[str, Any]:
        """
        Get loader statistics.

        Returns:
            Dictionary with stats
        """
        total = len(self.agents)
        loaded = sum(1 for a in self.agents.values() if a.status == AgentLoadStatus.LOADED)
        failed = sum(1 for a in self.agents.values() if a.status == AgentLoadStatus.FAILED)

        return {
            "total_agents": total,
            "loaded_agents": loaded,
            "failed_agents": failed,
            "capabilities_indexed": len(self.capability_index),
            "hot_reload_enabled": self.enable_hot_reload,
            "is_initialized": self._is_initialized
        }

    async def cleanup(self):
        """Cleanup resources."""
        if self.observer:
            self.observer.stop()
            self.observer.join()

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_END,
            message="Agent loader cleanup complete",
            level=TraceLevel.INFO,
            metadata=self.get_agent_stats()
        )
