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
from typing import Any
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
    logger.debug(
        "transformation_event_publisher not available, transformation events will not be logged"
    )
    KAFKA_AVAILABLE = False

# Import transformation validator
try:
    from omniclaude.lib.core.transformation_validator import (
        TransformationValidationResult,
        TransformationValidator,
        ValidatorOutcome,
    )

    VALIDATOR_AVAILABLE = True
except ImportError:  # nosec B110 - Optional dependency, graceful degradation
    logger.debug(
        "transformation_validator not available, transformations will not be validated"
    )
    VALIDATOR_AVAILABLE = False
    # Stub types for when validator is not available
    ValidatorOutcome = None  # type: ignore[misc,assignment]
    TransformationValidator = None  # type: ignore[misc,assignment]
    TransformationValidationResult = None  # type: ignore[misc,assignment]


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
        triggers_formatted = "\n".join(
            f"  - {trig}" for trig in self.triggers[:5]
        )  # Top 5

        # Format success criteria if available
        success_formatted = ""
        if self.success_criteria:
            success_formatted = "\n\n**SUCCESS CRITERIA**:\n" + "\n".join(
                f"  - {criterion}" for criterion in self.success_criteria
            )

        # Format intelligence integration if available
        intelligence_formatted = ""
        if self.intelligence_integration:
            intelligence_formatted = f"\n\n**INTELLIGENCE WORKFLOWS**:\n{self.intelligence_integration[:1000]}..."

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
        with open(config_path, encoding="utf-8") as f:
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
            description=config.get(
                "agent_description", config.get("agent_purpose", "")
            ),
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
        skip_validation: bool = False,
    ) -> str:
        """
        Load agent, validate transformation, log event to Kafka, and return formatted prompt.

        This is the RECOMMENDED method for transformations as it provides:
        - Transformation validation (prevents invalid self-transformations)
        - Full observability via Kafka events
        - Validation outcome tracking for metrics

        Args:
            agent_name: Agent to transform into
            source_agent: Original agent identity (default: "polymorphic-agent")
            transformation_reason: Why this transformation occurred
            correlation_id: Request correlation ID for tracing
            user_request: Original user request
            routing_confidence: Router confidence score (0.0-1.0)
            routing_strategy: Routing strategy used
            skip_validation: Skip validation (use with caution)

        Returns:
            Formatted prompt for identity assumption

        Raises:
            ValueError: If transformation is blocked by validator
        """
        start_time = time.time()
        validation_result: TransformationValidationResult | None = None
        validation_outcome: str | None = None
        validation_metrics: dict | None = None

        try:
            # Step 1: Validate transformation (unless skipped)
            if VALIDATOR_AVAILABLE and not skip_validation:
                validator = TransformationValidator()
                validation_result = validator.validate(
                    from_agent=source_agent,
                    to_agent=agent_name,
                    reason=transformation_reason or "",
                    confidence=routing_confidence,
                    user_request=user_request,
                )
                validation_outcome = validation_result.outcome.value
                validation_metrics = validation_result.metrics

                # Log validation result
                if validation_result.warning_message:
                    logger.warning(
                        f"Transformation validation warning: {validation_result.warning_message}"
                    )

                # Block invalid transformations
                if not validation_result.is_valid:
                    transformation_duration_ms = int((time.time() - start_time) * 1000)

                    # Emit blocked transformation event
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
                            error_message=validation_result.error_message,
                            error_type="ValidationError",
                            event_type=TransformationEventType.FAILED,
                            validation_outcome=validation_outcome,
                            validation_metrics=validation_metrics,
                        )

                    logger.warning(
                        f"Transformation blocked: {source_agent} → {agent_name} | "
                        f"Reason: {validation_result.error_message}"
                    )
                    raise ValueError(
                        f"Transformation blocked: {validation_result.error_message}"
                    )

            # Step 2: Load agent identity
            identity = self.load_agent(agent_name)

            # Calculate transformation duration
            transformation_duration_ms = int((time.time() - start_time) * 1000)

            # Step 3: Log transformation event to Kafka (async, non-blocking)
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
                    validation_outcome=validation_outcome,
                    validation_metrics=validation_metrics,
                )
                logger.debug(
                    f"Transformation: {source_agent} → {identity.name} | "
                    f"validation={validation_outcome} | "
                    f"duration={transformation_duration_ms}ms"
                )
            else:
                logger.debug(
                    f"Transformation {source_agent} → {identity.name} "
                    f"(validation={validation_outcome}, events unavailable)"
                )

            return identity.format_assumption_prompt()

        except ValueError:
            # Re-raise validation errors (already logged above)
            raise

        except Exception as e:
            # Log failed transformation (non-validation errors)
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
                    validation_outcome=validation_outcome,
                    validation_metrics=validation_metrics,
                )
                logger.error(
                    f"Failed transformation: {source_agent} → {agent_name} | error={e}"
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
        skip_validation: bool = False,
    ) -> str:
        """
        Synchronous wrapper for transform_with_logging.

        Use async version when possible. This creates event loop if needed.

        WARNING: Do not call this from async code (within a running event loop).
        Doing so will raise RuntimeError. Use `transform_with_logging` directly
        in async contexts, or call via `asyncio.run_coroutine_threadsafe()`.

        Args:
            Same as transform_with_logging

        Returns:
            Formatted prompt for identity assumption

        Raises:
            ValueError: If transformation is blocked by validator
            RuntimeError: If called from within a running event loop
        """
        # Check if we're already in an async context
        try:
            asyncio.get_running_loop()
            # If we get here, there IS a running loop - we cannot use run_until_complete
            raise RuntimeError(
                "Cannot call transform_sync_with_logging from within a running event loop. "
                "Use `await transform_with_logging(...)` instead, or run in a separate thread."
            )
        except RuntimeError as e:
            # If the error is our own, re-raise it
            if "Cannot call transform_sync_with_logging" in str(e):
                raise
            # Otherwise, no running loop exists - create one for sync execution
            pass

        # No running loop - safe to create and run synchronously
        loop = asyncio.new_event_loop()
        try:
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
                    skip_validation=skip_validation,
                )
            )
        finally:
            loop.close()


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
