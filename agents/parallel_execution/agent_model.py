"""
Simple Pydantic models for agent configs and execution.
Loads directly from YAML files in agents/configs/
"""

import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Minimal agent configuration loaded from YAML."""

    agent_name: str
    agent_domain: str
    agent_purpose: str
    archon_mcp_enabled: bool = False
    parallel_capable: bool = False

    # Intelligence queries
    domain_query: Optional[str] = None
    implementation_query: Optional[str] = None
    match_count: int = 5

    # Instructions for execution
    instructions: str = ""

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "AgentConfig":
        """Load agent config from YAML file."""
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        return cls(
            agent_name=Path(yaml_path).stem,
            agent_domain=data.get("agent_domain", ""),
            agent_purpose=data.get("agent_purpose", ""),
            archon_mcp_enabled=data.get("archon_mcp_enabled", False),
            parallel_capable=data.get("parallel_capable", False),
            domain_query=data.get("domain_query"),
            implementation_query=data.get("implementation_query"),
            match_count=data.get("match_count", 5),
            instructions=data.get("instructions", ""),
        )

    @classmethod
    def load(cls, agent_name: str, config_dir: Optional[str] = None) -> "AgentConfig":
        """Load agent config by name."""
        if config_dir is None:
            # Default to repo agents/configs directory
            config_dir = Path(__file__).parent.parent.parent / "agents" / "configs"
        yaml_path = Path(config_dir) / f"{agent_name}.yaml"
        return cls.from_yaml(str(yaml_path))


class AgentTask(BaseModel):
    """Task for agent to execute."""

    task_id: str
    description: str
    agent_name: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)


class AgentResult(BaseModel):
    """Result from agent execution."""

    task_id: str
    agent_name: str
    success: bool
    output_data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: float
    trace_id: Optional[str] = None
