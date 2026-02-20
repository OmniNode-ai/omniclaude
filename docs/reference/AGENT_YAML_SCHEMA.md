# Agent YAML Schema Reference

Agents are defined as YAML files in `plugins/onex/agents/configs/`.
All files are loaded by the agent framework at routing time.

## Required Fields

```yaml
schema_version: "1.0.0"     # Required — always "1.0.0"
agent_type: snake_case       # Required — e.g., api_architect, polymorphic_agent

agent_identity:
  name: "agent-..."          # Required — must start with "agent-"
  description: "..."         # Required — one-line description

activation_patterns:
  explicit_triggers: [...]   # Required — exact keyword/phrase matches
  context_triggers: [...]    # Required — semantic patterns for routing
```

## Optional Fields

```yaml
agent_identity:
  short_name: "..."          # Alternate short name used in routing output
  aliases: [...]             # Additional names that map to this agent
  title: "..."               # Display title (longer than name)
  color: "blue"              # UI color hint
  domain: "..."              # Domain classification
  core_purpose: "..."        # Extended purpose statement
  specializations: [...]     # List of specialization strings

agent_philosophy:
  core_responsibility: "..." # Primary responsibility statement
  approach: "..."            # Methodology description
  core_principles: [...]     # Bulleted principles
  methodology:
    primary: "..."
    quality_gates: "..."
    compliance: "..."

capabilities:
  primary: [...]             # Top-level capability list
  secondary: [...]           # Supporting capabilities
  specialized: [...]         # Niche capabilities
  primary_functions:         # Structured function list with performance targets
    - name: "..."
      description: "..."
      performance_target: "..."

activation_patterns:
  activation_keywords: [...] # Exact keyword list for fuzzy matching
  context_requirements: [...] # Context conditions that increase confidence
  success_indicators: [...]  # Signals the agent was correctly selected

framework_integration:
  template_system:
    primary_template: "..."
    parameters:
      confidence_threshold: 0.6
  mandatory_functions: [...] # List of functions the agent must call

onex_integration:
  four_node_coordination:    # Maps ONEX node types to agent types
    effect: ...
    compute: ...
    reducer: ...
    orchestrator: ...

git_policy:
  auto_commit: "NEVER"       # Commit behavior — always "NEVER"
  rules: [...]

claude_skills_references:    # Skills this agent uses
  - "@skill-name - Description"

priority: "high"             # Routing priority hint
specialization: "..."        # Specialization domain string
```

## Example — Minimal Working Agent

```yaml
schema_version: "1.0.0"
agent_type: "documentation_writer"

agent_identity:
  name: "agent-documentation-writer"
  description: "Writes and maintains technical documentation for ONEX services"
  color: "green"

activation_patterns:
  explicit_triggers:
    - "write documentation"
    - "update README"
    - "document this"
  context_triggers:
    - "creating or updating markdown documentation"
    - "writing API reference or guides"
```

## Example — Extended Agent (api-architect)

```yaml
schema_version: "1.0.0"
agent_type: "api_architect"
definition_format: "yaml_agent_v1"

agent_identity:
  name: "agent-api-architect"
  title: "API Architect Specialist Agent"
  description: "RESTful API design, OpenAPI specification, FastAPI optimization"
  color: "blue"
  specialization_level: "expert"

agent_philosophy:
  core_responsibility: "Expert in API design patterns and FastAPI optimization"
  principles:
    - "API-first development approach"
    - "Contract-driven design with OpenAPI specifications"

capabilities:
  primary:
    - "RESTful API design and architecture patterns"
    - "OpenAPI specification generation and validation"

activation_patterns:
  explicit_triggers:
    - "api design"
    - "openapi"
    - "fastapi"
  context_triggers:
    - "designing HTTP endpoints for ONEX services"
    - "creating OpenAPI specifications"
```

## Authoring Guide

1. Choose a descriptive `agent_type` in `snake_case` (e.g., `api_architect`, `debug_database`).
2. Set `name` to `"agent-<type-with-hyphens>"` — must start with `"agent-"`.
3. Add `explicit_triggers` for common exact phrases users type (e.g., `"review pr"`, `"openapi"`).
4. Add `context_triggers` for semantic patterns the router uses (e.g., `"designing HTTP endpoints"`).
5. Keep `description` to one line — it appears in routing candidate output shown to Claude.
6. Add `activation_keywords` for additional fuzzy-match terms beyond explicit triggers.
7. Do not invent fields not listed here — unknown fields are silently ignored but create confusion.

### Naming Rules

| Field | Rule | Example |
|-------|------|---------|
| `agent_type` | `snake_case` | `api_architect` |
| `name` | `agent-<kebab-case>` | `agent-api-architect` |
| `short_name` | `<kebab-case>` (no `agent-` prefix) | `api-architect` |
| `aliases` | Any string, preferably kebab-case | `["openapi-expert"]` |

### Routing Confidence

The router computes a confidence score based on:
- Exact match of `explicit_triggers` against the user prompt (high weight)
- Semantic similarity of `context_triggers` against the prompt (medium weight)
- Presence of `activation_keywords` in the prompt (low weight)

A minimum threshold of `0.6` (configurable via `framework_integration.template_system.parameters.confidence_threshold`)
is required for a candidate to appear in the routing output.
