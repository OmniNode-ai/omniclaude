# Adding an Agent

## Overview

Agents are YAML files in `plugins/onex/agents/configs/`. They define a
named agent with activation patterns that the routing system uses to match
user prompts. When a prompt matches, the agent's YAML is injected into
Claude's context so it can apply the agent's domain expertise.

---

## Step 1: Create the YAML File

Create `plugins/onex/agents/configs/my-agent.yaml`:

```yaml
schema_version: "1.0.0"
agent_type: "my_agent"

agent_identity:
  name: "agent-my-agent"
  description: "Brief description of what this agent does"
  color: "blue"

activation_patterns:
  explicit_triggers:
    - "keyword one"
    - "keyword two"
  context_triggers:
    - "phrase that implies this domain"
    - "another contextual phrase"
```

**Required fields:**

| Field | Description |
|-------|-------------|
| `schema_version` | Always `"1.0.0"` |
| `agent_type` | Snake-case identifier (e.g., `api_architect`) |
| `agent_identity.name` | Kebab-case with `agent-` prefix (e.g., `agent-api-architect`) |
| `agent_identity.description` | One-line description shown in candidate list |
| `activation_patterns.explicit_triggers` | Exact keywords/phrases in user prompts |
| `activation_patterns.context_triggers` | Contextual phrases that imply this domain |

**Optional fields** (add as needed):

```yaml
agent_identity:
  color: "blue"          # Display color in UI (optional)

capabilities:
  - "capability description one"
  - "capability description two"

constraints:
  - "what this agent does NOT do"
```

---

## Step 2: Define Activation Patterns

Good activation patterns are the difference between an agent that routes
correctly and one that never gets selected.

**Explicit triggers** match directly against the user's prompt text:

```yaml
explicit_triggers:
  - "openapi"
  - "rest api design"
  - "api schema"
```

**Context triggers** match on implied intent or domain language:

```yaml
context_triggers:
  - "designing HTTP endpoints"
  - "request response contract"
  - "path parameters"
```

Tips:

- Use lowercase strings. Matching is case-insensitive.
- Prefer specific phrases over single generic words.
- Avoid triggers that will collide with other agents (check existing configs
  in `plugins/onex/agents/configs/` before adding).
- Start with 3-5 explicit triggers and 2-3 context triggers. You can tune
  after testing.

---

## Step 3: Test Routing

Verify the agent appears in the candidate list for expected prompts:

```bash
uv run python plugins/onex/hooks/lib/route_via_events_wrapper.py \
  "your test prompt here" \
  "test-correlation-id"
```

The output is a JSON object containing `candidates` (all matched agents) and
`best` (the top-scoring match). Your agent should appear in `candidates` for
prompts that match its triggers.

```json
{
  "candidates": [
    {"name": "agent-my-agent", "score": 0.92},
    {"name": "agent-polymorphic", "score": 0.45}
  ],
  "best": "agent-my-agent"
}
```

If your agent does not appear, check:

1. Trigger phrases are present verbatim in the test prompt.
2. YAML syntax is valid (`jq . plugins/onex/agents/configs/my-agent.yaml`
   will error on invalid YAML — use a YAML linter).
3. The file is in `plugins/onex/agents/configs/` (not a subdirectory).

---

## Step 4: Verify in Candidate List

The routing system returns a ranked candidate list that Claude uses to select
the active agent. Confirm your agent:

- Scores higher than `polymorphic-agent` for its domain prompts.
- Does not appear as top candidate for unrelated prompts (false positives
  reduce routing accuracy).

If scoring is off, adjust trigger specificity. More specific phrases score
higher than generic single words.

---

## Step 5: Deploy

Deploy the plugin to the Claude Code plugin cache:

```
/deploy-local-plugin
```

Start a new Claude Code session and try a prompt that should trigger your
agent. The routing log shows which agent was selected:

```bash
tail -f ~/.claude/hooks.log | grep "agent"
```

---

## Reference

- Agent configs: `plugins/onex/agents/configs/*.yaml`
- Routing handler: `plugins/onex/hooks/lib/route_via_events_wrapper.py`
- Agent YAML schema: `docs/reference/AGENT_YAML_SCHEMA.md`
- Routing architecture: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`
- Routing comparison: `docs/architecture/ROUTING_ARCHITECTURE_COMPARISON.md`
