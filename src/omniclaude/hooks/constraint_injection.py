# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Architectural constraint injection for skill context (OMN-6817).

Injects relevant architectural constraints into the context when a skill starts,
preventing agents from taking approaches that violate known conventions.

Constraints are loaded from built-in constraint templates covering naming
conventions, bus policy, env var rules, modeling rules, and infrastructure
policy. Future extension: memory files from the user's auto-memory directory.

The injector selects constraints relevant to the current skill/domain and formats
them as a markdown block for inclusion in the agent's context window.

Environment variables:
    OMNICLAUDE_CONSTRAINT_INJECTION_ENABLED: Enable/disable (default: true)
    OMNICLAUDE_CONSTRAINT_MAX_ITEMS: Max constraints to inject (default: 10)
"""

from __future__ import annotations

import logging
import os
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class EnumConstraintDomain(str, Enum):
    """Domains that constraints can apply to."""

    NAMING = "naming"
    BUS_POLICY = "bus_policy"
    ENV_VARS = "env_vars"
    INFRASTRUCTURE = "infrastructure"
    MODELING = "modeling"
    TESTING = "testing"
    GENERAL = "general"


class ModelConstraintTemplate(BaseModel):
    """A single architectural constraint template.

    Attributes:
        name: Short identifier for the constraint.
        domain: Which domain this constraint belongs to.
        rule: The constraint rule text.
        reason: Why this constraint exists.
        applies_to_skills: Skill names this applies to (empty = all skills).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Short identifier for the constraint")
    domain: EnumConstraintDomain = Field(description="Constraint domain")
    rule: str = Field(description="The constraint rule text")
    reason: str = Field(description="Why this constraint exists")
    applies_to_skills: tuple[str, ...] = Field(
        default=(),
        description="Skill names this applies to (empty = all skills)",
    )


class ModelConstraintInjectionConfig(BaseModel):
    """Configuration for constraint injection.

    Attributes:
        enabled: Whether constraint injection is enabled.
        max_items: Maximum number of constraints to inject.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(default=True, description="Enable constraint injection")
    max_items: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum constraints to inject",
    )

    @classmethod
    def from_env(cls) -> ModelConstraintInjectionConfig:
        """Load config from environment variables."""
        enabled_str = os.getenv(
            "OMNICLAUDE_CONSTRAINT_INJECTION_ENABLED",
            "true",  # ONEX_FLAG_EXEMPT: migration
        )
        enabled = enabled_str.lower() in ("true", "1", "yes")

        max_items_str = os.getenv("OMNICLAUDE_CONSTRAINT_MAX_ITEMS", "10")
        try:
            max_items = int(max_items_str)
        except ValueError:
            max_items = 10

        return cls(enabled=enabled, max_items=max_items)


# ─── Built-in constraint templates ──────────────────────────────────────────

BUILTIN_CONSTRAINTS: tuple[ModelConstraintTemplate, ...] = (
    ModelConstraintTemplate(
        name="model_prefix",
        domain=EnumConstraintDomain.NAMING,
        rule="All Pydantic models MUST use the 'Model' prefix (e.g., ModelFoo, not Foo).",
        reason="Enforced naming convention across all OmniNode repos for grep-ability and consistency.",
    ),
    ModelConstraintTemplate(
        name="enum_prefix",
        domain=EnumConstraintDomain.NAMING,
        rule="All enums MUST use the 'Enum' prefix and inherit from (str, Enum).",
        reason="Enforced naming convention; str enums serialize cleanly to JSON.",
    ),
    ModelConstraintTemplate(
        name="no_dataclass",
        domain=EnumConstraintDomain.MODELING,
        rule="Never use @dataclass. Always use Pydantic BaseModel with ConfigDict(frozen=True, extra='forbid').",
        reason="Pydantic provides validation, serialization, and schema generation.",
    ),
    ModelConstraintTemplate(
        name="no_ollama",
        domain=EnumConstraintDomain.INFRASTRUCTURE,
        rule="Never deploy or use Ollama. Existing LLM architecture covers all tiers.",
        reason="Ollama was decommissioned; adapters exist but active usage is forbidden.",
    ),
    ModelConstraintTemplate(
        name="bus_policy_local",
        domain=EnumConstraintDomain.BUS_POLICY,
        rule="Docker containers use redpanda:9092 (internal). Host scripts use localhost:19092. Never use port 29092 inside docker-compose.",
        reason="Two-bus architecture: cloud bus (29092) vs local Docker bus (19092).",
    ),
    ModelConstraintTemplate(
        name="no_env_fallbacks",
        domain=EnumConstraintDomain.ENV_VARS,
        rule="No env var fallbacks for runtime config. Use Infisical or crash.",
        reason="Fallbacks hide broken config silently; caused production incidents.",
    ),
    ModelConstraintTemplate(
        name="single_env_source",
        domain=EnumConstraintDomain.ENV_VARS,
        rule="~/.omnibase/.env is the SINGLE source of truth for all configuration. No .env.local files in any repo.",
        reason="Env shadowing caused auth failures; single source prevents divergence.",
    ),
    ModelConstraintTemplate(
        name="inmemory_bus_forbidden",
        domain=EnumConstraintDomain.BUS_POLICY,
        rule="ONEX_EVENT_BUS_TYPE=inmemory is FORBIDDEN. It silently drops all Kafka events.",
        reason="In-memory bus looks like it works but drops all events, breaking observability.",
    ),
    ModelConstraintTemplate(
        name="pep604_unions",
        domain=EnumConstraintDomain.NAMING,
        rule="Use PEP 604 type unions: X | Y, not Optional[X] or Union[X, Y].",
        reason="Python 3.12+ standard; cleaner and more readable.",
    ),
    ModelConstraintTemplate(
        name="uv_only",
        domain=EnumConstraintDomain.GENERAL,
        rule="Always use 'uv run' for all Python commands. Never use direct pip or python.",
        reason="uv manages virtual environments and dependencies consistently.",
    ),
)


def select_constraints(
    skill_name: str | None = None,
    domains: tuple[EnumConstraintDomain, ...] | None = None,
    max_items: int = 10,
) -> list[ModelConstraintTemplate]:
    """Select relevant constraints for a given skill and domain context.

    Args:
        skill_name: Current skill name (None = select general constraints).
        domains: Filter to specific domains (None = all domains).
        max_items: Maximum number of constraints to return.

    Returns:
        List of matching constraint templates, up to max_items.
    """
    candidates: list[ModelConstraintTemplate] = []

    for constraint in BUILTIN_CONSTRAINTS:
        # Filter by skill applicability
        if constraint.applies_to_skills and skill_name:
            if skill_name not in constraint.applies_to_skills:
                continue
        elif constraint.applies_to_skills and not skill_name:
            continue

        # Filter by domain
        if domains and constraint.domain not in domains:
            continue

        candidates.append(constraint)

    return candidates[:max_items]


def format_constraints_markdown(
    constraints: list[ModelConstraintTemplate],
) -> str:
    """Format constraints as a markdown block for context injection.

    Args:
        constraints: List of constraints to format.

    Returns:
        Markdown string with constraints formatted as a numbered list.
        Empty string if no constraints.
    """
    if not constraints:
        return ""

    lines: list[str] = ["## Architectural Constraints", ""]
    lines.append(
        "The following constraints MUST be followed. "
        "Violating these will cause CI failures or runtime errors."
    )
    lines.append("")

    for i, c in enumerate(constraints, 1):
        lines.append(f"{i}. **{c.name}** [{c.domain.value}]: {c.rule}")
        lines.append(f"   - *Why*: {c.reason}")

    return "\n".join(lines)


def inject_constraints(
    skill_name: str | None = None,
    domains: tuple[EnumConstraintDomain, ...] | None = None,
    config: ModelConstraintInjectionConfig | None = None,
) -> str:
    """Main entry point: select and format constraints for injection.

    Args:
        skill_name: Current skill name.
        domains: Filter to specific domains.
        config: Override config (default: from environment).

    Returns:
        Formatted markdown string with constraints, or empty string if disabled.
    """
    if config is None:
        config = ModelConstraintInjectionConfig.from_env()

    if not config.enabled:
        return ""

    constraints = select_constraints(
        skill_name=skill_name,
        domains=domains,
        max_items=config.max_items,
    )

    return format_constraints_markdown(constraints)


__all__ = [
    "BUILTIN_CONSTRAINTS",
    "EnumConstraintDomain",
    "ModelConstraintInjectionConfig",
    "ModelConstraintTemplate",
    "format_constraints_markdown",
    "inject_constraints",
    "select_constraints",
]
