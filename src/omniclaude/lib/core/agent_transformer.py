#!/usr/bin/env python3
"""
Agent Polymorphic Transformation Helper

Loads YAML agent configs and formats them for identity assumption.
Enables agent-workflow-coordinator to transform into any agent.

Now with integrated transformation event logging to Kafka for observability.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import yaml

# Set up logging
logger = logging.getLogger(__name__)

# Import transformation event publisher (optional integration)
try:
    from omniclaude.lib.transformation_event_publisher import (
        TransformationEventType,
        publish_transformation_event,
    )

    KAFKA_AVAILABLE = True
except ImportError:  # nosec B110 - Optional dependency, graceful degradation
    logger.warning(
        "transformation_event_publisher not available, transformation events will not be logged"
    )
    KAFKA_AVAILABLE = False


@dataclass
class AgentIdentity:
    """Parsed agent identity for transformation."""

    name: str
    purpose: str
    domain: str
    description: str
    capabilities: list[str]
    triggers: list[str]
    intelligence_integration: str | None = None
    success_criteria: list[str] | None = None

    def format_assumption_prompt(self) -> str:
        """Format identity for assumption by coordinator."""

        # Format capabilities
        caps_formatted = "\n".join(f"  - {cap}" for cap in self.capabilities)

        # Format triggers
        triggers_formatted = "\n".join(f"  - {trig}" for trig in self.triggers[:5])  # Top 5

        # Format success criteria if available
        success_formatted = ""
        if self.success_criteria:
            success_formatted = "\n\n**SUCCESS CRITERIA**:\n" + "\n".join(
                f"  - {criterion}" for criterion in self.success_criteria
            )

        # Format intelligence integration if available
        intelligence_formatted = ""
        if self.intelligence_integration:
            intelligence_formatted = (
                f"\n\n**INTELLIGENCE WORKFLOWS**:\n{self.intelligence_integration[:1000]}..."
            )

        prompt = f"""
========================================================================
🎭 IDENTITY TRANSFORMATION COMPLETE
========================================================================

YOU HAVE TRANSFORMED INTO: {self.name}

**YOUR NEW IDENTITY**:
- **Name**: {self.name}
- **Domain**: {self.domain}
- **Description**: {self.description}

**YOUR PRIMARY PURPOSE**:
{self.purpose}

**YOUR CAPABILITIES**:
{caps_formatted}

**ACTIVATION TRIGGERS** (what users say to invoke you):
{triggers_formatted}
{success_formatted}{intelligence_formatted}

========================================================================
EXECUTION DIRECTIVE
========================================================================

YOU ARE NO LONGER agent-workflow-coordinator.
YOU ARE NOW {self.name}.

- Think ONLY as {self.name}
- Apply {self.domain} expertise
- Use your capabilities to solve the user's problem
- Follow your intelligence workflows if applicable
- Speak with domain authority

Execute the user's request AS {self.name}, not as a coordinator.
========================================================================
"""
        return prompt


class AgentTransformer:
    """Loads and transforms agent identities from YAML configs."""

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize transformer.

        Args:
            config_dir: Directory containing agent-*.yaml files
        """
        if config_dir is None:
            # Default to consolidated agent definitions location (claude/agents/)
            # Path relative to this module: claude/lib/core/ -> claude/agents/
            config_dir = Path(__file__).parent.parent.parent / "agents"

        self.config_dir = Path(config_dir)

        if not self.config_dir.exists():
            raise ValueError(f"Config directory not found: {self.config_dir}")

    def load_agent(self, agent_name: str) -> AgentIdentity:
        """
        Load agent identity from YAML config.

        Args:
            agent_name: Agent name (e.g., "agent-devops-infrastructure")

        Returns:
            AgentIdentity with parsed configuration

        Raises:
            FileNotFoundError: If agent config doesn't exist
            ValueError: If config is malformed
        """
        # Normalize name (add agent- prefix if missing)
        if not agent_name.startswith("agent-"):
            agent_name = f"agent-{agent_name}"

        config_path = self.config_dir / f"{agent_name}.yaml"

        if not config_path.exists():
            raise FileNotFoundError(
                f"Agent config not found: {config_path}\nAvailable agents: {self.list_agents()}"
            )

        # Load YAML
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Parse capabilities (handle dict or list format)
        capabilities = config.get("capabilities", [])
        if isinstance(capabilities, dict):
            # Flatten dict to list
            caps_list = []
            for key, value in capabilities.items():
                if isinstance(value, list):
                    caps_list.extend(value)
                elif isinstance(value, bool) and value:
                    caps_list.append(key)
                else:
                    caps_list.append(f"{key}: {value}")
            capabilities = caps_list
        elif not isinstance(capabilities, list):
            capabilities = [str(capabilities)]

        # Parse intelligence integration (large section)
        intelligence = config.get("intelligence_integration")
        if intelligence:
            intelligence = str(intelligence)

        # Parse success criteria
        success_criteria = config.get("success_criteria")
        if isinstance(success_criteria, dict):
            success_criteria = list(success_criteria.values())
        elif isinstance(success_criteria, str):
            success_criteria = [success_criteria]

        return AgentIdentity(
            name=agent_name,
            purpose=config.get("agent_purpose", "No purpose defined"),
            domain=config.get("agent_domain", "general"),
            description=config.get("agent_description", config.get("agent_purpose", "")),
            capabilities=capabilities,
            triggers=config.get("triggers", []),
            intelligence_integration=intelligence,
            success_criteria=success_criteria,
        )

    def list_agents(self) -> list[str]:
        """List all available agent names."""
        return sorted([f.stem for f in self.config_dir.glob("agent-*.yaml")])

    def transform(self, agent_name: str) -> str:
        """
        Load agent and return formatted transformation prompt.

        Args:
            agent_name: Agent to transform into

        Returns:
            Formatted prompt for identity assumption
        """
        identity = self.load_agent(agent_name)
        return identity.format_assumption_prompt()

    async def transform_with_logging(
        self,
        agent_name: str,
        source_agent: str = "polymorphic-agent",
        transformation_reason: str | None = None,
        correlation_id: str | UUID | None = None,
        user_request: str | None = None,
        routing_confidence: float | None = None,
        routing_strategy: str | None = None,
    ) -> str:
        """
        Load agent, log transformation event to Kafka, and return formatted prompt.

        This is the RECOMMENDED method for transformations as it provides full observability.

        Args:
            agent_name: Agent to transform into
            source_agent: Original agent identity (default: "polymorphic-agent")
            transformation_reason: Why this transformation occurred
            correlation_id: Request correlation ID for tracing
            user_request: Original user request
            routing_confidence: Router confidence score (0.0-1.0)
            routing_strategy: Routing strategy used

        Returns:
            Formatted prompt for identity assumption
        """
        start_time = time.time()

        try:
            # Load agent identity
            identity = self.load_agent(agent_name)

            # Calculate transformation duration
            transformation_duration_ms = int((time.time() - start_time) * 1000)

            # Log transformation event to Kafka (async, non-blocking)
            if KAFKA_AVAILABLE:
                await publish_transformation_event(
                    source_agent=source_agent,
                    target_agent=identity.name,
                    transformation_reason=transformation_reason
                    or f"Transformed to {identity.name}",
                    correlation_id=correlation_id,
                    user_request=user_request,
                    routing_confidence=routing_confidence,
                    routing_strategy=routing_strategy,
                    transformation_duration_ms=transformation_duration_ms,
                    success=True,
                    event_type=TransformationEventType.COMPLETED,
                )
                logger.debug(
                    f"Logged transformation: {source_agent} → {identity.name} "
                    f"(duration={transformation_duration_ms}ms)"
                )
            else:
                logger.warning(
                    f"Transformation {source_agent} → {identity.name} not logged (Kafka unavailable)"
                )

            return identity.format_assumption_prompt()

        except Exception as e:
            # Log failed transformation
            transformation_duration_ms = int((time.time() - start_time) * 1000)

            if KAFKA_AVAILABLE:
                await publish_transformation_event(
                    source_agent=source_agent,
                    target_agent=agent_name,
                    transformation_reason=transformation_reason
                    or f"Attempted to transform to {agent_name}",
                    correlation_id=correlation_id,
                    user_request=user_request,
                    routing_confidence=routing_confidence,
                    routing_strategy=routing_strategy,
                    transformation_duration_ms=transformation_duration_ms,
                    success=False,
                    error_message=str(e),
                    error_type=type(e).__name__,
                    event_type=TransformationEventType.FAILED,
                )
                logger.error(
                    f"Logged failed transformation: {source_agent} → {agent_name} (error={e})"
                )

            # Re-raise the exception
            raise

    def transform_sync_with_logging(
        self,
        agent_name: str,
        source_agent: str = "polymorphic-agent",
        transformation_reason: str | None = None,
        correlation_id: str | UUID | None = None,
        user_request: str | None = None,
        routing_confidence: float | None = None,
        routing_strategy: str | None = None,
    ) -> str:
        """
        Synchronous wrapper for transform_with_logging.

        Use async version when possible. This creates event loop if needed.

        Args:
            Same as transform_with_logging

        Returns:
            Formatted prompt for identity assumption
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.transform_with_logging(
                agent_name=agent_name,
                source_agent=source_agent,
                transformation_reason=transformation_reason,
                correlation_id=correlation_id,
                user_request=user_request,
                routing_confidence=routing_confidence,
                routing_strategy=routing_strategy,
            )
        )


def main() -> None:
    """CLI interface for testing transformations."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Agent polymorphic transformer")
    parser.add_argument("agent_name", nargs="?", help="Agent to transform into")
    parser.add_argument("--list", action="store_true", help="List available agents")

    args = parser.parse_args()

    transformer = AgentTransformer()

    if args.list:
        print("Available agents:")
        for agent in transformer.list_agents():
            print(f"  - {agent}")
        return

    if not args.agent_name:
        parser.error("agent_name is required unless using --list")
        # parser.error() raises SystemExit, this line is never reached

    try:
        transformation_prompt = transformer.transform(args.agent_name)
        print(transformation_prompt)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Transformation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
